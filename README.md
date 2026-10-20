# Calibra

<p align="center">
  <a href="https://github.com/Calibra-Robotics/Calibra/actions/workflows/ci.yml"><img src="https://github.com/Calibra-Robotics/Calibra/actions/workflows/ci.yml/badge.svg" alt="CI"/></a>
  <a href="https://calibra-robotics.github.io/Calibra/"><img src="https://img.shields.io/badge/docs-GitHub%20Pages-blue" alt="Docs"/></a>
  <a href="https://github.com/astral-sh/ruff"><img src="https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json" alt="Ruff"/></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-Apache_2.0-blue.svg" alt="License"/></a>
  <a href="CHANGELOG.md"><img src="https://img.shields.io/badge/changelog-v0.13.1-informational" alt="Changelog"/></a>
</p>

<p align="center"><b>Train robot policies with up to 75% less data.</b></p>

<p align="center">
Calibra is a robotics dataset decision layer. It audits integrity, characterizes every episode, and helps you decide what to keep, drop, downweight, review, or annotate before training. Prune to a smaller training set, or export per-episode metadata for a training pipeline that can use it.
</p>

---

## Results

| Dataset | Quality Score | Best Retention | Result |
|---|---:|---:|---|
| PushT (`lerobot/pusht`) | 76.7 | 25% | Held-out action-prediction error 0.8% above full data with 75% less training data (random: 2.2% above) |
| DROID-100 (`lerobot/droid_100`) | 77.0 | 75% | Held-out action-prediction error 3% below full data |
| ALOHA sim (`lerobot/aloha_sim_insertion_human`) | 87.3 | Higher | Smaller gains; already a clean dataset |
| xArm lift (`lerobot/xarm_lift_medium`) | 82.7 | n/a | Little benefit; already a high-quality simulation dataset |

Across four public robotics datasets, Calibra consistently preserved more rare behaviors than random selection. The magnitude of training-data reduction depended on the dataset's quality and redundancy.

Across three datasets and three policy families (BC-MLP, ACT, Diffusion Policy) at 30% retention, Calibra improves over random by **+24.5%** on average.

Quality scores in this table were recorded at benchmark time (Calibra v0.8.0, on the dataset revisions then on the Hub; PushT had 206 episodes in LeRobot v2 format, 165 used for training and 41 held out). All four results are offline action-prediction error on held-out episodes (BC-MLP), not policy success rate. Scoring and the datasets have both changed since, so `calibra analyze` on today's `lerobot/pusht` (206 episodes, LeRobot v3) reports a different score.

→ [Full benchmark results, ablation tables, and limitations](docs/benchmarks.md)

---

## How it works

The reason Calibra can remove 75% of demonstrations without hurting performance is that most robotics datasets contain two distinct problems: bad episodes (jerk spikes, dropped frames, sync errors) and redundant episodes (near-duplicate demonstrations of the same behavior). Calibra finds both, then assigns each episode a disposition: drop it, keep it, downweight it, flag it for review, or keep it with a characterization annotation so a metadata-aware trainer can still use it.

**The pipeline:**

| Step | Question | Command |
|---|---|---|
| 1. Integrity | Can I trust this dataset? | `calibra integrity` |
| 2. Quality | Which episodes are clean? | `calibra audit` |
| 3. Coverage | Which episodes are distinct? | `calibra review` |
| 4. Decide | Keep, drop, downweight, review, or annotate, then export. | `calibra prune` |

```
$ calibra integrity /data/my_demos.h5

─── Dataset Integrity ────────────────────────────────────
my_demos · 120 episodes

Critical (1)
  ❌ camera_freeze_events: 1 of 120 episodes (0.8%) contain a run of ≥5
     consecutive near-identical camera frames (episode ep_17).

Warnings (1)
  ⚠️  blurry_episode_fraction: camera frames markedly blurrier than the
     rest of the dataset in 1 episode.

Passed (7)
  ✅ timestamp_jitter_cv  ✅ timestamp_dropout_rate  ✅ short_episode_fraction
  ✅ action_dropout_rate  ✅ duplicate_frame_rate    ✅ jerk_spike_rate
  ✅ velocity_discontinuity_rate

Integrity Score: 83/100  ·  Status: Warning
```

Or run all four steps as one report with `calibra analyze`: integrity, Calibra Score, estimated redundancy, and a training-set recommendation from the diversity selector (`calibra prune --strategy diversity`):

