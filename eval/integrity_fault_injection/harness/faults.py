"""
Fault injectors for LeRobot v3 working copies (PROTOCOL.md section 5).

Each injector takes (dataset, rng, **params) and returns an Injection: the
ground truth (which episodes / cameras are corrupt), the level each in-scope
check is expected to emit, the checks the fault legitimately triggers as a side
effect, and any value measured from the injected files.

Expected levels are derived from the realized injection and the thresholds in
config.toml (checked against the Calibra source by run.py), never from what
Calibra emits.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable, Optional

import numpy as np
import pyarrow as pa

from harness.v3 import V3Dataset, decode

OK, WARNING, CRITICAL = "OK", "WARNING", "CRITICAL"
ANY = "ANY"  # some non-OK flag from the listed checks
NONE = "NONE"  # nothing should fire

TIMESTAMP_CHECKS = ("timestamp_jitter_cv", "timestamp_dropout_rate")

# Set by run.py from config.toml after it is checked against the source.
THRESHOLDS: dict[str, dict] = {}


@dataclass
class Injection:
    # corrupt units: {"episode": int, "camera": Optional[str]}
    units: list[dict]
    # check -> expected minimum level (OK/WARNING/CRITICAL), NONE or ANY
    expected: dict[str, str]
    # checks the fault triggers by construction (not collateral false positives)
    explained: list[str] = field(default_factory=list)
    measured: dict = field(default_factory=dict)
    modified_files: list[str] = field(default_factory=list)
    # variant does not apply to this dataset (e.g. no episode of matching length)
    skipped: Optional[str] = None


def _level(value: float, metric: str) -> str:
    t = THRESHOLDS[metric]
    if value >= t["critical"]:
        return CRITICAL
    if value >= t["warning"]:
        return WARNING
    return NONE


def _pick(rng, items: list, k: int) -> list:
    return [items[i] for i in sorted(rng.choice(len(items), size=k, replace=False))]


def _ep_rows(ds: V3Dataset) -> list[dict]:
    return ds.episodes()


def _n_of(frac: float, n: int) -> int:
    return max(1, math.ceil(frac * n - 1e-9))


# ── 5.1 duplicate episodes ──────────────────────────────────────────────────


def _append_copy(
    ds: V3Dataset,
    src: dict,
    data_fn: Callable[[pa.Table], pa.Table] = lambda t: t,
    video_from: Optional[dict] = None,
) -> int:
    """Append episode `src` as a new episode; its video points at `video_from`'s segment."""
    data = ds.read_data()
    ep_col = data.column("episode_index").to_numpy()
    rows = data.filter(pa.array(ep_col == int(src["episode_index"])))
    new = int(max(ep_col)) + 1
    rows = data_fn(rows)
    rows = rows.set_column(
        rows.schema.get_field_index("episode_index"),
        "episode_index",
        pa.array(np.full(len(rows), new), pa.int64()),
    )
    start = int(data.column("index").to_numpy().max()) + 1
    rows = rows.set_column(
        rows.schema.get_field_index("index"),
        "index",
        pa.array(np.arange(start, start + len(rows)), pa.int64()),
    )
    path = ds.append_data(rows)
    row = dict(src)
    vf = video_from or src
    for key in ds.video_keys:
        for col in ("chunk_index", "file_index", "from_timestamp", "to_timestamp"):
            row[f"videos/{key}/{col}"] = vf[f"videos/{key}/{col}"]
    row.update(
        {
            "episode_index": new,
            "data/chunk_index": 0,
            "data/file_index": int(path.stem.split("-")[1]),
            "dataset_from_index": start,
            "dataset_to_index": start + len(rows),
            "length": len(rows),
        }
    )
    ds.append_episode_row(row)
    ds.info["total_episodes"] = int(ds.info["total_episodes"]) + 1
    ds.info["total_frames"] = int(ds.info["total_frames"]) + len(rows)
    ds.info["splits"] = {"train": f"0:{ds.info['total_episodes']}"}
    ds.save_info()
    return new


