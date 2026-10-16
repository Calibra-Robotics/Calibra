# batch-003 labeling record

- **Dataset:** lerobot/aloha_static_battery @ `06dc3da83c4fd3d1889b00f1dfd3780da8421f64`
  (v3.0, static ALOHA, 4 cameras 480×640, 50 fps, 49 episodes × 600 steps,
  task "Place the battery into the slot of the remote control")
- **Calibra:** 0.12.0 + unreleased (per-sub-movement LDLJ, synthetic-timestamp handling)
- **Unit of evaluation:** one episode. All 49 labeled (inclusion probability 1), so no
  sampling weights apply.
- **Labeler:** AI first pass (Claude), 2026-10-16. **Not yet verified by a human.**
- **Blinding:** labels assigned from the episodes; `key.jsonl` not opened before labeling.
  Calibra's snapshot had no per-episode flags at all (no Stage-1, short or video faults).

## Evidence

Same checks as batch-002 (frames per camera, NaN, stuck state, duplicate episodes, uncommanded
oscillation, frozen frames) plus a contact sheet of the final `cam_low` and `cam_high` frame
of every episode to judge task completion.

## Labels

All 49 `clean`: the battery is in the remote's slot in every final `cam_low` frame and the
remote is back on its stand. Episodes 17, 19, 29, 37, 43 and 48 end (fixed 600 steps) while an
arm is still returning to rest; the task is already complete, so this is noted, not labeled.
No duplicates, NaN, stuck sensors, frame-count mismatches or uncommanded oscillation.

## Result (provisional)

No per-episode detector fires (0 false positives on 49 clean episodes); `anomaly_score >= 0.8`
marks 1 clean episode for review. With no positives, recall is not measurable on this dataset.

## Dataset-level findings (not per-episode labels)

1. **Camera frame repetition on all four cameras, every episode.** 17–37% of consecutive
   frames are near-identical (mean |Δ| < 0.5), and repeats occur at even gaps (2, 4, 6
   frames), the signature of cameras running at roughly 25–30 Hz written into a 50 Hz stream
   by repeating frames. The policy sees visual observations at about half the labelled rate,
   lagging state/action. Calibra's `duplicate_frame_rate` / `camera_freeze_events` measure
   exactly this but were **Not Evaluated on v2/v3** (no frame decoding). Since
   `calibra integrity --decode-video` (same release) they run on decoded video: this dataset
   gets `duplicate_frame_rate` CRITICAL (cam_high 30.0%, 10 of 49 episodes decoded), with
   no freeze runs (repeats alternate, they do not stall).

   | ep | cam_high | cam_left_wrist | cam_low | cam_right_wrist |
   |---:|---:|---:|---:|---:|
   | 0 | 35.1% | 26.5% | 24.9% | 16.9% |
   | 24 | 35.1% | 27.7% | 27.9% | 17.7% |
   | 48 | 36.9% | 33.1% | 27.9% | 18.5% |

2. **Two grippers, one excluded.** The largest action jump usually involves dims 1, 4 and 11
   (arm joints and a gripper); ALOHA has a gripper per arm (dims 6 and 13 by the usual layout)
   but only the last dim is excluded by default. Likely contributes to
   `velocity_discontinuity_rate` CRITICAL. Dataset-profile issue.
3. **Fixed-length recordings** (all 600 steps): the short-episode IQR fence is degenerate
   here too (IQR = 0) but fires on nothing because no episode is shorter. Same latent bug as
   batch-002.
4. On an incomplete download (one camera file missing) `calibra integrity` correctly blocked
   on `video_missing_rate` (download artifact, not a dataset fault).
