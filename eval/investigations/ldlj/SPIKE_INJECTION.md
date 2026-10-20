# Does per-sub-movement LDLJ detect injected jerk spikes?

- **Date:** 2026-10-19
- **Calibra:** 0.13.1 + unreleased (`ldlj_definition: per_submovement_v1`)
- **Data:** lerobot/aloha_static_battery @ `06dc3da8`, lerobot/aloha_sim_insertion_human @ `cc571a3c`, lerobot/svla_so100_stacking @ `476c6810`
- **Question:** claim LDLJ-002's falsification condition: does LDLJ distinguish a known-worse copy of a dataset from the clean one, within the same type?
- **Status:** answered (no, for this injector at dataset level; see Implications for a second benchmark where it partly does).

## Method

`calibra corrupt` with `--inject-spikes RATE` swaps RATE of each episode's
action steps with a step more than 10% of the episode away (`calibra/corrupt.py`,
`_inject_spikes`), then reruns the analyzers on the corrupted copy. ALOHA runs
exclude both grippers; SO-100 excludes its last dim (gripper). Seed 42.

```bash
calibra corrupt lerobot/aloha_static_battery      --inject-spikes 0.005 --gripper-dims 6,13
calibra corrupt lerobot/aloha_static_battery      --inject-spikes 0.02  --gripper-dims 6,13
calibra corrupt lerobot/aloha_sim_insertion_human --inject-spikes 0.02  --gripper-dims 6,13
calibra corrupt lerobot/aloha_sim_insertion_human --inject-spikes 0.05  --gripper-dims 6,13
calibra corrupt lerobot/svla_so100_stacking       --inject-spikes 0.02
calibra corrupt lerobot/svla_so100_stacking       --inject-spikes 0.05
```

## Results

LDLJ is expected to fall (more negative) on the corrupted copy.

| Dataset | Injected | Jerk spike rate | LDLJ clean → corrupted |
|---|---:|---|---|
| aloha_static_battery (50 Hz, real) | 0.5% | 0.5% → 4.3% | −12.63 → −12.66 (no response) |
| aloha_static_battery | 2% | 0.5% → 15.2% | −12.63 → −11.29 (**improves**) |
| aloha_sim_insertion_human (50 Hz, sim) | 2% | 0.4% → 15.0% | −11.01 → −10.54 (**improves**) |
| aloha_sim_insertion_human | 5% | 0.4% → 33.0% | −11.01 → −9.90 (**improves**) |
| svla_so100_stacking (real) | 2% | 1.0% → 13.9% | −10.64 → −10.99 (weak, right direction) |
| svla_so100_stacking | 5% | 1.0% → 30.5% | −10.64 → −10.55 (no response) |

Jerk spike rate responds strongly in every case. LDLJ responds in the expected
direction in 1 of 6 runs, and only weakly; on ALOHA it scores the corrupted
copy as smoother.

Until 2026-10-19 `calibra corrupt` listed any metric that moved under
"Detected by Calibra", including LDLJ when it improved. It now lists such
metrics under "Moved the wrong way".

## Interpretation

Per-sub-movement LDLJ does not distinguish these known-worse copies from the
clean data, which meets LDLJ-002's falsification condition.

Untested hypothesis for the inversion: each swap creates a large step, and the
speed minima around it split the episode into more, shorter sub-movements. The
duration-weighted mean then gives the short, jerky segments little weight, and
the remaining segments are each closer to a single smooth movement.

## Implications

- The result depends on the injector. `experiments/benign_firing_rate_benchmark.py`
  swaps *adjacent* steps (mixed with timestamp jitter and dropped frames) and
  uses per-episode MAD outliers; rerun on 2026-10-20 it catches 5 of 7
  corrupted episodes on aloha_sim_insertion_scripted with `ldlj`, but 0 of 30
  on PushT (`jerk_spike_rate`: 6/7 and 12/30). So LDLJ is not blind to faults;
  it is inconsistent, and `jerk_spike_rate` catches more on both datasets.
- `ldlj` was removed from `calibra integrity` on that basis; it still feeds
  the Calibra Score.
- Noise-type corruption (Gaussian action noise) is untested here; FINDINGS.md
  reports that heavy white noise still lowers LDLJ on synthetic data.
