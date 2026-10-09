# ADR-012: Apache 2.0 Core and Separately Licensed Commercial Code

**Status:** Proposed  
**Date:** 2026-10-09  
**Deciders:** Calibra core team

---

## Context

Calibra is licensed under BSL 1.1 (see [LICENSING.md](../../LICENSING.md)),
with a scheduled conversion to Apache 2.0 on 2030-06-30. The project intends to
move the core to Apache 2.0 now, starting with v0.12, so that the integrity,
review and dataset decision workflow is OSI open source today rather than in
2030.

A small amount of code exists for organizational and hosted workflows (cloud
login and upload, outcome sync to a hosted service, the hosted aggregation
server). That code should not be released under Apache by accident. Two research
modules, `predict` and `strategy`, have not been assigned to either side yet.

Releasing a version under Apache 2.0 cannot be undone for that version. The
boundary therefore has to be settled, and enforced in code, before v0.12 is
tagged. [open-core-boundary.md](../open-core-boundary.md) records which
features belong on which side; this ADR records how the boundary is
implemented, based on the current import graph.

---

## Findings: the current import graph

A static AST scan of `calibra/`, `server/`, `spaces/`, `scripts/`, `tests/` and
`experiments/` (1,454 intra-project import edges, classified as module level,
function level, or `TYPE_CHECKING`) gives the following picture.

### 1. The core QA workflow has no direct dependency on the candidate modules

Ignoring the package `__init__.py`, none of these modules import `cloud`,
`outcome_db`, `predict` or `strategy`, at load time or lazily:

`integrity`, `audit`, `review`, `watch`, `prune`, `pruning`, `annotate`,
`pipeline`, `certify`, `compare`.

### 2. All coupling comes from five places

| Importer | Imports | Kind | Effect |
|---|---|---|---|
| `calibra/__init__.py:17` | `predict.predict_outcome` | module level | `import calibra` (and therefore every submodule) loads `predict` |
| `calibra/__init__.py:38` | `strategy.diagnose_regime`, `select_with_regime`, `RegimeDiagnosis`, `SelectionRegime` | module level | every submodule loads `strategy` |
| `calibra/analyze.py:55` | `strategy._REGIME_LABELS`, `RegimeDiagnosis`, `diagnose_regime` | module level | `calibra analyze` prints the selection regime |
| `calibra/card.py:39`, `calibra/benchmark.py:14` | `predict.predict_outcome` (`card.py:143` also `_extract_metrics`) | module level | dataset cards and `benchmark` include a predicted outcome |
| `calibra/diagnose.py:180`, `calibra/gap.py:165`, `calibra/serve.py:234,416,488` | `predict.predict_outcome` | function level | prediction shown inside these commands |

Because of the two `__init__.py` lines, every entry point (including
`integrity`, `review` and `watch`) currently loads `predict` and `strategy` at
import time.

### 3. `cloud/` is already nearly isolated

`cloud/` is imported only by `__main__.py:63-81` (`login`, `logout`, `whoami`,
`cloud push`) and by `outcome_db.py:337` (`cloud.auth.get_token`, used for
authenticated sync). `cloud/` itself depends only on `pipeline` and on
`__main__._get_reader`.

### 4. `outcome_db` mixes a local store with network sync

`outcome_db.py` contains the local outcome store (`record`, `find_similar`,
`blend_prediction`) used by `predict`, `serve`, `sft_outcome`, `llm.predict` and
the CLI, plus three network paths:

- anonymous metric sync to `https://outcomes.calibra.ai/v1/record` when an
  outcome is recorded. This is **on by default**; users opt out with
  `CALIBRA_NO_CLOUD_SYNC=1`.
- authenticated sync to `https://app.calibra.io` via `cloud.auth`.
- `download_global_weights` (community weights, `calibra calibrate --global`).

`outcome_db.py:502` also reads `predict._THRESHOLDS`, and
`predict._load_weights` reads `~/.calibra/weights.json`, which is the file the
community weights download writes.

### 5. Hosted service code lives outside the wheel already

`server/main.py` (accounts, report history, outcome aggregation, community
weights, badges, public registry) is not in the published wheel
(`[tool.hatch.build.targets.wheel] packages = ["calibra"]`). `web/` is the
project website, built by Vercel and optionally served by `calibra serve`; it
talks only to the GitHub API and is not part of the commercial layer.

### 6. Three more network calls outside `outcome_db` (found during implementation)

A search for `urllib` and the service hostnames in `calibra/` found:

- `card.py`: after `calibra card --push`, a POST registering the badge status
  with `outcomes.calibra.ai/v1/badge`, and a card badge pointing at that
  service whenever a dataset ID is given.