```
$ calibra analyze lerobot/pusht

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  CALIBRA ANALYSIS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Dataset
    Name       : pusht
    Episodes   : 206
    ...
────────────────────────────────────────────────────────────
  Integrity
    ✅ Timestamps & sync
    ✅ Episode structure
    ·   Camera feed  (not evaluated)
    ✅ Motion & control
    Integrity score: 100/100 · Healthy
────────────────────────────────────────────────────────────
  Quality (Calibra Score)    60.5 / 100   ·  Fair
  Coverage / diversity       61.2 / 100
  Redundancy (estimated)     3.2%  of state-space occupies duplicate regions
────────────────────────────────────────────────────────────
  RECOMMENDATION

    Regime             : MODERATE NOISE
    Training set       : 175 / 206 episodes
    Expected retention : 85%
    ...
    This is a heuristic starting point (~1 - measured redundancy), not a
    validated retention curve. Run the design-partner protocol
    (`calibra experiment` + `calibra case-study`) before committing a
    production training run to this number.
```

---

## Quick start

```bash
pip install calibra-robotics

calibra integrity /data/my_demos.h5
calibra audit lerobot/pusht
calibra prune lerobot/pusht --keep 0.25 --report results/pusht/latest.json

# or the whole pipeline in one command:
calibra analyze lerobot/pusht
```

---

## Using Calibra

A full pass on one dataset, from install to a trained policy. Every step accepts a
local path (`.h5`, `.hdf5`, a LeRobot directory) or a HuggingFace Hub ID.

**Dataset profiles.** By default, smoothness checks treat the last action
dimension as a gripper and leave it out. That is right for most arm datasets but
not for PushT, whose 2-D action is an `(x, y)` target with no gripper. The
built-in `pusht` profile scores both axes instead. PushT's mouse teleop at 10 Hz
also gives it a clean velocity-discontinuity rate (16.7%) above the global
HIGH NOISE cutoff; the profile judges it against PushT's own clean rate instead,
so `analyze` does not treat normal PushT motion as corruption, `integrity` rates
motion against PushT's clean episodes instead of arm-calibrated thresholds, and
`prune`'s quality filter uses matching limits instead of cutting PushT's clean tail. It applies automatically to
`lerobot/pusht` and `lerobot/pusht_image`; for a local copy, pass
`--profile pusht` (supported by `integrity`, `audit`, `review`, `prune`,
`analyze`, and `score`). The `aloha` profile excludes both of ALOHA's grippers
(dims 6 and 13) instead of only the last dim; it applies to the ten ALOHA Hub
datasets Calibra has references for, and `--profile aloha` covers the rest.
Reports record the profile in `dataset_profile`.

### 1. Trust: `calibra integrity`

```bash
pip install 'calibra-robotics[lerobot]'
calibra integrity lerobot/pusht
```

Answers *can I trust this dataset?* Timestamp sync, episode completeness, and
duplicate, frozen, and blurry camera frames (on HDF5 and LeRobot v1, and on
local LeRobot v2/v3 copies with `--decode-video`). Read it top-down:

- **Critical** findings with `suggested_action: block` are objective acquisition
  failures. Fix the data or drop those episodes before training.
- **Critical / inspect** and everything under **Warnings** are context-dependent:
  jerky motion is a defect for a delicate insertion and normal for a fast reach.
  Open those episodes and decide.
- **Status: Healthy** (Integrity Score ≥ 90) means nothing objective is broken.
  **Warning** (70–89) and **Critical** (below 70) mean you should expect to lose
  or fix episodes. The `CI result` line (and exit code) fails only on `block` findings.
- **Motion checks depend on sampling rate.** The same ALOHA trajectories read
  1.45% velocity discontinuities at 50 Hz and 15.6% at 10 Hz. Compare motion
  findings only between datasets recorded at similar rates
  ([details](eval/investigations/ldlj/SUBSAMPLING.md)).

### 2. Quality: `calibra audit`

```bash
calibra audit lerobot/pusht --html-out report.html
```

The full diagnostic: every metric with a bootstrap confidence interval and its
threshold, per-episode outliers, and a calibration table comparing flag rates to
known-clean baselines (for Hub datasets that have one). Open `report.html` for the
dashboard. Exits 1 when any metric is CRITICAL (`--strict` also fails on
WARNING). For the 0–100 Calibra Score, run `calibra score` or `calibra analyze`.

