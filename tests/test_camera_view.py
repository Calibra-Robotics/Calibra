"""Tests for the Camera View Mismatch Analyzer."""

from __future__ import annotations

import zlib

import numpy as np

from calibra.analyzers.camera_view import (
    CameraViewMismatchAnalyzer,
    compute_egomotion_correlation,
    declared_viewpoint,
)
from calibra.schema.episode import Episode, EpisodeBatch, EpisodeMetadata
from calibra.schema.report import RiskLevel

# ── fixtures ─────────────────────────────────────────────────────────────────

_H = _W = 8
_T = 40


def _wrist_frames(action_motion: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """Frames whose whole-frame change tracks arm motion — a wrist camera.

    A uniform full-frame offset proportional to the cumulative action motion is
    added each step, so mean abs inter-frame difference ∝ action motion, i.e.
    egomotion correlation ≈ 1.
    """
    cum = np.concatenate([[0.0], np.cumsum(action_motion)])  # (T,)
    base = rng.random((_H, _W, 3)).astype(np.float32)
    return (base[None] + cum[:, None, None, None].astype(np.float32) * 10.0).astype(np.float32)


def _fixed_frames(rng: np.random.Generator) -> np.ndarray:
    """Frames that change independently of the arm — a fixed camera."""
    return (rng.random((_T, _H, _W, 3)) * 255).astype(np.float32)


def _make_ep(episode_id: str, cams: dict[str, str]) -> Episode:
    # zlib.crc32 (not builtin hash()) so the seed is stable across PYTHONHASHSEED.
    rng = np.random.default_rng(zlib.crc32(episode_id.encode()) % (2**31))
    ts = np.arange(_T, dtype=np.float64) * 0.05
    actions = rng.random((_T, 6)).astype(np.float32)
    action_motion = np.linalg.norm(np.diff(actions, axis=0), axis=1)

    obs: dict = {"proprio": rng.random((_T, 8)).astype(np.float32)}
    for key, mode in cams.items():
        obs[key] = _wrist_frames(action_motion, rng) if mode == "wrist" else _fixed_frames(rng)

    return Episode(
        metadata=EpisodeMetadata(episode_id=episode_id),
        timestamps=ts,
        observations=obs,
        actions=actions,
    )


def _make_batch(cams: dict[str, str], n: int = 5) -> EpisodeBatch:
    episodes = [_make_ep(f"ep_{i}", cams) for i in range(n)]
    return EpisodeBatch(
        episodes=episodes, dataset_name="cam_view_test", format="hdf5", source_path="/dummy.h5"
    )


# ── declared_viewpoint ───────────────────────────────────────────────────────


class TestDeclaredViewpoint:
    def test_wrist_names_are_moving(self):
        for key in ("camera_wrist", "images.wrist", "obs/gripper_cam", "robot0_eye_in_hand_image"):
            assert declared_viewpoint(key) == "moving"

    def test_fixed_names_are_static(self):
        for key in ("camera_top", "images.overhead", "agentview_image", "camera_front"):
            assert declared_viewpoint(key) == "static"

    def test_laptop_is_unknown_not_static(self):
        # "laptop" contains "top" — must not be misread as an overhead view.
        assert declared_viewpoint("images.laptop") == "unknown"

    def test_generic_names_are_unknown(self):
        for key in ("camera_main", "images.rgb", "camera0", "webcam"):
            assert declared_viewpoint(key) == "unknown"


# ── compute_egomotion_correlation ────────────────────────────────────────────


class TestEgomotionCorrelation:
    def test_wrist_frames_high_correlation(self):
        rng = np.random.default_rng(0)
        actions = rng.random((_T, 6)).astype(np.float32)
        am = np.linalg.norm(np.diff(actions, axis=0), axis=1)
        r = compute_egomotion_correlation(_wrist_frames(am, rng), actions)
        assert r is not None and r > 0.9

    def test_fixed_frames_low_correlation(self):
        rng = np.random.default_rng(1)
        actions = rng.random((_T, 6)).astype(np.float32)
        r = compute_egomotion_correlation(_fixed_frames(rng), actions)
        assert r is not None and abs(r) < 0.5

    def test_static_scene_returns_none(self):
        # No motion in either signal → nothing to correlate.
        frames = np.zeros((_T, _H, _W, 3), dtype=np.float32)
        actions = np.zeros((_T, 6), dtype=np.float32)
        assert compute_egomotion_correlation(frames, actions) is None

    def test_too_few_frames_returns_none(self):
        rng = np.random.default_rng(2)
        assert (
            compute_egomotion_correlation(
                rng.random((3, _H, _W, 3)).astype(np.float32), rng.random((3, 6)).astype(np.float32)
            )
            is None
        )


# ── CameraViewMismatchAnalyzer ───────────────────────────────────────────────


class TestCameraViewMismatchAnalyzer:
    def test_consistent_naming_is_ok(self):
        batch = _make_batch({"camera_wrist": "wrist", "camera_top": "fixed"})
        result = CameraViewMismatchAnalyzer().analyze(batch)
        assert len(result.flags) == 1
        assert result.flags[0].level == RiskLevel.OK
        assert result.flags[0].metric == "camera_view_name_mismatch"

    def test_swapped_cameras_flagged_relative(self):
        # 'camera_top' behaves like a wrist cam; 'camera_wrist' behaves fixed.
        batch = _make_batch({"camera_top": "wrist", "camera_wrist": "fixed"})
        result = CameraViewMismatchAnalyzer().analyze(batch)
        assert any(f.level == RiskLevel.WARNING for f in result.flags)
        flagged = set(result.raw_metrics["flagged_camera_keys"])
        assert {"camera_top", "camera_wrist"} <= flagged

    def test_single_static_named_wrist_cam_warns(self):
        batch = _make_batch({"camera_top": "wrist"})
        result = CameraViewMismatchAnalyzer().analyze(batch)
        assert result.flags[0].level == RiskLevel.WARNING
        assert "camera_top" in result.raw_metrics["flagged_camera_keys"]

    def test_ambiguous_laptop_wrist_cam_info(self):
        batch = _make_batch({"images.laptop": "wrist"})
        result = CameraViewMismatchAnalyzer().analyze(batch)
        assert result.flags[0].level == RiskLevel.INFO
        assert "images.laptop" in result.raw_metrics["flagged_camera_keys"]

    def test_too_few_episodes_skips(self):
        batch = _make_batch({"camera_top": "wrist"}, n=2)
        result = CameraViewMismatchAnalyzer().analyze(batch)
        assert result.flags[0].level == RiskLevel.INFO
        assert "skipped" in result.raw_metrics

    def test_empty_batch_returns_no_flags(self):
        batch = EpisodeBatch(episodes=[], dataset_name="x", format="hdf5", source_path="/d.h5")
        result = CameraViewMismatchAnalyzer().analyze(batch)
        assert result.flags == []

    def test_requires_images_capability(self):
        assert CameraViewMismatchAnalyzer.requires == frozenset({"images"})
