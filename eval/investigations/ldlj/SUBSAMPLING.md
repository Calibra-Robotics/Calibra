# Is per-sub-movement LDLJ comparable across sampling rates?

- **Date:** 2026-10-19
- **Calibra:** 0.13.1 + unreleased (`ldlj_definition: per_submovement_v1`)
- **Data:** lerobot/aloha_static_battery @ `06dc3da8`, lerobot/aloha_sim_insertion_human @ `cc571a3c` (both 50 Hz, `gripper_dims [6, 13]`)
- **Question:** claim LDLJ-001: does LDLJ change when only the sampling rate changes?
- **Status:** answered (yes, by 3 to 5 units over 50 → 5 Hz).

## Method

Take every episode's timestamps, actions and observations, keep every k-th
step (k = 1, 2, 5, 10 → 50, 25, 10, 5 Hz), and run `ControlSmoothnessAnalyzer`
on the result. The trajectories are the same; only the sampling rate changes.

## Results

| Dataset | Rate | LDLJ | Jerk spike rate | Vel. discontinuity |
|---|---:|---:|---:|---:|
| aloha_static_battery | 50 Hz | −12.63 | 0.45% | 5.46% |
| | 25 Hz | −9.86 | 0.39% | 2.93% |
| | 10 Hz | −8.57 | 1.55% | 14.11% |
| | 5 Hz | −7.53 | 3.22% | 32.72% |
| aloha_sim_insertion_human | 50 Hz | −11.01 | 0.35% | 1.45% |
| | 25 Hz | −9.23 | 0.66% | 3.56% |
| | 10 Hz | −8.82 | 4.35% | 15.57% |
| | 5 Hz | −8.38 | 6.43% | 27.92% |

For reference, lerobot/pusht (10 Hz, native) scores LDLJ −8.89, spike 4.9%,
vel. discontinuity 16.7%.

**Control mode at a matched native rate, same task.** `lerobot/pusht` (sim,
absolute (x, y) position targets) and `lerobot/columbia_cairlab_pusht_real`
(real robot, velocity commands: its actions correlate 1.00 with the next
state change and 0.03 with the state) are both recorded at 10 Hz:

| Dataset | Control | LDLJ (95% CI) | Jerk spikes | Vel. discontinuity |
|---|---|---:|---:|---:|
| lerobot/pusht | position | −8.89 (−9.01 to −8.78) | 4.95% | 16.7% |
| columbia_cairlab_pusht_real | velocity | −9.71 (−9.83 to −9.58) | 1.83% | 17.3% |

At the same rate LDLJ ranks position as smoother than velocity, the physically
expected order, by 0.8 units with non-overlapping CIs; velocity discontinuities
are nearly identical across the two control modes. Sim vs real is a remaining
confound. Reproduce: `python eval/investigations/ldlj/control_mode.py`.

**Control mode at a matched rate, across tasks.** nvidia/BridgeData2_LeRobot_v3 (velocity
command, native 5 Hz, revision `b96f7216`, last dim excluded) scores LDLJ
−8.70 (CI −8.71 to −8.70, 50,413 episodes). Against ALOHA at its native 50 Hz
(−11.0 to −13.2) the velocity-command data looks smoother, the physically
unexpected order. Against ALOHA subsampled to the same 5 Hz (−7.53, −8.38) the
order is the expected one (position smoother). On both matched-rate
comparisons the sampling rate, not the control mode, is what breaks
cross-dataset comparison.

BridgeData2 was measured from the revision's `data/` and `meta/` files only
(170 MB; loading the Hub ID instead downloads the whole repo, about 90 GB of
video). Its spike and velocity-discontinuity rates on this revision (0.81%,
59.9%) did not match the old `calibra/references/bridgedata_v2.json` (0.71%,
80.5%). The cause was the old file, not the data: it was labelled velocity
mode but its smoothness metrics had been computed in position mode, and the
June 2026 analyzer (commit `f8ec78b`) in position mode reproduces all three
old values exactly (spike 0.71%, vel_disc 80.5%, whole-episode LDLJ −13.79);
entropy, PCA, jitter and dropout were already identical. The reference was
re-profiled in velocity mode on 2026-10-20 and records its revision.

## Interpretation

- LDLJ rises (scores smoother) as the rate falls, from WARNING at 50 Hz to OK
  at 10 Hz, on identical motion. ALOHA subsampled to 10 Hz scores about the
  same as PushT at its native 10 Hz, so the PushT-vs-ALOHA gap is explained by
  sampling rate. This supports LDLJ-001.
- Jerk spike rate and velocity-discontinuity rate are also rate-dependent, in
  the opposite direction: velocity discontinuities grow about 10x from 50 to
  10 Hz on the same trajectories, to PushT's level. This bears on JS-003 (spike
  rate as the more frequency-robust metric), VD-001 (a position-command bound
  that does not state a rate) and the `pusht` profile's reading of its 16.7% as
  a mouse-teleop property. Not acted on here.

Reproduce:

```bash
python eval/investigations/ldlj/subsample.py lerobot/aloha_static_battery 6,13
python eval/investigations/ldlj/subsample.py lerobot/aloha_sim_insertion_human 6,13
```
