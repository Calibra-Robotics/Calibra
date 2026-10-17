# Integrity fault-injection benchmark: protocol

Status: **draft, pre-registration**. Thresholds, severity tiers, expected levels
and success criteria below are fixed *before* any injected run is scored. Changes
after the first scored run go in the changelog at the bottom with a reason, and
the report states which version of this protocol it used.

## 1. Question

Does `calibra integrity` (v0.13.0) flag controlled acquisition faults in real
LeRobot datasets, at the expected severity, without flagging data that is not
corrupt?

In scope: the objective acquisition/format/completeness checks in
`calibra integrity`. Out of scope:

- Motion-review signals (`ldlj`, `jerk_spike_rate`, `velocity_discontinuity_rate`,
  `joint_offset_max_abs`). They are "worth a look" signals, not corruption
  verdicts, and are already scored against human labels in `eval/real_faults/`.
- Selection/pruning robustness. The configuration-sensitivity rerun is a
  separate benchmark (`eval/selection_sensitivity/`, section 12) and shares no
  results with this one.
- Real-world detection rates. Injection shows what a detector *can* catch; only
  labeled real data (`eval/real_faults/`) speaks to how often real faults occur
  or are caught. The report keeps the two apart.

## 2. System under test

| Item | Value |
|---|---|
| Calibra | 0.13.0, git commit recorded per run (`a710aa6` at protocol time) |
| Entry point | `calibra integrity <root> --json --decode-video --video-sample <N>` |
| Profile | none (integrity checks are profile-independent; recorded anyway) |
| Policy | default block/inspect split, no `--strict`, no `--policy` |
| Environment | Python, NumPy, pyarrow, OpenCV, ffmpeg versions recorded per run |

Two passes per trial:

- **Full decode** (`--video-sample` = number of episodes). Primary result: removes
  episode sampling as a cause of misses.
- **Default decode** (`--video-sample 20`). Secondary result: what a user running
  the default sees. Misses here that the full pass catches are reported as
  *sampling-limited*, not as detector misses.

The public `--json` output is dataset-level (one flag per metric, no episode
list). The verdict a user sees is therefore the primary unit (section 7). Where
an analyzer exposes episode attribution internally (`duplicate_of`, per
(episode, camera) video entries, per-episode freeze runs), the harness reads it
through the Python API for a secondary episode-level score.

## 3. Datasets

All three are LeRobot v3.0 (episodes concatenated into shared mp4 and parquet
files, located through `meta/episodes/`). Revisions are the ones already pinned
in `eval/real_faults/snapshots/`, so labels from that eval apply unchanged.

| Dataset | Revision | Episodes | fps | Cameras | Timestamps |
|---|---|---|---|---|---|
| `lerobot/pusht` | `7628202a2180972f291ba1bc6723834921e72c19` | 206 | 10 | 1 | synthetic |
| `lerobot/unitreeh1_rearrange_objects` | `e874d89b9024bad414deb45d7da82fa93601c260` | 30 | 50 | 2 | synthetic |
| `lerobot/aloha_static_battery` | `06dc3da83c4fd3d1889b00f1dfd3780da8421f64` | 49 | 50 | 4 | synthetic |

Known properties of the unmodified data, recorded before any run:

- **Native duplicate**: H1 episode 26 is a byte-identical copy of episode 6
  (`eval/real_faults/`, extra-copy convention: 26 is the fault, 6 is clean). The
  H1 baseline is therefore *not* clean for `duplicate_episode_fraction`; a
  CRITICAL there is a true positive.
- **Synthetic timestamps** on all three: timestamp jitter/dropout checks report
  "not evaluated" on unmodified data. See section 5.4.
- **Static scenes**: PushT is a simulator, so idle steps render byte-identical
  frames. These are intentional repeats, not recording faults (section 6).

Gap: none of the three has real hardware timestamps. The report states this as a
limitation unless a fourth dataset with logged clocks is added (open decision 1).

