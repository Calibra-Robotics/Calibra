# Changelog

All notable changes to Calibra are documented here.

## [Unreleased]

### Changed

- **`ldlj` is no longer an integrity check.** It no longer counts toward
  `calibra integrity`'s score, findings or CI result, or `calibra analyze`'s
  "Motion & control" row; it still feeds the Calibra Score (unchanged). Its
  fault detection is inconsistent: rerun on current code, the benign-firing
  benchmark has it catching 5 of 7 corrupted ALOHA episodes but 0 of 30 on
  PushT (`jerk_spike_rate`: 6/7 and 12/30), it scores far-swap spike injection
  as smoother, and it moves about 4 units with sampling rate alone
  (`eval/investigations/ldlj/`). Integrity scores that included an LDLJ
  WARNING or CRITICAL go up.
- **Benign-firing benchmark rerun** (`experiments/results/benign_firing_rates.*`,
  2026-10-20): only `ldlj` changed (PushT clean flag rate 0/206 → 2/206;
  detection 50.0% → 35.7%); the README table and the PushT `ldlj` baseline in
  `calibra/calibration.py` follow it.
- README / `docs/integrity.md`: motion checks depend on sampling rate (the same
  ALOHA trajectories read 1.45% velocity discontinuities at 50 Hz and 15.6% at
  10 Hz); compare motion findings only between datasets at similar rates.

### Fixed

- **Clean PushT no longer reads as a motion defect in `integrity` and
  `analyze`.** The `pusht` profile set gripper dims, regime thresholds and
  prune limits, but not flag severity, so the arm-calibrated thresholds
  (0.02 / 0.05) rated PushT's normal 16.7% velocity-discontinuity rate CRITICAL
  and its 4.9% spike rate WARNING. Profiles now carry `flag_thresholds`; `pusht`
  sets `jerk_spike_rate` 0.11 / 0.25 and `velocity_discontinuity_rate`
  0.28 / 0.40 (clean p95 episode / past the clean max).
  `tests/test_dataset_profiles.py` checks each threshold against the clean
  baseline. Thresholds the caller sets explicitly still win
  (`DefaultThreshold` marker, as for `gripper_dims`). Regression golden:
  `analyze[lerobot/pusht]` `jerk_spike_rate` WARNING → OK and
  `velocity_discontinuity_rate` CRITICAL → OK; the unprofiled path and prune
  decisions are unchanged. The Calibra Score is not affected (it uses its own
  thresholds in `calibra/score.py`). Detection on PushT is less sensitive as a
  result: a dataset-wide motion fault must now push the mean past PushT's clean
  p95 to warn.
- **`analyze` now includes the 0.13.1 timestamp checks.** `timestamp_non_monotonic`
  and `timestamp_scale_mismatch` were missing from `analyze`'s integrity
  categories, so they were left out of its integrity rows and score (a CRITICAL
  from either showed in `calibra integrity` but not in `analyze`). They now roll
  up into "Timestamps & sync"; a test keeps the category map in sync with
  `calibra integrity`'s metric set.
- README, `docs/guide.md` and `docs/commands.md`: the `calibra analyze
  lerobot/pusht` example output was from before the per-sub-movement LDLJ
  change and these fixes. It is regenerated from the PushT regression fixture:
  Integrity 100/100 Healthy, Calibra Score 60.5, coverage 61.2 (was 69 / 44.6 /
  47.4); the recommendation is unchanged.
- **`--cache-dir` no longer serves reports from older code or other settings.**
  The key covered only the episodes, policy family and profile name, so a
  report cached before an upgrade or a threshold change kept being returned.
  It now also covers the Calibra version and every analyzer's resolved
  settings (after the profile is applied). Existing cache entries are
  recomputed once.
- **PushT references re-profiled** (`pusht_velocity_command.json`,
  `pusht_image.json`, revision `7628202a`) with per-sub-movement LDLJ: mean
  −16.34 → −8.89, now recorded as `ldlj_definition: per_submovement_v1`, so
  `calibra compare` compares LDLJ against them again. Spike and
  velocity-discontinuity distributions are unchanged; the 0.13.x timestamp and
  duplicate-episode metrics are added. The other 14 references still use the
  whole-episode definition. Claims LDLJ-001 / LDLJ-002 now declare
  `evidence_ldlj_definition: whole_episode`, and
  `tests/test_claims_references.py` checks LDLJ evidence only against a
  reference with the same definition; LDLJ-001's re-test note records PushT's
  new value.
- **13 more references re-profiled with per-sub-movement LDLJ** (all ALOHA
  sim/static/mobile, DROID-100, SO-100 pickplace/stacking), offline from the
  local HF cache, each with its recorded settings. Apart from LDLJ, the only
  differences are documented code changes (velocity-discontinuity CIs now on
  the filtered rate, the 0.13.x short-episode fence, current flag thresholds);
  raw means are unchanged. LDLJ values move from −17…−28 to −9…−13.
  `bridgedata_v2.json` is not replaced: on its Hub revision `b96f7216` its
  spike and velocity-discontinuity rates do not reproduce (0.81% / 59.9% vs
  0.71% / 80.5%), and the June 2026 analyzer gives today's numbers on that
  data, so the reference came from other data (an unrecorded revision or
  loader). It stays whole-episode.
- **ALOHA references exclude both grippers** (`gripper_dims [6, 13]`, the
  ALOHA/ACT layout of 6 joints + gripper per arm). Before, nine excluded only
  the last dim (scoring the left gripper as a joint), `aloha_sim_insertion_human`
  excluded none and `aloha_mobile_cabinet` already used `[6, 13]`. Only
  smoothness metrics change (coverage, temporal and task-structure output is
  identical). Claim evidence that cites these references is updated in the
  same change: JS-001 (9 entries), VD-001 (9), JS-003 (2), LDLJ, each with a
  `[Corrected 2026-10-19]` note; no JS-001 / VD-001 entry crosses its claim's
  boundary. `aloha_static_cups_open` now reads 8.10% velocity discontinuities
  (was 6.44%), just above VD-001's 0.08 falsification threshold: a review
  pending test records it; the claim's status is unchanged pending that review.
  Runtime analysis of ALOHA datasets is unchanged (still `[-1]` by default).
