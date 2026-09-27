"""
Benchmark regression gate: verdicts and prune decisions on real data.

Runs the analyze and prune paths on a frozen copy of lerobot/pusht
(tests/regression/fixtures/pusht.npz, built by
scripts/build_regression_fixture.py) and compares every verdict-level output
against tests/regression/golden/pusht.json: analyzer flag levels, the noise
regime, headline metrics, and which episodes prune keeps and drops.

A failure here means a change moved Calibra's decisions on real data. That is
allowed, but never silently. If the change is intended, regenerate the golden
file and commit it with the change, with the before and after in the PR and
CHANGELOG.md:

    CALIBRA_UPDATE_GOLDEN=1 pytest tests/regression
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np
import pytest

from calibra.pipeline import Pipeline
from calibra.schema.episode import Episode, EpisodeBatch, EpisodeMetadata
from calibra.strategy import diagnose_regime

HERE = Path(__file__).parent
FIXTURE = HERE / "fixtures" / "pusht.npz"
GOLDEN = HERE / "golden" / "pusht.json"
UPDATE = os.environ.get("CALIBRA_UPDATE_GOLDEN") == "1"

# Hub ID gets the pusht profile automatically; the local path runs on globals.
PROFILED = "lerobot/pusht"
GLOBAL = "./datasets/pusht"


def _load_batch(source_path: str) -> EpisodeBatch:
    data = np.load(FIXTURE)
    bounds = np.cumsum(data["lengths"])[:-1]
    task = str(data["task"]) or None
    episodes = [
        Episode(
            metadata=EpisodeMetadata(episode_id=str(ep_id), task_description=task),
            timestamps=ts,
            observations={"state": state},
            actions=acts,
        )
        for ep_id, ts, state, acts in zip(
            data["episode_ids"],
            np.split(data["timestamps"], bounds),
            np.split(data["state"], bounds),
            np.split(data["actions"], bounds),
        )
    ]
    return EpisodeBatch(
        episodes=episodes, dataset_name="pusht", format="lerobot", source_path=source_path
    )


def _analyze(source_path: str) -> dict:
    report = Pipeline().run(_load_batch(source_path))
    smooth = next(r for r in report.analyzer_results if r.analyzer_name == "control_smoothness")
    regime = diagnose_regime(report)
    return {
        "dataset_profile": report.dataset_profile,
        "flags": {
            f"{r.analyzer_name}/{f.metric}": f.level.value
            for r in report.analyzer_results
            for f in r.flags
        },
        "regime": regime.regime.value,
        "noise_score": round(regime.noise_score, 6),
        "metrics": {
            "mean_spike_fraction": round(
                smooth.raw_metrics["jerk_spikes"]["mean_spike_fraction"], 6
            ),
            "mean_disc_fraction": round(
                smooth.raw_metrics["vel_discontinuities"]["mean_disc_fraction"], 6
            ),
        },
    }


def _prune(source_path: str, monkeypatch, tmp_path) -> dict:
    import calibra.ingestion.registry as registry
    from calibra.prune import run_prune

    monkeypatch.setattr(registry, "load", lambda path, reader=None: _load_batch(path))
    out = tmp_path / "coreset.json"
    run_prune([source_path, "--keep", "0.5", "--policy", "act", "--out", str(out)])
    result = json.loads(out.read_text())
    return {
        "n_kept": result["n_kept"],
        "n_quality_failures": result["n_quality_failures"],
        "keep_episode_ids": sorted(result["keep_episode_ids"], key=int),
        "quality_fail_ids": sorted(result["quality_fail_ids"], key=int),
    }


@pytest.fixture(scope="module")
def golden() -> dict:
    if UPDATE or not GOLDEN.exists():
        return {}
    return json.loads(GOLDEN.read_text())


@pytest.fixture(scope="module")
def observed(golden):
    """Collects this run's snapshot; writes it as the new golden when updating."""
    snap: dict = {}
    yield snap
    if UPDATE:
        GOLDEN.parent.mkdir(exist_ok=True)
        GOLDEN.write_text(json.dumps(snap, indent=2, sort_keys=True) + "\n")


def _check(name: str, value: dict, golden: dict, observed: dict) -> None:
    observed[name] = value
    if UPDATE:
        return
    assert name in golden, f"no golden entry for {name!r}; run CALIBRA_UPDATE_GOLDEN=1"
    expected = golden[name]
    # Numbers get a float tolerance for cross-platform rounding; levels and IDs are exact.
    matches = value == pytest.approx(expected, abs=1e-6) if _flat(value) else value == expected
    assert matches, (
        f"{name} changed on real PushT data.\n"
        f"  golden:   {json.dumps(expected, sort_keys=True)}\n"
        f"  observed: {json.dumps(value, sort_keys=True)}\n"
        "If intended, regenerate with CALIBRA_UPDATE_GOLDEN=1 pytest tests/regression "
        "and record the change in CHANGELOG.md."
    )


def _flat(value: dict) -> bool:
    return all(isinstance(v, (int, float)) for v in value.values())


def test_fixture_is_pinned():
    data = np.load(FIXTURE)
    assert str(data["dataset"]) == "lerobot/pusht"
    assert len(str(data["revision"])) == 40, "fixture must record a full Hub commit SHA"
    assert int(data["lengths"].sum()) == 25650


@pytest.mark.parametrize("source", [PROFILED, GLOBAL])
def test_analyze_verdicts(source, golden, observed):
    snap = _analyze(source)
    _check(f"analyze[{source}]/flags", snap["flags"], golden, observed)
    _check(
        f"analyze[{source}]/regime",
        {"regime": snap["regime"], "dataset_profile": snap["dataset_profile"]},
        golden,
        observed,
    )
    _check(
        f"analyze[{source}]/metrics",
        {**snap["metrics"], "noise_score": snap["noise_score"]},
        golden,
        observed,
    )


@pytest.mark.parametrize("source", [PROFILED, GLOBAL])
def test_prune_decisions(source, golden, observed, monkeypatch, tmp_path):
    snap = _prune(source, monkeypatch, tmp_path)
    _check(
        f"prune[{source}]/counts",
        {"n_kept": snap["n_kept"], "n_quality_failures": snap["n_quality_failures"]},
        golden,
        observed,
    )
    _check(
        f"prune[{source}]/episodes",
        {"keep": snap["keep_episode_ids"], "quality_fail": snap["quality_fail_ids"]},
        golden,
        observed,
    )
