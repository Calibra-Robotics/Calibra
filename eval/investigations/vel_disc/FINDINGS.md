# Why `velocity_discontinuity_rate` was CRITICAL on clean datasets

- **Date:** 2026-10-17
- **Calibra:** 0.12.0 + unreleased (`calibra/analyzers/smoothness.py`, `_episode_vel_disc_fraction`)
- **Data:** lerobot/pusht @ `7628202a`, lerobot/unitreeh1_rearrange_objects @ `e874d89b`,
  lerobot/aloha_static_battery @ `06dc3da8` (all episodes labeled valid, batches 001-003)
- **Reproduce:** `python eval/investigations/vel_disc/probe.py pusht data/unitreeh1_rearrange_objects data/aloha_static_battery`
- **Status:** fixed for the flag's severity; the raw rate is unchanged for calibrated consumers.

## Metric

Fraction of steps with ‖Δv‖ > 20% of the episode's peak speed; WARNING at 2%, CRITICAL at 5%.
It was CRITICAL on all three datasets although every labeled episode is valid
(PushT 16.7%, H1 6.3%, ALOHA 6.5%).

## Causes (probe output)

**A. Coarse sampling.** Perfectly smooth minimum-jerk movements trip it whenever a movement
spans fewer than ~15 samples: 1 s movements at 10 Hz score 60.6%, 0.5 s at 30 Hz 13.4%, any
of them at 50 Hz 0%. PushT (10 Hz mouse teleop) is this case: the metric measures sampling
resolution, not discontinuity.

**B. Sensor noise at high rates.** Smooth 1 s movements at 50 Hz: noise 1e-4 → 0%,
3e-4 → 51%, 1e-3 → 99%.

**C. Held commands (refuted for this data).** A teleop device updating slower than the
recording rate would trip it (k = 2: 76%), but H1 and ALOHA have 0.2–0.3% zero-change steps
and no flagged step is next to one.

**Low-pass test on real data** (same ~10 Hz moving average LDLJ uses):

| Dataset | Unfiltered | Filtered |
|---|---|---|
| pusht (10 Hz) | 16.7% | 16.7% (filter is a no-op at 10 Hz) |
| unitreeh1_rearrange_objects (50 Hz) | 6.3% | 3.8% |
| aloha_static_battery (50 Hz) | 6.5% | **0.0%** |

**The unfiltered rate is non-monotone in real faults.** Injecting spikes with
`calibra corrupt`'s method (swap a step with a distant one) into ALOHA:

| Spikes | Unfiltered | Filtered |
|---|---|---|
| none | 6.5% | 0.0% |
| 0.5% of steps | **2.9%** | 3.8% |
| 1% | 5.7% | 7.5% |
| 2% | 11.2% | 14.3% |

A spike inflates peak speed, which raises the threshold and hides the noise that was being
counted, so lightly corrupted data scored better than clean data. Filtered, the rate rises
monotonically with corruption (H1: 3.8% → 6.0 → 8.6 → 13.7%).

## Fix

The flag's severity now uses the filtered rate; its text shows the unfiltered rate when they
differ. The unfiltered rate is unchanged in `raw_metrics["vel_discontinuities"]["mean_disc_fraction"]`
and per-episode values, because regime thresholds (4% / 13%), Stage-1 prune limits, the
PushT profile's evidence, the Calibra Score and claim VD-001 were calibrated on it. The
filtered values are added as `mean_disc_fraction_filtered` and `episode_values_filtered`.

Result: ALOHA CRITICAL → OK, H1 CRITICAL → WARNING (remaining steps are hand open/close
jumps), PushT unchanged (coarse sampling, handled by its dataset profile for regime and
pruning). Very heavy noise (1e-3 at 50 Hz) still filters to ~2.4%, a WARNING.

## Not changed

Coarse sampling (cause A) still makes 10 Hz datasets with fast motion CRITICAL. Making the
threshold depend on samples per movement would change the raw rate every consumer uses, so it
needs its own evidence round.