- **LDLJ claims judged on direct tests** instead of single-dataset values
  (whole-episode evidence and the single-dataset measurements are retracted
  with reasons):
  - **LDLJ-002 falsified.** Per-sub-movement LDLJ does not separate
    spike-injected copies from the clean data: on ALOHA it scores the corrupted
    copy as *smoother* (battery −12.63 → −11.29 at 2% injected spikes;
    insertion −11.01 → −9.90 at 5%), and on SO-100 it barely moves; jerk spike
    rate detects every run. `eval/investigations/ldlj/SPIKE_INJECTION.md`.
  - **LDLJ-001 supported (MODERATE), frequency half only.** Changing only
    the sampling rate of the same ALOHA trajectories moves LDLJ by 2.6–5.1
    units (battery −12.63 at 50 Hz → −8.57 at 10 Hz → −7.53 at 5 Hz), and
    ALOHA at 10 Hz scores like PushT at its native 10 Hz. BridgeData2
    (velocity, 5 Hz, −8.70) scores smoother than native 50 Hz ALOHA, but at a
    matched 5 Hz the order is the physical one, so control mode alone is not
    shown to break comparability (pending test). `eval/investigations/ldlj/SUBSAMPLING.md`,
    `eval/investigations/ldlj/subsample.py`.
  - Same-trajectory subsampling also moves jerk-spike and
    velocity-discontinuity rates (ALOHA insertion 1.45% → 15.6% velocity
    discontinuities at 10 Hz, close to PushT's 16.7%). This bears on JS-003,
    VD-001 and the `pusht` profile's reading of its rate; not acted on here.
- **`calibra corrupt` no longer counts an improved metric as a detection.** A
  metric that scores the corrupted copy better (LDLJ under spike injection)
  was listed under "Detected by Calibra"; it is now listed under "Moved the
  wrong way".
- `calibra/claims/SPEC.md` documents `"supports": null` (measured, not yet
  judged; ⏳ in `docs/claims.md`, no confidence credit), and
  `tests/test_claims_references.py` checks LDLJ evidence only against
  references with the same `ldlj_definition`.
- `docs/benchmarks.md`: the PushT / DROID-100 observation claimed CRITICAL
  jerk and velocity-discontinuity flags (not true under current code) and an
  8–10 point win over random (the table shows 1.3 on PushT). It now follows the
  table, and the page says its scores are from Calibra 0.8.0.

## [0.13.1] - Integrity fixes from fault injection

### Added

- **`timestamp_non_monotonic`** (temporal analyzer, `calibra integrity`):
  CRITICAL when any episode's timestamps repeat or go backwards. v0.13.0 caught
  swapped timestamps only through jitter CV, which missed them when few
  episodes were affected (0/30 at 10% of episodes; now 30/30).
- **`timestamp_scale_mismatch`**: CRITICAL when an episode's median step is
  more than 10x away from the dataset's (e.g. one episode in milliseconds). In
  v0.13.0 such an episode still lay on a frame grid, so timing was reported as
  not evaluated (now 30/30 detected). Both checks run even when timestamps are
  synthetic. On the PushT regression fixture both are OK; no other output
  changed (golden updated for the two new entries only).
- **Integrity fault-injection benchmark** (`eval/integrity_fault_injection/`):
  pre-registered protocol, injectors for LeRobot v3 on-disk copies (duplicate
  episodes, missing/truncated/wrong-fps video, dropped video frames, frozen and
  repeated frames, dropped steps, timestamp jitter, swaps, offsets and units),
  `run.py` / `score.py`, the v0.13.0 results (981 trials on Unitree H1, PushT
  and ALOHA), the post-fix rerun (471 trials) and a technical report. Findings
  are listed under [0.13.0] Known limitations.
- `tests/regression/test_fault_injection_findings.py`: the benchmark's confirmed
  detections as tests, and its remaining known miss as a strict xfail that fails
  once a detector change fixes it.

### Changed

- **`--decode-video` says what it did not check.** When fewer episodes are
  decoded than exist, the `duplicate_frame_rate` and `camera_freeze_events`
  output says episodes outside the sample were not checked and gives the
  `--video-sample` value that checks all of them.
- **`duplicate_frame_rate` states that it is a lower bound on inter-coded
  video** (AV1, H.264, ...; codec read from `info.json`). Levels are unchanged.

### Documentation

- README: frame checks on LeRobot v2/v3 via `--decode-video` were documented as
  unsupported; they shipped in 0.13.0. Added the AV1 caveat, the 20-episode
  default sample, and a fault-injection results section. Removed the stale
  "next: Vision Integrity for v2/v3" roadmap entry.
- Corrected the first fault-injection report (2026-10-17): it said AV1
  compression erases repeated frames and that ALOHA's `duplicate_frame_rate`
  flag is a compression artifact. A harness error placed every injected repeat
  on a keyframe; see [0.13.0] Known limitations for the measured behavior.

## [0.13.0] - Trustworthy integrity checks

### Changed

- **`velocity_discontinuity_rate` severity ignores sensor noise.** The flag
  level now comes from the rate after the same ~10 Hz low-pass LDLJ uses (no-op
  at ≤10 Hz); the text shows the unfiltered rate when it differs. Unfiltered, the
  metric was CRITICAL on clean 50 Hz data and non-monotone: an injected spike
  raised peak speed and hid the noise, so lightly corrupted ALOHA scored 2.9% vs
  6.5% clean. Filtered: 0.0% clean, rising with corruption. ALOHA CRITICAL → OK,
  Unitree H1 CRITICAL → WARNING, PushT unchanged. The unfiltered rate is kept
  (`mean_disc_fraction`, per-episode values) for regime thresholds, prune limits,
  profiles, the Calibra Score and claims, so those do not move; filtered values
  are added alongside. Evidence: `eval/investigations/vel_disc/FINDINGS.md`.

- **Local dataset copies get their dataset profile automatically** when they
  can be identified from their own files: the `hf download` revision equals the
  revision a profile was measured on, or the dataset card links a covered Hub
  ID. Previously only Hub IDs did, so `calibra prune ./pusht` silently used the
  global Stage-1 limits and dropped 48 clean PushT episodes (0 with the
  profile). The applied profile and the evidence are printed and stored in the
  report (`dataset_profile_reason`); a directory named like a profiled dataset
  only prints a `--profile` hint. An explicit `--profile` still wins.

- **`short_episode_fraction` no longer flags fixed-length recordings.** The lower
  fence is now `Q1 − 1.5 × max(IQR, 0.25 × median)`. Datasets recorded at a few
  fixed lengths have IQR = 0, which put the fence at Q1: on
  `lerobot/unitreeh1_rearrange_objects` (23 × 250 and 7 × 200 steps) every
  complete 200-step episode was an "outlier" and `calibra integrity` failed CI.
  An episode must now be below about 62% of the typical length to count as
  short; ordinary variable-length datasets are unaffected (regression goldens
  unchanged for this metric).

- **`ldlj` is now computed per sub-movement** (`ldlj_definition:
  per_submovement_v1`). Whole-episode LDLJ was defined for a single movement;
  over a demonstration of N movements it fell by about 4 ln N regardless of
  smoothness, and triple differentiation amplified sensor noise by 1/dt³, so it
  was CRITICAL on all 30 official LeRobot datasets audited and correlated −0.95
  with episode length on PushT. Velocities are now low-pass filtered (moving
  average, ~10 Hz; no-op at ≤10 Hz), split into sub-movements at speed minima,
  scored per sub-movement and combined as a duration-weighted mean. Thresholds
  (−10 / −15) are unchanged; they are the single-movement scale the new values
  are on. Details and evidence: `eval/investigations/ldlj/FINDINGS.md`.
  - Smooth synthetic demos score −4.6 to −5.0 for any number of movements
    (previously −4.5 to −18.4). Injected glitches and heavy noise still lower
    the score. White-noise actions score about −11 to −13 (WARNING); they
    remain CRITICAL on `velocity_discontinuity_rate`.
  - PushT: `ldlj` CRITICAL → OK (mean −16.0 → −8.1); Calibra Score
    44.3 → 63.1. The old value zeroed the smoothness dimension, which through
    the integrity gate also halved coverage and task-structure credit.
    Regression goldens updated (`ldlj` only). [Corrected 2026-10-19: these
    numbers are from an unprofiled run (`./datasets/pusht`), which scores the x
    axis only. With the `pusht` profile, as `lerobot/pusht` runs by default:
    mean −16.34 → −8.89, Calibra Score 60.5 on 0.13.1.]
  - Expect higher Calibra Scores and fewer `ldlj` flags on most datasets,
    especially long or 50 Hz ones. Stage-1 per-episode drops at `min_ldlj`
    (−30) effectively no longer occur.
  - Reference profiles in `calibra/references/` were made with the old
    definition. `calibra compare` no longer compares `ldlj` against them and
    says so; regenerate a reference with `scripts/profile_dataset.py`, which
    now records `ldlj_definition`. Claims LDLJ-001 / LDLJ-002 are annotated as
    measured with the old definition, with re-tests pending.

- **Synthetic timestamps are reported as not evaluable, not passed.** When every
  episode's timestamps lie on an exact `t0 + k*dt` grid (LeRobot writes
  `frame_index / fps`; simulators step a fixed clock), `timestamp_jitter_cv` and
  `timestamp_dropout_rate` are emitted at level INFO with the reason, and
  `calibra integrity` lists them under Not Evaluated instead of Passed. They no
  longer count toward the integrity score, so integrity scores of LeRobot and
  simulated datasets drop accordingly. Raw metric values, the Calibra Score and
  pruning decisions are unchanged. Regression goldens for PushT updated
  (OK → INFO for these two metrics only).
