"""
Regression tests for the integrity fault-injection benchmark findings
(eval/integrity_fault_injection/, PROTOCOL.md section 11).

Each test reproduces one confirmed result at minimal size with a synthetic
fixture. Detections are asserted as detections. Known misses are written as the
behaviour we would want and marked xfail(strict=True): if a detector change
fixes one, the test XPASSes, fails, and the marker has to be removed with the
change, so the benchmark report gets updated too.
"""

from __future__ import annotations

import shutil
import subprocess

import numpy as np
import pytest

from calibra.analyzers.camera_freeze import CameraFreezeAnalyzer
from calibra.analyzers.duplicate_frame import repeated_transitions
from calibra.analyzers.task_structure import TaskStructureAnalyzer
from calibra.analyzers.temporal import TemporalAnalyzer
from calibra.schema.episode import Episode, EpisodeBatch, EpisodeMetadata
from calibra.schema.report import RiskLevel

FPS = 50.0
NON_OK = (RiskLevel.WARNING, RiskLevel.CRITICAL)


def _episode(eid: int, n: int = 200, ts=None, frames=None, seed: int | None = None) -> Episode:
    rng = np.random.default_rng(eid if seed is None else seed)
    obs = {"observation.state": rng.random((n, 8)).astype(np.float32)}
    if frames is not None:
        obs["observation.images.cam"] = frames
    return Episode(
        metadata=EpisodeMetadata(episode_id=str(eid)),
        timestamps=np.arange(n) / FPS if ts is None else ts,
        observations=obs,
        actions=rng.random((n, 6)).astype(np.float32),
    )


def _batch(episodes: list[Episode]) -> EpisodeBatch:
    return EpisodeBatch(
        episodes=episodes, dataset_name="fi", format="lerobot", source_path="/dummy"
    )


def _level(analyzer, batch: EpisodeBatch, metric: str):
    flags = [f for f in analyzer.analyze(batch).flags if f.metric == metric]
    return flags[0].level if flags else None


def _texture(n: int, size: int = 96, seed: int = 0) -> np.ndarray:
    """A drifting textured scene: every frame differs from the last by more than noise."""
    rng = np.random.default_rng(seed)
    base = rng.integers(0, 256, (size, 2 * size, 3), dtype=np.uint8)
    return np.stack([base[:, i % size : i % size + size] for i in range(n)])


# ── duplicate episodes ──────────────────────────────────────────────────────


def test_exact_duplicate_episode_is_critical():
    eps = [_episode(i) for i in range(10)]
    copy = _episode(10, seed=3)  # byte-identical data to episode 3
    assert (
        _level(TaskStructureAnalyzer(), _batch(eps + [copy]), "duplicate_episode_fraction")
        == RiskLevel.CRITICAL
    )


def test_one_ulp_near_duplicate_is_not_flagged_by_design():
    eps = [_episode(i) for i in range(10)]
    near = _episode(10, seed=3)
    near.actions[5, 2] = np.nextafter(near.actions[5, 2], np.float32(np.inf))
    assert (
        _level(TaskStructureAnalyzer(), _batch(eps + [near]), "duplicate_episode_fraction")
        == RiskLevel.OK
    )


# ── timestamps ──────────────────────────────────────────────────────────────


def _with_gaps(run: int, every: int = 20, n: int = 200) -> np.ndarray:
    """Frame-grid timestamps with `run` consecutive steps removed every `every` steps."""
    keep = np.ones(n, bool)
    for s in range(10, n - run, every):
        keep[s : s + run] = False
    return (np.arange(n) / FPS)[keep]


def test_runs_of_three_dropped_steps_are_detected():
    eps = [_episode(i, n=len(t := _with_gaps(3)), ts=t) for i in range(5)]
    assert _level(TemporalAnalyzer(), _batch(eps), "timestamp_dropout_rate") in NON_OK


def test_single_dropped_steps_are_invisible_by_design():
    # One missing step leaves a 2x gap; dropout only counts gaps > 3x the median.
    eps = [_episode(i, n=len(t := _with_gaps(1, every=10)), ts=t) for i in range(5)]
    assert _level(TemporalAnalyzer(), _batch(eps), "timestamp_dropout_rate") == RiskLevel.OK


def _swapped(n_swapped: int, n: int = 10) -> list[Episode]:
    eps = []
    for i in range(n):
        ts = np.arange(200) / FPS
        if i < n_swapped:
            ts[[50, 51]] = ts[[51, 50]]
        eps.append(_episode(i, ts=ts))
    return eps