### 3. Coverage: `calibra review`

```bash
calibra review lerobot/pusht --top 20 --output review.json
```

Ranks episodes by three separate signals (anomaly, quality risk, and coverage
value) so you can see which episodes are broken *and* which rare ones you cannot
afford to drop. Skim the top of the queue before pruning.

### 4. Decide: `calibra prune`

```bash
calibra prune lerobot/pusht --keep 0.25 --report results/pusht/latest.json
```

`--export-dataset` needs a local copy, so download the dataset first:

```bash
hf download lerobot/pusht --repo-type dataset --local-dir ./datasets/pusht
calibra prune ./datasets/pusht --keep 0.25 --profile pusht \
  --report results/pusht/latest.json \
  --export-dataset ./pusht_coreset
```

Two stages: filter quality failures, then select episodes until `--keep` is hit.
The Stage 2 selector depends on your flags. With `--policy` (e.g. `act`,
`diffusion`, `gr00t`) or `--strategy diversity`, it greedily picks the most
behaviorally distinct episodes; that is the selector `calibra analyze` and the
benchmarks use. With neither flag, it defaults to `--strategy world-model`
(JEPA surprise), which keeps the episodes a learned dynamics model finds hardest
to predict. `--report` writes a stable JSON of per-episode verdicts, the coreset
index is also written to `coreset_index.json`, and `--export-dataset`
materialises a ready-to-train copy (LeRobot v1/v2/v3 or HDF5, in the source's
own layout, videos included).

**Annotate mode.** `calibra prune --annotate DIR` keeps *every* episode instead
of removing any, and writes a per-episode sidecar recording what Calibra would
have done (`KEEP` / `DROP` / `ANNOTATE`) and why (`quality_risk`,
`coverage_value`, `anomaly_score`, …). A training pipeline that can condition
on that metadata can then use the weaker episodes rather than discarding them.
`--annotate-format {jsonl,parquet,both}`. Model-agnostic;
see [Annotate Mode](docs/annotate.md).

Unsure what `--keep` to use? Run `calibra analyze lerobot/pusht` first; it
recommends a retention fraction from the diversity selector. It is a heuristic starting
point, not a validated retention curve; confirm it with the design-partner
protocol (`calibra experiment` + `calibra case-study`) before a production run.

### 5. Train

```bash
lerobot-train --policy.type=act --policy.push_to_hub=false \
  --dataset.repo_id=local/pusht_coreset --dataset.root=./pusht_coreset
```

