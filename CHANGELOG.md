# Changelog

All notable changes to Calibra are documented here.

## [Unreleased]

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
  PushT's own clean p95 (10.4%, 27.5%), so they removed 27 known-clean episodes.
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
