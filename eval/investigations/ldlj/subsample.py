"""
Same trajectories, different sampling rate: smoothness metrics on a dataset
subsampled by keeping every k-th step (see SUBSAMPLING.md).

Usage:
    python eval/investigations/ldlj/subsample.py lerobot/aloha_static_battery 6,13
    python eval/investigations/ldlj/subsample.py lerobot/aloha_sim_insertion_human 6,13
"""

from __future__ import annotations

import dataclasses
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from calibra.analyzers.base import parse_gripper_dims  # noqa: E402
from calibra.analyzers.smoothness import ControlSmoothnessAnalyzer  # noqa: E402
from calibra.ingestion.registry import load  # noqa: E402
from calibra.schema.episode import EpisodeBatch  # noqa: E402

STEPS = (1, 2, 5, 10)


def subsample(batch: EpisodeBatch, k: int) -> EpisodeBatch:
    episodes = [
        dataclasses.replace(
            ep,
            timestamps=ep.timestamps[::k],
            actions=ep.actions[::k],
            observations={key: v[::k] for key, v in ep.observations.items()},
        )
        for ep in batch.episodes
    ]
    return dataclasses.replace(batch, episodes=episodes)


def main() -> None:
    name, dims = sys.argv[1], parse_gripper_dims(sys.argv[2] if len(sys.argv) > 2 else None)
    batch = load(name)
    base_hz = 1.0 / float(batch.episodes[0].timestamps[1] - batch.episodes[0].timestamps[0])
    analyzer = ControlSmoothnessAnalyzer(gripper_dims=dims)
    for k in STEPS:
        raw = analyzer.analyze(subsample(batch, k)).raw_metrics
        print(
            f"{name} @ {base_hz / k:4.0f} Hz: ldlj {raw['ldlj']['mean_ldlj']:7.2f}  "
            f"spike {raw['jerk_spikes']['mean_spike_fraction']:.2%}  "
            f"vel_disc {raw['vel_discontinuities']['mean_disc_fraction']:.2%}"
        )


if __name__ == "__main__":
    main()
