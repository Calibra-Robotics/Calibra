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

Across three datasets and three policy families (BC-MLP, ACT, Diffusion Policy) at 30% retention, Calibra's selection lowers held-out action-prediction error relative to random selection by 24.5%, 23.7% and 13.8%. That puts it on par with K-Center greedy on BC-MLP and ACT, where diversity-only selection (no quality filter) does best, and first on Diffusion Policy. Which strategy wins depends on the policy and the retention budget.

Quality scores in this table were recorded at benchmark time (Calibra v0.8.0, on the dataset revisions then on the Hub; PushT had 206 episodes in LeRobot v2 format, 165 used for training and 41 held out). All four results are offline action-prediction error on held-out episodes (BC-MLP), not policy success rate. Scoring and the datasets have both changed since, so `calibra analyze` on today's `lerobot/pusht` (206 episodes, LeRobot v3) reports a different score.

→ [Full benchmark results, ablation tables, and limitations](docs/benchmarks.md)

---

## How it works

Robotics datasets have two distinct problems: bad episodes (jerk spikes, dropped frames, sync errors) and redundant episodes (near-duplicate demonstrations of the same behavior). Calibra checks for both. In the selection ablation, most of the gain at a fixed data budget comes from diversity selection; the quality filter helps on some policy architectures (Diffusion Policy) and not on others (BC-MLP, ACT), so its main job is integrity, not selection. Calibra then assigns each episode a disposition: drop it, keep it, downweight it, flag it for review, or keep it with a characterization annotation so a metadata-aware trainer can still use it.

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

**A flag is not proof of corruption.** Each detector ships a measured benign firing rate on known-clean data, and the integrity checks were tested against 981 injected acquisition faults. See [how reliable the checks are](docs/integrity.md#how-reliable-are-the-checks).

---

## Quick start

```bash
pip install 'calibra-robotics[lerobot]'

calibra integrity lerobot/pusht
calibra audit lerobot/pusht
calibra review lerobot/pusht --top 20
calibra prune lerobot/pusht --keep 0.25 --report results/pusht/latest.json

# or the whole pipeline in one command:
calibra analyze lerobot/pusht
```

Every command accepts a local path (`.h5`, `.hdf5`, a LeRobot directory) or a HuggingFace Hub ID. `calibra prune --annotate DIR` keeps every episode and writes a per-episode decision sidecar instead ([Annotate Mode](docs/annotate.md)). Some datasets need their own analyzer settings, such as PushT's 10 Hz position actions; see [dataset profiles](docs/commands.md#dataset-profiles).

→ [Full walkthrough with annotated output](docs/guide.md) · [Command reference](docs/commands.md)

No install: try [Calibra Dataset Decisions](https://huggingface.co/spaces/omert27/calibra-dataset-decisions) on Hugging Face Spaces with any LeRobot dataset.

---

## Integrations

**LeRobot**

```bash
calibra prune ~/.cache/huggingface/lerobot/$HF_USER/my_dataset --keep 0.3 --policy act \
  --report results/my_dataset/latest.json --export-dataset ./my_dataset_coreset

lerobot-train --policy.type=act --policy.push_to_hub=false \
  --dataset.repo_id=$HF_USER/my_dataset_coreset --dataset.root=./my_dataset_coreset
```

```python
from calibra.integrations.lerobot import load_dataset

ds = load_dataset("lerobot/pusht", report_path="results/pusht/latest.json")
# ds is a datasets.Dataset with only Calibra-approved episodes
```

**Isaac Lab → GR00T (NVIDIA)**

```python
from calibra.integrations.isaac_lab import export_gr00t_manifest, filter_hdf5

export_gr00t_manifest("results/franka/latest.json", demos_path="demos.hdf5")
filter_hdf5("demos.hdf5", "results/franka/latest.json", "demos_coreset.hdf5")
```

**Python API**

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

| Command | Description |
|---|---|
| `calibra analyze` | One-command report: integrity, Calibra Score, estimated redundancy, and a training-set recommendation |
| `calibra integrity` | "Can I trust this dataset?" Timestamps, sync, episode completeness, duplicate/frozen/blurry camera frames, jittery/jerky motion |
| `calibra leakage` | Validation episodes that copy or nearly copy training episodes, from a holdout id list or a second dataset |
| `calibra audit` | Full diagnostic report with bootstrap CIs and per-episode outlier detection |
| `calibra review` | Ranked episode review queue: separates anomaly, quality-risk, and coverage-value signals |
| `calibra prune` | Two-stage coreset: quality filter + greedy max-coverage selection, or `--annotate` for a per-episode sidecar |

Also: `certify`, `score`, `compare`, `card`, `watch`, `benchmark`, `experiment`, `case-study` and more. → [Full command reference](docs/commands.md)

---

## Install

> **PyPI package name:** `calibra-robotics` (the `calibra` name on PyPI is an unrelated package)

```bash
pip install calibra-robotics                      # core (numpy + pydantic only)
pip install 'calibra-robotics[lerobot]'           # LeRobot / HuggingFace Hub (recommended)
pip install 'calibra-robotics[hdf5]'              # HDF5 (Isaac Lab, Robomimic)
pip install 'calibra-robotics[rlds]'              # RLDS / TF Datasets
pip install 'calibra-robotics[mcap]'              # MCAP / ROS2 bags
pip install 'calibra-robotics[video]'             # decoded-video checks for local LeRobot v2/v3
pip install 'calibra-robotics[all]'               # everything
```

**Formats supported:** LeRobot v1/v2/v3 (Parquet), HuggingFace Hub IDs, HDF5 (Isaac Lab, Robomimic), RLDS/TF Datasets, MCAP/ROS2 bags.

---

## Roadmap

**Next: does the metadata help?** A partner benchmark
(`experiments/METADATA_CONDITIONING_BENCHMARK.md`) measures whether conditioning
ACT / Diffusion Policy on the annotate-mode sidecar recovers what aggressive
pruning loses. That result decides whether Calibra's emphasis is smaller
datasets or richer characterization.

Release history: [CHANGELOG.md](CHANGELOG.md).

---

## Paper

*Coming soon.* The central empirical finding, that the optimal coreset selection strategy depends on the data-retention budget, will be described in full detail.

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
