# batch-001 labeling record

- **Dataset:** lerobot/pusht @ `7628202a2180972f291ba1bc6723834921e72c19` (v3.0, 1 camera, 10 fps)
- **Items:** 50 (20 of 48 flagged, top 10 of review queue, 20 random controls)
- **Labeler:** AI first pass (Claude), 2026-10-16. **Not yet verified by a human.**
  Every row's `notes` starts with `[AI first pass, needs human check]`. Do not
  quote numbers from this batch until a human has confirmed or corrected the labels.
- **Blinding:** labels were assigned from the episodes only; `key.jsonl` and the
  Calibra snapshot were not opened until all 50 labels were written.

## Evidence used per episode

Rendered from the dataset files, not from Calibra output:

- 10 evenly spaced video frames plus the final frame (is the T on the target?)
- commanded (action) vs actual (state) xy path
- per-step |Δaction| over time, reward over time, video frame difference over time
- timestamp gaps, decoded vs expected frame count
- for the largest action jump: direction of the following step (out-and-back
  glitch vs continued motion) and whether the state converged to the new target
- frames unchanged while the agent state moved > 25 px (frozen camera / desync)

Dataset context: final reward over all 206 episodes is 0.84 to 0.93 (p5 to p95),
and `next.success` is false on every row, so "success" was judged from the final
frame and reward relative to the dataset, not the 0.95 threshold.

## Rules applied

| Label | Rule |
|---|---|
| `acquisition_fault` | timestamp gap, frame count mismatch, frozen frames while the agent moves, out-and-back action glitch. **None found.** |
| `execution_failure` | final frame does not show the T on the target. **None found.** |
| `unusual_valid` | valid demo with max \|Δaction\| above the dataset p90 (71 px) or length above the dataset p95 (186 steps): episodes 3, 4, 174 |
| `clean` | everything else (47) |

## Re-score with the PushT dataset profile

The first snapshot ran on a local copy (`./pusht`) without `--profile pusht`, so Stage 1 used
the global limits (spike 0.10, vel_disc 0.25). Hub IDs get the profile automatically; local
copies do not. With the profile (`snapshots/lerobot__pusht__0.12.0__profile-pusht.json`,
limits 0.25 / 0.40): **0 Stage-1 drops** (was 48), 0 false positives on this batch.
The drops below therefore measure the global defaults, not a correctly configured run. The
product gap is that local copies silently lose their profile.

## Result (Calibra 0.12.0, global defaults, provisional)

- Stage 1 drops (all `jerk_spike` in this sample): 0 of 20 sampled are
  acquisition faults; 18 clean, 2 unusual_valid.
- anomaly_score >= 0.8 fired on all 3 unusual_valid episodes and 12 clean ones.
- No acquisition faults exist in this sample, so recall is not measurable on
  PushT (a rendered simulation). Real-robot datasets are needed for that.
