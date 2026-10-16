"""Tests for training LeRobot policies on Calibra-selected episodes in place."""

from __future__ import annotations

import json
import sys
import types

import pytest

from calibra.integrations.lerobot import (
    lerobot_episode_indices,
    lerobot_train_args,
    load_lerobot_dataset,
)


@pytest.fixture
def report(tmp_path):
    path = tmp_path / "report.json"
    path.write_text(
        json.dumps({"episode_verdicts": {"keep_episode_ids": ["12", "0", "7", "4"]}}),
        encoding="utf-8",
    )
    return path


def test_indices_are_sorted_ints(report):
    assert lerobot_episode_indices(report) == [0, 4, 7, 12]
    assert lerobot_episode_indices(["3", "1", "3"]) == [1, 3]


def test_non_lerobot_ids_rejected():
    with pytest.raises(ValueError, match="not LeRobot episode indices"):
        lerobot_episode_indices(["demo_0", "demo_1"])


def test_train_args(report):
    assert lerobot_train_args(report, "lerobot/pusht") == [
        "--dataset.repo_id=lerobot/pusht",
        "--dataset.episodes=[0,4,7,12]",
    ]
    args = lerobot_train_args(["2"], "local/ds", root="/data/ds")
    assert args == [
        "--dataset.repo_id=local/ds",
        "--dataset.root=/data/ds",
        "--dataset.episodes=[2]",
    ]


@pytest.mark.parametrize(
    "module", ["lerobot.datasets.lerobot_dataset", "lerobot.common.datasets.lerobot_dataset"]
)
def test_load_lerobot_dataset_passes_episodes(monkeypatch, report, module):
    calls = {}

    class FakeLeRobotDataset:
        def __init__(self, repo_id, **kwargs):
            calls.update(repo_id=repo_id, **kwargs)

    for name in [
        "lerobot",
        "lerobot.datasets",
        "lerobot.datasets.lerobot_dataset",
        "lerobot.common",
        "lerobot.common.datasets",
        "lerobot.common.datasets.lerobot_dataset",
    ]:
        monkeypatch.setitem(sys.modules, name, None)
    mod = types.ModuleType(module)
    mod.LeRobotDataset = FakeLeRobotDataset
    monkeypatch.setitem(sys.modules, module, mod)

    load_lerobot_dataset("lerobot/pusht", report, root="/x")
    assert calls == {"repo_id": "lerobot/pusht", "episodes": [0, 4, 7, 12], "root": "/x"}


def test_load_lerobot_dataset_without_lerobot(monkeypatch, report):
    for name in ["lerobot.datasets.lerobot_dataset", "lerobot.common.datasets.lerobot_dataset"]:
        monkeypatch.setitem(sys.modules, name, None)
    with pytest.raises(ImportError, match="pip install lerobot"):
        load_lerobot_dataset("lerobot/pusht", report)


def test_prune_hint_hub_and_local(tmp_path, capsys):
    from calibra.prune import _print_lerobot_train_hint

    _print_lerobot_train_hint(["4", "0"], "lerobot/pusht", print)
    out = capsys.readouterr().out
    assert "--dataset.repo_id=lerobot/pusht" in out
    assert "'--dataset.episodes=[0,4]'" in out

    local = tmp_path / "my_ds"
    local.mkdir()
    _print_lerobot_train_hint(["1"], str(local), print)
    out = capsys.readouterr().out
    assert "--dataset.repo_id=local/my_ds" in out
    assert f"--dataset.root={local}" in out
