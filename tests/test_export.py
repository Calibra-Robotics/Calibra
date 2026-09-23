"""Tests for calibra.curation.export — dataset materialisation after pruning."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from calibra.pruning import PruningResult

# ── helpers ───────────────────────────────────────────────────────────────────


def _make_result(keep_ids: list[str], n_original: int = 10) -> PruningResult:
    all_ids = [str(i) for i in range(n_original)]
    quality_fail = []
    diversity_pruned = [eid for eid in all_ids if eid not in keep_ids]
    return PruningResult(
        keep_episode_ids=keep_ids,
        quality_fail_ids=quality_fail,
        diversity_pruned_ids=diversity_pruned,
        quality_scores={eid: float(i) * 0.1 for i, eid in enumerate(all_ids)},
        diversity_scores={eid: float(i) * 0.2 for i, eid in enumerate(all_ids)},
        n_original=n_original,
        n_kept=len(keep_ids),
        n_quality_failures=0,
        n_diversity_pruned=len(diversity_pruned),
        keep_fraction_actual=len(keep_ids) / n_original,
    )


def _make_lerobot_v2_dir(tmp_path: Path, n_episodes: int = 5, steps_per_ep: int = 10) -> Path:
    """
    Create a minimal LeRobot v2 dataset on disk (Parquet + meta).
    Uses pyarrow directly; skips if unavailable.
    """
    pytest.importorskip("pyarrow")
    pytest.importorskip("pyarrow.parquet")

    import pyarrow as pa_mod
    import pyarrow.parquet as pq_mod

    ds_dir = tmp_path / "my_dataset"
    data_dir = ds_dir / "data" / "chunk-000"
    data_dir.mkdir(parents=True)
    meta_dir = ds_dir / "meta"
    meta_dir.mkdir()

    rows: dict[str, list] = {
        "episode_index": [],
        "frame_index": [],
        "timestamp": [],
        "action": [],
        "observation.state": [],
    }
    for ep in range(n_episodes):
        for step in range(steps_per_ep):
            rows["episode_index"].append(ep)
            rows["frame_index"].append(step)
            rows["timestamp"].append(step * 0.02)
            rows["action"].append([float(ep), float(step)])
            rows["observation.state"].append([float(ep + 0.1), float(step + 0.1)])

    table = pa_mod.table(
        {
            "episode_index": pa_mod.array(rows["episode_index"], type=pa_mod.int64()),
            "frame_index": pa_mod.array(rows["frame_index"], type=pa_mod.int64()),
            "timestamp": pa_mod.array(rows["timestamp"], type=pa_mod.float64()),
            "action": pa_mod.array(rows["action"], type=pa_mod.list_(pa_mod.float32())),
            "observation.state": pa_mod.array(
                rows["observation.state"], type=pa_mod.list_(pa_mod.float32())
            ),
        }
    )
    pq_mod.write_table(table, data_dir / "train-00000-of-00001.parquet")

    info = {
        "total_episodes": n_episodes,
        "total_frames": n_episodes * steps_per_ep,
        "fps": 50,
        "features": {
            "action": {"dtype": "float32", "shape": [2]},
            "observation.state": {"dtype": "float32", "shape": [2]},
            "episode_index": {"dtype": "int64"},
            "frame_index": {"dtype": "int64"},
            "timestamp": {"dtype": "float64"},
        },
        "splits": {"train": f"0:{n_episodes * steps_per_ep}"},
    }
    (meta_dir / "info.json").write_text(json.dumps(info, indent=2))

    episodes_lines = [
        json.dumps({"episode_index": ep, "length": steps_per_ep}) for ep in range(n_episodes)
    ]
    (meta_dir / "episodes.jsonl").write_text("\n".join(episodes_lines) + "\n")
    (meta_dir / "tasks.jsonl").write_text(json.dumps({"task_index": 0, "task": "pick"}) + "\n")

    return ds_dir


# ── LeRobot v2 export ─────────────────────────────────────────────────────────


class TestExportLeRobotV2:
    def test_basic_export_creates_output(self, tmp_path):
        pytest.importorskip("pyarrow")
        from calibra.curation.export import export_dataset

        src = _make_lerobot_v2_dir(tmp_path, n_episodes=5)
        result = _make_result(keep_ids=["0", "2", "4"], n_original=5)

        out = tmp_path / "coreset"
        exported = export_dataset(result, str(src), out)

        assert exported.exists()
        assert (exported / "meta" / "info.json").exists()
        assert list((exported / "data").rglob("*.parquet"))

    def test_row_count_matches_kept_episodes(self, tmp_path):
        pytest.importorskip("pyarrow")
        import pyarrow.parquet as pq

        from calibra.curation.export import export_dataset

        src = _make_lerobot_v2_dir(tmp_path, n_episodes=5, steps_per_ep=10)
        keep_ids = ["1", "3"]
        result = _make_result(keep_ids=keep_ids, n_original=5)

        out = tmp_path / "coreset"
        exported = export_dataset(result, str(src), out)

        parquet_files = list((exported / "data").rglob("*.parquet"))
        table = pq.read_table(parquet_files[0])
        assert len(table) == len(keep_ids) * 10  # 2 episodes × 10 steps

    def test_episode_index_remapped_to_zero_based(self, tmp_path):
        pytest.importorskip("pyarrow")
        import pyarrow.parquet as pq

        from calibra.curation.export import export_dataset

        src = _make_lerobot_v2_dir(tmp_path, n_episodes=5)
        result = _make_result(keep_ids=["2", "4"], n_original=5)

        out = tmp_path / "coreset"
        exported = export_dataset(result, str(src), out)

        parquet_files = list((exported / "data").rglob("*.parquet"))
        table = pq.read_table(parquet_files[0])
        ep_indices = sorted(set(table.column("episode_index").to_pylist()))
        assert ep_indices == [0, 1]  # remapped, not original [2, 4]

    def test_info_json_updated(self, tmp_path):
        pytest.importorskip("pyarrow")
        from calibra.curation.export import export_dataset

        src = _make_lerobot_v2_dir(tmp_path, n_episodes=6, steps_per_ep=8)
        result = _make_result(keep_ids=["0", "3", "5"], n_original=6)

        out = tmp_path / "coreset"
        export_dataset(result, str(src), out)

        info = json.loads((out / "meta" / "info.json").read_text())
        assert info["total_episodes"] == 3
        assert info["total_frames"] == 3 * 8

    def test_episodes_jsonl_filtered_and_reindexed(self, tmp_path):
        pytest.importorskip("pyarrow")
        from calibra.curation.export import export_dataset

        src = _make_lerobot_v2_dir(tmp_path, n_episodes=5)
        result = _make_result(keep_ids=["1", "4"], n_original=5)

        out = tmp_path / "coreset"
        export_dataset(result, str(src), out)

        lines = (out / "meta" / "episodes.jsonl").read_text().strip().splitlines()
        assert len(lines) == 2
        indices = [json.loads(line)["episode_index"] for line in lines]
        assert sorted(indices) == [0, 1]

    def test_tasks_jsonl_copied(self, tmp_path):
        pytest.importorskip("pyarrow")
        from calibra.curation.export import export_dataset

        src = _make_lerobot_v2_dir(tmp_path, n_episodes=3)
        result = _make_result(keep_ids=["0", "1"], n_original=3)

        out = tmp_path / "coreset"
        export_dataset(result, str(src), out)

        assert (out / "meta" / "tasks.jsonl").exists()


def _write_frames(pq_mod, pa_mod, path: Path, episodes: list[int], steps_per_ep: int) -> None:
    eps = [ep for ep in episodes for _ in range(steps_per_ep)]
    path.parent.mkdir(parents=True, exist_ok=True)
    pq_mod.write_table(
        pa_mod.table(
            {
                "episode_index": pa_mod.array(eps, type=pa_mod.int64()),
                "frame_index": pa_mod.array(
                    [s for _ in episodes for s in range(steps_per_ep)], type=pa_mod.int64()
                ),
                "index": pa_mod.array(
                    [ep * steps_per_ep + s for ep in episodes for s in range(steps_per_ep)],
                    type=pa_mod.int64(),
                ),
                "action": pa_mod.array(
                    [[float(ep)] for ep in eps], type=pa_mod.list_(pa_mod.float32())
                ),
            }
        ),
        path,
    )


class TestExportLeRobotV3:
    """LeRobot v3: concatenated data/video files indexed by meta/episodes/*.parquet."""

    def _make(self, tmp_path: Path, n_episodes: int = 5, steps_per_ep: int = 4) -> Path:
        pa_mod = pytest.importorskip("pyarrow")
        import pyarrow.parquet as pq_mod

        ds = tmp_path / "v3"
        # Episodes 0-2 in data file 0 / video file 0, the rest in file 1.
        split = 3
        _write_frames(
            pq_mod, pa_mod, ds / "data/chunk-000/file-000.parquet", list(range(split)), steps_per_ep
        )
        _write_frames(
            pq_mod,
            pa_mod,
            ds / "data/chunk-000/file-001.parquet",
            list(range(split, n_episodes)),
            steps_per_ep,
        )
        for f in (0, 1):
            video = ds / f"videos/observation.image/chunk-000/file-{f:03d}.mp4"
            video.parent.mkdir(parents=True, exist_ok=True)
            video.write_bytes(b"mp4-%d" % f)

        files = [0 if ep < split else 1 for ep in range(n_episodes)]
        starts = [
            (ep if ep < split else ep - split) * steps_per_ep / 10 for ep in range(n_episodes)
        ]
        episodes = pa_mod.table(
            {
                "episode_index": list(range(n_episodes)),
                "data/chunk_index": [0] * n_episodes,
                "data/file_index": files,
                "dataset_from_index": [ep * steps_per_ep for ep in range(n_episodes)],
                "dataset_to_index": [(ep + 1) * steps_per_ep for ep in range(n_episodes)],
                "videos/observation.image/chunk_index": [0] * n_episodes,
                "videos/observation.image/file_index": files,
                "videos/observation.image/from_timestamp": starts,
                "videos/observation.image/to_timestamp": [s + steps_per_ep / 10 for s in starts],
                "length": [steps_per_ep] * n_episodes,
            }
        )
        (ds / "meta/episodes/chunk-000").mkdir(parents=True)
        pq_mod.write_table(episodes, ds / "meta/episodes/chunk-000/file-000.parquet")
        pq_mod.write_table(pa_mod.table({"task_index": [0]}), ds / "meta/tasks.parquet")
        info = {
            "codebase_version": "v3.0",
            "total_episodes": n_episodes,
            "total_frames": n_episodes * steps_per_ep,
            "fps": 10,
            "splits": {"train": f"0:{n_episodes}"},
            "data_path": "data/chunk-{chunk_index:03d}/file-{file_index:03d}.parquet",
            "video_path": "videos/{video_key}/chunk-{chunk_index:03d}/file-{file_index:03d}.mp4",
            "features": {"observation.image": {"dtype": "video"}, "action": {"dtype": "float32"}},
        }
        (ds / "meta/info.json").write_text(json.dumps(info))
        return ds

    def test_layout_and_episode_index(self, tmp_path):
        import pyarrow.parquet as pq

        from calibra.curation.export import export_dataset

        src = self._make(tmp_path)
        out = export_dataset(_make_result(["1", "4"], n_original=5), str(src), tmp_path / "out")

        data = pq.read_table(out / "data/chunk-000/file-000.parquet")
        assert data.column("episode_index").to_pylist() == [0] * 4 + [1] * 4
        assert data.column("index").to_pylist() == list(range(8))
        assert data.column("action").to_pylist()[-1] == [4.0]

        eps = pq.read_table(out / "meta/episodes/chunk-000/file-000.parquet").to_pylist()
        assert [e["episode_index"] for e in eps] == [0, 1]
        assert [(e["dataset_from_index"], e["dataset_to_index"]) for e in eps] == [(0, 4), (4, 8)]
        assert all(e["data/file_index"] == 0 for e in eps)
        # Video references are untouched and both referenced files are copied.
        assert [e["videos/observation.image/file_index"] for e in eps] == [0, 1]
        assert eps[1]["videos/observation.image/from_timestamp"] == pytest.approx(0.4)
        for f in (0, 1):
            assert (out / f"videos/observation.image/chunk-000/file-{f:03d}.mp4").exists()
        assert (out / "meta/tasks.parquet").exists()

        info = json.loads((out / "meta/info.json").read_text())
        assert (info["total_episodes"], info["total_frames"], info["splits"]) == (
            2,
            8,
            {"train": "0:2"},
        )

    def test_unreferenced_video_files_not_copied(self, tmp_path):
        from calibra.curation.export import export_dataset

        src = self._make(tmp_path)
        out = export_dataset(_make_result(["0", "2"], n_original=5), str(src), tmp_path / "out")
        assert (out / "videos/observation.image/chunk-000/file-000.mp4").exists()
        assert not (out / "videos/observation.image/chunk-000/file-001.mp4").exists()


class TestExportLeRobotV2Layout:
    """LeRobot v2.x with data_path/video_path templates: one file per episode."""

    def test_per_episode_files_renumbered(self, tmp_path):
        pa_mod = pytest.importorskip("pyarrow")
        import pyarrow.parquet as pq_mod

        from calibra.curation.export import export_dataset

        ds = tmp_path / "v2"
        for ep in range(4):
            _write_frames(pq_mod, pa_mod, ds / f"data/chunk-000/episode_{ep:06d}.parquet", [ep], 3)
            video = ds / f"videos/chunk-000/observation.image/episode_{ep:06d}.mp4"
            video.parent.mkdir(parents=True, exist_ok=True)
            video.write_bytes(b"ep%d" % ep)
        (ds / "meta").mkdir()
        (ds / "meta/episodes.jsonl").write_text(
            "".join(json.dumps({"episode_index": ep, "length": 3}) + "\n" for ep in range(4))
        )
        (ds / "meta/tasks.jsonl").write_text(json.dumps({"task_index": 0, "task": "pick"}) + "\n")
        info = {
            "codebase_version": "v2.1",
            "total_episodes": 4,
            "total_frames": 12,
            "total_videos": 4,
            "total_chunks": 1,
            "chunks_size": 1000,
            "splits": {"train": "0:4"},
            "data_path": "data/chunk-{episode_chunk:03d}/episode_{episode_index:06d}.parquet",
            "video_path": "videos/chunk-{episode_chunk:03d}/{video_key}/episode_{episode_index:06d}.mp4",
            "features": {"observation.image": {"dtype": "video"}},
        }
        (ds / "meta/info.json").write_text(json.dumps(info))

        out = export_dataset(_make_result(["1", "3"], n_original=4), str(ds), tmp_path / "out")

        assert sorted(p.name for p in (out / "data/chunk-000").iterdir()) == [
            "episode_000000.parquet",
            "episode_000001.parquet",
        ]
        second = pq_mod.read_table(out / "data/chunk-000/episode_000001.parquet")
        assert set(second.column("episode_index").to_pylist()) == {1}
        assert second.column("index").to_pylist() == [3, 4, 5]
        videos = out / "videos/chunk-000/observation.image"
        assert (videos / "episode_000001.mp4").read_bytes() == b"ep3"
        info_out = json.loads((out / "meta/info.json").read_text())
        assert (info_out["total_episodes"], info_out["total_videos"], info_out["splits"]) == (
            2,
            2,
            {"train": "0:2"},
        )


class TestExportHdf5:
    def test_robomimic_layout_filters_demos_and_mask(self, tmp_path):
        h5py = pytest.importorskip("h5py")
        import numpy as np

        from calibra.curation.export import export_dataset

        src = tmp_path / "demos.hdf5"
        with h5py.File(src, "w") as f:
            data = f.create_group("data")
            data.attrs["total"] = 12
            data.attrs["env_args"] = "{}"
            for i in range(12):
                f.create_dataset(
                    f"data/demo_{i}/actions", data=np.full((3, 2), i, dtype=np.float32)
                )
            f.create_dataset(
                "mask/train", data=np.array([f"demo_{i}" for i in range(10)], dtype="S")
            )

        result = _make_result(["demo_2", "demo_10", "demo_11"], n_original=12)
        out = export_dataset(result, str(src), tmp_path / "out")

        with h5py.File(out / "demos.hdf5", "r") as f:
            assert sorted(f["data"]) == ["demo_0", "demo_1", "demo_2"]
            # Numeric order: demo_2 < demo_10 < demo_11.
            assert [f[f"data/demo_{i}/actions"][0, 0] for i in range(3)] == [2, 10, 11]
            assert f["data"].attrs["total"] == 3
            assert f["data"].attrs["env_args"] == "{}"
            assert list(f["mask/train"][()]) == [b"demo_0"]


# ── Hub ID guard ──────────────────────────────────────────────────────────────


class TestHubIdGuard:
    def test_hub_id_raises_valueerror(self, tmp_path):
        from calibra.curation.export import export_dataset

        result = _make_result(keep_ids=["0"], n_original=5)
        with pytest.raises(ValueError, match="Hub IDs are not supported"):
            export_dataset(result, "lerobot/pusht", tmp_path / "out")

    def test_hf_uri_raises_valueerror(self, tmp_path):
        from calibra.curation.export import export_dataset

        result = _make_result(keep_ids=["0"], n_original=5)
        with pytest.raises(ValueError, match="Hub IDs are not supported"):
            export_dataset(result, "hf://lerobot/pusht", tmp_path / "out")


# ── unknown format ────────────────────────────────────────────────────────────


class TestUnknownFormat:
    def test_unknown_path_raises_valueerror(self, tmp_path):
        from calibra.curation.export import export_dataset

        result = _make_result(keep_ids=["0"], n_original=5)
        unknown = tmp_path / "some_random_dir"
        unknown.mkdir()
        with pytest.raises(ValueError, match="Cannot determine format"):
            export_dataset(result, str(unknown), tmp_path / "out")
