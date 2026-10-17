# Integrity fault-injection benchmark: Calibra v0.13.0

Technical report, 2026-10-17. Protocol: [PROTOCOL.md](PROTOCOL.md) (pre-registered,
changes logged in its changelog). Raw results: `results/v0.13.0/trials.jsonl`;
tables: `results/v0.13.0/summary.md`, regenerated with
`python eval/integrity_fault_injection/score.py results/v0.13.0`.

## Summary

We injected controlled acquisition faults into on-disk copies of three real
LeRobot v3.0 datasets and ran `calibra integrity --json` on each copy, 981
trials in total, with no harness errors.

- **File-level and episode-level faults are caught reliably.** Duplicate
  episodes, missing, truncated or wrong-fps video, and dropped video frames were
  detected in every clear-tier trial (105/105, 96/96, 60/60), at the expected
  CRITICAL level, with no side-effect flags.
- **Frozen camera streams are caught when every episode is decoded** (60/60
  clear tier), but the default `--video-sample 20` misses about a third of them
  (19/60) because the frozen episode is not in the sample.
- **Repeated-frame detection does not work on LeRobot AV1 video.** Isolated
  duplicated frames are erased by the encoder (0/5 detected on H1), and static
  scenes are flagged as duplicates (the only false positive on clean data:
  ALOHA, `duplicate_frame_rate` CRITICAL).
- **Timing checks catch dropout and jitter above threshold** (150/150), but
  not swapped timestamps confined to a few episodes (0/30), and an episode
  stored in milliseconds makes them silently skip (30/30 not evaluated). All
  three datasets have synthetic timestamps, so timing results validate the
  detectors on injected noise, not on real clock faults.

Against the proposed engineering targets: **zero false positives on clean data
was not met** (1 of 300 evaluated checks, Wilson 95% upper bound 1.9%), and
**95% clear-tier recall was met for four of six fault types** (duplicates,
missing/broken video, dropped video frames, frozen frames) and not met for
timestamp faults (83%) or repeated frames (0%). These are measurements of
synthetic injection, not estimates of how often faults occur in real datasets.

## Setup

| | |
|---|---|
| System under test | Calibra 0.13.0 (commit `a710aa6`), `calibra integrity <copy> --json [--decode-video --video-sample N]`, default policy, no profile |
| Datasets | `lerobot/unitreeh1_rearrange_objects` @ `e874d89` (30 episodes, 2 cameras), `lerobot/pusht` @ `7628202` (206 episodes, 1 camera, simulator), `lerobot/aloha_static_battery` @ `06dc3da` (49 episodes, 4 cameras); all LeRobot v3.0, AV1 video |
| Injection | on-disk copies; frame faults re-encode only the affected episode (libsvtav1, GOP 2, crf 30, as LeRobot encodes) |
| Passes | frame faults: every episode decoded (primary) and the default 20-episode sample; other faults: file checks only |
| Seeds | `sha256(dataset, variant, rep)`; injections are regenerated exactly from the trial id |

Frame-content faults (frozen and repeated frames, re-encode control) ran on H1
and PushT only: decoding ALOHA once takes about 14 minutes (36 gigapixels of
video), which made 40 decoded trials impractical. ALOHA ran every other variant
plus one fully decoded clean copy.

## Clean data

| Dataset | Clean trials | Evaluated checks | False positives | Wilson 95% upper |
|---|---|---|---|---|
| H1 | 16 | 124 | 0 | 3.0% |
| PushT | 13 | 97 | 0 | 3.8% |
| ALOHA | 11 | 79 | 1 | 6.8% |
| **All** | 40 | 300 | **1** | **1.9%** |

- **H1** has one real fault, episode 26 is a byte-identical copy of episode 6;
  it is flagged CRITICAL on every clean trial and counted as a true positive.
- **ALOHA**: `duplicate_frame_rate` is CRITICAL on the unmodified data (29% of
  transitions on the static overhead camera, 6% to 18% on the others). The
  repeats fall only on every other frame, in step with the encoder's 2-frame
  GOP: near-static predicted frames are decoded as exact copies of the keyframe
  before them. This is a compression effect, not a recording fault (see
  finding 1).
- **PushT** re-encoded with LeRobot's settings reads `duplicate_frame_rate`
  WARNING (7.0% vs 2.4% on the source files). This is a harness artifact and is
  not counted against Calibra, but it means repeated-frame injections on PushT
  cannot be scored (they are reported as masked).
- Timestamp checks report "not evaluated" on all three datasets: every
  episode's timestamps sit on an exact `frame_index / fps` grid.

## Detection (clear tier)

