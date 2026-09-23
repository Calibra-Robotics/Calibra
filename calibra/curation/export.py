"""
calibra.curation.export — Materialise a pruned coreset as a ready-to-train dataset.

After ``calibra prune`` selects a coreset index (``coreset_index.json``), this
module writes the *actual* dataset files so training scripts can consume the
pruned data directly without any glue code.

Supported source formats
------------------------
* **LeRobot v3** (concatenated Parquet/mp4 files + ``meta/episodes/*.parquet``)
  — data re-indexed into one file, episode index rewritten, the video files the
  kept episodes point into copied unchanged (their timestamps stay valid).
* **LeRobot v2** (one Parquet/mp4 per episode + ``meta/*.jsonl``) — per-episode
  files re-numbered following ``info.json``'s ``data_path`` / ``video_path``.
* **HDF5** (Isaac Lab / Robomimic) — copies kept episode groups into a new file.
* **LeRobot v1** (HuggingFace Datasets on disk) — filters and saves with
  ``save_to_disk``.

Hub IDs (``lerobot/pusht``, ``hf://…``) are *not* directly supported — download
the dataset locally first (``hf download``), then run prune + export.

All formats re-number episode IDs from 0 to N-1 so the output is a self-contained,
valid dataset that training scripts (LeRobot ``train.py``, etc.) can consume
without modification. ``meta/stats.json`` is copied as-is (full-dataset stats).
"""

from __future__ import annotations

import json
import math
import shutil
from collections import Counter
from pathlib import Path
from typing import Callable, Optional

from calibra.pruning import PruningResult


def export_dataset(
    result: PruningResult,
    source_path: str,
    out_dir: str | Path,
    *,
    log: Optional[Callable[[str], None]] = None,
) -> Path:
    """
    Materialise the coreset identified by *result* as a dataset directory.

    Parameters
    ----------
    result      : output of ``CoresetSelector.select()``
    source_path : path of the original **local** dataset (Hub IDs not supported)
    out_dir     : directory to write the exported dataset into
    log         : optional callable(str) for progress messages

    Returns
    -------
    Path to the written dataset directory.

    Raises
    ------
    ValueError  : if source_path is a Hub ID or the format cannot be determined.
    RuntimeError: if required dependencies (pyarrow, h5py, datasets) are missing.
    """
    if log is None:
        log = lambda _: None  # noqa: E731

    from calibra.ingestion.adapters.lerobot import _is_hub_id, _strip_hf_prefix

    if _is_hub_id(source_path):
        raise ValueError(
            f"Hub IDs are not supported by --export-dataset. "
            f"Download '{source_path}' locally first:\n"
            f"  hf download {source_path} --repo-type dataset --local-dir ./datasets/{source_path.split('/')[-1]}\n"
            f"Then re-run: calibra prune ./datasets/{source_path.split('/')[-1]} "
            f"--keep ... --export-dataset <out>"
        )

    bare = _strip_hf_prefix(source_path)
    p = Path(bare)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    if (p / "meta" / "info.json").exists():
        return _export_lerobot_v2(p, out, result, log)

    if (p / "metadata.json").exists() or (p / "dataset_dict.json").exists():
        return _export_lerobot_v1(p, out, result, log)

    if p.suffix in (".h5", ".hdf5"):
        return _export_hdf5(p, out, result, log)

    h5_files = list(p.glob("**/*.h5")) + list(p.glob("**/*.hdf5"))
    if h5_files:
        return _export_hdf5(p, out, result, log)

    raise ValueError(
        f"Cannot determine format for '{source_path}'.\n"
        "Supported: LeRobot v2/v3 (local Parquet), LeRobot v1 (HF Datasets on disk), HDF5."
    )


# ── LeRobot v2 / v3 ───────────────────────────────────────────────────────────