## 4. Checks in scope and their thresholds (v0.13.0)

Read from the code at protocol time; the harness re-reads them at run time and
refuses to score if they differ from this table.

| Check (metric) | Measured as | WARNING | CRITICAL |
|---|---|---|---|
| `duplicate_episode_fraction` | episodes whose actions+observations are byte-identical to an earlier one | n/a | any (> 0) |
| `video_missing_rate` | (episode, camera) pairs whose mp4 is absent | n/a | any |
| `video_decode_failure_rate` | pairs whose first/last episode frame cannot be decoded | n/a | any |
| `video_frame_mismatch_rate` | pairs whose video does not cover the episode's frames (tolerance 1 frame) | n/a | any |
| `video_fps_mismatch_rate` | stream fps differs from `info.json` (tolerance 1%) | n/a | any |
| `duplicate_frame_rate` | worst camera's mean fraction of repeated transitions (< 0.05% pixels changed by > 2 levels) | ≥ 5% | ≥ 15% |
| `camera_freeze_events` | fraction of decoded episodes with a run of ≥ 5 repeated transitions | any | ≥ 10% |
| `timestamp_dropout_rate` | fraction of steps after a gap | ≥ 1% | ≥ 5% |
| `timestamp_jitter_cv` | coefficient of variation of step intervals | ≥ 0.15 | ≥ 0.30 |
| `short_episode_fraction` | outlier-short episodes | ≥ 5% | ≥ 15% |

## 5. Faults

Every injector works on a copy of the dataset **on disk** (parquet, mp4,
`meta/`), so the file-reading path users hit is the one tested. `calibra corrupt`
is not reused for the primary result because it corrupts the in-memory batch and
never touches mp4 files or metadata. Injectors keep `meta/` consistent unless the
fault *is* a metadata inconsistency, so that a detection is caused by the fault
and not by a broken index.

Each fault has a severity grid placed relative to its threshold. Tiers
(section 8) are assigned from the grid here, before running.

Working copies copy `meta/` and symlink every data and video file; injectors
unlink a file before writing it, so the source dataset is never modified. A
fault that changes video frames *relocates* the affected episode: its segment is
decoded, transformed, re-encoded into a new per-episode mp4 (libsvtav1, GOP 2,
crf 30, yuv420p, as LeRobot encodes; preset 12), and `meta/episodes` is pointed
at it. That is a valid v3 layout, every other episode keeps its untouched
source file, and an episode costs about a second to re-encode instead of
re-encoding a whole shared file.

### 5.1 Duplicate episodes

Append a copy of episode *k* (parquet rows, as a new data file) as a new episode
index whose video pointers reference *k*'s segment; original kept, copy is the
fault (extra-copy convention).

| Variant | Grid | Tier |
|---|---|---|
| exact copy | 1 copy; 5%; 15% of episodes | clear |
| near copy: one action value changed by 1 ULP | 1 copy | undetectable by design |
| near copy: video segment re-encoded, parquet identical | 1 copy | clear (the digest hashes actions and numeric observations, not images) |
| parquet identical, video from a *different* episode | 1 copy | ambiguous: flagged by design since images are not hashed; reported separately as "parquet duplicate, video differs" |
| near copy: same trajectory, 1-step time shift | 1 copy | undetectable by design |

"Undetectable by design" and "ambiguous" variants document the boundary of exact-match
detection. They are reported in their own table, never pooled into recall.

### 5.2 Missing and broken video files

In v3 one mp4 holds many episodes, so deleting a file removes several
(episode, camera) pairs at once. The ground-truth unit is the set of pairs whose
frames live in the affected file.

