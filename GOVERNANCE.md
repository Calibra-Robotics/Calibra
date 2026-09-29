# Governance

Calibra is maintained by a single maintainer today. This page says who decides
what.

## Maintainers

| Maintainer | GitHub | Areas |
|------------|--------|-------|
| Ömer Tahtacı | [@omertt27](https://github.com/omertt27) | Everything; sole code owner |

## How decisions are made

- **Day-to-day changes** are committed to `main` by the maintainer. CI runs on
  every push. Outside contributions are not open yet (see
  [CONTRIBUTING.md](CONTRIBUTING.md)).
- **Verdict-affecting changes** (thresholds, scoring, pruning, dataset
  profiles) are decided on evidence, not preference. The standards are in
  [docs/contributing.md](docs/contributing.md).
- **Significant design decisions** are recorded as architecture decision
  records in [`docs/adr/`](docs/adr/).
- **Licensing and the open-core boundary** are decided by the maintainer. See
  [LICENSING.md](LICENSING.md) and [docs/open-core-boundary.md](docs/open-core-boundary.md).

## What to expect

- Security reports are acknowledged within 48 hours (see [SECURITY.md](SECURITY.md)).
