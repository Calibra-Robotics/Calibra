# Real-fault eval set

Human labels for real LeRobot episodes, used to measure whether Calibra's
flags point at broken recordings or at unusual-but-valid demonstrations.
Synthetic corruption (`calibra corrupt`, `experiments/benign_firing_rate_benchmark.py`)
cannot answer that; only labeled real data can.

Labels are tied to a dataset **revision**, not to a Calibra version, so the
same labels score every future version of the detectors.

## Layout

```
eval/real_faults/
  snapshots/<dataset>__<calibra_version>.json   per-episode signals
  batches/batch-NNN/sheet.csv                   blinded labeling sheet (you fill this)
  batches/batch-NNN/key.jsonl                   stratum + inclusion probability (don't open while labeling)
```

## Workflow

```bash
# 1. Download a pinned revision and snapshot it
hf download --repo-type dataset lerobot/pusht --revision <sha> --local-dir ./data/pusht
python scripts/fault_eval.py snapshot ./data/pusht --dataset lerobot/pusht \
    --revision <sha> --out eval/real_faults/snapshots/

# 2. Sample a labeling batch (several datasets at once is fine)
python scripts/fault_eval.py mine eval/real_faults/snapshots/*.json \
    --out eval/real_faults/batches/batch-001

# 3. Label batch-001/sheet.csv (see protocol below)

# 4. Score; rerun with newer snapshots whenever detectors change
python scripts/fault_eval.py score eval/real_faults/batches/batch-001 \
    eval/real_faults/snapshots/*.json
```

## Sampling

Per dataset, `mine` takes:

| Stratum | What | Inclusion probability |
|---|---|---|
| `flagged` | every episode Calibra would drop (Stage 1 quality), block (video fault) or flag as a short-length outlier (behind integrity's `short_episode_fraction`); with `--max-flagged N`, a random sample of N | 1, or N / flagged |
| `review_top` | the top-K remaining episodes of the review queue | 1 |
| `control` | a seeded random sample of everything else | sample size / remaining |

Controls are what make recall measurable: a fault found among controls is a
fault Calibra missed. Scores are weighted by 1 / inclusion probability.

## Labeling protocol

Label each row of `sheet.csv` **from the episode itself** (video and
trajectory), not from Calibra's output. With LeRobot installed, the local
visualizer shows camera frames, actions and state on one timeline:

```bash
lerobot-dataset-viz --repo-id lerobot/pusht --root ./data/pusht --episode-index 17
``` The sheet deliberately does not say why an episode was sampled; keep
`key.jsonl` closed until the batch is labeled.

| `label` | Use when |
|---|---|
| `acquisition_fault` | the recording is broken: frozen or missing camera frames, timestamp gaps, sensor glitch, camera/action desync, truncated episode |
| `execution_failure` | the recording is intact but the demonstration is bad: task failed, operator error, aborted attempt |
| `unusual_valid` | unusual motion that is still a legitimate demonstration: recovery, rare state, different strategy |
| `clean` | nothing notable |
| `unsure` | can't tell; excluded from scoring |

**Duplicates:** when two or more episodes are identical, the first one (lowest episode
index) is the original and is labeled on its own merits; each additional copy is
`acquisition_fault` with `fault_type` `duplicate_episode`. This matches what
`duplicate_episode_fraction` flags, and duplicate recall is only meaningful under it.

`fault_type` is a short free tag (`frozen_camera`, `timestamp_gap`,
`teleop_glitch`, ...). Use `notes` for the evidence (timestamp, camera), so a
second labeler can check it. Where possible have a second person label a
subset and record disagreements in `notes`.

## Reading the scores

- **Precision** of `blocked`: of the episodes Calibra drops or blocks, how
  many are real acquisition faults. This is the number that justifies
  blocking in CI.
- **Recall**: of the real acquisition faults, how many Calibra flags.
- **Fires on unusual_valid**: how often a detector flags legitimate rare
  behavior. High values mean the detector should stay `inspect`, never `block`.

Small n: read the raw counts and Wilson intervals, not just the point
estimates. Do not quote these numbers publicly until the batch, revisions and
Calibra version are recorded alongside them.