| Variant | Grid | Expected check | Tier |
|---|---|---|---|
| delete one camera's mp4 file | 1 file | `video_missing_rate` | clear |
| delete every camera's file for one chunk | 1 chunk | `video_missing_rate` | clear |
| delete one episode's own (relocated) file | 1 episode, 1 camera | `video_missing_rate` | clear |
| truncate one episode's relocated file (moov first) to X% of its bytes | X = 90, 50, 10 | `video_decode_failure_rate` | clear |
| change `info.json` fps by +5% | 1 | `video_fps_mismatch_rate` | clear |
| change `info.json` fps by +0.5% | 1 | none (inside tolerance) | sub-threshold |

### 5.3 Frozen and repeated frames

Within one episode's segment of one camera, replace frames with copies of an
earlier frame and relocate the episode (above). Source frames are taken from a
decode of the original file, so the only difference from the re-encode control
(section 6.2) is the fault.

| Variant | Grid | Expected check | Tier |
|---|---|---|---|
| freeze run of length L in one episode | L = 3, 4 | none (< 5-run minimum) | sub-threshold |
| | L = 5 | `camera_freeze_events` WARNING | near |
| | L = 10, 30 | `camera_freeze_events` WARNING | clear |
| freeze run L = 10 in a fraction F of episodes | F = 5%, 10%, 20%, 50% | WARNING below 10%, CRITICAL at ≥ 10% | clear |
| scattered single-frame repeats ("repeat-fill" drops) at rate R in all episodes | R = 2%, 4% | none | sub-threshold |
| | R = 5%, 7.5% | `duplicate_frame_rate` WARNING | near |
| | R = 10%, 15%, 30% | WARNING below 15%, CRITICAL at ≥ 15% | clear |

Injected rates are measured from the injected files, not taken from the
parameter, because native static frames add to the rate (section 6.3).

### 5.4 Dropped frames and timestamp faults

Two different faults that are often called "dropped frames":

**(a) Video frames dropped, parquet intact.** Remove frames from an episode's
video segment and update `meta/episodes` to the shorter span, as a recorder that
lost frames would. Expected: `video_frame_mismatch_rate` (tolerance 1 frame).

| Frames dropped per episode | Tier |
|---|---|
| 1 | sub-threshold |
| 2 | near |
| 5; 10% of the episode | clear |

Applied to 1 episode and to 10% of episodes. A second variant keeps the full
span in `meta/episodes` while the file is short (a recorder whose metadata
disagrees with its file): 1 frame (sub-threshold) and 5 frames (clear), where
`video_frame_mismatch_rate` or `video_decode_failure_rate` may catch it.

**(b) Steps dropped, timestamps kept.** Remove runs of consecutive parquet rows
so the remaining timestamps have gaps; frame_index is renumbered. This makes the
timestamp grid non-synthetic, so the timestamp checks become evaluable. Video is
not re-encoded (that would mean re-encoding every episode of every camera), so
the parquet/video frame mismatch this creates is an *explained* flag, not
collateral. `timestamp_dropout_rate` only counts an interval longer than 3x the
episode's median, so a run of r dropped rows is visible only when r + 1 > 3:

| Variant | Gap rate (mean over episodes) | Expected `timestamp_dropout_rate` | Tier |
|---|---|---|---|
| single dropped rows (2x gap) | 5% | none | undetectable by design |
| runs of 3 rows (4x gap) | 0.5% | none | sub-threshold |
| | 1% | WARNING | near |
| | 2% | WARNING | clear |
| | 5%, 10% | CRITICAL | clear |

**(c) Timestamp inconsistencies.**

| Variant | Grid | Expected | Tier |
|---|---|---|---|
| Gaussian jitter on intervals, target CV | 0.05; 0.10; 0.16; 0.20; 0.30; 0.45 | none; none; WARNING; WARNING; CRITICAL; CRITICAL | sub; sub; near; near; clear; clear |
| two adjacent timestamps swapped (non-monotonic) | 1 per episode, 10% of episodes | some flag | clear |
| constant offset on one episode (+1 s) | 1 | none (no cross-episode clock check) | undetectable by design |
| one episode's timestamps in ms instead of s | 1 | some flag | clear |