def duplicate_exact(
    ds, rng, frac: Optional[float] = None, count: Optional[int] = None
) -> Injection:
    rows = _ep_rows(ds)
    k = count if count is not None else _n_of(frac, len(rows))
    units = [
        {"episode": _append_copy(ds, src), "camera": None, "copy_of": int(src["episode_index"])}
        for src in _pick(rng, rows, k)
    ]
    return Injection(units, {"duplicate_episode_fraction": CRITICAL})


def duplicate_reencoded(ds, rng) -> Injection:
    """Exact parquet copy whose video was re-encoded into its own file."""
    src = _pick(rng, _ep_rows(ds), 1)[0]
    new = _append_copy(ds, src)
    for key in ds.video_keys:
        ds.relocate(new, key)
    return Injection(
        [{"episode": new, "camera": None, "copy_of": int(src["episode_index"])}],
        {"duplicate_episode_fraction": CRITICAL},
    )


def duplicate_ulp(ds, rng) -> Injection:
    """Copy with one action value moved by one ULP: not an exact copy."""
    src = _pick(rng, _ep_rows(ds), 1)[0]

    def nudge(t: pa.Table) -> pa.Table:
        actions = [list(a) for a in t.column("action").to_pylist()]
        i, j = int(rng.integers(len(actions))), int(rng.integers(len(actions[0])))
        actions[i][j] = float(np.nextafter(np.float32(actions[i][j]), np.float32(np.inf)))
        return t.set_column(
            t.schema.get_field_index("action"),
            "action",
            pa.array(actions, t.schema.field("action").type),
        )

    new = _append_copy(ds, src, nudge)
    return Injection(
        [{"episode": new, "camera": None, "copy_of": int(src["episode_index"])}],
        {"duplicate_episode_fraction": NONE},
    )


def duplicate_shifted(ds, rng) -> Injection:
    """Same trajectory shifted by one step (first row dropped, last repeated)."""
    src = _pick(rng, _ep_rows(ds), 1)[0]

    def shift(t: pa.Table) -> pa.Table:
        idx = np.r_[np.arange(1, len(t)), len(t) - 1]
        for c in ("observation.state", "action"):
            if c in t.schema.names:
                t = t.set_column(t.schema.get_field_index(c), c, t.column(c).take(pa.array(idx)))
        return t

    new = _append_copy(ds, src, shift)
    return Injection(
        [{"episode": new, "camera": None, "copy_of": int(src["episode_index"])}],
        {"duplicate_episode_fraction": NONE},
    )


def duplicate_other_video(ds, rng) -> Injection:
    """Exact parquet copy, video pointing at a different episode of equal length."""
    rows = _ep_rows(ds)
    for src in _pick(rng, rows, len(rows)):
        same = [
            r
            for r in rows
            if r["length"] == src["length"] and r["episode_index"] != src["episode_index"]
        ]
        if same:
            other = _pick(rng, same, 1)[0]
            new = _append_copy(ds, src, video_from=other)
            return Injection(
                [{"episode": new, "camera": None, "copy_of": int(src["episode_index"])}],
                {"duplicate_episode_fraction": CRITICAL},
                measured={"video_from": int(other["episode_index"])},
            )
    return Injection([], {}, skipped="no two episodes share a length")


def append_control(ds, rng) -> Injection:
    """New episode with reversed actions/state; video points at the source segment."""
    src = _pick(rng, _ep_rows(ds), 1)[0]

    def reverse(t: pa.Table) -> pa.Table:
        idx = pa.array(np.arange(len(t))[::-1].copy())
        for c in ("observation.state", "action"):
            if c in t.schema.names:
                t = t.set_column(t.schema.get_field_index(c), c, t.column(c).take(idx))
        return t

    _append_copy(ds, src, reverse)
    return Injection([], {"duplicate_episode_fraction": NONE})


# ── 5.2 missing and broken video files ──────────────────────────────────────


