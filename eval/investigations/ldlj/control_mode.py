"""
Control mode at a matched native rate (see SUBSAMPLING.md): lerobot/pusht (sim,
absolute (x, y) position targets, 10 Hz) vs lerobot/columbia_cairlab_pusht_real
(real, velocity commands in action dims 0-1, 10 Hz). Also checks that the
cairlab actions are per-step state changes.

Usage:
    python eval/investigations/ldlj/control_mode.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from calibra.analyzers.smoothness import ControlSmoothnessAnalyzer  # noqa: E402
from calibra.ingestion.registry import load  # noqa: E402

UNUSED_DIMS = [2, 3, 4, 5, 6]  # cairlab action dims that are always zero


def delta_check(batch) -> tuple[float, float]:
    """Median corr(action, next state change) and corr(action, state) on dims 0-1."""
    key = next(iter(batch.episodes[0].observations))
    c_delta, c_state = [], []
    for ep in batch.episodes:
        a = ep.actions[:-1, :2].astype(float)
        s = ep.observations[key][:, :2].astype(float)
        ds = s[1:] - s[:-1]
        for d in range(2):
            if a[:, d].std() > 0 and ds[:, d].std() > 0:
                c_delta.append(np.corrcoef(a[:, d], ds[:, d])[0, 1])
                c_state.append(np.corrcoef(a[:, d], s[:-1, d])[0, 1])
    return float(np.median(c_delta)), float(np.median(c_state))


def main() -> None:
    real = load("lerobot/columbia_cairlab_pusht_real")
    c_delta, c_state = delta_check(real)
    print(
        f"cairlab corr(action, next state change) {c_delta:.2f}, corr(action, state) {c_state:.2f}"
    )
    for name, batch, mode, dims in (
        ("lerobot/pusht (sim, position)", load("lerobot/pusht"), "position", []),
        ("columbia_cairlab_pusht_real (real, velocity)", real, "velocity", UNUSED_DIMS),
    ):
        raw = (
            ControlSmoothnessAnalyzer(action_type=mode, gripper_dims=dims)
            .analyze(batch)
            .raw_metrics
        )
        ldlj = raw["ldlj"]
        print(
            f"{name:46s} ldlj {ldlj['mean_ldlj']:.2f} ({ldlj['ci_lower']:.2f}..{ldlj['ci_upper']:.2f})  "
            f"spike {raw['jerk_spikes']['mean_spike_fraction']:.2%}  "
            f"vel_disc {raw['vel_discontinuities']['mean_disc_fraction']:.2%}"
        )


if __name__ == "__main__":
    main()
