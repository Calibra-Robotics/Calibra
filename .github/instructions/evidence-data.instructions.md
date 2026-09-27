---
applyTo: "calibra/references/**,tests/regression/**,calibra/dataset_profiles.py"
---

These files are Calibra's evidence base. When reviewing changes here, check:

- **References** (`calibra/references/*.json`) come from `scripts/profile_dataset.py`
  or `scripts/profile_pusht.py`, never hand edits. `meta` must record the
  settings actually applied (`control_mode`, `gripper_dims`, `dataset_profile`).
  Numbers quoted in `calibra/references/README.md`, `docs/` or `paper/` must
  match the regenerated file.
- **Golden results** (`tests/regression/golden/*.json`) change only with
  `CALIBRA_UPDATE_GOLDEN=1 pytest tests/regression`, alongside a code change,
  with the before and after in the PR description and `CHANGELOG.md`. The
  fixture (`tests/regression/fixtures/`) changes only via
  `scripts/build_regression_fixture.py` with a pinned revision.
- **Dataset profiles** override defaults for the Hub IDs they name. Thresholds
  must clear the profile's own clean data (the tests in
  `tests/test_dataset_profiles.py` check this), and `ProfileEvidence` must be
  complete.