- `calibra analyze` and `calibra integrity` treat INFO integrity flags as not
  evaluated. Previously a category with only skipped checks (e.g. calibration
  drift with no stationary holds) showed as OK in `analyze` and was omitted
  entirely from `integrity`.
- **Dataset cards no longer show a predicted training success rate.** The
  prediction is not validated, and cards are meant for other people's dataset
  pages. The Calibra Score is labelled as a heuristic composite.
- `calibra prune` prints a ready `lerobot-train` command for LeRobot sources
  instead of the old `python train.py` hint.

### Added

- **`calibra integrity --decode-video`** runs `duplicate_frame_rate` and
  `camera_freeze_events` on LeRobot v2/v3 video (previously Not Evaluated).
  Opt-in, sampled (`--video-sample N`, default 20 episodes, evenly spaced),
  full resolution in 64-frame chunks, every camera; same measure and
  thresholds as for image datasets. Validated on real data: flags
  `lerobot/aloha_static_battery` (`cam_high` 30% repeated frames, cameras
  slower than the 50 Hz recording), passes `unitreeh1_rearrange_objects`
  (<1%) and `pusht` (1.5%).
- **Duplicate episode check** (`duplicate_episode_fraction`, task_structure
  analyzer): episodes whose actions and numeric observations are byte-identical
  to another episode are CRITICAL and block-level in `calibra integrity`; the
  finding names each copy and its original. Found in practice: episode 26 of
  `lerobot/unitreeh1_rearrange_objects` @ `e874d89b` copies episode 6.
- `calibra integrity` checks LeRobot v2/v3 video files (missing, undecodable,
  frame-count/coverage mismatch, wrong fps) on local datasets. New optional
  extra `calibra-robotics[video]` (OpenCV).
- `calibra.integrations.lerobot`: `lerobot_train_args`, `lerobot_episode_indices`
  and `load_lerobot_dataset` to train on kept episodes without exporting a copy.
- `calibra card --push --create-pr` opens the card as a Hub pull request.
- Real-fault evaluation tooling (`calibra.fault_eval`, `scripts/fault_eval.py`,
  `eval/real_faults/`).

### Fixed

- `calibra card --push` replaced the dataset's entire README with the card (it
  read a non-existent attribute and always saw an empty README). It now edits
  only the Calibra section and aborts if the README can't be read.
- `calibra benchmark` printed `--dataset.episodes` with batch positions instead
  of LeRobot `episode_index` values.

### Known limitations

Measured after release (2026-10-17, corrected 2026-10-18) by the integrity
fault-injection benchmark; see `eval/integrity_fault_injection/REPORT.md`. Items
marked *addressed* are changed in [0.13.1].

- **`duplicate_frame_rate` under-counts on AV1-encoded video** (LeRobot v2/v3
  with `--decode-video`). With LeRobot's 2-frame GOP, a repeated frame coded as
  a predicted frame is detected (18/18), but one that lands on a keyframe is
  re-encoded with fresh noise and looks new (0/18), so the rate is about half
  the true rate. It does not flag static scenes: unmodified
  `lerobot/aloha_static_battery` reads CRITICAL because its frames really
  repeat, including while the arms move. *Addressed:* the flag now says the
  rate is a lower bound.
- **`--decode-video` checks 20 episodes by default**, so a frozen camera in an
  episode outside the sample is missed (19 of 60 injected freezes). Pass
  `--video-sample N` with the episode count to check every episode.
  *Addressed:* the output now says so.
- **No timestamp monotonicity check.** Swapped timestamps are caught only
  through jitter CV, which misses them when few episodes are affected (0/30 at
  10% of episodes). *Addressed:* `timestamp_non_monotonic`.
- **An episode stored in milliseconds disables the timing checks**: its
  timestamps still lie on a frame grid, so the dataset is reported as synthetic
  and timing is not evaluated. *Addressed:* `timestamp_scale_mismatch`.
- **`timestamp_dropout_rate` cannot see single dropped steps**: it counts gaps
  longer than 3x the median interval, and one missing step leaves a 2x gap.
  Deliberate threshold; not changed.

## [0.12.0] - Apache 2.0 core

### Changed

- **Calibra is now licensed under the Apache License 2.0** (previously Business
  Source License 1.1). It is OSI open source with no restriction on hosting.
  The `ee/` directory keeps its own license and is not part of the
  `calibra-robotics` package; see `NOTICE` and `LICENSING.md`. Releases up to
  0.11.x keep their BSL terms.
- **Calibra Cloud code moved out of the core into `ee/`** (ADR-012), ahead of
  relicensing the core under Apache 2.0. `calibra/cloud/` is now
  `ee/calibra_ee/cloud/` and `server/` is now `ee/server/`; neither is
  published to PyPI. The core finds them through a new `calibra.plugins` entry
  point (`calibra/plugins.py`).
  - `calibra login`, `logout`, `whoami` and `cloud` are available only with
    the extension installed (`pip install -e ee/`). Without it they exit 2
    with an explanation.
  - **The core no longer contacts Calibra Cloud on its own.** Recording an
    outcome stays local (`~/.calibra/outcomes.jsonl`); the anonymous outcome
    sync, the community percentiles printed after
    `calibra predict --record-outcome`, and badge registration after
    `calibra card --push` now run only with the extension. Dataset cards use
    the static shields.io badge unless the extension provides a live one.
    `calibra compare --community` and `calibra calibrate --global` still reach
    the service, because the user asks for them explicitly.
  - `predict_outcome()` accepts an `outcome_source` for empirical blending;
    the local outcome store remains the default.