def _export_lerobot_v2(
    src: Path,
    out: Path,
    result: PruningResult,
    log: Callable[[str], None],
) -> Path:
    """
    Export a Parquet-backed LeRobot dataset (v2 or v3) filtered to the coreset.

    Steps
    -----
    1. Read all Parquet shards with pyarrow and filter rows to ``keep_episode_ids``.
    2. Remap ``episode_index`` to 0..N-1 and the global ``index`` to 0..frames-1.
    3. Write data (and copy videos) in the layout ``meta/info.json`` declares.
    4. Write the matching episode metadata, tasks, stats and updated info.json.
    """
    try:
        import pyarrow as pa
        import pyarrow.compute as pc
        import pyarrow.parquet as pq
    except ImportError:
        raise RuntimeError(
            "pyarrow is required for LeRobot export.\n"
            "Install it with: pip install 'calibra-robotics[lerobot]'"
        ) from None

    keep_int: set[int] = {int(eid) for eid in result.keep_episode_ids}
    # Mapping: original episode_index → new 0-based index (ascending order).
    ep_remap: dict[int, int] = {old: new for new, old in enumerate(sorted(keep_int))}

    # ── read and filter Parquet ───────────────────────────────────────────────
    parquet_files = sorted(src.glob("data/**/*.parquet"))
    if not parquet_files:
        parquet_files = sorted(src.glob("*.parquet"))
    if not parquet_files:
        raise ValueError(f"No Parquet files found in {src}")

    log(f"  Reading {len(parquet_files)} Parquet shard(s) …")

    keep_arr = pa.array(sorted(keep_int), type=pa.int64())
    tables: list[pa.Table] = []
    for pf in parquet_files:
        tbl = pq.read_table(pf)
        filtered = tbl.filter(pc.is_in(tbl.column("episode_index").cast(pa.int64()), keep_arr))
        if len(filtered) > 0:
            tables.append(filtered)

    if not tables:
        raise ValueError("No rows remain after filtering; coreset is empty.")

    combined = pa.concat_tables(tables)
    log(f"  {len(combined)} rows kept")

    # ── remap episode_index / index ───────────────────────────────────────────
    new_eps = [ep_remap[v] for v in combined.column("episode_index").to_pylist()]
    combined = _set_column(combined, "episode_index", pa.array(new_eps, type=pa.int64()))
    combined = combined.take(pc.sort_indices(combined, sort_keys=[("episode_index", "ascending")]))
    if "index" in combined.schema.names:
        combined = _set_column(combined, "index", pa.array(range(len(combined)), type=pa.int64()))
    frames_per_ep = Counter(combined.column("episode_index").to_pylist())
    n_episodes = len(frames_per_ep)

    meta_src = src / "meta"
    meta_out = out / "meta"
    meta_out.mkdir(parents=True, exist_ok=True)
    info = json.loads((meta_src / "info.json").read_text(encoding="utf-8"))
    video_keys = [k for k, f in info.get("features", {}).items() if f.get("dtype") == "video"]

    if str(info.get("codebase_version", "")).startswith("v3"):
        _write_v3(src, out, info, combined, ep_remap, frames_per_ep, video_keys, log)
    elif "{episode_index" in info.get("data_path", ""):
        _write_v2(src, out, info, combined, ep_remap, video_keys, log)
    else:
        # No layout template: legacy single-shard output.
        data_out = out / "data" / "chunk-000"
        data_out.mkdir(parents=True, exist_ok=True)
        out_parquet = data_out / "train-00000-of-00001.parquet"
        pq.write_table(combined, out_parquet)
        log(f"  Wrote {out_parquet}")
        _filter_jsonl(meta_src / "episodes.jsonl", meta_out / "episodes.jsonl", ep_remap)
        _copy_if_exists(meta_src / "tasks.jsonl", meta_out / "tasks.jsonl")

    info["total_episodes"] = n_episodes
    info["total_frames"] = len(combined)
    if "splits" in info:
        # LeRobot splits are episode ranges, not frame ranges.
        info["splits"] = {"train": f"0:{n_episodes}"}
    (meta_out / "info.json").write_text(json.dumps(info, indent=4), encoding="utf-8")
    _copy_if_exists(meta_src / "stats.json", meta_out / "stats.json")

    log(f"  Meta written to {meta_out}")
    return out