def _units_in_file(ds, path) -> list[dict]:
    units = []
    for r in _ep_rows(ds):
        for key in ds.video_keys:
            if ds.segment(r, key)[0] == path:
                units.append({"episode": int(r["episode_index"]), "camera": key})
    return units


def video_delete_camera_file(ds, rng) -> Injection:
    key = _pick(rng, ds.video_keys, 1)[0]
    r = _pick(rng, _ep_rows(ds), 1)[0]
    path = ds.segment(r, key)[0]
    units = _units_in_file(ds, path)
    path.unlink()
    return Injection(units, {"video_missing_rate": CRITICAL}, modified_files=[str(path)])


def video_delete_chunk(ds, rng) -> Injection:
    units, files = [], []
    for key in ds.video_keys:
        for path in sorted((ds.root / "videos" / key).rglob("*.mp4")):
            units += _units_in_file(ds, path)
            path.unlink()
            files.append(str(path))
    return Injection(units, {"video_missing_rate": CRITICAL}, modified_files=files)


def video_delete_episode(ds, rng) -> Injection:
    """One episode's own (relocated) file is missing; every other episode intact."""
    key = _pick(rng, ds.video_keys, 1)[0]
    e = int(_pick(rng, _ep_rows(ds), 1)[0]["episode_index"])
    path, _ = ds.relocate(e, key)
    path.unlink()
    return Injection(
        [{"episode": e, "camera": key}],
        {"video_missing_rate": CRITICAL},
        modified_files=[str(path)],
    )


def video_truncate(ds, rng, keep: float) -> Injection:
    """Relocated episode file (moov first) cut to `keep` of its bytes."""
    key = _pick(rng, ds.video_keys, 1)[0]
    e = int(_pick(rng, _ep_rows(ds), 1)[0]["episode_index"])
    path, frames = ds.relocate(e, key, faststart=True)
    data = path.read_bytes()
    path.write_bytes(data[: int(len(data) * keep)])
    return Injection(
        [{"episode": e, "camera": key}],
        {"video_decode_failure_rate": CRITICAL},
        measured={"bytes_kept": int(len(data) * keep), "bytes_total": len(data)},
        modified_files=[str(path)],
    )


def info_fps_shift(ds, rng, rel: float) -> Injection:
    ds.info["fps"] = ds.fps * (1 + rel)
    ds.save_info()
    tol = THRESHOLDS["video_fps_mismatch_rate"]["rel_tolerance"]
    expected = CRITICAL if abs(rel) > tol else NONE
    units = [
        {"episode": int(r["episode_index"]), "camera": k}
        for r in _ep_rows(ds)
        for k in ds.video_keys
    ]
    return Injection(
        units if expected != NONE else [],
        {"video_fps_mismatch_rate": expected},
        modified_files=["meta/info.json"],
    )


# ── 5.3 frozen and repeated frames ──────────────────────────────────────────


def _repeat_mask(frames: np.ndarray) -> np.ndarray:
    from calibra.analyzers.duplicate_frame import repeated_transitions

    return repeated_transitions(frames[..., ::-1])  # RGB -> BGR, as Calibra decodes


def _max_run(mask: np.ndarray) -> int:
    from calibra.analyzers.camera_freeze import _max_run_length

    return int(_max_run_length(mask))


def _freeze(frames: np.ndarray, rng, run: int) -> np.ndarray:
    out = frames.copy()
    s = int(rng.integers(0, len(frames) - run - 1))
    out[s + 1 : s + 1 + run] = frames[s]
    return out


def _measure(ds, path) -> np.ndarray:
    h, w, _ = ds.info["features"][next(k for k in ds.video_keys if k in str(path))]["shape"]
    return _repeat_mask(decode(path, (h, w)))


