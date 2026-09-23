"""Tests for the Duplicate Frame Analyzer."""

from __future__ import annotations

import numpy as np

from calibra.analyzers.duplicate_frame import DuplicateFrameAnalyzer, repeated_transitions
from calibra.schema.episode import Episode, EpisodeBatch, EpisodeMetadata
from calibra.schema.report import RiskLevel

# ── fixtures ─────────────────────────────────────────────────────────────────


def _make_ep(episode_id: str = "ep_0", n_steps: int = 30, image_mode: str = "random") -> Episode:
    rng = np.random.default_rng(0)
    ts = np.arange(n_steps, dtype=np.float64) * 0.05
    obs: dict = {"proprio": rng.random((n_steps, 8)).astype(np.float32)}

    if image_mode == "random":
        obs["camera_rgb"] = rng.integers(0, 255, (n_steps, 8, 8, 3), dtype=np.uint8)
    elif image_mode == "identical":
        frame = rng.integers(0, 255, (8, 8, 3), dtype=np.uint8)
        obs["camera_rgb"] = np.tile(frame, (n_steps, 1, 1, 1))
    # "none" → no image key at all

    return Episode(
        metadata=EpisodeMetadata(episode_id=episode_id),
        timestamps=ts,
        observations=obs,
        actions=rng.random((n_steps, 6)).astype(np.float32),
    )


def _make_batch(episodes: list[Episode]) -> EpisodeBatch:
    return EpisodeBatch(
        episodes=episodes, dataset_name="dup_test", format="hdf5", source_path="/dummy/path.h5"
    )


# ── tests ────────────────────────────────────────────────────────────────────


class TestDuplicateFrameAnalyzer:
    def test_all_identical_frames_flagged(self):
        batch = _make_batch([_make_ep(image_mode="identical")])
        result = DuplicateFrameAnalyzer().analyze(batch)
        flag = result.flags[0]
        assert flag.metric == "duplicate_frame_rate"
        assert flag.level in (RiskLevel.WARNING, RiskLevel.CRITICAL)
        assert flag.observed.value == 1.0

    def test_all_different_frames_ok(self):
        batch = _make_batch([_make_ep(image_mode="random")])
        result = DuplicateFrameAnalyzer().analyze(batch)
        flag = result.flags[0]
        assert flag.level == RiskLevel.OK
        assert flag.observed.value < 0.05

    def test_no_image_data_returns_info(self):
        batch = _make_batch([_make_ep(image_mode="none")])
        result = DuplicateFrameAnalyzer().analyze(batch)
        flag = result.flags[0]
        assert flag.level == RiskLevel.INFO
        assert result.raw_metrics["skipped"] == "no image observations"

    def test_empty_batch_returns_no_flags(self):
        batch = _make_batch([])
        result = DuplicateFrameAnalyzer().analyze(batch)
        assert result.flags == []

    def test_requires_images_capability(self):
        assert DuplicateFrameAnalyzer.requires == frozenset({"images"})


# ── repeated_transitions: what counts as a repeated frame ───────────────────


def _moving_dot_frames(n_steps: int = 30, size: int = 96) -> np.ndarray:
    """Static background with a small dot moving 1 px per step (PushT-like)."""
    frames = np.full((n_steps, size, size, 3), 200, dtype=np.uint8)
    for t in range(n_steps):
        frames[t, 40:46, 10 + t : 16 + t] = 30
    return frames


class TestRepeatedTransitions:
    def test_small_moving_object_is_not_a_repeat(self):
        # Mean abs diff here is ~0.3 (below the old 0.5 threshold), yet the
        # camera is clearly live: the old detector blocked PushT for this.
        frames = _moving_dot_frames()
        assert np.abs(np.diff(frames.astype(np.float32), axis=0)).mean() < 0.5
        assert not repeated_transitions(frames).any()

    def test_live_camera_on_still_scene_is_not_a_repeat(self):
        rng = np.random.default_rng(0)
        scene = np.full((20, 32, 32, 3), 120.0)
        noisy = np.clip(scene + rng.normal(0, 2.0, scene.shape), 0, 255).astype(np.uint8)
        assert not repeated_transitions(noisy).any()

    def test_re_emitted_frame_is_a_repeat(self):
        frames = _moving_dot_frames()
        frames[10:15] = frames[10]
        assert repeated_transitions(frames).tolist() == [9 < t < 14 for t in range(29)]

    def test_float_images_in_unit_range(self):
        frames = _moving_dot_frames().astype(np.float32) / 255.0
        frames[5] = frames[4]
        assert repeated_transitions(frames).tolist() == [t == 4 for t in range(29)]


def test_moving_object_dataset_not_flagged():
    episodes = []
    for i in range(3):
        ep = _make_ep(f"ep_{i}")
        ep.observations["camera_rgb"] = _moving_dot_frames(n_steps=ep.n_steps)
        episodes.append(ep)
    flag = DuplicateFrameAnalyzer().analyze(_make_batch(episodes)).flags[0]
    assert flag.level == RiskLevel.OK
