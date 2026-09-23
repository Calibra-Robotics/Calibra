"""Tests for calibra.models.robot_jepa (world-model surprise scoring)."""

from __future__ import annotations

import numpy as np
import pytest

from calibra.models.robot_jepa import RobotJEPAConfig, score_by_jepa_surprise
from calibra.schema.episode import Episode, EpisodeBatch, EpisodeMetadata

torch = pytest.importorskip("torch")


def _batch(n: int = 8, T: int = 40) -> EpisodeBatch:
    rng = np.random.default_rng(0)
    episodes = []
    for i in range(n):
        t = np.linspace(0, 1, T)[:, None]
        state = np.sin(2 * np.pi * t * rng.uniform(0.5, 2.0, 3)).astype(np.float32)
        episodes.append(
            Episode(
                metadata=EpisodeMetadata(episode_id=str(i)),
                timestamps=np.arange(T, dtype=np.float64) * 0.1,
                observations={"state": state},
                actions=np.diff(state, axis=0, append=state[-1:]).astype(np.float32),
            )
        )
    return EpisodeBatch(episodes=episodes, dataset_name="toy", format="hdf5", source_path="toy")


def test_surprise_scores_are_reproducible():
    # Same data and seed must give the same scores, so `calibra prune` with the
    # default world-model strategy keeps the same coreset on every run.
    cfg = RobotJEPAConfig(n_epochs=3, hidden_dim=32, latent_dim=8)
    batch = _batch()
    torch.manual_seed(123)  # global RNG state must not matter
    first = score_by_jepa_surprise(batch, cfg)
    torch.manual_seed(456)
    second = score_by_jepa_surprise(batch, cfg)
    assert first and first == second


def test_scoring_leaves_global_rng_untouched():
    torch.manual_seed(7)
    expected = torch.rand(3)
    torch.manual_seed(7)
    score_by_jepa_surprise(_batch(), RobotJEPAConfig(n_epochs=1, hidden_dim=16, latent_dim=4))
    assert torch.equal(torch.rand(3), expected)
