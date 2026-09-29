# Governance

Calibra is maintained by a single maintainer today. This page says who decides
what, and what contributors can expect.

## Maintainers

| Maintainer | GitHub | Areas |
|------------|--------|-------|
| Ömer Tahtacı | [@omertt27](https://github.com/omertt27) | Everything; sole code owner |

## How decisions are made

- **Day-to-day changes** are decided in pull request review. A change merges
  when CI passes and a code owner approves it (see
  [`.github/CODEOWNERS`](.github/CODEOWNERS)).
- **Verdict-affecting changes** (thresholds, scoring, pruning, dataset
  profiles) are decided on evidence, not preference. The standards are in
  [docs/contributing.md](docs/contributing.md).
- **Significant design decisions** are recorded as architecture decision
  records in [`docs/adr/`](docs/adr/). Propose one in an issue first.
- **Licensing and the open-core boundary** are decided by the maintainer. See
  [LICENSING.md](LICENSING.md) and [docs/open-core-boundary.md](docs/open-core-boundary.md).

## What to expect

- New issues and pull requests get a first response within 7 days.
- Security reports are acknowledged within 48 hours (see [SECURITY.md](SECURITY.md)).
- A pull request that stalls on the author's side for 30 days may be closed;
  it can be reopened at any time.

## Becoming a maintainer

Contributors with a sustained record of high-quality, evidence-backed
contributions may be invited to become maintainers and code owners for the
areas they know. As the project grows, this page will describe that process in
more detail.
