# Using Calibra

A full pass on one dataset, from install to a trained policy, with annotated output
at each step. This is the long version of the README's [Using Calibra](https://github.com/Calibra-Robotics/Calibra#using-calibra)
section.

Every command below accepts either a **local path** (`.h5`, `.hdf5`, a LeRobot
directory, an RLDS dir, an MCAP bag) or a **HuggingFace Hub ID**
(`lerobot/pusht`). Examples use `lerobot/pusht`.

If you just want the answer without the intermediate steps, skip to
[One command instead](#one-command-instead).

---

## The four questions

Calibra is organized around the questions practitioners ask about a new dataset, in
the order they ask them:

| Step | Question | Command |
|---|---|---|
| 1. Integrity | Can I trust this dataset? | `calibra integrity` |
| 2. Quality | Which episodes are clean? | `calibra audit` |
| 3. Coverage | Which episodes are distinct? | `calibra review` |
| 4. Select | Keep only what matters. | `calibra prune` |

Steps 1–3 are read-only diagnostics. Step 4 is the only one that produces a
training set.

---

## 1. Trust — `calibra integrity`

```bash
pip install 'calibra-robotics[lerobot]'
calibra integrity lerobot/pusht
```

```
─── Dataset Integrity ────────────────────────────────────
pusht · 206 episodes

Critical (1)
  ❌ camera_freeze_events: 1 of 206 episodes (0.5%) contain a run of ≥5
     consecutive near-identical camera frames (episode ep_17).
     suggested_action: block

Warnings (1)
  ⚠️  jerk_spike_rate: acceleration spikes above the dataset-wide 99th
     percentile in 3 episodes. suggested_action: inspect

Passed (8)
  ✅ timestamp_jitter_cv     ✅ timestamp_dropout_rate
  ✅ short_episode_fraction  ✅ action_dropout_rate
  ✅ duplicate_frame_rate    ✅ ldlj
  ✅ velocity_discontinuity_rate  ✅ blurry_episode_fraction

Integrity Score: 88/100  ·  Status: Warning
```

**How to read it:**

- **`suggested_action: block`** — an objective acquisition/format/sync/completeness
  failure. The data is wrong, not just unusual. Fix it upstream or exclude those
  episodes before you do anything else. These are the only findings that fail CI by
  default (exit code 1).
- **`suggested_action: inspect`** and everything under **Warnings** — context
  dependent. `jerk_spike_rate`, `ldlj`, and `velocity_discontinuity_rate` are a
  defect for a delicate insertion task and normal for a fast reach or a whipping
  motion. Open the named episodes and decide for your task.
- **Status: Healthy** (Integrity Score ≥ 90): nothing objective is broken.
  **Warning** (70–89) or **Critical** (below 70): expect to lose episodes in step 4.

**Flags you'll actually use:**

| Flag | When |
|---|---|
| `--decode-images` | LeRobot **v1** datasets — turns on `duplicate_frame_rate` / `camera_freeze_events` / `blurry_episode_fraction`, which are off by default there because decoding is slow. Not available for v2/v3 (video-encoded). |
| `--strict` | CI — also fail on `inspect` findings, not just `block`. |
| `--policy FILE` | CI — a JSON map of `metric -> block\|inspect` to override the default split. See [Integrity Checks → CI Policy Files](integrity.md). |
| `--json` | Pipe the report somewhere. |

---

## 2. Quality — `calibra audit`

```bash
calibra audit lerobot/pusht --policy diffusion --html-out report.html
```

`audit` runs four analyzers over every episode with bootstrap confidence intervals
and per-episode outlier detection. For Hub datasets with a known-clean baseline
(e.g. `lerobot/pusht`), it also compares each detector's flag rate to that
baseline. `--html-out` writes the same diagnostics as a dashboard. It exits 1 when
any metric is CRITICAL.

The **Calibra Score** (0–100, broken into Quality, Synchrony, Coverage, and Task
Structure) comes from `calibra score lerobot/pusht` or `calibra analyze`.

**How to read the score:**

| Calibra Score | What it means | What Calibra can do |
|---|---|---|
| **< 60** | Real quality problems — corrupted episodes, sync errors, jerky motion. | Big gains from the quality filter alone. |
| **60–80** | Normal, usable dataset with redundancy to remove. | This is the sweet spot — expect a large training-data reduction from step 4. |
| **> 80** | Already clean (often a polished sim dataset). | Smaller gains; the coverage selector still helps, the quality filter won't. |

`--policy {diffusion,act,transformer}` conditions the hints on your target policy
family. Add `--cache-dir .calibra/cache` if you re-audit the same dataset as you
collect more demos — unchanged data returns instantly.

---

## 3. Coverage — `calibra review`

```bash
calibra review lerobot/pusht --top 20 --output review.json
```

`review` ranks episodes by **three separate signals** so you don't conflate them:

- **anomaly** — this episode is unlike the rest (could be a defect, could be a rare
  behavior worth keeping).
- **quality risk** — this episode is likely to hurt training.
- **coverage value** — this episode is the *only* example of some behavior; dropping
  it loses a mode.

Skim the top of the queue before pruning. If a high-coverage-value episode also
shows up as a quality risk, that's the one to fix by hand rather than drop.

| Flag | When |
|---|---|
| `--top N` | How many episodes to show / export (default 20). For a full per-episode assessment (e.g. to feed `calibra experiment --from-review`), set `--top` ≥ the episode count. |
| `--mode fast` | Very large datasets — action/timestamp diagnostics only, skips `coverage_value`. |
| `--group-by task,robot` | Rank within each task/robot group so a harder task's episodes don't all look like outliers. |
| `--output PATH` | Write the ranked IDs + assessments as JSON. |

---

## 4. Select — `calibra prune`

`--export-dataset` needs a local copy, so download the dataset first. A local
copy has no Hub ID, so pass `--profile pusht` to get the same settings
`lerobot/pusht` gets automatically (see [Dataset profiles](commands.md#dataset-profiles)):

```bash
hf download lerobot/pusht --repo-type dataset --local-dir ./datasets/pusht
calibra prune ./datasets/pusht --keep 0.25 --policy act --profile pusht \
  --report results/pusht/latest.json \
  --export-dataset ./pusht_coreset
```

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  CALIBRA PRUNING SUMMARY
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Original episodes  : 206
  Quality failures   : 0  (removed in Stage 1)
  Diversity pruned   : 154  (removed in Stage 2)
  Coreset size       : 52  (25.2% of original)
  Not evaluated      : 0  (passed Stage 1 with no quality metrics)
  Method             : quality_filter + greedy_max_coverage
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

**Two stages:**

1. **Quality filter** — drops episodes that fail kinematic/temporal thresholds
   (jerk spike rate, velocity discontinuity, dropout, LDLJ, minimum length). Tune
   with `--max-spike-rate`, `--max-vel-disc-rate`, `--max-dropout`, `--min-ldlj`,
   `--min-length`, or run `--quality-only` to stop here.
2. **Greedy max-coverage** — from the survivors, farthest-point sampling on
   action-space statistics picks the `--keep` fraction of most behaviorally
   distinct episodes. O(N × K); handles ~50k episodes without approximation.
   This is the selector with `--policy` or `--strategy diversity`. With neither,
   `prune` defaults to `--strategy world-model`, which keeps the episodes a small
   learned dynamics model (JEPA, seeded so runs are reproducible) finds most
   surprising.

**Outputs:**

| Flag | Produces |
|---|---|
| `--out PATH` | `coreset_index.json` — just the kept episode IDs (default). |
| `--report PATH` | Schema-versioned **CalibraReport JSON** — per-episode verdicts, reason codes (`jerk_spike`, `diversity_pruned`, …), quality scores, SHA-256 content hashes. Use this; it's the stable contract the integrations read. |
| `--export-dataset DIR` | A materialised, ready-to-train copy of a **local** dataset in its own layout (LeRobot v1/v2/v3 with videos, HDF5 / robomimic including `mask/`). |

**Other knobs:**

- `--policy gr00t` — stricter quality thresholds + entropy-weighted diversity, tuned
  for GR00T fine-tuning.
- `--strategy influence` — select by estimated learning value (action novelty +
  contact representation + entropy) instead of pure coverage.
- `--entropy-weight 0.4` — bias toward informationally rich episodes.
- `--curriculum` — slice the coreset into progressive curriculum stages.

### Picking `--keep`

Don't guess. Run `calibra analyze` (below) once — it recommends a retention fraction
from the diversity selector, based on measured state-space redundancy. Then treat that
number as a **heuristic starting point, not a validated retention curve**. Confirm
it with the design-partner protocol (`calibra experiment` + `calibra case-study`)
before you commit a production training run to it.

---

## 5. Train

Point your trainer at the exported coreset:

```bash
lerobot-train --policy.type=act --policy.push_to_hub=false \
  --dataset.repo_id=local/pusht_coreset --dataset.root=./pusht_coreset
```

Or keep your existing training script and filter at load time from the report:

```python
from calibra.integrations.lerobot import load_dataset

ds = load_dataset("lerobot/pusht", report_path="results/pusht/latest.json")
# ds is a datasets.Dataset with only Calibra-approved episodes
```

Isaac Lab → GR00T:

```python
from calibra.integrations.isaac_lab import export_gr00t_manifest, filter_hdf5

export_gr00t_manifest("results/franka/latest.json", demos_path="demos.hdf5")
filter_hdf5("demos.hdf5", "results/franka/latest.json", "demos_coreset.hdf5")
```

---

## One command instead

`calibra analyze` composes steps 1, 2, and 4 into a single report — trust, quality,
estimated redundancy, and a training-set recommendation from the diversity
selector (`calibra prune --strategy diversity`):

```bash
calibra analyze lerobot/pusht --policy act
calibra analyze lerobot/pusht --keep 0.4 --export coreset_index.json
```

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  CALIBRA ANALYSIS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Dataset
    Name       : pusht
    Episodes   : 206
    Frames     : 25,650
    Format     : lerobot
    Tasks      : 1 distinct
    Action dim : 2
    Policy     : ACT
────────────────────────────────────────────────────────────
  Integrity
    ✅ Timestamps & sync
    ✅ Episode structure
    ·   Camera feed  (not evaluated)
    ❌ Motion & control
    Integrity score: 69/100 · Critical
────────────────────────────────────────────────────────────
  Quality (Calibra Score)    44.6 / 100   ·  Poor
  Coverage / diversity       47.4 / 100
  Redundancy (estimated)     3.2%  of state-space occupies duplicate regions
────────────────────────────────────────────────────────────
  RECOMMENDATION

    Regime             : MODERATE NOISE
    Training set       : 175 / 206 episodes
    Expected retention : 85%

    Reasons:
      • removes 31 redundant episodes (diversity selection)
      • preserves behavioral coverage via greedy max-coverage selection

    This is a heuristic starting point (~1 - measured redundancy), not a
    validated retention curve. Run the design-partner protocol
    (`calibra experiment` + `calibra case-study`) before committing a
    production training run to this number.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

Use `analyze` for the first look at a dataset; use the four separate commands when
you need to act on the intermediate output — inspect specific episodes, tune quality
thresholds, or export a review queue.

---

## Where to go next

- [Integrity Checks](integrity.md) — every check `calibra integrity` runs, and CI policy files.
- [Command Reference](commands.md) — all commands and every flag.
- [Benchmarks](benchmarks.md) — how much data reduction to expect, by dataset regime.
