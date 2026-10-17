# Integrity fault-injection benchmark: Calibra v0.13.0

Technical report, 2026-10-17, corrected 2026-10-18. Protocol:
[PROTOCOL.md](PROTOCOL.md) (pre-registered, changes logged in its changelog).
Raw results: `results/v0.13.0/` (v0.13.0 as released) and `results/post-fix/`
(after the fixes in [Changes after v0.13.0](#changes-after-v0130)). Tables are
regenerated with `python eval/integrity_fault_injection/score.py results/<run>`.

> **Correction (2026-10-18).** The first version of this report said that AV1
> compression erases repeated frames (0/3 detected) and that ALOHA's
> `duplicate_frame_rate` flag is a compression artifact. Both were wrong. The
> repeated-frame injector placed every repeat on a keyframe, the one position
> where the codec hides it. With repeats at both frame parities, the check
> detects them and reports about half of the true rate; ALOHA's flag reflects
> real repeated frames. Details under finding 1.

## Summary

We injected controlled acquisition faults into on-disk copies of three real
LeRobot v3.0 datasets and ran `calibra integrity --json` on each copy: 981
trials on v0.13.0 and 471 after the fixes, with no harness errors.

- **File-level and episode-level faults are caught reliably.** Duplicate
  episodes, missing, truncated or wrong-fps video, and dropped video frames were
  detected in every clear-tier trial (105/105, 96/96, 60/60), at the expected
  CRITICAL level, with no side-effect flags.
- **Frozen camera streams are caught when every episode is decoded** (60/60
  clear tier). The default `--video-sample 20` missed about a third of them
  (19/60) because the frozen episode was not in the sample.
- **Repeated frames are detected but under-counted on AV1 video.** A repeat is
  visible only when it is coded as a predicted frame, so the reported rate is
  about half the true rate (clear tier 3/3; near-threshold repeats fall below
  the threshold).
- **Timing checks:** v0.13.0 caught dropout and jitter above threshold
  (150/150) but missed swapped timestamps (0/30) and skipped episodes stored in
  milliseconds (30/30 not evaluated). Two checks added after v0.13.0 close both
  gaps: 210/210 after the fixes. All three datasets have synthetic timestamps,
  so timing results validate the detectors on injected faults, not on real
  clock faults.

Against the proposed engineering targets: **zero flags on clean data was not
met** (1 of 300 evaluated checks on v0.13.0: ALOHA `duplicate_frame_rate`). That
flag is a correctly detected anomaly, real repeated frames, but nothing labels it
a recording fault, so the pre-registered rule counts it. **95% clear-tier recall
was met for every fault type after the fixes**, and for four of six on v0.13.0
(timestamp faults 83%; repeated frames could not be measured because of the
injector error). These are measurements of synthetic injection, not estimates of
how often faults occur in real datasets.

## Setup

| | |
|---|---|
| System under test | Calibra 0.13.0 (commit `a710aa6`); fixes in the commits after it. `calibra integrity <copy> --json [--decode-video --video-sample N]`, default policy, no profile |
| Datasets | `lerobot/unitreeh1_rearrange_objects` @ `e874d89` (30 episodes, 2 cameras), `lerobot/pusht` @ `7628202` (206 episodes, 1 camera, simulator), `lerobot/aloha_static_battery` @ `06dc3da` (49 episodes, 4 cameras); all LeRobot v3.0, AV1 video |
| Injection | on-disk copies; frame faults re-encode only the affected episode (libsvtav1, GOP 2, crf 30, as LeRobot encodes) |
| Passes | frame faults: every episode decoded (primary) and the default 20-episode sample; other faults: file checks only |
| Seeds | `sha256(dataset, variant, rep)`; injections are regenerated exactly from the trial id |

Frame-content faults (frozen and repeated frames, re-encode control) ran on H1
and PushT only: decoding ALOHA once takes about 14 minutes (36 gigapixels of
video), which made 40 decoded trials impractical. ALOHA ran every other variant
plus one fully decoded clean copy.

## Clean data

| Dataset | Clean trials (v0.13.0) | Evaluated checks | Flags not explained by a labeled fault | Wilson 95% upper |
|---|---|---|---|---|
| H1 | 16 | 124 | 0 | 3.0% |
| PushT | 13 | 97 | 0 | 3.8% |
| ALOHA | 11 | 79 | 1 | 6.8% |
| **All** | 40 | 300 | **1** | **1.9%** |

- **H1** has one real fault, episode 26 is a byte-identical copy of episode 6;
  it is flagged CRITICAL on every clean trial and counted as a true positive.
- **ALOHA**: `duplicate_frame_rate` is CRITICAL on the unmodified data (29% of
  transitions on the overhead camera, 6% to 18% on the others). The repeats
  continue while the arms move (27% of transitions during motion vs 30% at
  rest on the overhead camera), when a moving arm changes far more pixels than
  the repeat tolerance allows, so these are identical frames from the camera:
  most likely cameras running slower than the 50 Hz recording rate, padded by
  repetition. This is a real acquisition property and a correct detection. It
  is listed here because it is not a labeled recording fault; whether repeated
  frames matter depends on the policy.
- **PushT** re-encoded with LeRobot's settings reads `duplicate_frame_rate`
  WARNING (7.0% vs 2.4% on the source files). This is a harness artifact and is
  not counted against Calibra, but it means repeated-frame injections on PushT
  cannot be scored (reported as masked).
- Timestamp jitter and dropout report "not evaluated" on all three datasets:
  every episode's timestamps sit on an exact `frame_index / fps` grid. The two
  checks added after v0.13.0 are OK on all clean data.

## Detection (clear tier)

| Fault type | v0.13.0 | After fixes | Notes |
|---|---|---|---|
| Duplicate episodes (exact, re-encoded copy) | 105/105 | unchanged | episode-level attribution, all copies named |
| Missing / truncated video, wrong fps | 96/96 | unchanged | |
| Dropped video frames (2+ frames) | 60/60 | unchanged | a single dropped frame is within the 1-frame tolerance, by design |
| Frozen frames (run of 10 or 30, or in 5% to 50% of episodes) | 60/60 | unchanged | H1 and PushT; 19/60 missed by the default 20-episode sample |
| Repeated frames (10% to 30% isolated repeats) | n/a, injector error | 3/3 | H1 only (PushT masked); measured rate about half the injected rate |
| Timestamp faults | 150/180 | 210/210 | v0.13.0 missed swaps (30) and skipped ms units (30, not evaluated) |

Wilson 95% intervals: duplicates 96.5% to 100%, missing/broken video 96.2% to
100%, dropped video frames and frozen frames 94.0% to 100%, timestamps after
fixes 98.2% to 100%, repeated frames 43.9% to 100% (n = 3).

Near-threshold trials: dropped video frames 15/15, timestamp dropout and jitter
90/90, frozen frames 1/4 (a 5-transition freeze usually decodes as 4 and falls
under the 5-run minimum), repeated frames 0/2 (5% and 7.5% repeats read as 3% and
4%). Every sub-threshold and by-design variant stayed quiet: no check fired
below its documented threshold, and the new timestamp checks did not fire on
jitter, dropout or offset variants.

**Severity.** Every detection was emitted at the level the pre-registered rubric
expected, except repeated frames at 15% (WARNING instead of CRITICAL, because
only about half the repeats are visible). The other level disagreements are the
misses themselves.

**Side effects.** No check fired on an injected copy that was quiet on the
corresponding clean or re-encoded control and not explained by the fault.

## Findings

1. **`duplicate_frame_rate` under-counts on AV1 video.** LeRobot encodes with a
   2-frame GOP: every other frame is a keyframe. A repeated frame coded as a
   predicted frame decodes as an exact copy and is detected (18/18); one that
   lands on a keyframe is re-encoded with fresh compression noise, about 19% of
   pixels differ, and it looks new (0/18). The measured rate is therefore about
   half the true rate. It does not raise false alarms on static scenes: ALOHA's
   repeats continue while the arms move. *After v0.13.0:* the flag says the rate
   is a lower bound on inter-coded video.
2. **The default video sample hides frozen cameras.** With `--video-sample 20`,
   19 of 60 clear-tier freezes were missed because the frozen episode was not
   decoded (14/36 on PushT, where 20 episodes are under 10% of the dataset).
   *After v0.13.0:* the output says that episodes outside the sample were not
   checked and gives the `--video-sample` value that checks all of them.
3. **Freezes read one transition shorter after encoding**, for the same
   keyframe reason, so a freeze of exactly 5 transitions (the minimum) is
   usually missed.
4. **v0.13.0 had no timestamp monotonicity check.** Swapped timestamps raised
   the episode's jitter CV, which crossed the threshold only when most episodes
   were affected; swaps in 10% of episodes: 0/30. *After v0.13.0:*
   `timestamp_non_monotonic` (CRITICAL when any episode's timestamps repeat or go
   backwards) catches 30/30.
5. **In v0.13.0, an episode in milliseconds disabled the timing checks.** Its
   timestamps still lie on an exact grid, so the dataset was reported as
   synthetic and timing was not evaluated (30/30). *After v0.13.0:*
   `timestamp_scale_mismatch` (CRITICAL when an episode's median step is more
   than 10x away from the dataset's) catches 30/30.
6. **Single dropped steps are invisible to `timestamp_dropout_rate`** by design:
   it counts gaps longer than 3x the median interval, and one missing step
   leaves a 2x gap. Runs of 3 missing steps are detected. Not changed.
7. **Duplicate detection is exact-match on non-image data.** A copy with one
   value changed by one float step, or shifted by one step, is not flagged
   (0/60, by design). A copy whose parquet is identical but whose video comes
   from a different episode is flagged CRITICAL (30/30), since images are not
   hashed.

## Changes after v0.13.0

Made on 2026-10-18 in response to findings 1, 2, 4 and 5 and released as
Calibra 0.13.1 (finding 6 is a deliberate threshold and was left as is):

- `timestamp_non_monotonic` and `timestamp_scale_mismatch` in the temporal
  analyzer, part of `calibra integrity`. Both run even when timestamps are
  synthetic, since ordering and units do not depend on clock noise.
- `--decode-video` flags state when episodes outside the sample were not
  checked.
- `duplicate_frame_rate` on inter-coded video (AV1, H.264, ...) states that its
  rate is a lower bound.

Detector logic for every other check is unchanged; the PushT regression golden
changed only by the two new checks, both OK. The rerun (`results/post-fix/`)
covers the timestamp variants, repeated frames with the corrected injector, the
re-encode control and fresh clean copies of all three datasets.

## Limitations

1. Injected faults are idealized; their mix says nothing about how often faults
   occur in real data.
2. No dataset has real hardware timestamps, so timing results are detector unit
   validation only. Real-clock validation needs design-partner data.
3. LeRobot v3.0 with AV1 video only; v2.x, other codecs and other formats
   (HDF5, RLDS, MCAP) are not covered.
4. Frame-content faults were not run on ALOHA, and repeated frames could only
   be scored on H1 (n = 5).
5. Re-encoding is not always faithful to the source encoding (PushT: 2.4% to
   7.0% repeated transitions with no fault).
6. "Not corrupt" relies on provisional, non-expert labels for the native data
   (`eval/real_faults/SPOT_CHECK.md`).
7. Repetition counts were reduced during the v0.13.0 run to fit compute, before
   any scoring (protocol changelog). Trials 1 to 124 ran under the original
   counts; the first invocation's manifest was overwritten (later ones are in
   `results/<run>/manifests/`).
8. The repeated-frame injector error was found after the first report; see the
   protocol changelog entry of 2026-10-18.

## Regression protection

`tests/regression/test_fault_injection_findings.py` reproduces findings 1 and
4 to 7 and the freeze threshold on small synthetic fixtures. Detections are
asserted; the one remaining known miss (a repeat on a keyframe) is
`xfail(strict=True)`, so fixing it fails the test until the marker and this
report are updated.

## Reproduce

```bash
# v0.13.0 (run with the detectors as released in commit a710aa6; the harness
# itself came later, so run it from main against a 0.13.0 install)
python eval/integrity_fault_injection/run.py --run v0.13.0 --datasets h1,pusht
python eval/integrity_fault_injection/run.py --run v0.13.0 --datasets pusht \
    --variants freeze.run10,freeze.run30 --reps 6
python eval/integrity_fault_injection/run.py --run v0.13.0 --datasets aloha \
    --variants clean.copy,clean.append,dup.,video.,vdrop.,steps.,jitter.,ts.

# after the fixes
python eval/integrity_fault_injection/run.py --run post-fix --datasets h1,pusht \
    --variants clean.copy,clean.reencode,repeat.,steps.,jitter.,ts.
python eval/integrity_fault_injection/run.py --run post-fix --datasets aloha \
    --variants clean.copy,steps.,jitter.,ts.

python eval/integrity_fault_injection/score.py results/<run>
```