- `predict.py`: after `calibra predict --record-outcome`, a GET of community
  percentiles from `app.calibra.io`, printed to stderr.
- `compare.py`: `calibra compare --community` fetches the same percentiles.

The test suite exercised the automatic ones: a sandboxed run before this change
showed dozens of blocked connections to `outcomes.calibra.ai`.

---

## Decision

### Repository layout

One repository, two license zones:

```
LICENSE                 Apache 2.0, covers everything except ee/
calibra/                Apache 2.0 core, the only package published to PyPI
ee/
  LICENSE               commercial / source-available license for ee/
  calibra_ee/           commercial Python package (not published to PyPI)
    cloud/              moved from calibra/cloud/
    sync.py             network sync paths moved out of outcome_db.py
  server/               moved from server/
```

`calibra_ee` is a separate top-level package, not a subpackage of `calibra`, so
the existing wheel configuration cannot pick it up by accident.

### Dependency rule

`calibra` must never import `calibra_ee`. `calibra_ee` may import `calibra`.
The core finds commercial functionality only through a plugin entry point
(`[project.entry-points."calibra.plugins"]`), which `calibra_ee` registers. The
`login`, `logout`, `whoami` and `cloud` CLI commands are registered by the
plugin and do not exist in a core-only install.

### Module assignment

| Zone | Modules |
|---|---|
| **Apache core** | `ingestion/`, `core/`, `schema/`, `analyzers/`, `metrics/`, `kinematics/`, `temporal/`, `pipeline`, `integrity`, `audit`, `audit_all`, `review`, `watch`, `prune`, `pruning`, `curation/`, `annotate`, `assessment`, `anomalies`, `calibration`, `claims` and the claims/references/knowledge base data, `compare`, `comparison/`, `certify`, `corrupt`, `score`, `report_html`, `report_json`, `cache`, `dataset_profiles`, `integrations/`, local `serve` dashboard, and the local part of `outcome_db` |
| **Commercial (`ee/`)** | `cloud/`, outcome sync (from `outcome_db`), community context after recording an outcome (from `predict`), badge registration and live badges (from `card`), `server/` |
| **Apache core (Option A, see below)** | `predict` rubric, `strategy` |
| **Commercial extension point** | outcome-data calibration for `predict` (hosted or customer-specific outcome sources) |

Modules not listed (`analyze`, `card`, `benchmark`, `diagnose`, `gap`,
`experiment`, `experiment_log`, `case_study`, `llm/`, `sft_*`, `sim2real`,
`transfer`, `retarget`, `cure`, `surprise`, `world_model/`, `models/`) stay in
the core. Their only link to the commercial side is through `predict` or
`strategy`, which also stay in the core under Option A.

### `predict` and `strategy`: Option A chosen (2026-10-09)

"Undecided" cannot survive v0.12 unchanged: as shipped today, both modules load
with every entry point and would be released under Apache. Two options were
considered; **Option A was chosen**. The ADR as a whole remains Proposed until
the implementation step is reviewed.

**Option A: both stay in the core, with the commercial seam inside `predict`.**
The transparent rubric (`_THRESHOLDS`, `_WEIGHTS`, `predict_outcome` with
`use_outcome_db=False`) and `strategy` are released under Apache. The paid
extension point is empirical blending and calibration from outcome data:
`predict_outcome` accepts an optional outcome source, and the hosted or
customer-specific source lives in `calibra_ee`. No core command loses
functionality.

**Option B: both move to `ee/`.** `__init__.py` stops re-exporting them;
`analyze`, `card`, `benchmark`, `diagnose`, `gap` and `serve` lose their
prediction and regime sections in a core-only install (guarded by
`try: import calibra_ee` through the plugin interface); `card.py` needs its own
copy of `_extract_metrics`; `spaces/app.py` and five test files need changes.