def test_non_monotonic_timestamps_in_one_episode_are_critical():
    # v0.13.0 missed this: jitter CV averaged over episodes diluted a swap in
    # 10% of episodes below threshold. timestamp_non_monotonic catches it.
    assert (
        _level(TemporalAnalyzer(), _batch(_swapped(1)), "timestamp_non_monotonic")
        == RiskLevel.CRITICAL
    )


def test_monotonic_timestamps_pass():
    assert (
        _level(TemporalAnalyzer(), _batch(_swapped(0)), "timestamp_non_monotonic") == RiskLevel.OK
    )


def test_one_episode_in_milliseconds_is_critical():
    # v0.13.0 missed this: ms timestamps still lie on a frame grid, so the
    # timing checks were reported as not evaluated.
    eps = [_episode(i) for i in range(10)]
    eps[4] = _episode(4, ts=np.arange(200) / FPS * 1000.0)
    assert _level(TemporalAnalyzer(), _batch(eps), "timestamp_scale_mismatch") == RiskLevel.CRITICAL


def test_consistent_time_scale_passes():
    eps = [_episode(i) for i in range(10)]
    eps[4] = _episode(4, ts=np.arange(200) / (FPS * 1.5))  # different rate, same unit
    assert _level(TemporalAnalyzer(), _batch(eps), "timestamp_scale_mismatch") == RiskLevel.OK


# ── frozen and repeated frames ──────────────────────────────────────────────


@pytest.mark.parametrize("run, expected", [(4, RiskLevel.OK), (5, RiskLevel.WARNING)])
def test_freeze_run_threshold(run, expected):
    eps = []
    for i in range(20):
        frames = _texture(100, seed=i)
        if i == 0:
            frames[41 : 41 + run] = frames[40]
        eps.append(_episode(i, n=100, frames=frames))
    assert _level(CameraFreezeAnalyzer(), _batch(eps), "camera_freeze_events") == expected


def _av1_roundtrip(frames: np.ndarray) -> np.ndarray:
    """Encode with LeRobot's settings (libsvtav1, GOP 2, crf 30, yuv420p) and decode."""
    n, h, w, _ = frames.shape
    enc = subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-v",
            "error",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-s",
            f"{w}x{h}",
            "-r",
            "50",
            "-i",
            "-",
            "-c:v",
            "libsvtav1",
            "-g",
            "2",
            "-crf",
            "30",
            "-pix_fmt",
            "yuv420p",
            "-f",
            "ivf",
            "-",
        ],
        input=frames.tobytes(),
        capture_output=True,
        check=True,
    ).stdout
    dec = subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-v",
            "error",
            "-f",
            "ivf",
            "-i",
            "-",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-",
        ],
        input=enc,
        capture_output=True,
        check=True,
    ).stdout
    return np.frombuffer(dec, np.uint8).reshape(-1, h, w, 3)


def _has_svtav1() -> bool:
    if shutil.which("ffmpeg") is None:
        return False
    out = subprocess.run(
        ["ffmpeg", "-hide_banner", "-encoders"], capture_output=True, text=True
    ).stdout
    return "libsvtav1" in out


def test_isolated_repeats_are_detected_before_encoding():
    frames = _texture(100)
    pos = np.arange(10, 90, 10)
    frames[pos] = frames[pos - 1]
    assert repeated_transitions(frames)[pos - 1].all()


def _encoded_repeats(pos: np.ndarray) -> float:
    frames = _texture(100)
    frames[pos] = frames[pos - 1]
    return float(repeated_transitions(_av1_roundtrip(frames))[pos - 1].mean())


@pytest.mark.skipif(not _has_svtav1(), reason="needs ffmpeg with libsvtav1")
def test_repeats_on_predicted_frames_survive_lerobot_encoding():
    # With GOP 2, odd frames are predicted from the keyframe before them.
    assert _encoded_repeats(np.arange(11, 90, 10)) == 1.0


@pytest.mark.skipif(not _has_svtav1(), reason="needs ffmpeg with libsvtav1")
@pytest.mark.xfail(
    strict=True,
    reason="a repeat that lands on a keyframe is re-encoded with fresh compression noise; "
    "duplicate_frame_rate is a lower bound on inter-coded video (fault-injection benchmark)",
)
def test_repeats_on_keyframes_survive_lerobot_encoding():
    assert _encoded_repeats(np.arange(10, 90, 10)) >= 0.5
