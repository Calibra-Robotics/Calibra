"""
Tests for calibra.video_integrity on real (tiny) mp4 files.

Fixtures are LeRobot v2 (one mp4 per episode/camera) and v3 (episodes
concatenated per mp4, located by meta/episodes/*.parquet) datasets written to
disk with OpenCV, so open/seek/decode go through the same code path as real
data.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2", reason="pip install 'calibra-robotics[video]'")
pa = pytest.importorskip("pyarrow", reason="pip install 'calibra-robotics[lerobot]'")
pq = pytest.importorskip("pyarrow.parquet")

from calibra.schema.report import RiskLevel  # noqa: E402
from calibra.video_integrity import VIDEO_METRICS, check_video_integrity  # noqa: E402

FPS = 10
KEY = "observation.images.top"


def _write_mp4(path: Path, n_frames: int, fps: float = FPS) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (32, 24))
    for i in range(n_frames):
        writer.write(np.full((24, 32, 3), (i * 7) % 255, dtype=np.uint8))
    writer.release()


def _write_frames(path: Path, lengths: dict[int, int]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    eps, idx, ts = [], [], []
    for ep, n in lengths.items():
        eps += [ep] * n
        idx += list(range(n))
        ts += [i / FPS for i in range(n)]
    pq.write_table(
        pa.table(
            {
                "episode_index": pa.array(eps, type=pa.int64()),
                "frame_index": pa.array(idx, type=pa.int64()),
                "timestamp": pa.array(ts, type=pa.float64()),
                "action": pa.array([[0.0, 1.0]] * len(eps), type=pa.list_(pa.float32())),
            }
        ),
        path,
    )


def _info(version: str, video_path: str, data_path: str) -> dict:
    return {
        "codebase_version": version,
        "fps": FPS,
        "chunks_size": 1000,
        "data_path": data_path,
        "video_path": video_path,
        "features": {
            KEY: {"dtype": "video", "shape": [24, 32, 3]},
            "action": {"dtype": "float32", "shape": [2]},
        },
    }


def _make_v2(tmp_path: Path, lengths: dict[int, int]) -> Path:
    root = tmp_path / "v2"
    info = _info(
        "v2.1",
        "videos/chunk-{episode_chunk:03d}/{video_key}/episode_{episode_index:06d}.mp4",
        "data/chunk-{episode_chunk:03d}/episode_{episode_index:06d}.parquet",
    )
    (root / "meta").mkdir(parents=True)
    (root / "meta/info.json").write_text(json.dumps(info))
    (root / "meta/episodes.jsonl").write_text(
        "".join(json.dumps({"episode_index": e, "length": n}) + "\n" for e, n in lengths.items())
    )
    for ep, n in lengths.items():
        _write_frames(root / f"data/chunk-000/episode_{ep:06d}.parquet", {ep: n})
        _write_mp4(root / f"videos/chunk-000/{KEY}/episode_{ep:06d}.mp4", n)
    return root


def _v2_video(root: Path, ep: int) -> Path:
    return root / f"videos/chunk-000/{KEY}/episode_{ep:06d}.mp4"


def _make_v3(tmp_path: Path, lengths: dict[int, int], video_frames: int | None = None) -> Path:
    """All episodes concatenated into one data file and one video file."""
    root = tmp_path / "v3"
    info = _info(
        "v3.0",
        "videos/{video_key}/chunk-{chunk_index:03d}/file-{file_index:03d}.mp4",
        "data/chunk-{chunk_index:03d}/file-{file_index:03d}.parquet",
    )
    (root / "meta/episodes/chunk-000").mkdir(parents=True)
    (root / "meta/info.json").write_text(json.dumps(info))
    _write_frames(root / "data/chunk-000/file-000.parquet", lengths)
    total = sum(lengths.values())
    _write_mp4(root / f"videos/{KEY}/chunk-000/file-000.mp4", video_frames or total)

    starts, t = [], 0
    for n in lengths.values():
        starts.append(t / FPS)
        t += n
    eps = list(lengths)
    pq.write_table(
        pa.table(
            {
                "episode_index": eps,
                "length": list(lengths.values()),
                f"videos/{KEY}/chunk_index": [0] * len(eps),
                f"videos/{KEY}/file_index": [0] * len(eps),
                f"videos/{KEY}/from_timestamp": starts,
                f"videos/{KEY}/to_timestamp": [
                    s + n / FPS for s, n in zip(starts, lengths.values())
                ],
            }
        ),
        root / "meta/episodes/chunk-000/file-000.parquet",
    )
    return root


def _levels(result) -> dict[str, RiskLevel]:
    return {f.metric: f.level for f in result.flags}


# ── v2 ────────────────────────────────────────────────────────────────────────


def test_v2_healthy(tmp_path):
    root = _make_v2(tmp_path, {0: 20, 1: 25, 2: 15})
    result = check_video_integrity(root)
    assert result.n_checked == 3
    assert _levels(result) == {m: RiskLevel.OK for m in VIDEO_METRICS}
    assert result.affected == {}


def test_v2_missing_video(tmp_path):
    root = _make_v2(tmp_path, {0: 20, 1: 20, 2: 20})
    _v2_video(root, 1).unlink()
    result = check_video_integrity(root)
    assert _levels(result)["video_missing_rate"] == RiskLevel.CRITICAL
    assert result.affected == {"video_missing_rate": [1]}
    flag = next(f for f in result.flags if f.metric == "video_missing_rate")
    assert flag.observed.value == pytest.approx(1 / 3)


def test_v2_truncated_video(tmp_path):
    root = _make_v2(tmp_path, {0: 20, 1: 20})
    path = _v2_video(root, 0)
    path.write_bytes(path.read_bytes()[: path.stat().st_size // 2])
    result = check_video_integrity(root)
    assert result.affected.get("video_decode_failure_rate") == [0]


def test_v2_video_shorter_than_episode(tmp_path):
    root = _make_v2(tmp_path, {0: 20, 1: 20})
    _write_mp4(_v2_video(root, 1), 12)
    result = check_video_integrity(root)
    assert result.affected == {"video_frame_mismatch_rate": [1]}


def test_v2_one_frame_difference_tolerated(tmp_path):
    root = _make_v2(tmp_path, {0: 20})
    _write_mp4(_v2_video(root, 0), 19)
    assert check_video_integrity(root).affected == {}


def test_v2_fps_mismatch(tmp_path):
    root = _make_v2(tmp_path, {0: 20, 1: 20})
    _write_mp4(_v2_video(root, 0), 20, fps=30)
    result = check_video_integrity(root)
    assert result.affected["video_fps_mismatch_rate"] == [0]
    flag = next(f for f in result.flags if f.metric == "video_fps_mismatch_rate")
    assert flag.observed.value == pytest.approx(0.5)  # per file


def test_lengths_from_batch_override_meta(tmp_path):
    root = _make_v2(tmp_path, {0: 20})
    result = check_video_integrity(root, episode_lengths={0: 40})
    assert result.affected == {"video_frame_mismatch_rate": [0]}


# ── v3 ────────────────────────────────────────────────────────────────────────


def test_v3_healthy(tmp_path):
    root = _make_v3(tmp_path, {0: 20, 1: 30, 2: 10})
    result = check_video_integrity(root)
    assert result.n_checked == 3
    assert result.affected == {}


def test_v3_video_file_too_short_flags_cut_episodes(tmp_path):
    # Episode 1 (frames 20-49) is cut short; episode 2 (50-59) is absent entirely.
    root = _make_v3(tmp_path, {0: 20, 1: 30, 2: 10}, video_frames=45)
    result = check_video_integrity(root)
    assert result.affected == {"video_frame_mismatch_rate": [1, 2]}


def test_v3_one_frame_overrun_tolerated(tmp_path):
    root = _make_v3(tmp_path, {0: 20, 1: 30}, video_frames=49)
    assert check_video_integrity(root).affected == {}


def test_v3_span_disagrees_with_length(tmp_path):
    root = _make_v3(tmp_path, {0: 20, 1: 30})
    result = check_video_integrity(root, episode_lengths={0: 20, 1: 25})
    assert result.affected == {"video_frame_mismatch_rate": [1]}


def test_v3_missing_shared_file_flags_every_episode(tmp_path):
    root = _make_v3(tmp_path, {0: 20, 1: 30})
    (root / f"videos/{KEY}/chunk-000/file-000.mp4").unlink()
    assert check_video_integrity(root).affected == {"video_missing_rate": [0, 1]}


# ── not evaluated ─────────────────────────────────────────────────────────────


def test_no_video_features(tmp_path):
    root = _make_v2(tmp_path, {0: 5})
    info = json.loads((root / "meta/info.json").read_text())
    info["features"].pop(KEY)
    (root / "meta/info.json").write_text(json.dumps(info))
    result = check_video_integrity(root)
    assert result.flags == [] and result.not_evaluated_reason


def test_without_opencv(tmp_path, monkeypatch):
    import calibra.video_integrity as vi

    root = _make_v2(tmp_path, {0: 5})
    monkeypatch.setattr(vi, "_require_cv2", lambda: None)
    result = vi.check_video_integrity(root)
    assert result.flags == []
    assert "opencv" in result.not_evaluated_reason


# ── calibra integrity CLI ─────────────────────────────────────────────────────


def test_integrity_cli_blocks_on_missing_video(tmp_path, capsys):
    from calibra.integrity import run_integrity

    root = _make_v2(tmp_path, {0: 20, 1: 20, 2: 20})
    _v2_video(root, 2).unlink()
    with pytest.raises(SystemExit) as exc:
        run_integrity([str(root), "--json"])
    out = json.loads(capsys.readouterr().out)
    assert exc.value.code == 1
    assert out["ci_result"] == "Failed"
    crit = {f["metric"]: f for f in out["critical"]}
    assert crit["video_missing_rate"]["suggested_action"] == "block"
    assert out["video_affected_episodes"] == {"video_missing_rate": [2]}


def test_integrity_cli_healthy_videos_pass(tmp_path, capsys):
    from calibra.integrity import run_integrity

    root = _make_v2(tmp_path, {0: 20, 1: 20})
    with pytest.raises(SystemExit):
        run_integrity([str(root), "--json"])
    out = json.loads(capsys.readouterr().out)
    passed = {f["metric"] for f in out["passed"]}
    assert set(VIDEO_METRICS) <= passed
    assert not [n for n in out["not_evaluated"] if n["check"] == "video_integrity"]