**Rationale for Option A.** The rubric is designed to be auditable ("every
deduction is explained and backed by a Calibra claim"), it is cited by the
benchmark and dataset card outputs that public results depend on, and
[open-core-boundary.md](../open-core-boundary.md) already lists "baseline
`predict`" as public core. `strategy` is a 398-line heuristic over published
ablations. Withholding either would weaken reproducibility, which the boundary
doc's rule 4 forbids. What has commercial value is calibration from real
outcome data, and Option A keeps that out of the core. Option A also keeps
the decision open in the useful direction: a future paid predictor can be added
as a new outcome source without touching the Apache code.

### Network behaviour of the core

An Apache core should not send data over the network unless the user asks it
to. The rule applied:

- **Calls the user did not ask for move to `calibra_ee`:** outcome sync, the
  community context printed after recording an outcome, and badge
  registration. A core-only install never makes them.
- **Calls behind an explicit flag stay in the core:** `calibra compare
  --community` and `calibra calibrate --global` (`download_global_weights`).
  The user requested the network call by passing the flag. This amends the
  original plan, which moved `download_global_weights` to `calibra_ee`.

Whether recording an outcome with the extension installed syncs by default or
requires opt-in is left to the commercial layer, but the current opt-out
default should be revisited.

---

## Required changes (implementation step, after this ADR is accepted)

1. Create `ee/` with its own `LICENSE`; move `calibra/cloud/` to
   `ee/calibra_ee/cloud/` and `server/` to `ee/server/`. Update `vercel.json`
   and `[tool.vercel] entrypoint` if the server deployment depends on the old
   path.
2. Split `outcome_db.py`: keep the local store and `download_global_weights`
   in the core; move `_sync_authenticated` and the anonymous sync to
   `calibra_ee/sync.py`. Remove the `cloud.auth` import from the core. Move the
   badge registration and community context the same way (finding 6).
3. Add the `calibra.plugins` entry point group; register the `login`,
   `logout`, `whoami` and `cloud` commands from `calibra_ee`, plus hooks for
   recorded outcomes, pushed cards and badge URLs. Remove the command branches
   from `__main__.py`.
4. Apply Option A: add the outcome-source parameter to `predict_outcome`
   (the local outcome store stays the core default) and keep `__init__.py`
   unchanged.
5. Test the sync code in `ee/tests/`. (`tests/test_outcome_db.py` had no
   sync tests to move.)
6. Add two CI guards:
   - **wheel check:** build the wheel, install it in a clean environment
     without `calibra_ee`, assert no `ee/` or `calibra_ee` files are inside,
     run `import calibra` and the core test suite.
   - **import rule:** a test that walks `calibra/` with `ast` and fails on any
     import of `calibra_ee`.
7. Only after steps 1 to 6 pass: replace `LICENSE` with Apache 2.0, update
   `pyproject.toml` (`license = "Apache-2.0"`), README, LICENSING.md,
   CLA.md and open-core-boundary.md, then tag v0.12.

Before step 7, confirm that no third party (employer, university) holds rights
to any part of the code. The git history shows a single author.

**Status (2026-10-10):** steps 1 to 6 are implemented. Two details beyond the
plan: the sdist also had to exclude `ee/` (`[tool.hatch.build.targets.sdist]`,
since hatch puts the whole repository in the sdist by default), and
`calibra login` and the other cloud commands print an explanation and exit 2
in a core-only install instead of being parsed as a dataset path. Step 7 is
not started.

---

## Alternatives considered

**Two repositories (public core, private commercial).** Clean separation, but
doubles release and CI overhead for a commercial layer with no customers yet,
and makes cross-cutting refactors harder. The `ee/` folder plus the CI guards
gives the same guarantee on what reaches PyPI. Splitting the repository
later remains possible.

**Two packages from the same repository published to PyPI.** Unnecessary
until there is a commercial product to distribute; `calibra_ee` can be
installed from source or a private index when needed.

**Relicense everything, including `cloud/` and `server/`, to Apache.**
Simplest, but releases the hosted-service code permanently while the
commercial model is still undecided. Rejected.

**Keep BSL 1.1 until the 2030 change date.** Keeps the hosting restriction, but
BSL is not OSI open source, which limits adoption by labs and companies whose
policies require an OSI license. Rejected.

---

## Consequences

**Positive:**
- The integrity, review, watch and decision-layer workflow becomes OSI open
  source, with no change to how users install or run it.
- The boundary is enforced by CI, not by convention.
- A core-only install no longer makes network calls by default.
- Commercial features can be added later as plugins without touching Apache
  code.

**Negative:**
- Anyone may host the Apache core as a service; the BSL hosting restriction
  no longer applies to it. Accepted: the commercial layer is the
  organizational workflow, not hosted analysis.
- Users of `calibra login` / `cloud push` / `calibrate --global` need the
  commercial package after v0.12. Today these commands target a service with
  no paying users, so the impact is small, but it should be in the changelog.
- One more CI job and a plugin interface to maintain.

---

## References

- [open-core-boundary.md](../open-core-boundary.md): feature-level boundary and rules of thumb
- [LICENSING.md](../../LICENSING.md): current BSL 1.1 terms
- `calibra/__init__.py`, `calibra/analyze.py`, `calibra/card.py`, `calibra/benchmark.py`: the module-level couplings listed above
- `calibra/outcome_db.py`: local store and network sync (split target)
- `calibra/cloud/`, `server/main.py`: commercial code to move
- [ADR-007](adr-007-optional-format-dependencies.md): lazy-import convention reused for the plugin interface
- [ADR-011](adr-011-dataset-decision-layer.md): the decision layer that stays in the Apache core
