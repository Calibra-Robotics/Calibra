# Jerk Spike Rate

**Confidence: MODERATE** (2 datasets, same direction as velocity discontinuity,
but n too small to confirm thresholds)

---

## What it measures

Fraction of steps where the L2 norm of jerk exceeds 5× the median jerk magnitude
within the episode. Jerk here is the third derivative of the action signal (or
fewer derivatives if the action is already velocity or acceleration).

Spike detection is relative (multiples of median), not absolute, so it is
scale-invariant. A spike is meaningful relative to the episode's own motion
baseline.

---

## Rules with evidence

**Rule 1: Jerk spike rate depends on sampling rate; compare only at similar rates.**

| Dataset | Rate (native) | Spike rate |
|---------|---------------|-----------|
| lerobot/aloha_sim_insertion_human, 12 joint dims | 50 Hz | 0.35% |
| same trajectories, subsampled | 10 Hz | 4.35% |
| lerobot/pusht, absolute (x, y) targets | 10 Hz | 4.9% |

An earlier version of this page read the pusht/aloha gap (14×) as the metric
separating control modes. Subsampled to 10 Hz, aloha's own trajectories read
about what pusht reads at its native 10 Hz, so the gap is mostly sampling rate
([`SUBSAMPLING.md`](../../eval/investigations/ldlj/SUBSAMPLING.md)).

**Rule 2: The 2% warning threshold is correctly calibrated for position-command
datasets.**

aloha at 0.35% sits comfortably below the 2% warning level, consistent with clean
teleop position commands.

**Rule 3 (retracted 2026-10-20): "jerk spike rate is more frequency-robust than LDLJ".**

The reasoning was that the 5× median threshold scales with control frequency, so
the spike fraction would be roughly frequency-invariant. Tested on the same
trajectories at different rates, it is not: aloha insertion goes from 0.35% at
50 Hz to 4.35% at 10 Hz (12×, crossing the 2% warning level), aloha battery from
0.45% to 1.55%. LDLJ moves by 2 to 4 units over the same range. Neither metric is
frequency-robust (claim JS-003 is under review).

---

## Open questions (needs more datasets)

1. **Does the 5× multiplier hold across action types?** The spike_k=5 was set from
   synthetic data. Real datasets with bimodal motion (slow approach, fast grasp)
   may have episodes where the fast phase is systematically flagged as "spikes"
   relative to the slow-phase median.

2. **How does it behave on high-speed manipulation?** Datasets like DROID or
   Berkeley Humanoid may have much higher absolute velocities. The relative
   threshold should handle this, but needs validation.

3. **Correlation with task success.** Same question as velocity discontinuity: do
   failed episodes have higher spike rates? This would confirm the metric has
   quality-predictive value beyond describing the control mode.

---

## Known failure modes

**Bimodal motion episodes.** In a task where the robot moves fast to approach and
then slows for fine manipulation, the fast-approach steps could register as "spikes"
relative to the manipulation-phase median. This would inflate spike rates for
tasks with strong speed transitions. Watch for this in pick-and-place datasets.

---

## Datasets profiled

- `references/pusht_velocity_command.json` — velocity-command reference (4.9%)
- `references/aloha_sim_insertion_human.json` — position-command reference (0.35%, grippers excluded)
