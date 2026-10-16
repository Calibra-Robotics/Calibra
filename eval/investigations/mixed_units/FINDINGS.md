# Mixed action units in the smoothness metrics

- **Date:** 2026-10-17
- **Calibra:** 0.12.0 + unreleased (`calibra/analyzers/smoothness.py`)
- **Data:** lerobot/unitreeh1_rearrange_objects @ `e874d89b`, lerobot/aloha_static_battery @
  `06dc3da8`, lerobot/pusht @ `7628202a` (local copies)
- **Status:** investigated, **not changed**. No verdict improves on the labeled data.

## Question

`ldlj`, `jerk_spike_rate` and `velocity_discontinuity_rate` combine all active action
dimensions into one velocity norm. If dimensions use different units, the large-unit ones
dominate. Should each dimension be normalized first?

## Evidence

Per-dimension action range (p5–p95):

| Dataset | Range across dims | Note |
|---|---|---|
| pusht | 309–328 (2 dims) | same units |
| aloha_static_battery | 0.05–1.2 (14 dims) | consistent units (≈20× spread) |
| unitreeh1_rearrange_objects | body 0.03–1.1 (26 dims), hands 22–107 (14 dims) | **mixed units**, hands 100–700× larger |

Plain per-dimension normalization would amplify ALOHA's small-range joints ~20× to fix a
problem only H1 has. The minimal candidate, rescaling only dims more than 10× the median
range down to the median range, touches exactly H1's 14 hand dims and leaves ALOHA and PushT
unchanged. Its effect on H1 (all labeled episodes clean, batch-002):

| Metric | Current | Rescaled hands |
|---|---|---|
| `velocity_discontinuity_rate` | 6.3% CRITICAL | 21.5% CRITICAL |
| `jerk_spike_rate` | 4.7% WARNING | 2.0% WARNING |
| `ldlj` | −12.05 WARNING | −12.65 WARNING |

No verdict changes, and none of these flags marks a real fault, so the change has no measured
benefit while moving scores. Not shipped. Revisit if a labeled dataset shows a verdict that
depends on units.

## What the evidence points at instead

`velocity_discontinuity_rate` is CRITICAL on all three datasets although every labeled
episode is valid (PushT 11.1% with global defaults, ALOHA 5.5%, H1 6.3%; thresholds 2% / 5%).
That is the same pattern `ldlj` showed before the per-sub-movement fix and is the next metric
to investigate.

## Reproduce

Rescale factor per dim: `ref / range if range > 10 * ref else 1`, with `ref` the median of the
per-dim p5–p95 ranges; multiply each episode's actions by it and run
`ControlSmoothnessAnalyzer().analyze(batch)` before and after.