- **Outside contributions are closed for now:** issues and discussions are
  turned off, and a workflow closes external pull requests automatically with
  a pointer to the contact email. A draft Contributor License Agreement
  (`CLA.md`) is kept for when contributions open. `GOVERNANCE.md` describes
  who decides what.
- **CI now also runs on Python 3.13, fails if the mypy error count rises**
  above its baseline (`scripts/mypy_ratchet.py`), and **fails if test coverage
  drops below 58%** (measured with only the dev extra installed, as in CI).
- Added `pre-commit` hooks and `CITATION.cff`. `SECURITY.md` now points to
  private vulnerability reporting, and `SECURITY.md` and `CODE_OF_CONDUCT.md`
  name a contact.

### Fixed

- **The certify GitHub Actions never failed a job.** In
  `.github/actions/certify` and the reusable `.github/workflows/certify.yml`,
  `$(calibra certify ...) || true` followed by `EXIT_CODE=$?` always read 0, so
  NOT CERTIFIED datasets passed and `strict` had no effect. Both now fail on
  NOT CERTIFIED, and on warnings when `strict` is on.
- **The reusable certify workflow could not see local datasets:** it never
  checked out the caller's repository. It now does.
- **The root `action.yml` interpolated the report into its PR-comment script,**
  so report text containing a backtick or `${` broke the script or ran as
  JavaScript. All three certify entry points now pass inputs and outputs
  through environment variables. Its `score` output was always empty (it read
  a key `certify --json` does not emit) and now comes from `calibra score`.
  The comment is truncated to fit GitHub's size limit, and a comment that
  cannot be posted no longer fails the job.
- **`calibra compare <dataset> pusht`** judged velocity discontinuities with the
  position-command thresholds calibrated on arm datasets once the PushT
  reference was correctly labelled `position`, so PushT-like data (~17%) read
  as "significantly rougher than pusht". References produced under a dataset
  profile are now interpreted against their own clean baseline, and only
  class-agnostic claims are shown next to them.
- **Claim confidence now follows the SPEC scale** (`calibra/claims/SPEC.md`):
  2–4 supporting datasets is MODERATE. The code had labelled 2 as LOW (below
  1's LOW-MODERATE) and 3–4 as an undocumented MEDIUM. JS-003, PAI-001 and
  TEMP-003 (2 supporting datasets each) move LOW → MODERATE.
- **aloha_mobile_cabinet numbers in `calibra/references/README.md`** quoted
  the first reference run (2026-06-15, 5387172), which excluded only dim 13 and
  scored the left gripper as motion. They now match the committed reference
  (both grippers excluded), which reproduces on current code: LDLJ −24.08 →
  −24.70, spikes 1.0% → 0.42%, velocity discontinuities 1.3% → 0.84%, jitter
  3.1e-5 → 3.0e-5, contact 78.9% → 78.8%. The 8 / 85 outliers reproduce
  exactly (same episodes) and are unchanged.
- **An explicit `--gripper-dims` now survives a dataset profile.** Profiles
  replaced any `gripper_dims` equal to the default `[-1]`, so asking for `-1`
  explicitly on a profiled Hub ID (e.g. `lerobot/pusht`) was silently
  overridden. Analyzers now default to a marked `DefaultGripperDims([-1])`,
  which behaves identically but is the only value a profile replaces.
  `compare`, `corrupt` and `scripts/profile_dataset.py` share one
  `parse_gripper_dims` helper. No default behavior changes (the benchmark
  regression gate is unchanged).

### Added

- **Evidence-gated dataset profiles.** Every profile now carries a
  `ProfileEvidence` record (dataset revision, sampling rate, action space,
  reference run, clean baseline, justification, reproduction command). Tests
  fail if it is incomplete, if the baseline disagrees with the cited reference
  file, or if a profile's prune limits would cut its own clean episodes.
- **Benchmark regression gate** (`tests/regression/`, its own CI step). Runs
  analyze and prune on a frozen copy of `lerobot/pusht` (revision `7628202a`,
  259 KB fixture) and fails when any flag level, regime, headline metric or
  kept/dropped episode changes. Intended changes regenerate the golden file
  with `CALIBRA_UPDATE_GOLDEN=1 pytest tests/regression`.
- **Evidence rules for GitHub Copilot code review**
  (`.github/copilot-instructions.md`, plus path-specific rules in
  `.github/instructions/` for claims and for references, golden results and
  profiles). Copilot's advisory review flags PRs that change golden results,
  thresholds, profiles, claims or reference data without evidence. It needs no
  repository secret, unlike the Claude Code workflow it replaces.
- `.github/CODEOWNERS` for verdict-affecting code, a dataset profile proposal
  issue form, and contribution docs describing the evidence standard.

### Changed

- **Refreshed the PushT reference** (`calibra/references/pusht_velocity_command.json`).
  It predated the float64 differentiation fix in the smoothness analyzer, so its
  means were stale: spike rate 4.939% → 4.946%, velocity discontinuity rate
  16.718% → 16.696%. p95 and max, which the profile thresholds rest on, are
  unchanged, so no verdict moves. The stale `control_mode: velocity` label is
  dropped (PushT actions are position targets).
- **Regenerated the `pusht_image` reference.** The old file reproduces exactly
  on its original code (8762669), which scored only the x axis (the y target
  was excluded as a "gripper"), differentiated in float32, and labelled the
  data `velocity` without using that label. `lerobot/pusht_image` has the same
  actions as `lerobot/pusht`; profiled correctly (position, both axes) its
  smoothness distributions match PushT exactly (spike 7.76% → 4.95%, velocity
  discontinuities 11.11% → 16.70%, LDLJ −16.01 → −16.34).
- **Reference metadata is now authoritative.** `scripts/profile_pusht.py`
  records `control_mode`, `gripper_dims` and `dataset_profile`, and
  `scripts/profile_dataset.py` records the gripper dims actually applied (a
  dataset profile can replace an explicit `--gripper-dims` equal to the
  default). The paper table's Ctrl column for both PushT rows now reads
  `position` from that metadata.
- PushT episode outliers in `calibra/references/README.md`: 27 / 206 → 16 / 206.
  27 reproduces only on June 2026 code (x axis only, float32).
- **Claims registry corrected.** PushT is position control, so it was never
  evidence for the velocity-class claims JS-002, JS-004, VD-002 and VD-003, and
  `pusht_image` (the same data) was never a second dataset. Those entries, and
  two BridgeData-vs-PushT comparisons that assumed both were velocity control
  (JS-003, LDLJ-002), move to a new `retracted_evidence` list with a date and
  reason. Confidence: JS-004 and VD-003 MEDIUM → LOW-MODERATE, LDLJ-002
  STRONG → HIGH; no status changes. LDLJ-001 and ENT-001 keep their PushT
  evidence with dated corrections to its reasoning. Three stale values
  (ENT-001 for two ALOHA datasets, VD-001 for aloha_mobile_cabinet) now match
  their references and still support their claims.
- **Claim values are checked against references**
  (`tests/test_claims_references.py`): every numeric evidence entry must match
  its dataset's reference file. `docs/claims.md` shows retracted evidence.
- The report's cross-dataset table lists pusht and pusht_image as one row.

## [0.11.0] - Dataset profiles and README fixes

Every command in the README was re-run end to end; this release fixes what did
not work as documented. Highlights: the Isaac Lab → GR00T integration and
`--export-dataset` produce usable output again (the exported PushT coreset loads
and trains in LeRobot 0.4.4), `calibra serve` POST endpoints work again, and
dataset profiles let PushT be analysed correctly without changing any global
default.

### Added

- **Dataset profiles** (`calibra/dataset_profiles.py`). Smoothness and
  calibration-drift checks exclude the last action dimension as a gripper by
  default, which silently dropped PushT's `y` axis (its 2-D action is an
  `(x, y)` target with no gripper). The global default is unchanged; instead the
  `pusht` profile sets `gripper_dims=[]` and applies automatically to
  `lerobot/pusht` and `lerobot/pusht_image`. Local copies take
  `--profile pusht` (on `integrity`, `audit`, `review`, `prune`, `analyze`,
  `score`; `Pipeline(profile=...)` in Python). Profiles only replace analyzer
  defaults, never explicit settings. The applied profile is recorded in the new
  `DiagnosticReport.dataset_profile` field and included in `config_hash` and the
  cache key. With the profile, PushT's smoothness metrics match the hand-measured
  reference profile in `calibra/references/README.md` (LDLJ −16.34, jerk spikes
  4.9%, velocity discontinuities 16.7%).
