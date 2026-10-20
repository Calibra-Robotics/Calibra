# Velocity Discontinuity Rate

**Confidence: MODERATE.** Reliable within one dataset or between datasets at
similar sampling rates; the rate itself depends strongly on sampling rate
(claim VD-004).

---

## What it measures

Fraction of steps where the L2 norm of the velocity change exceeds 20% of the
episode's peak velocity. "Velocity" here means the numerical first derivative of
actions — so for position-command datasets, this is change in positional velocity;
for velocity-command datasets, it is change in the velocity signal itself.

A discontinuity in this sense is a step where the agent reverses or sharply alters
its motion faster than smooth physical actuation would allow.

---

## Rules with evidence

**Rule 1: The rate depends strongly on sampling rate; compare only at similar rates.**

| Dataset | Rate (native) | Velocity discontinuity |
|---------|---------------|------------------------|
| lerobot/aloha_sim_insertion_human, 12 joint dims | 50 Hz | 1.45% |
| same trajectories, subsampled | 10 Hz | 15.6% |
| lerobot/pusht, absolute (x, y) targets | 10 Hz | 16.7% |
| nvidia/BridgeData2_LeRobot_v3, velocity commands | 5 Hz | 59.9% |

An earlier version of this page read the pusht/aloha gap (11×) as the metric
separating control modes. Subsampling aloha's own trajectories to 10 Hz closes
most of that gap, so the rate mostly reflects the sampling rate
([`SUBSAMPLING.md`](../../eval/investigations/ldlj/SUBSAMPLING.md)). It does
not, on this evidence, identify control mode by itself.

**Rule 2: At 50 Hz, the 5% critical threshold does not false-positive on clean
ALOHA joint data, but it is not a universal bound.** aloha insertion reads
1.45%; real ALOHA tasks at the same rate range up to 8.1% (aloha_static_cups_open),
which falsified the old "position-command datasets below 5%" claim (VD-001).

**Rule 3: Judge a dataset against its own clean episodes, or against references
at the same sampling rate.** PushT's 16.7% is normal for PushT at 10 Hz (the
`pusht` profile judges it that way); it is not a property of velocity-command
teleop, and PushT is position control.

---

## Open questions (needs more datasets)

1. **Does the rate change the same way on data recorded natively at two rates?**
   Subsampling changes only the rate; a dataset recorded at two native rates
   would separate the sampling effect from sensor and controller effects (VD-004).

2. **Does the rate correlate with task success?** If failed episodes in a dataset
   have higher discontinuity rates than successful ones, the metric has quality
   predictive value. This requires a dataset with per-episode success labels.

3. **How does the 20% threshold interact with very high-frequency datasets?** At
   200Hz or above, a 20% velocity change per step is physically impossible for most
   hardware — the threshold may be too permissive and need tightening.

4. **Real hardware vs sim.** Both datasets so far are simulated. Real hardware adds
   sensor noise and actuation lag that could artificially elevate discontinuity rates
   even for clean teleoperation.

---

## Known failure modes

None confirmed yet. The metric behaved as expected on both datasets.

---

## Datasets profiled

- `references/pusht_velocity_command.json` — velocity-command reference (16.7%)
- `references/aloha_sim_insertion_human.json` — position-command reference (1.45%, grippers excluded)
