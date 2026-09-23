"""Tests for calibra.integrations.isaac_lab (GR00T manifest + HDF5 filtering)."""

from __future__ import annotations

import json

import numpy as np
import pytest

from calibra.integrations.isaac_lab import (
    export_gr00t_manifest,
    filter_hdf5,
    recommended_demo_indices,
    rejected_demo_indices,
)


def _write_report(path, keep, reject):
    verdicts = {
        "keep_episode_ids": keep,
        "reject_episode_ids": reject,
        "n_original": len(keep) + len(reject),
        "n_kept": len(keep),
        "keep_fraction_actual": len(keep) / (len(keep) + len(reject)),
        "method": "quality_filter + greedy_max_coverage",
    }
    path.write_text(json.dumps({"episode_verdicts": verdicts}), encoding="utf-8")
    return path


@pytest.mark.parametrize(
    "keep, reject",
    [
        (["demo_3", "demo_0", "demo_10"], ["demo_1", "demo_2"]),  # IsaacLabReader IDs
        (["3", "0", "10"], ["1", "2"]),  # bare integer IDs
    ],
)
def test_indices_accept_reader_and_integer_ids(tmp_path, keep, reject):
    report = _write_report(tmp_path / "report.json", keep, reject)
    assert recommended_demo_indices(report) == [0, 3, 10]
    assert rejected_demo_indices(report) == [1, 2]


def test_manifest_from_isaac_lab_ids(tmp_path):
    report = _write_report(tmp_path / "report.json", ["demo_5", "demo_2"], ["demo_0"])
    manifest_path = export_gr00t_manifest(report, demos_path="demos.hdf5")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest_path == tmp_path / "gr00t_manifest.json"
    assert manifest["demo_indices"] == [2, 5]
    assert manifest["demo_ids"] == ["demo_2", "demo_5"]
    assert manifest["n_demos_selected"] == 2


def test_filter_hdf5_from_isaac_lab_ids(tmp_path):
    h5py = pytest.importorskip("h5py")
    src = tmp_path / "demos.hdf5"
    with h5py.File(src, "w") as f:
        f.attrs["total"] = 4
        f.create_group("data").attrs["env_args"] = "{}"
        for i in range(4):
            f.create_dataset(f"data/demo_{i}/actions", data=np.full((5, 2), i, dtype=np.float32))
        f.create_dataset("mask/train", data=np.array(["demo_0", "demo_1", "demo_2"], dtype="S"))
        f.create_dataset("mask/valid", data=np.array(["demo_3"], dtype="S"))

    report = _write_report(tmp_path / "report.json", ["demo_1", "demo_3"], ["demo_0", "demo_2"])
    dst = filter_hdf5(src, report, tmp_path / "coreset.hdf5")

    with h5py.File(dst, "r") as f:
        assert sorted(f["data"]) == ["demo_0", "demo_1"]
        assert f["data/demo_0/actions"][0, 0] == 1
        assert f["data/demo_1/actions"][0, 0] == 3
        assert f.attrs["total"] == 2
        assert f["data"].attrs["env_args"] == "{}"
        assert list(f["mask/train"][()]) == [b"demo_0"]
        assert list(f["mask/valid"][()]) == [b"demo_1"]
