# Contributing to Calibra

**Open contributions. Evidence-gated merges.**

Calibra's output decides which robot episodes are kept, dropped or sent to
training. A threshold that looks reasonable but was never measured can silently
remove good data. Anyone can propose a change. Only reproducible, benchmarked,
reviewed changes get merged.

## Current status: pull requests are not open yet

We are not accepting external pull requests yet. We will open them once a
Contributor License Agreement is in place, so that the rights to contributed
code are clear before any of it is merged.

Until then, you can contribute through issues:

- **Bug reports:** [open a bug report](https://github.com/Calibra-Robotics/Calibra/issues/new?template=bug_report.yml).
- **Dataset profile proposals:** if Calibra misjudges a dataset you know well,
  [propose a profile](https://github.com/Calibra-Robotics/Calibra/issues/new?template=dataset_profile.yml)
  with your measurements. A maintainer writes the profile, credits you, and
  holds it to the standards below.
- **Feature ideas:** [open a feature request](https://github.com/Calibra-Robotics/Calibra/issues/new?template=feature_request.yml).
- **Security issues:** do not open a public issue. Follow
  [`SECURITY.md`](https://github.com/Calibra-Robotics/Calibra/blob/main/SECURITY.md).

## What every merged change must meet

These apply to maintainers today and will apply to all contributors once pull
requests open.

- **Tests for every code change.** No exceptions for "small" changes.
- **Threshold changes need empirical evidence,** not intuition: the dataset, the
  measured distribution, and why the new value is right.
- **Scoring and pruning changes need before and after benchmarks** on the
  reference datasets.
- **No silent behavior changes.** A change that moves any verdict, score or
  prune count says so in the pull request and the changelog.
- **Global defaults are harder to change than dataset profiles.** A quirk of one
  dataset goes in a profile in `calibra/dataset_profiles.py`, never in a
  global default that would shift every other dataset's results.
- **Verdict-affecting code requires maintainer review.** See
  [`.github/CODEOWNERS`](https://github.com/Calibra-Robotics/Calibra/blob/main/.github/CODEOWNERS).
- **Include reproducibility details:** commands, seeds, dataset revision and
  expected outputs.

Each pull request also gets an automated evidence review that comments on
missing evidence against these rules. It is advisory; the tests and the
benchmark regression check are what block a merge.

### Dataset profiles

A dataset profile is treated like a short technical note. Each one carries a
`ProfileEvidence` record, and CI fails if any part is missing or inconsistent:

| Field | What it records |
|-------|-----------------|
| `dataset_revision` | Hub commit SHA or tag the baseline was measured on |
| `sampling_rate_hz` | Control frequency |
| `action_space` | What the action vector means (absolute or delta, units, gripper dims) |
| `reference` | The baseline run in `calibra/references/` |
| `clean_baseline` | Clean per-episode rates the thresholds rest on; must match the reference file |
| `justification` | Why each setting departs from the global default |
| `reproduce` | The command that regenerates the reference file |

CI also checks that a profile's prune limits do not cut its own clean episodes,
and that its HIGH NOISE thresholds sit above its clean mean. The PushT profile
is the worked example.

## Development setup

```bash
git clone https://github.com/Calibra-Robotics/Calibra.git
cd Calibra
pip install -e ".[dev]"
pytest tests/ -v --tb=short
ruff check . && ruff format --check .
python scripts/generate_claims_doc.py --check
```