def freeze_run(ds, rng, run: int, frac: Optional[float] = None) -> Injection:
    """
    A freeze of `run` repeated transitions in one camera of 1 (or frac) episodes.
    The expected level comes from the frames as injected (before encoding): what
    the codec does to them is part of what is being tested. Decoded runs are
    recorded alongside.
    """
    rows = _ep_rows(ds)
    chosen = _pick(rng, rows, 1 if frac is None else _n_of(frac, len(rows)))
    units, runs, decoded = [], [], []
    min_run = THRESHOLDS["camera_freeze_events"]["min_run"]
    for r in chosen:
        key = _pick(rng, ds.video_keys, 1)[0]
        e = int(r["episode_index"])
        path, frames = ds.relocate(e, key, lambda f: _freeze(f, rng, run))
        runs.append(_max_run(_repeat_mask(frames)))
        decoded.append(_max_run(_measure(ds, path)))
        units.append({"episode": e, "camera": key})
    frozen = sum(x >= min_run for x in runs)
    frac_eps = frozen / len(rows)
    t = THRESHOLDS["camera_freeze_events"]
    expected = NONE if frozen == 0 else CRITICAL if frac_eps >= t["critical"] else WARNING
    return Injection(
        units,
        {"camera_freeze_events": expected},
        measured={
            "injected_max_runs": runs,
            "decoded_max_runs": decoded,
            "frozen_episode_fraction": frac_eps,
        },
    )


def repeat_fill(ds, rng, rate: float) -> Injection:
    """Isolated single-frame repeats at `rate` of transitions, every episode, one camera."""
    key = _pick(rng, ds.video_keys, 1)[0]

    def fill(frames: np.ndarray) -> np.ndarray:
        n = len(frames) - 1
        k = round(rate * n)
        # non-adjacent transition positions 1..n-1 (every other slot, then sample)
        slots = np.arange(2, n, 2)
        pos = np.sort(rng.choice(slots, size=min(k, len(slots)), replace=False))
        out = frames.copy()
        out[pos] = frames[pos - 1]
        return out

    units, rates, decoded = [], [], []
    for r in _ep_rows(ds):
        e = int(r["episode_index"])
        path, frames = ds.relocate(e, key, fill)
        # Injected rate (incl. native repeats in the source decode) is the ground
        # truth; the decoded rate is what survives encoding.
        rates.append(float(_repeat_mask(frames).mean()))
        decoded.append(float(_measure(ds, path).mean()))
        units.append({"episode": e, "camera": key})
    injected = float(np.mean(rates))
    return Injection(
        units,
        {"duplicate_frame_rate": _level(injected, "duplicate_frame_rate")},
        measured={
            "camera": key,
            "injected_repeat_rate": injected,
            "decoded_repeat_rate": float(np.mean(decoded)),
        },
    )


def reencode_control(ds, rng) -> Injection:
    """Every episode of one camera relocated with no fault (the frame-fault control)."""
    key = _pick(rng, ds.video_keys, 1)[0]
    rates, runs = [], []
    for r in _ep_rows(ds):
        path, _ = ds.relocate(int(r["episode_index"]), key)
        mask = _measure(ds, path)
        rates.append(float(mask.mean()))
        runs.append(_max_run(mask))
    return Injection(
        [],
        {"duplicate_frame_rate": NONE, "camera_freeze_events": NONE},
        measured={"camera": key, "mean_repeat_rate": float(np.mean(rates)), "max_run": max(runs)},
    )


# ── 5.4 dropped frames and timestamps ───────────────────────────────────────


def _drop_positions(rng, n: int, k: int) -> np.ndarray:
    """k non-adjacent interior positions of 0..n-1."""
    slots = np.arange(1, n - 1, 2)
    return np.sort(rng.choice(slots, size=min(k, len(slots)), replace=False))


