"""
calibra.video_integrity — are the camera videos of a LeRobot v2/v3 dataset usable?

LeRobot v2/v3 store camera streams as mp4 files referenced from ``meta/``,
not as per-frame images, so a dataset whose Parquet data is perfect can still
fail at training time: a video is missing, truncated, recorded at the wrong
fps, or does not cover the episode's frames. These are objective acquisition
or format failures, checked per (episode, camera) pair without decoding whole
videos:

  video_missing_rate         referenced mp4 does not exist
  video_decode_failure_rate  mp4 cannot be opened, or the episode's first or
                             last frame cannot be decoded (truncated/corrupt)
  video_frame_mismatch_rate  video frames do not cover the episode's frames
                             (v2: frame count; v3: from/to timestamp span)
  video_fps_mismatch_rate    stream fps differs from info.json fps

Layouts (from ``meta/info.json``'s ``video_path`` template):
  v2.x  one mp4 per episode and camera:
        videos/chunk-{episode_chunk}/{video_key}/episode_{episode_index}.mp4
  v3.x  many episodes concatenated per mp4, located by
        meta/episodes/*.parquet columns videos/{key}/chunk_index, file_index,
        from_timestamp, to_timestamp

Needs OpenCV (``pip install 'calibra-robotics[video]'``). Hub datasets must be downloaded first, since their videos are not
fetched by the Parquet loader.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from calibra.schema.report import ObservedValue, RiskFlag, RiskLevel

VIDEO_METRICS = (
    "video_missing_rate",
    "video_decode_failure_rate",
    "video_frame_mismatch_rate",
    "video_fps_mismatch_rate",
)

# A one-frame difference is rounding at the episode boundary, not missing data.
_FRAME_TOLERANCE = 1
_FPS_REL_TOLERANCE = 0.01

_MESSAGES = {
    "video_missing_rate": (
        "{n} of {total} episode videos (episode x camera) are missing",
        "Training will fail when these episodes are sampled. Re-upload the videos or "
        "drop the episodes.",
    ),
    "video_decode_failure_rate": (
        "{n} of {total} episode videos cannot be decoded at the episode boundaries",
        "The files are truncated or corrupt; LeRobot raises on these frames. "
        "Re-encode from the source recording or drop the episodes.",
    ),
    "video_frame_mismatch_rate": (
        "{n} of {total} episode videos do not cover the episode's frames",
        "Camera frames and actions are out of sync or partly missing; the policy "
        "would learn from misaligned observations.",
    ),
    "video_fps_mismatch_rate": (
        "{n} of {total} video files are encoded at a different fps than info.json",
        "LeRobot looks frames up by timestamp, so a wrong fps returns the wrong "
        "frames or fails its timestamp tolerance check.",
    ),
}


@dataclass
class VideoIntegrityResult:
    flags: list[RiskFlag]
    # metric -> sorted episode indices (fps mismatch lists every episode in the file)
    affected: dict[str, list[int]] = field(default_factory=dict)
    n_checked: int = 0
    not_evaluated_reason: Optional[str] = None


@dataclass
class _Probe:
    ok: bool
    fps: float = 0.0
    n_frames: int = 0


def has_video_features(info: dict) -> bool:
    return bool(_video_keys(info))


def _video_keys(info: dict) -> list[str]:
    return [k for k, f in info.get("features", {}).items() if f.get("dtype") == "video"]


def _require_cv2():
    try:
        import cv2
    except ImportError:
        return None
    return cv2


class _VideoCache:
    """Opens each file once; v3 files are shared by many episodes."""

    def __init__(self, cv2) -> None:
        self.cv2 = cv2
        self._probes: dict[Path, _Probe] = {}

    def probe(self, path: Path) -> _Probe:
        if path not in self._probes:
            cap = self.cv2.VideoCapture(str(path))
            try:
                if not cap.isOpened():
                    self._probes[path] = _Probe(ok=False)
                else:
                    fps = float(cap.get(self.cv2.CAP_PROP_FPS) or 0.0)
                    n = int(cap.get(self.cv2.CAP_PROP_FRAME_COUNT) or 0)
                    self._probes[path] = _Probe(ok=fps > 0 and n > 0, fps=fps, n_frames=n)
            finally:
                cap.release()
        return self._probes[path]

    def decodes(self, path: Path, frame_indices: list[int]) -> bool:
        """True if every requested frame decodes."""
        cap = self.cv2.VideoCapture(str(path))
        try:
            if not cap.isOpened():
                return False
            for idx in frame_indices:
                cap.set(self.cv2.CAP_PROP_POS_FRAMES, max(idx, 0))
                ok, frame = cap.read()
                if not ok or frame is None:
                    return False
            return True
        finally:
            cap.release()


def check_video_integrity(
    root: Path, episode_lengths: Optional[dict[int, int]] = None
) -> VideoIntegrityResult:
    """
    Check every (episode, camera) video of a local LeRobot v2/v3 dataset.

    ``episode_lengths`` maps episode_index to its number of Parquet frames; when
    omitted it is read from ``meta/``.
    """
    info = json.loads((root / "meta" / "info.json").read_text(encoding="utf-8"))
    keys = _video_keys(info)
    if not keys:
        return VideoIntegrityResult(flags=[], not_evaluated_reason="dataset has no video features")
    if "video_path" not in info:
        return VideoIntegrityResult(
            flags=[], not_evaluated_reason="info.json has no video_path template"
        )
    cv2 = _require_cv2()
    if cv2 is None:
        return VideoIntegrityResult(
            flags=[],
            not_evaluated_reason=("requires opencv (pip install 'calibra-robotics[video]')"),
        )

    fps = float(info.get("fps") or 0.0)
    cache = _VideoCache(cv2)
    if str(info.get("codebase_version", "")).startswith("v3"):
        entries = _v3_entries(root, info, keys, episode_lengths)
    else:
        entries = _v2_entries(root, info, keys, episode_lengths)

    # metric -> failing (episode_index, video_key) pairs
    bad: dict[str, set[tuple[int, str]]] = {m: set() for m in VIDEO_METRICS}
    files_checked: set[Path] = set()
    bad_fps_files: set[Path] = set()

    for ep, key, path, start_s, end_s, length in entries:
        pair = (ep, key)
        if not path.exists():
            bad["video_missing_rate"].add(pair)
            continue
        probe = cache.probe(path)
        files_checked.add(path)
        if not probe.ok:
            bad["video_decode_failure_rate"].add(pair)
            continue
        if fps > 0 and abs(probe.fps - fps) / fps > _FPS_REL_TOLERANCE:
            bad_fps_files.add(path)
            bad["video_fps_mismatch_rate"].add(pair)

        # Frame range of this episode inside the file, at the file's own fps.
        first = round(start_s * probe.fps) if start_s is not None else 0
        if end_s is not None:
            last = round(end_s * probe.fps) - 1
        else:
            last = probe.n_frames - 1
        span = last - first + 1
        if length is not None and abs(span - length) > _FRAME_TOLERANCE:
            bad["video_frame_mismatch_rate"].add(pair)
        if last >= probe.n_frames + _FRAME_TOLERANCE:
            bad["video_frame_mismatch_rate"].add(pair)
        if first >= probe.n_frames:
            continue  # nothing of this episode is in the file; already a mismatch
        # Boundary frames that exist must decode; a truncated file fails here.
        last = min(last, probe.n_frames - 1)
        if not cache.decodes(path, [first, last]):
            bad["video_decode_failure_rate"].add(pair)

    n_pairs = len(entries)
    totals = {m: n_pairs for m in VIDEO_METRICS}
    counts = {m: len(bad[m]) for m in VIDEO_METRICS}
    # fps is a property of a file, so it is reported per file.
    totals["video_fps_mismatch_rate"] = len(files_checked)
    counts["video_fps_mismatch_rate"] = len(bad_fps_files)
    affected_eps = {m: sorted({ep for ep, _ in bad[m]}) for m in VIDEO_METRICS}

    flags = []
    for metric in VIDEO_METRICS:
        total = totals[metric]
        if total == 0:
            continue
        n = counts[metric]
        interp, implication = _MESSAGES[metric]
        rate = n / total
        affected = affected_eps[metric]
        detail = interp.format(n=n, total=total)
        if affected:
            shown = ", ".join(str(e) for e in affected[:10])
            more = f" (+{len(affected) - 10} more)" if len(affected) > 10 else ""
            detail += f"; episodes: {shown}{more}"
        flags.append(
            RiskFlag(
                level=RiskLevel.CRITICAL if n else RiskLevel.OK,
                metric=metric,
                observed=ObservedValue(value=rate, unit="fraction"),
                threshold=0.0,
                interpretation=detail if n else interp.format(n=0, total=total),
                implication=implication if n else "No problems found.",
                affected_fraction=rate,
            )
        )

    return VideoIntegrityResult(
        flags=flags,
        affected={m: eps for m, eps in affected_eps.items() if eps},
        n_checked=n_pairs,
    )


def _lengths_from_meta(root: Path) -> dict[int, int]:
    lengths: dict[int, int] = {}
    jsonl = root / "meta" / "episodes.jsonl"
    if jsonl.exists():
        for line in jsonl.read_text(encoding="utf-8").splitlines():
            if line.strip():
                obj = json.loads(line)
                if "length" in obj:
                    lengths[int(obj["episode_index"])] = int(obj["length"])
    return lengths


def _v2_entries(root, info, keys, episode_lengths):
    lengths = episode_lengths or _lengths_from_meta(root)
    chunks_size = int(info.get("chunks_size", 1000))
    entries = []
    for ep in sorted(lengths):
        for key in keys:
            rel = info["video_path"].format(
                episode_chunk=ep // chunks_size, video_key=key, episode_index=ep
            )
            entries.append((ep, key, root / rel, None, None, lengths[ep]))
    return entries


def _v3_entries(root, info, keys, episode_lengths):
    import pyarrow as pa
    import pyarrow.parquet as pq

    files = sorted((root / "meta" / "episodes").glob("**/*.parquet"))
    if not files:
        raise ValueError(f"No meta/episodes/*.parquet found in {root} (LeRobot v3)")
    rows = pa.concat_tables([pq.read_table(f) for f in files]).to_pylist()
    entries = []
    for row in sorted(rows, key=lambda r: int(r["episode_index"])):
        ep = int(row["episode_index"])
        length = (episode_lengths or {}).get(ep, row.get("length"))
        for key in keys:
            chunk = row.get(f"videos/{key}/chunk_index")
            file = row.get(f"videos/{key}/file_index")
            if chunk is None or file is None:
                continue
            rel = info["video_path"].format(video_key=key, chunk_index=chunk, file_index=file)
            entries.append(
                (
                    ep,
                    key,
                    root / rel,
                    row.get(f"videos/{key}/from_timestamp"),
                    row.get(f"videos/{key}/to_timestamp"),
                    length,
                )
            )
    return entries


# ── decoded content checks (opt-in) ──────────────────────────────────────────

_DECODE_CHUNK = 64  # frames held in memory at once per camera


@dataclass
class VideoContentResult:
    flags: list[RiskFlag]
    # camera -> mean repeated-frame fraction over the sampled episodes
    duplicate_rate_by_camera: dict[str, float] = field(default_factory=dict)
    # episode index -> longest run of repeated frames (max over cameras)
    freeze_runs: dict[int, int] = field(default_factory=dict)
    sampled_episodes: list[int] = field(default_factory=list)
    not_evaluated_reason: Optional[str] = None


def _sample_evenly(items: list[int], k: int) -> list[int]:
    if k <= 0 or len(items) <= k:
        return list(items)
    idx = sorted({round(i * (len(items) - 1) / (k - 1)) for i in range(k)}) if k > 1 else [0]
    return [items[i] for i in idx]


def _decoded_repeats(cv2, path: Path, first: int, n_frames: int):
    """Repeated-transition mask for frames [first, first + n_frames), decoded in chunks."""
    import numpy as np

    from calibra.analyzers.duplicate_frame import repeated_transitions

    cap = cv2.VideoCapture(str(path))
    try:
        cap.set(cv2.CAP_PROP_POS_FRAMES, max(first, 0))
        masks, carry, read = [], None, 0
        while read < n_frames:
            # Carry the last frame over so the transition across chunks is counted.
            chunk = [] if carry is None else [carry]
            new = 0
            for _ in range(min(_DECODE_CHUNK, n_frames - read)):
                ok, frame = cap.read()
                if not ok:
                    break
                chunk.append(frame)
                new += 1
            read += new
            if new == 0 or len(chunk) < 2:
                break
            masks.append(repeated_transitions(np.stack(chunk)))
            carry = chunk[-1]
        return np.concatenate(masks) if masks else np.zeros(0, dtype=bool)
    finally:
        cap.release()


def check_video_content(root: Path, max_episodes: int = 20) -> VideoContentResult:
    """
    Decode a sample of episodes from a local LeRobot v2/v3 dataset and run the
    duplicate-frame and camera-freeze checks on every camera, with the same
    measure and thresholds the image-based analyzers use
    (calibra.analyzers.duplicate_frame / camera_freeze). Up to `max_episodes`
    evenly spaced episodes; frames are processed in chunks at full resolution.
    """
    import numpy as np

    from calibra.analyzers.camera_freeze import (
        _FREEZE_CRITICAL_FRACTION,
        _FREEZE_WARNING_FRACTION,
        _MIN_FREEZE_RUN,
        _max_run_length,
    )
    from calibra.analyzers.duplicate_frame import _DUPLICATE_CRITICAL, _DUPLICATE_WARNING
    from calibra.analyzers.task_structure import _threshold_level_upper

    info = json.loads((root / "meta" / "info.json").read_text(encoding="utf-8"))
    keys = _video_keys(info)
    if not keys:
        return VideoContentResult(flags=[], not_evaluated_reason="dataset has no video features")
    cv2 = _require_cv2()
    if cv2 is None:
        return VideoContentResult(
            flags=[], not_evaluated_reason="requires opencv (pip install 'calibra-robotics[video]')"
        )

    if str(info.get("codebase_version", "")).startswith("v3"):
        entries = _v3_entries(root, info, keys, None)
    else:
        entries = _v2_entries(root, info, keys, None)
    by_ep: dict[int, list] = {}
    for ep, key, path, start_s, end_s, length in entries:
        by_ep.setdefault(ep, []).append((key, path, start_s, end_s, length))
    sampled = _sample_evenly(sorted(by_ep), max_episodes)

    cache = _VideoCache(cv2)
    rates: dict[str, list[float]] = {k: [] for k in keys}
    runs: dict[int, int] = {}
    for ep in sampled:
        for key, path, start_s, end_s, length in by_ep[ep]:
            if not path.exists():
                continue
            probe = cache.probe(path)
            if not probe.ok:
                continue
            first = round(start_s * probe.fps) if start_s is not None else 0
            if end_s is not None:
                n = round(end_s * probe.fps) - first
            else:
                n = length if length is not None else probe.n_frames
            mask = _decoded_repeats(cv2, path, first, int(n))
            if len(mask) == 0:
                continue
            rates[key].append(float(np.mean(mask)))
            runs[ep] = max(runs.get(ep, 0), _max_run_length(mask))

    per_camera = {k: float(np.mean(v)) for k, v in rates.items() if v}
    if not per_camera:
        return VideoContentResult(
            flags=[], not_evaluated_reason="no decodable video for the sampled episodes"
        )
    worst_cam, worst = max(per_camera.items(), key=lambda kv: kv[1])
    cams = ", ".join(f"{k.split('.')[-1]} {v:.1%}" for k, v in sorted(per_camera.items()))
    scope = f"decoded {len(sampled)} of {len(by_ep)} episodes"

    dup_level = _threshold_level_upper(worst, _DUPLICATE_WARNING, _DUPLICATE_CRITICAL)
    dup_flag = RiskFlag(
        level=dup_level,
        metric="duplicate_frame_rate",
        observed=ObservedValue(value=worst, unit="fraction"),
        threshold=_DUPLICATE_WARNING,
        interpretation=(
            "Camera frames show expected frame-to-frame variation"
            if dup_level == RiskLevel.OK
            else f"{worst:.1%} of frame transitions on {worst_cam.split('.')[-1]} repeat the "
            "previous frame"
        )
        + f" ({scope}; per camera: {cams}).",
        implication=(
            "No duplicate-frame risk detected."
            if dup_level == RiskLevel.OK
            else "Repeated frames usually mean the camera ran slower than the recording rate "
            "(frames padded by repetition) or the capture pipeline re-emitted buffers; the "
            "policy then sees stale or lower-rate visual input. Rendered simulations repeat "
            "frames legitimately when nothing in view moves."
        ),
        affected_fraction=worst,
    )

    frozen = sorted(ep for ep, r in runs.items() if r >= _MIN_FREEZE_RUN)
    frac = len(frozen) / max(len(runs), 1)
    frz_level = _threshold_level_upper(frac, _FREEZE_WARNING_FRACTION, _FREEZE_CRITICAL_FRACTION)
    frz_flag = RiskFlag(
        level=frz_level,
        metric="camera_freeze_events",
        observed=ObservedValue(value=frac, unit="fraction"),
        threshold=_FREEZE_WARNING_FRACTION,
        interpretation=(
            f"No sustained camera-freeze runs detected ({scope})."
            if frz_level == RiskLevel.OK
            else f"{len(frozen)} of {len(runs)} sampled episodes contain a run of "
            f">={_MIN_FREEZE_RUN} repeated frames (episodes {frozen[:10]}; {scope})."
        ),
        implication=(
            "No freeze risk detected."
            if frz_level == RiskLevel.OK
            else "A frozen camera segment trains the policy on stale visual input for that window."
        ),
        affected_fraction=frac,
    )
    return VideoContentResult(
        flags=[dup_flag, frz_flag],
        duplicate_rate_by_camera=per_camera,
        freeze_runs=runs,
        sampled_episodes=sampled,
    )
