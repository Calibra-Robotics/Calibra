# ee/: Calibra Cloud extension

Everything under `ee/` is **not** part of the Calibra open-source core. It is
licensed separately (see [ee/LICENSE](LICENSE)) and is not published to PyPI.
Everything outside `ee/` is covered by the root [LICENSE](../LICENSE).

| Path | What it is |
|---|---|
| `calibra_ee/cloud/` | `calibra login`, `logout`, `whoami`, `cloud push` |
| `calibra_ee/sync.py` | outcome sync to Calibra Cloud after `OutcomeDatabase.record()` |
| `calibra_ee/community.py` | community percentiles after recording an outcome; live dataset badges |
| `calibra_ee/plugin.py` | registers the above with the core |
| `server/` | the hosted Calibra Cloud API |

## How it connects to the core

The core never imports `calibra_ee` (enforced by `tests/test_core_boundary.py`).
`calibra_ee` registers itself through the `calibra.plugins` entry point, and the
core calls the registered commands and hooks (see `calibra/plugins.py` and
[ADR-012](../docs/adr/adr-012-apache-core-boundary.md)).

## Development

```bash
pip install -e ".[dev]" -e ee/
pytest ee/tests
```