Or keep your existing training script and load the coreset directly; see
[LeRobot integration](#lerobot-integration) and [Isaac Lab → GR00T](#isaac-lab--gr00t-nvidia) below.

→ [Full walkthrough with annotated output](docs/guide.md) · [Command reference](docs/commands.md)

---

## Try it online

No installation required.

🔗 [Calibra Dataset Decisions](https://huggingface.co/spaces/omert27/robot-dataset-health-check) (Hugging Face Space)

- See which episodes of any LeRobot dataset to keep, drop, or annotate, and why
- Check integrity: timestamps, sync, episode structure, camera feed, motion and control
- Compare detector rates against known-clean baselines
- Download the per-episode decisions as JSON

---

## Benchmark details

<p align="center">
  <img src="experiments/figures/fig_retention_columbia_cairlab_pusht_real.png" alt="Calibra vs random retention curve on PushT real" width="600"/>
</p>

On real PushT data: at **10% retention**, Calibra achieves lower prediction error than training on the **full dataset**, while random selection degrades sharply.

<p align="center">
  <img src="experiments/figures/fig_ablation_aloha_mobile_cabinet.png" alt="Ablation: which component drives Calibra's gains?" width="600"/>
</p>

Ablation across 5 seeds on ALOHA mobile (keep 30%): Calibra full pipeline and diversity-only both outperform all published baselines.

**Mean improvement over random selection (5 seeds, 30% retention, 3 datasets):**

| Method | BC-MLP | ACT | Diffusion Policy |
|---|---:|---:|---:|
| Diversity-only | **+29.5%** | **+26.5%** | +11.9% |
| Calibra full | +24.5% | +23.7% | **+13.8%** |
| K-Center | +24.0% | +23.1% | +10.1% |
| Facility Location | +21.5% | +18.4% | +8.7% |
| Random | 0.0% | 0.0% | 0.0% |

Method rankings are stable across all three policy families (Spearman ρ ≥ 0.86).

→ [Full benchmarks and ablations](docs/benchmarks.md)

---

## Detector calibration

Calibra flags episodes that look unusual relative to the rest of the dataset. Not every flag is corruption; some episodes are just at the tail of a clean distribution. The table below shows, for each detector, how often it fires on **ground-truth-clean data** (benign firing rate) and how often it catches **synthetically-corrupted episodes** (episode detection rate). Both measured on real LeRobot datasets via `experiments/benign_firing_rate_benchmark.py`.

| Detector | Benign firing rate | Episode detection rate | Signal ratio |
|---|---:|---:|---:|
| `jitter_cv` | 0.0% | 37.1% | n/a |
| `dropout_rate` | 0.0% | 18.8% | n/a |
| `spike_rate` | 6.9% | 62.9% | 9× |
| `vel_disc_rate` | 1.0% | 31.0% | 32× |
| `ldlj` | 0.5% | 42.9% | 88× |

Averaged across `lerobot/pusht` (n=206) and `lerobot/aloha_sim_insertion_scripted` (n=50) with 95% Wilson CIs. Signal ratio is undefined (n/a) when the benign rate is 0%. PushT is measured with its `pusht` dataset profile (both action axes scored) and ALOHA with its `aloha` profile (both grippers excluded); last re-measured 2026-10-20.

`ldlj` is the least consistent detector: it catches 6 of 7 corrupted ALOHA episodes but 0 of 30 on PushT, it scores some spike-injected data as *smoother*, and it shifts with sampling rate alone ([investigation](eval/investigations/ldlj/)). It is therefore not part of `calibra integrity`; it only feeds the Calibra Score.

**A detected anomaly is not the same as confirmed corruption.** Use `calibra review` to inspect flagged episodes before deciding to drop, downweight, or annotate them.

→ [Full per-dataset tables with confidence intervals](experiments/results/benign_firing_rates.md)

### Integrity checks under fault injection

We injected controlled acquisition faults into on-disk copies of three LeRobot v3.0 datasets (`unitreeh1_rearrange_objects`, `pusht`, `aloha_static_battery`) and ran `calibra integrity` on each copy: 981 trials on v0.13.0 and 471 after the fixes it led to, protocol pre-registered.

| Fault (clearly above threshold) | v0.13.0 | Current |
|---|---:|---:|
| Duplicate episodes | 105/105 | 105/105 |
| Missing, truncated, or wrong-fps video | 96/96 | 96/96 |
| Dropped video frames | 60/60 | 60/60 |
| Frozen camera stream (every episode decoded) | 60/60 | 60/60 |
| Repeated frames (10% to 30%) | n/a | 3/3 |
| Timestamp dropout, jitter, swaps, and unit errors | 150/180 | 210/210 |

On unmodified data, 1 of 300 evaluated checks fired: `duplicate_frame_rate` on ALOHA, which detects real repeated frames (most likely cameras slower than the 50 Hz recording rate), an anomaly rather than confirmed corruption. Known limits: on AV1 video, `duplicate_frame_rate` sees only repeats coded as predicted frames, so it reports about half the true rate; frozen cameras are missed when the frozen episode is outside the default 20-episode video sample (19/60), which the output now says. All three datasets have synthetic timestamps, so timing results show the detectors respond to injected faults, not to real clock faults. These are synthetic injections: they show what Calibra can detect, not how often faults occur in real data.

→ [Report, findings, and limitations](eval/integrity_fault_injection/REPORT.md)

---

## Measure real training savings

Calibra can record measured training results from real experiments and connect them to benchmark reports.

```bash
calibra experiment record --experiment-id my-run --condition calibra --retention 25 \
                           --gpu-hours 6.2 --eval-success-rate 0.88
calibra experiment list --experiment-id my-run
calibra experiment report --experiment-id my-run
```

Run a retention sweep:

```bash
calibra benchmark lerobot/pusht --sweep
```

Connect measured results to the benchmark:

```bash
calibra benchmark lerobot/pusht --sweep --experiment-id my-run
```

Reports distinguish **simulated**, **partially measured**, and **validated case-study** results so estimated compute savings are not confused with measured results.

Once a design partner's retention curve is fully recorded, turn it into a partner-facing report:

```bash
calibra case-study --experiment-id my-run --partner "Partner A" --gpu-cost-per-hour 2.50 --out case_study.md
```

`calibra case-study` reads only real measured `calibra experiment record` data (never `calibra benchmark`'s simulated numbers) and marks the report `DRAFT` rather than `VALIDATED` if any protocol condition is still unrecorded.

→ [Full command reference](docs/commands.md)

---

## Why diversity-aware selection beats random

<p align="center">
  <img src="docs/figures/diversity.svg" alt="Behavioral diversity comparison" width="680"/>
</p>

Random selection picks a clustered subset. Calibra's coverage-based selector spreads selections across the behavioral space, ensuring the policy sees every behavioral mode, even rare ones.

---

## In practice

<p align="center">
  <img src="docs/figures/before_after.svg" alt="Before and after Calibra" width="640"/>
</p>

---

## LeRobot integration

```bash
# 1. Record demos (see `lerobot-record --help` for your robot's ports and cameras)
lerobot-record --robot.type=so100_follower --robot.port=/dev/ttyACM0 \
  --teleop.type=so100_leader --teleop.port=/dev/ttyACM1 \
  --dataset.repo_id=$HF_USER/my_dataset --dataset.single_task="Pick up the cube"

# 2. Curate, write the report, and export the coreset
calibra prune ~/.cache/huggingface/lerobot/$HF_USER/my_dataset --keep 0.3 --policy act \
  --report results/my_dataset/latest.json --export-dataset ./my_dataset_coreset

# 3. Train on the coreset
lerobot-train --policy.type=act --policy.push_to_hub=false \
  --dataset.repo_id=$HF_USER/my_dataset_coreset --dataset.root=./my_dataset_coreset
```

```python
from calibra.integrations.lerobot import load_dataset

ds = load_dataset("lerobot/pusht", report_path="results/pusht/latest.json")
# ds is a datasets.Dataset with only Calibra-approved episodes
```

---

## Isaac Lab → GR00T (NVIDIA)

```python
from calibra.integrations.isaac_lab import export_gr00t_manifest, filter_hdf5

export_gr00t_manifest("results/franka/latest.json", demos_path="demos.hdf5")
filter_hdf5("demos.hdf5", "results/franka/latest.json", "demos_coreset.hdf5")
```

```bash
calibra prune demos.hdf5 --keep 0.3 --policy gr00t --report results/franka/latest.json
python -m gr00t.train --manifest results/franka/gr00t_manifest.json --demo-file demos_coreset.hdf5
```

---

## Python API

```python
from calibra.ingestion.registry import load
from calibra.pipeline import Pipeline
from calibra.pruning import CoresetSelector

batch = load("lerobot/pusht")
report = Pipeline().run(batch, policy_family="diffusion")

selector = CoresetSelector(keep_fraction=0.3)
result = selector.select(batch, report)
# result.keep_episode_ids → filter your dataset
```

---

## Commands

**Start here: the core workflow** ([full walkthrough](docs/guide.md)):

| Command | Description |
|---|---|
| `calibra analyze` | One-command report: integrity, Calibra Score, estimated redundancy, and a training-set recommendation |
| `calibra integrity` | "Can I trust this dataset?" Timestamps, sync, episode completeness, duplicate/frozen/blurry camera frames, jittery/jerky motion (`--decode-images` for LeRobot v1, `--decode-video` for local LeRobot v2/v3) |
| `calibra audit` | Full diagnostic report with bootstrap CIs and per-episode outlier detection |
| `calibra review` | Ranked episode review queue: separates anomaly, quality-risk, and coverage-value signals |
| `calibra prune` | Two-stage coreset: quality filter + greedy max-coverage selection. `--annotate DIR` keeps every episode instead and writes a per-episode decision + characterization sidecar ([Annotate Mode](docs/annotate.md)) |

**Everything else:**

| Command | Description |
|---|---|
| `calibra certify` | Structured CERTIFIED / PROVISIONAL / NOT CERTIFIED; `--json` for CI |
| `calibra predict` | Estimate training outcome before spending GPU time |
| `calibra watch` | Real-time quality feedback during teleoperation |
| `calibra score` | Composite 0–100 score across Quality, Synchrony, Coverage, Task Structure |
| `calibra compare` | Evidence-backed cross-dataset comparison with falsifiable claims |
| `calibra corrupt` | Inject synthetic corruptions to validate metric sensitivity |
| `calibra card` | Generate a HuggingFace dataset quality card |
| `calibra sim2real` | Quantify sim-to-real distribution gap and transfer risk |
| `calibra transfer` | Cross-embodiment compatibility scoring |
| `calibra cure` | Automatic data remediation (smoothing, resampling, trimming) |
| `calibra audit-all` | Bulk-audit an entire HF org; writes CalibraReport JSONs |
| `calibra site` | Generate a static leaderboard website from audit results |
| `calibra serve` | Local REST API server and web dashboard |
| `calibra benchmark` | Compare full, random, and Calibra-selected datasets across training-data retention levels (`--sweep`, `--experiment-id`) |
| `calibra experiment` | Record and report measured training results such as GPU-hours and evaluation success |
| `calibra case-study` | Render a fully (or partially) measured experiment into a partner-facing case-study report |

→ [Full command reference](docs/commands.md)

---

## Roadmap

**v0.13.1 (current), Integrity fixes from fault injection:** two new timestamp
checks, `timestamp_non_monotonic` (timestamps that repeat or go backwards) and
`timestamp_scale_mismatch` (an episode in different units, e.g. milliseconds),
which run even on synthetic timestamps; `--decode-video` says which episodes it
did not check; `duplicate_frame_rate` says it is a lower bound on AV1/H.264
video. See [Integrity checks under fault injection](#integrity-checks-under-fault-injection)
and [CHANGELOG.md](CHANGELOG.md).

**v0.13.0, Trustworthy integrity checks:** fewer false alarms on
real datasets (LDLJ per sub-movement, `velocity_discontinuity_rate` ignores
sensor noise, fixed-length recordings no longer flagged short, synthetic
timestamps reported as not evaluable) and new checks: duplicate episodes,
LeRobot v2/v3 video files, and opt-in `--decode-video` frame checks. Local
dataset copies now pick up their dataset profile automatically. See
[CHANGELOG.md](CHANGELOG.md).

**v0.12.0, Apache 2.0 core:** the core is now licensed under the
Apache License 2.0. Calibra Cloud code (login, cloud upload, outcome sync, the
hosted API) moved to the separately licensed `ee/` directory, and the core no
longer contacts Calibra Cloud unless you ask it to. See
[ADR-012](docs/adr/adr-012-apache-core-boundary.md) and
[CHANGELOG.md](CHANGELOG.md).

**v0.11.0, Dataset profiles:** per-dataset analyzer settings
(`calibra/dataset_profiles.py`) replace global defaults where they do not fit a
dataset, starting with PushT (both action axes scored, its own noise-regime and
`prune` limits, re-measured calibration baselines). Also fixes the Isaac Lab →
GR00T integration, `--export-dataset` for LeRobot v2/v3 and robomimic HDF5,
`calibra serve` endpoints, and duplicate-frame / camera-freeze false positives.
See [CHANGELOG.md](CHANGELOG.md).

**v0.10.0, Calibrated detection:** `CalibrationRegistry` ships
empirically-measured benign firing rates for each detector on known-clean LeRobot
datasets (PushT n=206, ALOHA n=50), so flagged episodes can be compared against a
baseline rather than treated as absolute. `AnomalySummary` (schema 1.2.0) exposes
per-detector context (baseline, concentration, detection rate) in the public JSON
report. Human-reviewed `FindingCharacterization` evidence schema provides
the vocabulary to distinguish true corruption from unusual-but-valid episodes. See
[CHANGELOG.md](CHANGELOG.md).

**v0.9.0, Dataset decision layer & annotate mode:** `calibra prune`
can now emit a per-episode decision (`KEEP` / `DROP` / `ANNOTATE` / …) plus a
characterization (`quality_risk`, `coverage_value`, `anomaly_score`, `calibra_score`,
`redundancy`), and `--annotate` writes it as a model-agnostic training sidecar
(JSONL / Parquet) so a metadata-conditioned policy can use episodes aggressive
pruning would drop. The existing coreset workflow is unchanged. See
[Annotate Mode](docs/annotate.md) and ADR-011; full details in [CHANGELOG.md](CHANGELOG.md).

**v0.8.0, Measured training results:** `calibra experiment record/list/report` logs a design partner's real training-run outcomes; `calibra benchmark --sweep` and `--experiment-id` fold measured numbers into the benchmark report wherever available, tagging every value `(measured)` or `(simulated)` and stamping the report `SIMULATED` / `PARTIAL MEASUREMENT` / `CASE STUDY / VALIDATED`.

**Also since v0.8.0, One-command report:** `calibra analyze` composes integrity, Calibra Score, and the coreset recommendation into a single report, and `calibra case-study` turns a completed experiment log into a partner-facing markdown report.

**Next: does the metadata help?** A partner benchmark
(`experiments/METADATA_CONDITIONING_BENCHMARK.md`) measures whether conditioning
ACT / Diffusion Policy on the annotate-mode sidecar recovers what aggressive
pruning loses. That result decides whether Calibra's emphasis is smaller
datasets or richer characterization.
---

## Install

> **PyPI package name:** `calibra-robotics` (the `calibra` name on PyPI is an unrelated package)

```bash
pip install calibra-robotics                      # core (numpy + pydantic only)
pip install 'calibra-robotics[lerobot]'           # LeRobot / HuggingFace Hub (recommended)
pip install 'calibra-robotics[hdf5]'              # HDF5 (Isaac Lab, Robomimic)
pip install 'calibra-robotics[rlds]'              # RLDS / TF Datasets
pip install 'calibra-robotics[mcap]'              # MCAP / ROS2 bags
pip install 'calibra-robotics[all]'               # everything
```

**Formats supported:** LeRobot v1/v2/v3 (Parquet), HuggingFace Hub IDs, HDF5 (Isaac Lab, Robomimic), RLDS/TF Datasets, MCAP/ROS2 bags.

Camera-frame checks (`duplicate_frame_rate`, `camera_freeze_events`, `blurry_episode_fraction` in `calibra integrity`) work out of the box on HDF5/Isaac Lab/robomimic data, and on LeRobot **v1** datasets via `calibra integrity <path> --decode-images` (opt-in; decodes HuggingFace `Image`-feature columns, off by default since it increases load time/memory). On local LeRobot **v2/v3** copies (video-encoded), `--decode-video` runs `duplicate_frame_rate` and `camera_freeze_events` on decoded frames (needs `calibra-robotics[video]`). It decodes 20 evenly spaced episodes by default; pass `--video-sample N` with the episode count to check every episode. Known limit: on inter-coded video such as LeRobot's AV1, a repeated frame is visible only when it is coded as a predicted frame, so `duplicate_frame_rate` is a lower bound (about half the true rate); the flag says so. See the [integrity fault-injection benchmark](eval/integrity_fault_injection/REPORT.md).

---

## Paper

*Coming soon.* The central empirical finding, that the optimal coreset selection strategy depends on the data-retention budget, will be described in full detail.

---

## Citation

Until the paper is out, cite the software. GitHub's **Cite this repository**
button reads [`CITATION.cff`](CITATION.cff), or use:

```bibtex
@misc{tahtaci2026calibra,
  author = {Tahtacı, Ömer},
  title  = {Calibra: Offline Dataset Observability and Coreset Selection for Robotic Imitation Learning},
  year   = {2026},
  url    = {https://github.com/Calibra-Robotics/Calibra}
}
```

---

## Contributing

Calibra is not accepting outside contributions yet: issues, discussions and
pull requests are closed. Report security issues privately as described in
[SECURITY.md](SECURITY.md); for anything else, such as a bug or a dataset
Calibra misjudges, email omertahtaci05@gmail.com. See
[CONTRIBUTING.md](CONTRIBUTING.md).

## Development

```bash
git clone https://github.com/Calibra-Robotics/Calibra
cd Calibra
pip install -e '.[all,dev]'
pre-commit install              # ruff, format and claims checks on every commit
pytest                          # 1,000+ tests
python scripts/mypy_ratchet.py  # fails if a change adds type errors
```

The standards every change must meet, including evidence for threshold and
scoring changes, are in [docs/contributing.md](docs/contributing.md).

---

## License

[Apache License 2.0](LICENSE). Calibra is open source: use, modify, self-host and redistribute it, including commercially. The Calibra Cloud extension in [`ee/`](ee/) is licensed separately and is not part of the `calibra-robotics` package. See [LICENSING.md](LICENSING.md). Contact: omertahtaci05@gmail.com