| Fault type | Detected | Wilson 95% | Notes |
|---|---|---|---|
| Duplicate episodes (exact, re-encoded copy) | 105/105 | 96.5% to 100% | episode-level attribution, all copies named |
| Missing / truncated video, wrong fps | 96/96 | 96.2% to 100% | |
| Dropped video frames (2+ frames) | 60/60 | 94.0% to 100% | single dropped frame is within the 1-frame tolerance, by design |
| Frozen frames (run of 10 or 30, or in 5% to 50% of episodes) | 60/60 | 94.0% to 100% | H1 and PushT; 19/60 missed by the default 20-episode sample |
| Timestamp faults | 150/180 | 77.2% to 88.1% | 30 misses: swapped timestamps; 30 more not evaluated: ms units |
| Repeated frames (10% to 30% isolated repeats) | 0/3 | 0% to 56% | H1 only; PushT masked by the re-encoding artifact |

Near-threshold trials: dropped video frames 15/15, timestamp dropout and
jitter 90/90, frozen frames 1/4 (a 5-transition freeze decodes as 4 and falls
under the 5-run minimum). Every sub-threshold and by-design variant stayed
quiet: no check fired below its documented threshold.

**Severity.** Every detection was emitted at the level the pre-registered rubric
expected (CRITICAL for missing, broken, mismatched and duplicated data;
WARNING or CRITICAL for freezes, dropout and jitter by fraction). The only
level disagreements are the misses themselves.

**Side effects.** No check fired on an injected copy that was quiet on the
corresponding clean or re-encoded control and not explained by the fault.

## Findings

1. **`duplicate_frame_rate` is unreliable on LeRobot AV1 video, in both
   directions.** The check counts a transition as a repeat when fewer than
   0.05% of pixels change by more than 2 levels. After encoding with LeRobot's
   settings, an exact duplicate frame differs from its predecessor in about 19%
   of pixels when it lands on a keyframe (0/18 isolated repeats detected, same
   with the default and the fast encoder preset). Conversely, static scenes
   produce exact copies at every predicted frame, which flags clean ALOHA as
   CRITICAL. The threshold was designed for raw images.
2. **The default video sample hides frozen cameras.** With `--video-sample 20`,
   19 of 60 clear-tier freezes were missed because the frozen episode was not
   decoded (14/36 on PushT, where 20 episodes are under 10% of the dataset).
3. **Freezes read one transition shorter after encoding.** The first copy of a
   frozen frame is not decoded within the repeat tolerance, so a freeze of
   exactly 5 transitions (the minimum) is usually missed.
4. **Non-monotonic timestamps are only caught indirectly.** There is no
   monotonicity check; a swap raises the episode's jitter CV, which crosses the
   threshold only when most episodes are affected. Swaps in 10% of episodes:
   0/30 detected.
5. **An episode in milliseconds disables the timing checks.** Its timestamps
   still lie on an exact grid, so the whole dataset is reported as synthetic and
   timing is not evaluated, instead of being flagged (30/30).
6. **Single dropped steps are invisible to `timestamp_dropout_rate`** by design:
   it counts gaps longer than 3x the median interval, and one missing step
   leaves a 2x gap. Runs of 3 missing steps are detected (150/150 with jitter).
7. **Duplicate detection is exact-match on non-image data.** A copy with one
   value changed by one float step, or shifted by one step, is not flagged
   (0/60, by design). A copy whose parquet is identical but whose video comes
   from a different episode is flagged CRITICAL (30/30), since images are not
   hashed.

None of these were changed in this benchmark. Whether to change a detector is a
separate decision.

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
7. Repetition counts were reduced during the run to fit compute, before any
   scoring (protocol changelog). Trials 1 to 124 ran under the original counts;
   the first run invocation's manifest was overwritten (later ones are kept in
   `results/v0.13.0/manifests/`).

## Regression protection

`tests/regression/test_fault_injection_findings.py` reproduces findings 1 and
4 to 7 and the freeze threshold on small synthetic fixtures. Detections are
asserted; known misses are `xfail(strict=True)`, so fixing one fails the test
until the marker and this report are updated.

## Reproduce

```bash
python eval/integrity_fault_injection/run.py --run v0.13.0 --datasets h1,pusht
python eval/integrity_fault_injection/run.py --run v0.13.0 --datasets pusht \
    --variants freeze.run10,freeze.run30 --reps 6
python eval/integrity_fault_injection/run.py --run v0.13.0 --datasets aloha \
    --variants clean.copy,clean.append,dup.,video.,vdrop.,steps.,jitter.,ts.
python eval/integrity_fault_injection/score.py results/v0.13.0
```
