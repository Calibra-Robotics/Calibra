---
applyTo: "calibra/claims/**"
---

Claims follow `calibra/claims/SPEC.md`. When reviewing changes here, check:

- An evidence entry's dataset belongs to the claim's `class` (or the class is
  `any`). PushT and pusht_image are position control, and are the same data.
- `observed` values match the dataset's reference file in `calibra/references/`
  (`tests/test_claims_references.py` enforces this; a claim about a different
  quantity names it with `reference_metric`).
- Evidence is never deleted. Invalid entries move to `retracted_evidence` with
  `retracted` and `retraction_reason`; valid entries with wrong reasoning get a
  dated `[Corrected YYYY-MM-DD: ...]` note.
- `confidence` is derived from the supporting-evidence count, never set by hand.
  Status changes follow the transitions in the SPEC.
- `docs/claims.md` is regenerated with `python scripts/generate_claims_doc.py`,
  not edited by hand.