def video_drop_frames(
    ds,
    rng,
    k: Optional[int] = None,
    frac: Optional[float] = None,
    eps_frac: Optional[float] = None,
    meta_claims_full: bool = False,
) -> Injection:
    """
    Drop video frames from one camera of 1 (or eps_frac) episodes; parquet intact.
    meta_claims_full=False: meta span reflects the shorter file (recorder knew).
    meta_claims_full=True: meta still claims the full span (file is short).
    """
    rows = _ep_rows(ds)
    chosen = _pick(rng, rows, 1 if eps_frac is None else _n_of(eps_frac, len(rows)))
    units, dropped = [], []
    tol = THRESHOLDS["video_frame_mismatch_rate"]["frame_tolerance"]
    for r in chosen:
        key = _pick(rng, ds.video_keys, 1)[0]
        e = int(r["episode_index"])
        n = int(r["length"])
        kk = k if k is not None else max(1, round(frac * n))
        drop = _drop_positions(rng, n, kk)
        full = n / ds.fps if meta_claims_full else None
        ds.relocate(e, key, lambda f, d=drop: np.delete(f, d, axis=0), to_timestamp=full)
        units.append({"episode": e, "camera": key})
        dropped.append(len(drop))
    if meta_claims_full:
        # span == length, so only the boundary decode / past-the-end check can see it
        expected = {"video_frame_mismatch_rate": ANY, "video_decode_failure_rate": ANY}
        if max(dropped) <= tol:
            expected = {"video_frame_mismatch_rate": NONE, "video_decode_failure_rate": NONE}
    else:
        expected = {"video_frame_mismatch_rate": CRITICAL if max(dropped) > tol else NONE}
    return Injection(
        units if max(dropped) > tol else [], expected, measured={"frames_dropped": dropped}
    )


def _write_timestamps(ds, data: pa.Table, ts: np.ndarray) -> None:
    i = data.schema.get_field_index("timestamp")
    ds.replace_data(
        data.set_column(i, "timestamp", pa.array(ts.astype(np.float32), data.schema.field(i).type))
    )


def _dropout_rate(data: pa.Table, k: float) -> float:
    """Calibra's measure: mean over episodes of the fraction of intervals > k x median."""
    ep = data.column("episode_index").to_numpy()
    ts = data.column("timestamp").to_numpy().astype(np.float64)
    vals = []
    for e in np.unique(ep):
        d = np.diff(ts[ep == e])
        vals.append(float(np.mean(d > k * np.median(d))) if len(d) >= 2 else 0.0)
    return float(np.mean(vals))


def steps_dropped(ds, rng, rate: float, run: int) -> Injection:
    """
    Remove runs of `run` consecutive parquet rows so that `rate` of each
    episode's intervals contain a gap (timestamps kept, frame_index renumbered).
    A run of r rows leaves a gap of (r + 1) intervals. Video is untouched, so
    the parquet/video frame mismatch this creates is explained, not collateral.
    """
    data = ds.read_data()
    ep = data.column("episode_index").to_numpy()
    keep = np.ones(len(data), bool)
    units = []
    for e in np.unique(ep):
        where = np.flatnonzero(ep == e)
        # ceil, so the realized rate does not round below the target
        n_events = math.ceil(rate * (len(where) - 1))
        if n_events == 0:
            continue
        # event starts on a grid of run + 1 so runs never touch
        slots = np.arange(1, len(where) - run - 1, run + 1)
        starts = np.sort(rng.choice(slots, size=min(n_events, len(slots)), replace=False))
        for s in starts:
            keep[where[s : s + run]] = False
        units.append({"episode": int(e), "camera": None})
    data = data.filter(pa.array(keep))
    ep = data.column("episode_index").to_numpy()
    fi = np.concatenate([np.arange((ep == e).sum()) for e in np.unique(ep)])
    data = data.set_column(
        data.schema.get_field_index("frame_index"), "frame_index", pa.array(fi, pa.int64())
    )
    ds.replace_data(data)
    k = THRESHOLDS["timestamp_dropout_rate"]["gap_k"]
    realized = _dropout_rate(data, k)
    # A gap of (run + 1) intervals is invisible when it does not exceed k x median.
    expected = _level(realized, "timestamp_dropout_rate") if run + 1 > k else NONE
    return Injection(
        units,
        {"timestamp_dropout_rate": expected},
        explained=["video_frame_mismatch_rate", "short_episode_fraction"],
        measured={"dropout_rate": realized, "rows_removed": int((~keep).sum())},
    )