def _write_v2(src, out, info, combined, ep_remap, video_keys, log) -> None:
    """LeRobot v2.x: one Parquet (and one mp4 per camera) per episode."""
    import pyarrow.compute as pc
    import pyarrow.parquet as pq

    chunks_size = int(info.get("chunks_size", 1000))
    ep_col = combined.column("episode_index")
    for new in sorted(ep_remap.values()):
        rel = info["data_path"].format(episode_chunk=new // chunks_size, episode_index=new)
        dst = out / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(combined.filter(pc.equal(ep_col, new)), dst)
    log(f"  Wrote {len(ep_remap)} episode Parquet file(s)")

    n_videos = 0
    for key in video_keys:
        for old, new in ep_remap.items():
            src_rel = info["video_path"].format(
                episode_chunk=old // chunks_size, video_key=key, episode_index=old
            )
            dst_rel = info["video_path"].format(
                episode_chunk=new // chunks_size, video_key=key, episode_index=new
            )
            n_videos += _copy_if_exists(src / src_rel, out / dst_rel)
    if video_keys:
        log(f"  Copied {n_videos} video file(s)")

    meta_src, meta_out = src / "meta", out / "meta"
    for name in ("episodes.jsonl", "episodes_stats.jsonl"):
        _filter_jsonl(meta_src / name, meta_out / name, ep_remap)
    _copy_if_exists(meta_src / "tasks.jsonl", meta_out / "tasks.jsonl")

    info["total_chunks"] = max(1, math.ceil(len(ep_remap) / chunks_size))
    if "total_videos" in info:
        info["total_videos"] = n_videos


def _write_v3(src, out, info, combined, ep_remap, frames_per_ep, video_keys, log) -> None:
    """LeRobot v3.x: concatenated data/video files indexed by meta/episodes/*.parquet."""
    import pyarrow as pa
    import pyarrow.compute as pc
    import pyarrow.parquet as pq

    data_rel = info["data_path"].format(chunk_index=0, file_index=0)
    (out / data_rel).parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(combined, out / data_rel)
    log(f"  Wrote {out / data_rel}")

    # Episode index: keep rows for kept episodes, point them at the new data file.
    ep_files = sorted((src / "meta" / "episodes").glob("**/*.parquet"))
    if not ep_files:
        raise ValueError(f"No meta/episodes/*.parquet found in {src} (LeRobot v3)")
    episodes = pa.concat_tables([pq.read_table(f) for f in ep_files])
    keep_arr = pa.array(sorted(ep_remap), type=pa.int64())
    episodes = episodes.filter(
        pc.is_in(episodes.column("episode_index").cast(pa.int64()), keep_arr)
    )
    episodes = episodes.take(pc.sort_indices(episodes, sort_keys=[("episode_index", "ascending")]))

    new_idx = [ep_remap[v] for v in episodes.column("episode_index").to_pylist()]
    lengths = [frames_per_ep[i] for i in new_idx]
    ends = [sum(lengths[: i + 1]) for i in range(len(lengths))]
    starts = [e - n for e, n in zip(ends, lengths)]
    zeros = [0] * len(new_idx)
    for name, values in (
        ("episode_index", new_idx),
        ("dataset_from_index", starts),
        ("dataset_to_index", ends),
        ("length", lengths),
        ("data/chunk_index", zeros),
        ("data/file_index", zeros),
        ("meta/episodes/chunk_index", zeros),
        ("meta/episodes/file_index", zeros),
    ):
        if name in episodes.schema.names:
            episodes = _set_column(episodes, name, pa.array(values, type=pa.int64()))

    ep_out = out / "meta" / "episodes" / "chunk-000" / "file-000.parquet"
    ep_out.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(episodes, ep_out)

    # Videos are concatenated per file; copying the referenced files unchanged
    # keeps every kept episode's from/to timestamps valid.
    n_videos = 0
    for key in video_keys:
        chunk_col, file_col = f"videos/{key}/chunk_index", f"videos/{key}/file_index"
        if chunk_col not in episodes.schema.names:
            continue
        pairs = set(
            zip(episodes.column(chunk_col).to_pylist(), episodes.column(file_col).to_pylist())
        )
        for chunk, file in sorted(pairs):
            rel = info["video_path"].format(video_key=key, chunk_index=chunk, file_index=file)
            n_videos += _copy_if_exists(src / rel, out / rel)
    if video_keys:
        log(f"  Copied {n_videos} video file(s)")

    _copy_if_exists(src / "meta" / "tasks.parquet", out / "meta" / "tasks.parquet")


def _set_column(table, name: str, values):
    return table.set_column(table.schema.get_field_index(name), name, values)


def _filter_jsonl(src_path: Path, dst_path: Path, ep_remap: dict[int, int]) -> None:
    """Keep lines whose episode_index is kept, re-numbered and sorted."""
    if not src_path.exists():
        return
    kept: list[dict] = []
    with open(src_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            orig_idx = obj.get("episode_index")
            if orig_idx in ep_remap:
                obj["episode_index"] = ep_remap[orig_idx]
                kept.append(obj)
    kept.sort(key=lambda o: o["episode_index"])
    with open(dst_path, "w", encoding="utf-8") as f:
        f.writelines(json.dumps(o) + "\n" for o in kept)


def _copy_if_exists(src: Path, dst: Path) -> int:
    if not src.exists():
        return 0
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return 1


# ── LeRobot v1 (HuggingFace Datasets) ────────────────────────────────────────


def _export_lerobot_v1(
    src: Path,
    out: Path,
    result: PruningResult,
    log: Callable[[str], None],
) -> Path:
    try:
        import datasets as hf_datasets
    except ImportError:
        raise RuntimeError(
            "The 'datasets' package is required for LeRobot v1 export.\n"
            "Install it with: pip install 'calibra-robotics[lerobot]'"
        ) from None

    keep_int: set[int] = {int(eid) for eid in result.keep_episode_ids}
    log(f"  Loading LeRobot v1 dataset from {src} …")
    ds = hf_datasets.load_from_disk(str(src))
    if hasattr(ds, "keys"):
        split_name = next(iter(ds))
        ds = ds[split_name]

    log(f"  Filtering to {len(keep_int)} episodes …")
    ds = ds.filter(lambda row: row["episode_index"] in keep_int)

    # Re-index episode_index 0..N-1.
    sorted_keep = sorted(keep_int)
    ep_remap = {old: new for new, old in enumerate(sorted_keep)}
    ds = ds.map(lambda row: {"episode_index": ep_remap[row["episode_index"]]})

    log(f"  Saving to {out} …")
    ds.save_to_disk(str(out))
    return out


# ── HDF5 ──────────────────────────────────────────────────────────────────────


def _export_hdf5(
    src: Path,
    out: Path,
    result: PruningResult,
    log: Callable[[str], None],
) -> Path:
    try:
        import h5py
    except ImportError:
        raise RuntimeError(
            "h5py is required for HDF5 export.\n"
            "Install it with: pip install 'calibra-robotics[hdf5]'"
        ) from None

    keep_ids: set[str] = set(result.keep_episode_ids)

    # Find the source HDF5 file.
    if src.suffix in (".h5", ".hdf5"):
        src_file = src
        out_file = out / src.name
    else:
        h5_files = sorted(src.glob("**/*.h5")) + sorted(src.glob("**/*.hdf5"))
        if not h5_files:
            raise ValueError(f"No HDF5 files found under {src}")
        src_file = h5_files[0]
        out_file = out / src_file.name

    log(f"  Copying kept episode groups from {src_file} …")
    with h5py.File(src_file, "r") as src_h5, h5py.File(out_file, "w") as dst_h5:
        for key, val in src_h5.attrs.items():
            dst_h5.attrs[key] = val

        # Robomimic / Isaac Lab keep demos under data/demo_N; others at the top level.
        nested = isinstance(src_h5.get("data"), h5py.Group) and any(
            k in src_h5["data"] for k in keep_ids
        )
        if nested:
            src_root = src_h5["data"]
            dst_root = dst_h5.create_group("data")
            for key, val in src_root.attrs.items():
                dst_root.attrs[key] = val
            for key in src_h5.keys():
                if key not in ("data", "mask"):
                    src_h5.copy(key, dst_h5)
        else:
            for key in src_h5.keys():
                if key not in keep_ids and not _is_episode_group(src_h5[key], keep_ids):
                    src_h5.copy(key, dst_h5)
            src_root, dst_root = src_h5, dst_h5

        # Copy kept episode groups, re-numbering from 0.
        renamed: dict[str, str] = {}
        for old_key in sorted(keep_ids, key=_episode_sort_key):
            if old_key in src_root:
                new_idx = len(renamed)
                new_key = str(new_idx) if old_key.isdigit() else f"demo_{new_idx}"
                src_root.copy(old_key, dst_root, name=new_key)
                renamed[old_key] = new_key
            else:
                log(f"  Warning: episode '{old_key}' not found in source HDF5, skipping.")

        if nested:
            if "total" in dst_root.attrs:
                dst_root.attrs["total"] = len(renamed)
            if "total" in dst_h5.attrs:
                dst_h5.attrs["total"] = len(renamed)
            if isinstance(src_h5.get("mask"), h5py.Group):
                remap_hdf5_mask(src_h5["mask"], dst_h5, renamed)

    log(f"  Wrote {out_file}")
    return out


def _episode_sort_key(episode_id: str) -> tuple[int, str]:
    """Sort ``demo_2`` before ``demo_10`` (and ``"2"`` before ``"10"``)."""
    digits = episode_id.rsplit("_", 1)[-1]
    return (int(digits), episode_id) if digits.isdigit() else (-1, episode_id)


def remap_hdf5_mask(src_mask, dst_h5, renamed: dict[str, str]) -> None:
    """Rewrite robomimic ``mask/<split>`` demo-name lists for a filtered file.

    Demos that were dropped are removed from each split and kept demos take their
    new names, so ``mask/train`` never points at a missing or different demo.
    """
    import numpy as np

    dst_mask = dst_h5.create_group("mask")
    for split, ds in src_mask.items():
        names = [n.decode() if isinstance(n, bytes) else str(n) for n in ds[()]]
        kept = [renamed[n] for n in names if n in renamed]
        dst_mask.create_dataset(split, data=np.array(kept, dtype="S"))


def _is_episode_group(obj, episode_ids: set[str]) -> bool:
    """Heuristic: True if obj is an HDF5 group whose name matches an episode ID."""
    try:
        import h5py

        return isinstance(obj, h5py.Group) and obj.name.lstrip("/") in episode_ids
    except Exception:
        return False
