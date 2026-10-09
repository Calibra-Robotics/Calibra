"""Tests for calibra_ee: registration with the core and outcome sync."""

from __future__ import annotations

import json
import urllib.request

import pytest

import calibra.plugins as plugins
from calibra.outcome_db import OutcomeDatabase
from calibra_ee import community, sync
from calibra_ee.plugin import register


@pytest.fixture
def registry(monkeypatch):
    reg = plugins.PluginRegistry()
    register(reg)
    monkeypatch.setattr(plugins, "_registry", reg)
    return reg


@pytest.fixture
def posts(monkeypatch, tmp_path):
    sent: list[tuple[str, dict]] = []

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return b"{}"

    def _urlopen(req, *args, **kwargs):
        body = json.loads(req.data) if req.data else {}
        sent.append((req.full_url, body))
        return _Resp()

    monkeypatch.setattr(urllib.request, "urlopen", _urlopen)
    monkeypatch.setattr(sync, "_CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr("calibra_ee.cloud.auth._CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.delenv("CALIBRA_NO_CLOUD_SYNC", raising=False)
    return sent


def test_registers_cloud_commands_and_hooks(registry):
    assert set(registry.commands) == {"login", "logout", "whoami", "cloud"}
    assert sync.on_outcome_recorded in registry.outcome_recorded
    assert community.register_badge in registry.card_pushed
    assert registry.badge_url is community.badge_url


def test_entry_point_is_declared():
    from importlib.metadata import entry_points

    eps = {ep.name: ep.value for ep in entry_points(group=plugins.ENTRY_POINT_GROUP)}
    assert eps.get("ee") == "calibra_ee.plugin:register"


def test_record_syncs_anonymously(registry, posts, tmp_path):
    db = OutcomeDatabase(path=tmp_path / "outcomes.jsonl")
    db.record({"ldlj": -8.0}, predicted_score=70.0, actual_success_rate=0.8, domain="llm_sft")
    assert len(posts) == 1
    url, body = posts[0]
    assert url.endswith("/v1/record")
    assert body["actual_success_rate"] == 0.8
    assert "installation_id" in body
    assert "dataset_name" not in body


def test_opt_out_disables_sync(registry, posts, tmp_path, monkeypatch):
    monkeypatch.setenv("CALIBRA_NO_CLOUD_SYNC", "1")
    db = OutcomeDatabase(path=tmp_path / "outcomes.jsonl")
    db.record({"ldlj": -8.0}, predicted_score=70.0, actual_success_rate=0.8)
    community.register_badge("org/ds", "CERTIFIED")
    assert posts == []


def test_badge_registration(posts):
    community.register_badge("org/ds", "CERTIFIED")
    url, body = posts[0]
    assert url.endswith("/v1/badge")
    assert body["dataset_id"] == "org/ds"
