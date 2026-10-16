# Why `ldlj` is CRITICAL on every official LeRobot dataset

- **Date:** 2026-10-16
- **Calibra:** 0.12.0 + unreleased (`calibra/analyzers/smoothness.py`, `_episode_ldlj`)
- **Data:** lerobot/pusht @ `7628202a2180972f291ba1bc6723834921e72c19`; synthetic trajectories
- **Reproduce:** `python eval/investigations/ldlj/probe.py ./pusht eval/real_faults/batches/batch-001/sheet.csv`
- **Status:** investigation only. The detector, thresholds and scores are unchanged.

## Observation

In the community audit (`results/community/`, Calibra 0.6.0, 30 official
datasets) `ldlj` was CRITICAL on all 30 and WARNING-or-worse on 30/30. A
detector that fires on every dataset carries no information about which one
is worse.

## Cause

LDLJ = −ln((T³ / v_max²) ∫‖jerk‖² dt) was defined for a **single discrete
movement**, where minimum-jerk motion scores about −6 and the "−3 to −7 is
smooth" range in the analyzer docstring comes from. A demonstration is a chain
of movements. For N identical minimum-jerk sub-movements the inner term scales
as N⁴, so

  LDLJ ≈ −5.9 − 4 ln N

independent of how smooth each movement is. The −10 warning / −15 critical
thresholds are crossed at about N = 3 and N = 10 *perfectly smooth* movements.

On top of that, LDLJ differentiates positions three times, so measurement
noise is amplified by 1/dt³: the same noise costs far more at 50 Hz than at
10 Hz.

## Evidence (probe output)

**A. Perfectly smooth minimum-jerk chains**, Calibra's own `_episode_ldlj`:

| N movements | 10 Hz | 50 Hz | −5.9 − 4 ln N |
|---:|---:|---:|---:|
| 1 | −4.50 | −5.13 | −5.90 |
| 3 | −9.00 | −9.36 | −10.29 |
| 10 | −13.91 | −14.18 | −15.11 |
| 30 | −18.42 | −18.65 | −19.50 |

The slope matches −4 ln N; the offset differs by about 1 from discrete differentiation.

**B. N = 10 chain plus position noise** (std relative to a movement size of 0.2):

| fps | no noise | 1e-4 | 1e-3 |
|---:|---:|---:|---:|
| 10 | −13.91 | −13.98 | −15.94 |
| 50 | −14.18 | −20.92 | −24.82 |

**C. Real PushT** (206 episodes, 10 Hz): median −16.37 (range −19.26 to −12.56);
206/206 below −10, 179/206 below −15. **corr(LDLJ, ln episode length) = −0.95.**
In the labeled batch-001 (provisional AI labels), clean episodes have median
−16.72 and unusual_valid episodes median −17.03: LDLJ does not separate them.

## Impact today

- **Calibra Score:** LDLJ is up to 15 of 100 points (control smoothness), and
  CRITICAL scores 0, so long or high-rate datasets lose about 15 points for
  their length and sensor noise.
- **`calibra integrity`:** `ldlj` is a motion-review metric (`inspect`), so it
  never fails CI, but it is always shown as a CRITICAL finding.
- **Stage 1 pruning:** the per-episode floor is −30 (`_DEFAULT_MIN_LDLJ`);
  PushT's minimum is −19.3, so LDLJ drives no PushT drops.

## Options (not implemented; need evidence from labeled real-robot data first)

1. Compute LDLJ per sub-movement (segment at velocity minima) and aggregate,
   which is how the motor-control literature applies it to multi-movement tasks.
2. Normalize for movement count or duration, then recalibrate thresholds on
   labeled data.
3. Low-pass or resample to a fixed rate before differentiating, so the sampling
   rate stops dominating.
4. Demote dataset-level `ldlj` to INFO until one of the above is validated.

Any change also moves the Calibra Score for every dataset, so it needs a
CHANGELOG entry and regenerated goldens and claims.
