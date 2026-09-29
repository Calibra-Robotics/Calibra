# Contributing to Calibra

**Open contributions. Evidence-gated merges.**

Calibra's output decides which robot episodes are kept, dropped or sent to
training. A threshold that looks reasonable but was never measured can silently
remove good data. Anyone can propose a change. Only reproducible, benchmarked,
reviewed changes get merged.

## Current status: not accepting outside contributions yet

Issues, discussions and external pull requests are closed, and pull requests
from outside the project are closed automatically.

- **Security issues:** report them privately by following
  [`SECURITY.md`](https://github.com/Calibra-Robotics/Calibra/blob/main/SECURITY.md).
- **A bug, or a dataset Calibra misjudges:** email **omertahtoko@gmail.com**.
  For a dataset, include your measurements; a maintainer writes the profile,
  credits you, and holds it to the standards below.

## What every change must meet

These apply to the maintainer's own commits today and will apply to all
contributors once pull requests open.

- **Tests for every code change.** No exceptions for "small" changes.
- **Threshold changes need empirical evidence,** not intuition: the dataset, the
  measured distribution, and why the new value is right.
- **Scoring and pruning changes need before and after benchmarks** on the
  reference datasets.
- **No silent behavior changes.** A change that moves any verdict, score or
  prune count says so in the commit message and the changelog.
- **Global defaults are harder to change than dataset profiles.** A quirk of one
  dataset goes in a profile in `calibra/dataset_profiles.py`, never in a
  global default that would shift every other dataset's results.
- **Verdict-affecting code requires maintainer review.** See
  [`.github/CODEOWNERS`](https://github.com/Calibra-Robotics/Calibra/blob/main/.github/CODEOWNERS).
- **Include reproducibility details:** commands, seeds, dataset revision and
  expected outputs.

CI runs on every push to `main`: tests on Python 3.10 to 3.13, lint, the
type-check ratchet, the claims check and the benchmark regression check. Run
the same checks locally before pushing (see below); `pre-commit` covers the
fast ones. Pull requests, when they open, also get an advisory GitHub Copilot
review against these rules (`.github/copilot-instructions.md` and
`.github/instructions/`).

Commit messages follow [Conventional Commits](https://www.conventionalcommits.org/)
(`fix(profiles): ...`, `feat: ...`, `docs: ...`).

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
pre-commit install          # ruff, format and claims checks on every commit
pytest tests/ -v --tb=short
python scripts/mypy_ratchet.py
```

`scripts/mypy_ratchet.py` fails if a change adds type errors. The codebase is
not type-clean yet; if your change removes errors, lower `BASELINE` in that
script in the same commit. Test coverage must stay at or above
`fail_under` in `pyproject.toml`.