def timestamp_jitter(ds, rng, cv: float) -> Injection:
    """
    Replace every interval by dt * (1 + cv * z), z standardized per episode so
    each episode's CV hits the target, clipped at 0.05 dt.
    """
    data = ds.read_data()
    ep = data.column("episode_index").to_numpy()
    ts = data.column("timestamp").to_numpy().astype(np.float64)
    dt = 1.0 / ds.fps
    out = ts.copy()
    cvs = []
    for e in np.unique(ep):
        where = np.flatnonzero(ep == e)
        z = rng.standard_normal(len(where) - 1)
        z = (z - z.mean()) / z.std()
        d = dt * np.clip(1 + cv * z, 0.05, None)
        out[where] = ts[where[0]] + np.r_[0.0, np.cumsum(d)]
    _write_timestamps(ds, data, out)
    # measured on the stored (float32) timestamps, as Calibra reads them
    stored = out.astype(np.float32).astype(np.float64)
    for e in np.unique(ep):
        d = np.diff(stored[ep == e])
        cvs.append(float(np.std(d) / np.mean(d)))
    measured = float(np.mean(cvs))
    units = [{"episode": int(e), "camera": None} for e in np.unique(ep)]
    return Injection(
        units,
        {"timestamp_jitter_cv": _level(measured, "timestamp_jitter_cv")},
        measured={"mean_episode_cv": measured},
    )


def timestamp_swap(ds, rng, eps_frac: float) -> Injection:
    """Two adjacent timestamps swapped (non-monotonic) in eps_frac of episodes."""
    data = ds.read_data()
    ep = data.column("episode_index").to_numpy()
    ts = data.column("timestamp").to_numpy().astype(np.float64)
    eps = _pick(rng, list(np.unique(ep)), _n_of(eps_frac, len(np.unique(ep))))
    for e in eps:
        where = np.flatnonzero(ep == e)
        i = int(rng.integers(1, len(where) - 2))
        ts[[where[i], where[i + 1]]] = ts[[where[i + 1], where[i]]]
    _write_timestamps(ds, data, ts)
    return Injection(
        [{"episode": int(e), "camera": None} for e in eps], {c: ANY for c in TIMESTAMP_CHECKS}
    )


def timestamp_offset(ds, rng, seconds: float) -> Injection:
    data = ds.read_data()
    ep = data.column("episode_index").to_numpy()
    ts = data.column("timestamp").to_numpy().astype(np.float64)
    e = _pick(rng, list(np.unique(ep)), 1)[0]
    ts[ep == e] += seconds
    _write_timestamps(ds, data, ts)
    return Injection([{"episode": int(e), "camera": None}], {c: NONE for c in TIMESTAMP_CHECKS})


def timestamp_units(ds, rng, scale: float) -> Injection:
    """One episode's timestamps in ms instead of s."""
    data = ds.read_data()
    ep = data.column("episode_index").to_numpy()
    ts = data.column("timestamp").to_numpy().astype(np.float64)
    e = _pick(rng, list(np.unique(ep)), 1)[0]
    ts[ep == e] *= scale
    _write_timestamps(ds, data, ts)
    return Injection([{"episode": int(e), "camera": None}], {c: ANY for c in TIMESTAMP_CHECKS})


def identity(ds, rng) -> Injection:
    return Injection([], {})


INJECTORS: dict[str, Callable[..., Injection]] = {
    f.__name__: f
    for f in (
        identity,
        append_control,
        reencode_control,
        duplicate_exact,
        duplicate_reencoded,
        duplicate_ulp,
        duplicate_shifted,
        duplicate_other_video,
        video_delete_camera_file,
        video_delete_chunk,
        video_delete_episode,
        video_truncate,
        info_fps_shift,
        freeze_run,
        repeat_fill,
        video_drop_frames,
        steps_dropped,
        timestamp_jitter,
        timestamp_swap,
        timestamp_offset,
        timestamp_units,
    )
}