- **PushT calibration baselines re-measured** with the profile
  (`experiments/benign_firing_rate_benchmark.py`, 2026-09-23): `spike_rate`
  5.8% (was 1.5%), `vel_disc_rate` 1.9% (was 3.9%), `jitter_cv` 0.0% (was 6.8%,
  stale since the 1% jitter floor). ALOHA was re-measured too and is unchanged.
  `calibra audit lerobot/pusht` now sits exactly at its baseline.
- **Profile regime thresholds.** Scoring PushT's `y` axis raises its velocity
  discontinuity rate to 16.7%, above the global 13% HIGH NOISE cutoff, which
  made `analyze` recommend 81/206 episodes and drop 125 as "corrupted". That rate
  is PushT's clean baseline under 10 Hz mouse teleop, not corruption, so the
  `pusht` profile sets `disc_high=0.25` (about 1.5× the clean rate) via the new
  `DatasetProfile.regime_thresholds`. `diagnose_regime` applies a report's
  profile thresholds automatically (explicit `custom_thresholds` still win), and
  the noise score uses the same thresholds. The global thresholds are unchanged.
  PushT stays MODERATE NOISE with 175/206 episodes recommended.
- **Profile `prune` limits** (`DatasetProfile.prune_thresholds`). `prune`'s
  global Stage 1 limits (spike 0.10, velocity discontinuities 0.25) sit at
  PushT's own clean p95 (10.4%, 27.5%), so they removed clean PushT episodes.
  The `pusht` profile uses the limits `analyze` already applies to PushT (0.25,
  0.40), which clear its clean maximum (16.1%, 37.5%): PushT now loses 0
  episodes in Stage 1 (48 without the profile, the global limits being
  unchanged). Explicit `--max-spike-rate` / `--max-vel-disc-rate` still win;
  `--max-vel-disc-rate` now defaults to unset (resolved to 0.25) so `prune` can
  tell. The profile also reaches `Pi0CompatibilityAnalyzer`'s internal
  smoothness check (new `gripper_dims` field) and every `calibra serve`
  endpoint (new optional `profile` request field for local paths).

### Fixed

- **Every `calibra serve` POST endpoint returned 422.** `serve.py` used
  `from __future__ import annotations` while defining its request models inside
  `_make_app()`, so FastAPI could not resolve `req: AnalyzeRequest` and expected
  a `req` query parameter instead of a JSON body. The import is removed; a test
  now checks every POST endpoint reads a JSON body. `serve` outlier detection
  also gets the dataset ID for calibration baselines, as `audit` does.
- **PushT was documented as velocity commands.** Its actions are absolute (x, y)
  target positions (they correlate 0.99 with the next position, 0.10 with the
  position change). `calibra/references/README.md` and
  `scripts/profile_pusht.py` are corrected; the reference metrics were already
  computed correctly in position mode.
- **Isaac Lab → GR00T integration crashed on every Isaac Lab file.** The reader
  emits episode IDs like `demo_21`, but `export_gr00t_manifest`,
  `recommended_demo_indices`, `rejected_demo_indices`, and `filter_hdf5` parsed
  them with `int()`. They now accept both `demo_N` and `N`. `filter_hdf5` also
  keeps the `data` group attributes (robomimic `env_args`), updates `total`, and
  rewrites `mask/train` / `mask/valid` for the new demo numbering.
- **`calibra prune --export-dataset` produced unloadable LeRobot datasets.** It
  wrote one `train-00000-of-00001.parquet` regardless of the source layout, and
  dropped videos and the episode index. It now follows `info.json`: LeRobot v3
  gets `data/…/file-000.parquet`, a rewritten `meta/episodes/*.parquet`, the
  referenced video files, and `tasks.parquet`. LeRobot v2 gets per-episode
  Parquet and mp4 files. `splits` is an episode range. Verified by loading the
  exported PushT coreset with `LeRobotDataset` (lerobot 0.4.4) and training on it.
- **HDF5 `--export-dataset` silently exported every demo** for robomimic /
  Isaac Lab files, because demos live under `data/demo_N`. Only the kept demos
  are now copied, with `total` and `mask/` updated.
- **`calibra audit` never showed calibration baselines.** The "Clean baseline"
  column always read "unavailable" because the dataset ID was not passed through.
  Hub datasets with a built-in baseline (e.g. `lerobot/pusht`) now show it.
- **`calibra prune` (default world-model strategy) was non-deterministic.** JEPA
  weights and minibatch order were unseeded, so the same input could keep
  different episodes. `RobotJEPAConfig.seed` (default 0) now fixes both, without
  touching global RNG state.
- **Duplicate-frame and camera-freeze checks blocked clean datasets.** A
  transition counted as a repeat when the *mean* pixel difference was below 0.5,
  which is also true when a small object moves in a low-resolution frame:
  `lerobot/pusht_image` got BLOCK on 206/206 episodes although no two consecutive
  frames are identical. A repeat is now a transition where fewer than 0.05% of
  pixels changed by more than 2 levels, which separates re-emitted frames from
  both small motion and live sensor noise. `activity_threshold` is replaced by
  `pixel_tolerance` and `min_changed_fraction` on both analyzers.
