"""
The Apache core stays independent of the separately licensed ee/ code (ADR-012).

These tests fail if a module under calibra/ imports calibra_ee, or if the core
contacts Calibra Cloud on its own when no extension is installed.
"""

from __future__ import annotations

import ast
import subprocess
import sys
import urllib.request
from pathlib import Path

import pytest

import calibra.plugins as plugins
from calibra.card import generate_card
from calibra.outcome_db import OutcomeDatabase

_CORE = Path(__file__).resolve().parents[1] / "calibra"


def _imported_modules(tree: ast.AST) -> list[str]:
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.append(node.module)
    return names


def test_core_never_imports_calibra_ee():
    offenders = []
    for path in sorted(_CORE.rglob("*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        for name in _imported_modules(tree):
            if name == "calibra_ee" or name.startswith("calibra_ee."):
                offenders.append(f"{path.relative_to(_CORE.parent)}: {name}")
    assert offenders == [], "core modules import calibra_ee:\n" + "\n".join(offenders)


@pytest.fixture
def no_plugins(monkeypatch):
    """Behave as a core-only install, even if calibra_ee is installed locally."""
    monkeypatch.setattr(plugins, "_registry", plugins.PluginRegistry())


@pytest.fixture
def no_network(monkeypatch):
    calls: list[str] = []

    def _fail(req, *args, **kwargs):
        calls.append(getattr(req, "full_url", str(req)))
        raise AssertionError("core made a network call")

    monkeypatch.setattr(urllib.request, "urlopen", _fail)
    return calls


def test_recording_an_outcome_stays_local(no_plugins, no_network, tmp_path):
    db = OutcomeDatabase(path=tmp_path / "outcomes.jsonl")
    db.record({"ldlj": -8.0}, predicted_score=70.0, actual_success_rate=0.8)
    assert no_network == []
    assert (tmp_path / "outcomes.jsonl").exists()


def test_outcome_hook_receives_record(no_plugins, tmp_path):
    seen = []
    plugins.get_registry().outcome_recorded.append(seen.append)
    db = OutcomeDatabase(path=tmp_path / "outcomes.jsonl")
    rec = db.record({"ldlj": -8.0}, predicted_score=70.0, actual_success_rate=0.8)
    assert seen == [rec]


def test_failing_hook_does_not_break_record(no_plugins, tmp_path):
    def _boom(record):
        raise RuntimeError("extension bug")

    plugins.get_registry().outcome_recorded.append(_boom)
    db = OutcomeDatabase(path=tmp_path / "outcomes.jsonl")
    db.record({"ldlj": -8.0}, predicted_score=70.0, actual_success_rate=0.8)
    assert len(OutcomeDatabase(path=tmp_path / "outcomes.jsonl")._records) == 1


def _report():
    from calibra.schema.report import DiagnosticReport

    return DiagnosticReport(
        dataset_name="ds", source_path="/tmp/ds", format="hdf5", n_episodes=1, n_samples=10
    )


def test_card_badge_is_static_without_extension(no_plugins):
    card, _ = generate_card(_report(), dataset_id="org/ds")
    assert "img.shields.io" in card
    assert "calibra.ai" not in card


def test_card_badge_from_extension(no_plugins):
    plugins.get_registry().badge_url = lambda dataset_id, status: f"https://x.test/{dataset_id}"
    card, _ = generate_card(_report(), dataset_id="org/ds")
    assert "https://x.test/org/ds" in card


@pytest.mark.parametrize("command", ["login", "cloud"])
def test_cloud_commands_absent_from_core(command):
    code = (
        "import sys, calibra.plugins as p; p._registry = p.PluginRegistry(); "
        f"sys.argv = ['calibra', {command!r}]; "
        "from calibra.__main__ import main; main()"
    )
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert proc.returncode == 2
    assert "not part of the open-source core" in proc.stderr
