"""
Claims evidence must match the reference files it cites.

The parity check in scripts/generate_claims_doc.py only counts files, so a
claim could keep citing a value its reference no longer measures (PushT's
evidence went stale this way). Every numeric evidence entry whose dataset has
a reference in calibra/references/ must agree with that reference's aggregate
metric at the precision the claim records.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

import calibra

PKG = Path(calibra.__file__).parent

# Claim metric -> "<analyzer>/<aggregate key>" in a reference file. A claim
# about a different quantity names it with its own `reference_metric`.
_REFERENCE_METRIC = {
    "velocity_discontinuity_rate": "control_smoothness/vel_discontinuities.mean_disc_fraction",
    "spike_rate": "control_smoothness/jerk_spikes.mean_spike_fraction",
    "ldlj": "control_smoothness/ldlj.mean_ldlj",
    "jitter_cv": "temporal_stability/jitter.mean_cv",
    "dropout_rate": "temporal_stability/dropout.mean_dropout_fraction",
    "action_entropy": "coverage_entropy/action_entropy.entropy_bits_per_dim",
}


def _references() -> dict[str, dict]:
    """Reference data keyed by its Hub ID and by `lerobot/<file stem>`."""
    refs = {}
    for path in sorted((PKG / "references").glob("*.json")):
        data = json.loads(path.read_text())
        refs[data["meta"]["dataset"]] = data
        refs.setdefault(f"lerobot/{path.stem}", data)
    return refs


def _evidence():
    refs = _references()
    for path in sorted((PKG / "claims").glob("*.json")):
        for claim in json.loads(path.read_text())["claims"]:
            metric = claim.get("reference_metric") or _REFERENCE_METRIC.get(claim["metric"])
            for entry in claim.get("evidence", []):
                observed = entry.get("observed")
                if metric is None or not isinstance(observed, (int, float)):
                    continue
                if entry["dataset"] not in refs:
                    continue
                analyzer, key = metric.split("/", 1)
                measured = refs[entry["dataset"]]["aggregate_metrics"].get(analyzer, {}).get(key)
                yield pytest.param(observed, measured, id=f"{claim['id']}:{entry['dataset']}")


def _decimals(x: float) -> int:
    return max(0, -Decimal(repr(float(x))).normalize().as_tuple().exponent)


@pytest.mark.parametrize("observed, measured", list(_evidence()))
def test_claim_value_matches_reference(observed, measured):
    assert measured is not None, "the cited reference does not record this metric"
    # Compare at the coarser of the two recorded precisions.
    places = min(_decimals(observed), _decimals(measured))
    assert abs(round(observed, places) - round(measured, places)) <= 0.5 * 10**-places, (
        f"claim records {observed}, reference measures {measured}"
    )


def test_every_retraction_is_explained():
    for path in sorted((PKG / "claims").glob("*.json")):
        for claim in json.loads(path.read_text())["claims"]:
            for entry in claim.get("retracted_evidence", []):
                assert entry.get("retracted") and entry.get("retraction_reason"), (
                    f"{claim['id']}: retracted {entry['dataset']} without a date and reason"
                )