- **Smoothness metrics depended on the action dtype.** Jerk, velocity
  discontinuity, and LDLJ were differentiated in whatever dtype the reader
  returned. With quantised actions (PushT's integer pixel targets), float32
  rounding broke exact ties at the `k × median` spike boundary, so the same data
  read by different loaders gave different results (PushT `spike_rate` outliers:
  7 vs 3), and audit disagreed with its own calibration baseline. Derivatives are
  now always computed in float64. With default analyzer settings (no dataset
  profile), `prune` on PushT now removes 48 (was 51) quality failures.
- **Install hints named the wrong PyPI package** (`calibra[...]`, an unrelated
  project). They now say `calibra-robotics[...]`.

## [0.10.1] — CLI fixes

### Fixed

- **`calibra audit` subcommand** — the command was documented in the README
  and the Commands table but had no dispatcher in the CLI, so running
  `calibra audit <path>` silently fell through to the wrong argument parser.
  `calibra/audit.py` now implements `run_audit()` with the full option set
  (`--html-out`, `--json`, `--policy`, `--format`, `--strict`,
  `--no-anomalies`, `--cache-dir`).
- **`calibra benchmark --help` crash** — a `%` character in the
  `--base-gpu-hours` help string (`"full (100%) dataset"`) caused a
  `ValueError: unsupported format character` in argparse on Python 3.14.
  Escaped to `100%%`.

## [0.10.0] — Calibrated detection

Addresses the core HF feedback question: "Is this anomaly actually corruption, or
just unusual data?" Three interlocking additions answer it. First, a
`CalibrationRegistry` ships empirically-measured benign firing rates — on known-clean
LeRobot datasets (PushT n=206, ALOHA n=50) the detectors fire at a known base rate,
so any observed rate can be compared to a baseline rather than treated as absolute.
Second, `AnomalySummary` (new in schema 1.2.0) surfaces that context — per-detector
flag counts, benign baseline rate, detection rate, and concentration score — directly
in the public JSON report. Third, `calibra.schema.evidence` (ADR-012) introduces the
`FindingCharacterization` vocabulary (`TRUE_CORRUPTION` / `UNUSUAL_VALID` /
`AMBIGUOUS`) for human-reviewed findings, letting teams build a labeled dataset that
quantifies per-detector precision. Architecture rule enforced throughout: detected
anomaly ≠ confirmed corruption ≠ DROP decision.

### Added

- **`CalibrationRegistry` / `CalibrationProfile`** (`calibra/calibration.py`) —
  in-memory registry of empirically-measured benign firing rates. Each profile is
  keyed by detector, dataset, task family, and detector version so a PushT baseline
  is never silently applied to ALOHA. `lookup()` returns `None` when no baseline
  exists — callers must not substitute a generic number. `benign_firing_rate()` and
  `calibration_context()` provide one-line display strings (e.g. "7.8% flag rate
  (clean baseline 3.2% from lerobot/pusht — 2.4× above)"). Profiles can be
  serialized (`save_json` / `load_json`) and merged so user-measured baselines
  override the built-ins. `DEFAULT_REGISTRY` ships 10 benchmark-measured profiles
  across PushT (n=206) and ALOHA (n=50) for five detectors
  (`jitter_cv`, `dropout_rate`, `spike_rate`, `vel_disc_rate`, `ldlj`). Provenance
  tag `"builtin_estimate"` vs `"benchmark_run"` is always shown so users know the
  quality of the baseline.
- **`AnomalySummary` / `DetectorCalibrationSummary`** (schema 1.2.0,
  `calibra/schema/public_report.py`) — new top-level field on `CalibraReport`
  (null when produced without anomaly detection). `AnomalySummary` carries
  `total_flags`, `affected_episodes`, `affected_episode_rate`, `n_total_episodes`,
  and a `detectors` list. Each `DetectorCalibrationSummary` pairs the observed
  `fraction_flagged` against `benign_firing_rate` from the registry, plus
  `corrupted_episode_detection_rate` from the benchmark and a `concentration` tag
  (`"spread"` / `"clustered"` / `"endpoint"` / `"unknown"`). The architecture note
  is encoded in the docstring: anomaly ≠ corruption ≠ DROP.
- **`Finding.benign_baseline_rate` / `Finding.baseline_source`** — two new nullable
  fields on `Finding` (schema 1.2.0) attach the calibration context per-finding so
  consumers that only read individual findings still get the baseline.
- **Human-reviewed evidence schema (ADR-012)** (`calibra/schema/evidence.py`) —
  `FindingCharacterization` enum (`TRUE_CORRUPTION` / `UNUSUAL_VALID` / `AMBIGUOUS`),
  `ReviewedFinding` (dataset, episode, detector, characterization, reviewer note,
  raw signal context), and `ReviewedFindingDataset` (JSONL-backed collection with
  `precision_table()`, `to_markdown()`, `summary()` for per-detector corruption vs.
  unusual-valid breakdowns).
- **Benign firing rate benchmark** (`experiments/benign_firing_rate_benchmark.py`) —
  full HuggingFace-backed script that downloads LeRobot datasets, runs every detector
  on every episode, computes Wilson-score 95% CIs, and writes
  `experiments/results/benign_firing_rates.{csv,json,md}`. Results for PushT and ALOHA
  sim are included. The benchmark also measures corrupted-episode detection rate
  against synthetically injected defects.

### Changed

- `CalibraReport.schema_version` bumped to `"1.2.0"`. Reports from earlier versions
  are structurally forward-compatible — new nullable fields default to null.

## [0.9.0] — Dataset decision layer & annotate mode

ADR-011: `calibra prune` no longer only removes episodes. It can now emit a
per-episode **decision layer** — every episode gets a disposition
(`KEEP` / `DROP` / `ANNOTATE` / …) and a characterization (`quality_risk`,
`coverage_value`, `anomaly_score`, `calibra_score`, `redundancy`, …) — and
**annotate mode** writes that as a training-ready, model-agnostic sidecar so a
metadata-conditioned policy can use data that aggressive pruning would drop.
The existing `calibra prune` coreset workflow is unchanged. See
`docs/adr/adr-011-dataset-decision-layer.md` and `docs/annotate.md`; the
research gate (does the metadata actually improve training?) is
`experiments/METADATA_CONDITIONING_BENCHMARK.md`.

### Added

- **Dataset decision layer (ADR-011), schema groundwork.** `CurationReport` now carries a `dispositions` list — one `EpisodeCharacterization` per episode holding its decision (new `Disposition` enum: `KEEP` / `DROP` / `DOWNWEIGHT` / `ANNOTATE` / `REVIEW` / `RECOLLECT`) plus the signals behind it (`n_steps`, `quality_risk`, `coverage_value`, `anomaly_score`, `integrity_flags`, `reasons`, …). The legacy `retained_indices` / `dropped_indices` are unchanged and now derived from `dispositions` (KEEP / DOWNWEIGHT / ANNOTATE → retained) when only one side is supplied, so existing callers keep working. `EpisodeCurator.curate()` populates `dispositions` (threshold pass → `KEEP`, threshold failure → `DROP`). New `CurationReport.by_disposition()` / `disposition_counts()`.
- **`calibra prune --annotate DIR`** — annotate mode (ADR-011): instead of only removing episodes, write a training-ready sidecar that keeps every episode with a decision and characterization attached. `calibra_annotations.jsonl` has one row per episode — `calibra_disposition` (`KEEP` / `DROP` / `ANNOTATE`) plus `calibra_score`, `quality_risk`, `coverage_value`, `anomaly_score`, `redundancy`, `success`, `n_steps`, `integrity_flags`, `weight` — alongside `calibra_annotations.manifest.json` (versioned schema + a field dictionary, so the sidecar is self-describing) and the raw `calibra_curation_report.json`. Redundant episodes (ones vanilla pruning would drop) are marked `ANNOTATE`: keep them if your trainer conditions on the metadata. `--annotate-format {jsonl,parquet,both}` (default `jsonl`) additionally writes `calibra_annotations.parquet` (columnar, explicit typed schema; needs pyarrow). The schema is model-agnostic; ACT / Diffusion / VLA conditioning recipes live in `docs/annotate.md`. New: `calibra.schema.annotations` (`AnnotationManifest`, `EpisodeAnnotation`), `calibra.annotate.write_annotations()`.
- **Decision-layer characterization** — `EpisodeCharacterization` (on `CurationReport.dispositions`) now carries `calibra_score` (`100·(1 − quality_risk)`), `quality_risk`, `anomaly_score`, `coverage_value`, `redundancy` (`1 − coverage_value`) and `success`, not just the triggering threshold. New helpers `calibra.assessment.episode_calibra_score()` / `episode_redundancy()`. `calibra.pruning.pruning_result_to_curation_report(result, batch, *, report=None, redundant_disposition=DROP)` maps a prune run to the decision-layer schema — pass the `DiagnosticReport` to fill the assessment axes, and `DOWNWEIGHT` / `ANNOTATE` to retain redundant episodes instead of dropping them — and is also reachable as `PruningResult.to_curation_report(batch, ...)`, so `CoresetSelector` and `EpisodeCurator` expose the same `CurationReport` view. `EpisodeCurator.curate()` populates the same enriched characterization.
- **`calibra experiment record --from-metrics PATH`** — reads GPU-hours / wall-clock / eval success / loss / energy straight out of a finished run's metrics file (flat JSON, or a Weights & Biases `wandb-summary.json` from an offline run) instead of retyping them. Point it at a file or a run directory. A built-in alias table matches common key names; `--map FIELD=path.to.key` (repeatable) handles anything unusual. An explicit flag always overrides the file. `gpu_hours` is only taken when literally present — never derived from wall-clock — so a derived figure can't be mistaken for a measured one by the benchmark classifier. The provenance string is stored on the record as `metrics_source`. New module `calibra/metrics_ingest.py`. No network access.
- **`calibra experiment record --from-review PATH`** — folds a `calibra review --json` file's per-episode assessments into the record's `mean_anomaly_score` / `mean_quality_risk` / `mean_coverage_value`, capturing the dataset side and the training-outcome side of an experiment in one command. Rejects a partial review queue rather than logging a biased dataset-level mean.
- **`calibra experiment record --dry-run`** — parse `--from-metrics` / `--from-review` and print what would be recorded, writing nothing.
- **`calibra experiment record` — metadata-conditioning benchmark fields.** New `--arm` (label in the A/B/C/D/R/R+ matrix), `--metadata-conditioning` (was the policy conditioned on the annotate-mode sidecar?), and `--actual-retention PCT` (fraction of the *original* dataset actually trained on — diverges from `--retention`, the nominal prune target, for the KEEP∪ANNOTATE arm where rescued episodes raise effective retention). `ExperimentRecord` gains `arm`, `metadata_conditioning`, `actual_retention_pct`; old rows default them. `calibra experiment list` shows `arm=… +meta` and `(actual N%)`. Supports `experiments/METADATA_CONDITIONING_BENCHMARK.md`.

### Fixed

- **Annotate mode verified against real data.** `tests/test_annotate_integration.py` (marked `integration`) runs `calibra prune --annotate` end-to-end against `lerobot/pusht` (206 episodes, v2 Parquet) and asserts sidecar/dataset episode alignment, disposition partitioning, `DROP` rows carrying integrity flags, populated non-degenerate characterization columns, `ANNOTATE < KEEP` mean coverage (rescue semantics), JSONL == Parquet == `load()` round-trip, and that the coreset output is unchanged by `--annotate`.
- **`anomaly_score` no longer saturates at 1.0 for every episode on small datasets.** `calibra.assessment.compute_episode_assessments` took the max percentile-rank extremity across *all* ~9 per-episode metrics; with few episodes relative to the metric count, nearly every episode is the batch min or max on *some* metric, so the score collapsed to ~1.0 for the whole batch (visible in `calibra review` and the annotate-mode sidecar). A metric now counts toward `anomaly_score` only when the episode is BOTH in that metric's rank tail (p≤0.1 or p≥0.9) AND ≥2.5 robust-MAD deviations from the batch median — i.e. being last in a tight cluster is not an anomaly, being a genuine magnitude outlier is. On a 12-episode dataset with two jerk-spike episodes, `anomaly_score` is now `1.0` for exactly those two and `0.0` for the rest (was `1.0` for all twelve). The reason list is unchanged. The signal is still weak below ~100 episodes and is documented as such.

## [0.8.0] — Measured training results

Calibra's predictions (`calibra benchmark`) were always simulated — a heuristic outcome model plus linear GPU-hour scaling. That's useful for a first pass, but not evidence. This adds the other half: a way to record what a design partner's *real* training runs actually cost and achieved, and to fold those measured numbers into the benchmark report wherever they're available, so a report is never presented as a validated result when parts of it are still predictions.

### Added

- **`calibra experiment record`** — logs one training run's result (GPU-hours, wall-clock time, energy, eval success rate) against the design-partner protocol's `full` / `random` / `calibra` conditions at a given retention percentage. Training itself runs in the partner's own pipeline; this only records the outcome. Stored locally as JSON Lines at `~/.calibra/experiments.jsonl` — never synced to any network endpoint. New module `calibra/experiment_log.py`.
- **`calibra experiment list` / `calibra experiment report`** — list recorded runs, or print the full retention-curve comparison for one experiment, including the Calibra-vs-random delta at each level and which `(retention%, condition)` pairs the protocol still expects but haven't been recorded yet. New CLI handler `calibra/experiment.py`.
- **`calibra benchmark --sweep`** — runs the full design-partner retention curve (default `10/25/50/75/100%`, override with `--fractions`) in one shot instead of a single `--keep` fraction.
- **`calibra benchmark --experiment-id ID`** — substitutes real measured GPU-hours / eval success rate from `calibra experiment record` into the benchmark report wherever a matching condition and retention level has been logged, falling back to simulated values for anything not yet measured.
- Benchmark reports now carry a **status**: `SIMULATED` (nothing measured — a prediction), `PARTIAL MEASUREMENT` (some conditions measured, others still simulated — not safe to report as validated), or `CASE STUDY / VALIDATED` (full, random, and Calibra all backed by real recorded training runs). Every number is individually tagged `(measured)` or `(simulated)`.
- Compute savings are now computed from GPU-hours rather than episode-count reduction, since the two can diverge once real measured numbers are mixed in.

See `docs/commands.md`'s `calibra benchmark` and `calibra experiment` sections for the full partner workflow.

### Fixed

- `compute_trajectory_entropy` force-cast actions to `float32` before `np.histogram`, which could collapse distinct values (and raise "Too many bins for data range") on large-offset, sub-millimeter-variance action columns — exactly the near-duplicate-trajectory case the function is meant to detect. Now computed in `float64`. Reported via a Reddit user testing on real data.

## [0.7.3] — Configurable Integrity CI policies

Direct follow-up to the same HF feedback thread that drove 0.7.2: after reviewing the built-in block/inspect split, the reviewer proposed letting teams configure it themselves rather than shipping one fixed policy for everyone (a research lab only blocking on corrupted timestamps vs. a production team also blocking on camera freezes vs. a team that's validated calibration-drift thresholds enough to block on those too).

### Added

- **`calibra integrity --policy FILE`** — a flat JSON file mapping a metric name (the exact names shown in `--json` output, e.g. `camera_freeze_events`) to `"block"` or `"inspect"`, overriding the built-in default for CRITICAL findings on the metrics it names. OK and WARNING findings are unaffected — a WARNING never fails CI regardless of policy. New module `calibra/policy.py` handles loading and validation. `--strict` and `--policy` are mutually exclusive. `--json` output gains a `policy_path` field for traceability. See `docs/integrity.md`'s "CI Policy Files" section.
- Policy files are JSON, not YAML — the core install has zero non-`numpy`/`pydantic` dependencies, and JSON needs no new one.

## [0.7.2] — CI policy split, Not Evaluated, calibration drift

Prompted by a community probe against six public LeRobot datasets (including matched ALOHA human/scripted pairs) run with `calibra integrity` v0.7.1, which surfaced a real gap: every dataset returned exit code 1, while five of six still showed overall `Status: Warning` — because a single CRITICAL motion-smoothness finding (which can legitimately fire on a scripted/planner dataset) carried the exact same operational weight as a dropped-timestamp or corrupted-frame finding.

### Added

- Every finding now carries a `suggested_action`: `informational` (OK), `inspect` (WARNING, or CRITICAL on a context-dependent motion-review metric), or `block` (CRITICAL on an objective acquisition/format/sync/completeness failure).
- `ci_result` (`Passed`/`Failed`) and `ci_reason` are now reported separately from the severity-only `status` line, and are what actually sets the exit code. By default, only `block`-level CRITICALs fail CI — `ldlj`, `jerk_spike_rate`, and `velocity_discontinuity_rate` no longer fail the build on their own.
- New `--strict` flag restores the old "any CRITICAL fails" behavior for pipelines that want the blunter policy.
- Skipped analyzers (e.g. camera checks on video-backed LeRobot v2/v3 without `--decode-images`) are now surfaced as `not_evaluated` with a reason, instead of disappearing from the output silently.
- **New check: leader/follower calibration drift** (`joint_offset_max_abs`, via `CalibrationDriftAnalyzer`) — detects a systematic per-motor `action - observation.state` offset during sustained stationary hold frames, the signature described in [LeRobot issue #3758](https://github.com/huggingface/lerobot/issues/3758) (a stable joint offset that trains fine but causes consistent under/overshoot at deployment). Post-hoc, read-only, thresholds capped at WARNING until validated against reference hardware data — see `docs/integrity.md`.

### Changed

- `calibra integrity`'s exit code now reflects `ci_result` rather than "any CRITICAL present." Existing CI pipelines that depend on the old blanket behavior should add `--strict`.

## [0.7.1] — Motion smoothness moves into Integrity

### Added

- **`calibra integrity`** now checks jittery/jerky motion — smoothness (`ldlj`), jerk spikes (`jerk_spike_rate`), and velocity discontinuities (`velocity_discontinuity_rate`) — via `ControlSmoothnessAnalyzer`. Prompted by direct practitioner feedback that named this alongside timestamps and blur as one of the recurring basics.
- `docs/integrity.md` — new "Jittery / jerky motion" section documenting the three metrics and the Integrity-vs-Quality split for motion (physical jitter is a trust check; tracking error and scripted-vs-teleop signature stay under `calibra audit`'s Motion Quality dimension).

### Fixed

- `docs/demo_fixture.py`'s synthetic actions were i.i.d. per-step noise — maximally jittery by construction, which would have swamped this release's own new checks. Replaced with a smooth low-frequency-sinusoid generator so the demo's "Passed" checks stay meaningful next to its three intentionally-injected defects (short episode, camera freeze, blur).

## [0.7.0] — Dataset Integrity

### Added

- **`calibra integrity`** — new front-door command answering "can I trust this dataset?" before quality, coverage, or optimization matter. Findings are grouped into Critical / Warnings / Passed rather than led with a single score; an `Integrity Score` is still computed but demoted to a summary line.
  - Timestamp consistency and sensor sync (jitter, dropout, camera lag, action/observation alignment)
  - Episode completeness (statistical short-episode detection)
  - Duplicate frame detection
  - Camera freeze detection
  - Blur detection
  - Image integrity checks (duplicate/freeze/blur) now available for **LeRobot v1** datasets via the new opt-in `--decode-images` flag
- `LeRobotReader(decode_images=True)` — decodes HuggingFace `Image`-feature columns for LeRobot v1 datasets. Off by default (increases load time/memory); no effect on the existing v2/v3 fast path.
- Homepage and documentation reorganized around the Integrity → Quality → Coverage → Optimize workflow (new `docs/integrity.md`, updated README, `mkdocs.yml` nav, demo assets under `docs/demo.tape`/`docs/demo_fixture.py`).
- Hugging Face Space (`spaces/app.py`) reorganized to check Dataset Integrity first, ahead of the Quality/Coverage score.

### Notes

- Duplicate-frame, camera-freeze, and blur checks work out of the box on HDF5/Isaac Lab/robomimic data, and on LeRobot v1 via `--decode-images`. LeRobot v2/v3 (video-encoded) datasets are intentionally out of scope for this release — `--decode-images` prints a warning and has no effect there.

## Planned next

- **Vision Integrity for video-backed LeRobot datasets (v2/v3)** — decode a sampled subset of frames from LeRobot's mp4-encoded v2/v3 datasets so duplicate-frame/camera-freeze/blur detection work there too. Needs a new video-decoding dependency and parsing per-episode chunk/timestamp offsets from `meta/episodes/*.parquet` (v3's multi-episode-per-file layout) — deferred until it can be validated against representative real datasets rather than shipped speculatively.