All of 5.4(b) and (c) are labeled **detector unit validation** in the report:
the baseline clocks are perfect frame grids, so these runs show the detector
responds to injected timing noise, not that it would catch real clock faults.
If no check fires for a "some flag" row, that is reported as a *coverage gap*
(no check exists), separate from a miss by an existing check.

## 6. Clean data and what counts as corruption

### 6.1 Ground truth

An episode (or (episode, camera) pair) is **corrupt** only if:

- the harness injected a fault into it in this trial, or
- it carries an `acquisition_fault` label in `eval/real_faults/` at the same
  revision (today: H1 episode 26).

Everything else is **not corrupt**, including static scenes, idle operators,
repeated frames that the source data already contains, and unusual-but-valid
motion. A flag on a not-corrupt unit is an *anomaly*, not confirmed corruption,
and counts as a false positive for the integrity checks in scope.

### 6.2 Clean trials

Per dataset:

1. **Unmodified**: the pinned revision as downloaded.
2. **Copy control**: byte-identical copy through the same harness path.
3. **Re-encode control**: every episode of one camera relocated exactly as the
   frame-level injectors do, with no fault. Detections caused by re-encoding
   show up here and are subtracted before any frame-level fault is scored.
4. **Append control**: one *new* episode built from an existing one with a
   different trajectory (episode k's actions and state reversed, video pointing
   at k's segment). Tests that the append mechanics of 5.1 do not themselves
   trigger a flag.

### 6.3 Baseline triage

Every non-OK flag on a clean trial is triaged, before injected runs are scored,
into one of:

- **true positive (native fault)**: matches a labeled `acquisition_fault`
- **false positive**: no labeled fault explains it
- **not evaluated**: the check ran but could not evaluate (INFO), e.g. timestamps
- **harness artifact**: appears only in a control (re-encode, append), not in
  the unmodified data; fixed in the harness, not counted against Calibra

Native repeated frames (PushT idle steps) are measured on the unmodified data
per episode and per camera. That baseline rate is reported, and frozen-frame
injections are placed in episodes and spans where the native rate is known.

## 7. Scoring

**Unit.** Primary: a *trial* is one dataset copy with one fault variant at one
severity and seed. The trial is *detected* if the expected check emits any
non-OK level (WARNING or CRITICAL); whether that level is the expected one is
scored separately (section 9). For checks with episode attribution (duplicates,
video file checks) the trial is detected only if *every* injected episode is
attributed, and attributed non-injected, non-native episodes are episode-level
false positives. Where a check without attribution is already non-OK on the
unmodified data, the trial is *masked*: it cannot show a detection and is
reported, not scored.

**Outcomes per trial and check**: detected / missed / masked / not evaluated /
sampling-limited (missed by default decode, caught by full decode). Trials whose
injection could not apply to a dataset (e.g. no two episodes of equal length) are
listed as skipped.

**Collateral flags**: any other in-scope check that goes non-OK on an injected
trial and is non-OK on neither its clean control nor explained by the fault's
mechanism (e.g. dropped steps legitimately shorten an episode) is a collateral
false positive and reported per fault type.

**Metrics**, separately for each fault type × tier (and each dataset):

- recall (= 1 - false-negative rate), Wilson 95% interval
- false-positive rate on clean trials, and at episode level on the non-injected
  episodes of injected trials, Wilson 95% upper bound
- precision at episode level, where attribution exists
- level agreement matrix: expected vs emitted (OK / WARNING / CRITICAL / INFO)

Every count is reported raw next to every rate. Not-evaluated outcomes are never
counted as true negatives or as misses.

## 8. Severity tiers and success criteria

| Tier | Definition | Use |
|---|---|---|
| sub-threshold | below the check's first (WARNING or zero-tolerance) threshold | reports specificity at the boundary; a flag here is "fires beyond spec", reported, not scored as FP or TP |
| near | 1× to 1.5× that threshold | recall curve, no target |
| clear | ≥ 2× that threshold, or any instance of a zero-tolerance fault | target applies |
| undetectable by design | outside what the check is built to see | reported separately, never pooled |

Proposed engineering targets (not established performance claims):

- **0 false positives on clean trials** for in-scope checks, reported with the
  Wilson upper bound for the number of clean units checked.
- **≥ 95% recall on clear-tier faults, per fault type.** To make this testable,
  each fault type gets at least 60 clear-tier trials pooled over datasets and
  seeds (60/60 gives a 95% lower bound of 0.94). With fewer, the report says the
  target was not testable at that n.

Neither target is adjusted after results are seen. A miss is a finding to
report; whether to change a detector is a separate decision.

## 9. Severity validation

Expected levels in section 5 come from this rubric, written before running:

- **CRITICAL**: training on the data as-is will fail, or silently train on wrong
  data: missing/undecodable video, video that does not cover the episode, wrong
  fps, exact duplicate episodes (train/val leakage, double weighting), ≥ 5% of
  steps missing.
- **WARNING**: the data is usable but degraded and worth a look: isolated
  freezes, moderate repeated-frame rates, small dropout, moderate jitter.
- **OK**: within tolerance.

The report gives the agreement matrix (rubric level vs emitted level) for every
fault type and lists each disagreement with the observed value. Where the rubric
and the code disagree, both are reported; neither is changed in this benchmark.

## 10. Reproducibility

- Each run writes `manifest.json` (dataset repos + revisions, Calibra version +
  git commit + dirty flag, environment and encoder settings, sha256 of
  `config.toml` and this protocol) and one JSONL row per trial (variant,
  parameters, seed, injected units as ground truth, sha256 of every modified
  file, measured injected rate where applicable, full CLI argv and parsed
  verdict of every pass, timings).
- Seed per trial: `sha256(dataset|variant|rep)` truncated to 32 bits; reps
  0..R-1. Rerunning a trial id regenerates the same injection (re-encoded mp4
  bytes can still differ across encoder builds, so the encoder version is
  recorded).
- Datasets are downloaded at the pinned revision; the harness verifies the
  revision and the sha256 of `meta/info.json` before running.
- Threshold table (section 4) is read from code and compared at run time.
- Results: `results/<run>/trials.jsonl`, plus `summary.json` / `summary.md`
  regenerated from it by `score.py`.

## 11. Regression protection

For every confirmed result (detected and missed alike):

- a small synthetic fixture test in `tests/regression/` that reproduces the
  injection at minimal size and asserts the current outcome, so a detector change
  that flips it fails CI and has to be re-justified. Fixtures are generated in
  the test, never downloaded.
- one `slow`-marked end-to-end test that runs the harness on the smallest
  dataset (H1) for one variant per fault type.

Known misses are asserted as misses with an `xfail(strict=True)` and a pointer to
the report, so fixing them is visible.

## 12. Separate benchmark: configuration sensitivity

The configuration-sensitivity experiment is rerun on v0.13.0 under
`eval/selection_sensitivity/`, with its own protocol and results. It measures
whether the episodes selected by `calibra prune` change under configuration
changes; it shares no metrics, tables or claims with this benchmark. The
original experiment (John6666's configuration) is not in this repository. If
its source or config is found, it is reproduced; otherwise a pre-registered
parameter sweep is run and described as inspired by it, not as a reproduction.

## 13. Layout

```
eval/integrity_fault_injection/
  PROTOCOL.md          this file
  README.md            how to run
  config.toml          datasets, revisions, thresholds, fault grid, reps, tiers
  harness/v3.py        copy-on-write LeRobot v3 working copies, episode relocation
  harness/faults.py    one injector per variant; ground truth and expected levels
  run.py               build trials, inject, run calibra integrity, write results
  score.py             results -> tables (JSON + Markdown)
  results/             JSONL per run, manifests (large injected data is not committed)
  REPORT.md            short technical report generated from score.py output + text
```

## 14. Known limitations (stated in the report)

1. No dataset with real hardware timestamps: timestamp results are unit
   validation only.
2. Injected faults are idealized; their distribution says nothing about how
   common faults are in the wild.
3. All three datasets are LeRobot v3.0; v2.x per-episode video layout and other
   formats (HDF5, RLDS, MCAP) are not covered.
4. Ground truth for "not corrupt" relies on provisional labels for the native
   data (`eval/real_faults/SPOT_CHECK.md`, non-expert, not expert-verified).
5. The public JSON is dataset-level, except `video_affected_episodes`; duplicate
   attribution is recomputed with Calibra's own digest function.
6. Dropped steps (5.4b) leave video untouched, so they do not test a recorder
   that drops parquet rows and video frames together.

## 15. Decisions

1. **Real timestamps (decided 2026-10-17):** accept the limitation for the first
   report. Timestamp results stay labeled detector unit validation; real-clock
   validation comes from design-partner data, not a speculative dataset search.
2. **Reps (decided 2026-10-17):** 10 for parquet-only variants, 5 for variants
   that re-encode video, fixed after a one-rep timing pass on H1. Seeds are
   deterministic, so cells can be topped up without changing earlier trials.
   Clear-tier cells are topped up until each fault type reaches 60 trials.
3. **Configuration sensitivity (decided 2026-10-17):** does not block this
   benchmark; see section 12.

## Changelog

- 2026-10-17: initial draft.
- 2026-10-17 (before any scored run): decisions recorded (section 15). Injection
  mechanics specified from the v0.13.0 code: per-episode relocation instead of
  whole-file re-encode; duplicates reuse the source video segment; added
  one-episode missing file, metadata-claims-full-span drop, and
  parquet-identical/other-video duplicate variants; dropped steps are runs of 3
  rows because `timestamp_dropout_rate` ignores gaps up to 3x the median
  (single drops are now a by-design row); recall counts any non-OK flag and
  tiers are relative to the first threshold, with level correctness scored in
  section 9; episode-attributed detection and the "masked" outcome defined.
- 2026-10-17 (after the unscored one-rep H1 smoke test, before any scored run):
  expected levels for frame faults now come from the frames as injected (before
  encoding), not from the decoded file; using the decoded file made encoder
  losses look like correct non-detections. Decoded values are still recorded.
  Dropped-step gap counts round up so the realized rate does not fall under the
  target. Jitter noise is standardized per episode, and the 0.15 grid point
  moved to 0.16 because 0.15 stores as 0.14999998 in float32 timestamps.
  Encoder: preset 12 is used for speed; the repeated-frame result was checked
  to be the same with LeRobot's default (unset) preset.
- 2026-10-17 (during the v0.13.0 run, before scoring; no results inspected):
  reps cut for decode-heavy variants to fit compute. Repeated frames: 1 rep per
  rate (the smoke test showed a deterministic codec effect: 0/18 isolated
  repeats survive encoding at either preset). Frozen frames: 4 reps for clear
  tier (72 clear trials over 3 datasets, still >= 60), 2 for sub/near.
  Re-encode control: 2 reps. Trials already run at the old rep count are kept.
  Parquet-only variants unchanged (10 reps).
- 2026-10-17 (during the v0.13.0 run, after H1 finished, before ALOHA ran):
  ALOHA has about 11x H1's decoded video (36 vs 3.3 gigapixels; ~10-15 min per
  decode pass), so the decoded frame-fault variants (frozen and repeated frames,
  re-encode control) run on H1 and PushT only. ALOHA runs every other variant
  plus a fully decoded clean copy. PushT gets 2 extra reps of the frozen-frame
  run10/run30 variants so the frozen clear tier still reaches 60 trials. Each
  run invocation now writes its own manifest under results/<run>/manifests/.
