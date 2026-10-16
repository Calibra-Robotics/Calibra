# batch-002 labeling record

- **Dataset:** lerobot/unitreeh1_rearrange_objects @ `e874d89b9024bad414deb45d7da82fa93601c260`
  (v3.0, Unitree H1 humanoid with dexterous hands, 2 cameras 640×360, 50 fps, 30 episodes,
  task "Put the object into the bin.")
- **Calibra:** 0.12.0 + unreleased (per-sub-movement LDLJ, synthetic-timestamp handling)
- **Unit of evaluation:** one episode. All 30 episodes labeled (inclusion probability 1 for
  every item), so no sampling weights apply to this batch.
- **Labeler:** AI first pass (Claude), 2026-10-16. **Not yet verified by a human.**
- **Blinding:** labels assigned from the episodes only; `key.jsonl` and the snapshot were not
  opened before labeling. The integrity output for the dataset (dataset-level, no episode IDs
  beyond the short-episode list) was seen before labeling.

## Evidence used per episode

From the dataset files: 9 evenly spaced frames plus the final frame from each camera;
per-step |Δaction| and |Δstate|; state dims 0-5 over time; per-camera frame difference;
NaN counts; longest run of an identical state row; decoded frames vs steps per camera;
frames unchanged while state moved; exact-equality check of actions, states and video frames
across all episode pairs; spectral check of state dims (>1 Hz) and whether actions share it.

## Labels

| Label | Episodes | Rule / evidence |
|---|---|---|
| `acquisition_fault` | 26 | Exact duplicate of episode 6: actions, states and sampled video frames bit-identical, stored at a different video offset (125 s vs 30 s). |
| `unsure` | 0, 1, 15, 17, 21, 22, 23 | ~6 Hz oscillation in `observation.state[4]` (std 0.022–0.028 vs 0.001–0.012 elsewhere), present in no action dim (not commanded), not resolvable in video. Joint chatter / sensor noise vs controller behaviour undetermined. Excluded from scoring. |
| `clean` | the other 22 | Object ends in the bin on both cameras; no NaN, stuck state, frame mismatch or frozen camera. Includes the 200-step episodes 6, 7, 12, 16, 20 and 29, which complete the task (the seventh, 26, is the duplicate above and also completes it). |

No `execution_failure` and no `unusual_valid` found.

## Result (provisional)

| Detector | TP / FP / FN | Note |
|---|---|---|
| `short_outlier` (behind integrity's block-level `short_episode_fraction`) | 1 / 6 / 0 | 6 of 7 flags are complete demos. The single TP (ep 26) is **coincidental**: it is flagged for being 200 steps, not for being a duplicate; its original (ep 6) gets the same flag and is clean. |
| `anomaly_score >= 0.8` | 1 / 4 / 0 | Also coincidental for ep 26 (same values as ep 6). |
| Stage 1, video, `quality_risk >= 0.5` | 0 / 0 / 1 | Duplicate missed. |

**Read the TP rows as 0 real detections.** No current detector looks for duplicate episodes.

### Re-score after fixes (same labels, new snapshot)

After the short-episode fence floor and the new `duplicate_episode_fraction` check:

| Detector | TP / FP / FN |
|---|---|
| `duplicate` (new) | 1 / 0 / 0 — names ep 26 as a copy of ep 6 |
| `blocked (stage1, video or duplicate)` | 1 / 0 / 0 |
| `short_outlier` | 0 / 0 / 1 — the six false flags are gone |

`calibra integrity` on this dataset now fails CI on `duplicate_episode_fraction` instead of
`short_episode_fraction`.

## Findings for Calibra

1. **`short_episode_fraction` false block.** Episodes are fixed-length recordings (23 × 250,
   7 × 200 steps). Q1 = Q3 = 250, so IQR = 0 and the lower fence is 250: every 200-step
   episode is an "outlier" and `calibra integrity` fails CI at block level on complete demos.
   The IQR fence degenerates whenever lengths are quantized.
2. **Duplicate episodes are not detected.** Cheap to add (hash per-episode actions/states).
3. **Hand dimensions inflate motion metrics.** The largest action jump in every episode sits in
   a contiguous block of hand dims (24–29 or 32–37): discrete open/close commands at grasp and
   release. Only the last dim is excluded as a gripper by default, so these drive
   `velocity_discontinuity_rate` CRITICAL on a dataset whose episodes are all valid.
   A dataset-profile issue (see feedback on dataset profiles).
4. **Uncommanded 6 Hz joint oscillation** in 7 episodes of one apparent session: candidate
   real hardware fault, needs a human with H1 knowledge.

Also observed while preparing batch-003: on an incompletely downloaded ALOHA copy (one camera
file missing), `calibra integrity` correctly blocked on `video_missing_rate` (25% of episode ×
camera pairs). Download artifact, not a dataset fault, so not labeled.
