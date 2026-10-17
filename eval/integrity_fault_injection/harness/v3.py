"""
Copy-on-write access to a local LeRobot v3.0 dataset.

A working copy has real copies of ``meta/`` and symlinks for every data and
video file, so building one is cheap and the source dataset is never written:
every write unlinks the target first. Episodes whose video a fault changes are
*relocated*: their segment is decoded, transformed and re-encoded into a new
per-episode mp4, and ``meta/episodes`` is pointed at it (a valid v3 layout).
Other episodes keep pointing at the untouched source files.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Callable, Optional

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

# LeRobot's encoder settings (libsvtav1, GOP 2, crf 30); preset 12 for speed.
ENCODE_ARGS = ["-c:v", "libsvtav1", "-g", "2", "-crf", "30", "-preset", "12", "-pix_fmt", "yuv420p"]


def _read(path: Path) -> pa.Table:
    # ParquetFile avoids pyarrow.dataset, which imports pandas.
    return pq.ParquetFile(str(path)).read()


def _write(table: pa.Table, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink() or path.exists():
        path.unlink()
    pq.write_table(table, str(path))


class V3Dataset:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.info = json.loads((self.root / "meta" / "info.json").read_text())
        if not str(self.info.get("codebase_version", "")).startswith("v3"):
            raise ValueError(f"{root} is not LeRobot v3")
        self.fps = float(self.info["fps"])
        self.video_keys = [k for k, v in self.info["features"].items() if v.get("dtype") == "video"]

    # ── copies ────────────────────────────────────────────────────────────────

    @classmethod
    def working_copy(cls, src: Path, dst: Path) -> "V3Dataset":
        src, dst = Path(src).resolve(), Path(dst)
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src / "meta", dst / "meta")
        for sub in ("data", "videos"):
            for f in sorted((src / sub).rglob("*")):
                if f.is_file():
                    link = dst / f.relative_to(src)
                    link.parent.mkdir(parents=True, exist_ok=True)
                    link.symlink_to(f)
        return cls(dst)

    # ── metadata ─────────────────────────────────────────────────────────────

    def save_info(self) -> None:
        (self.root / "meta" / "info.json").write_text(json.dumps(self.info, indent=4))

    def episode_files(self) -> list[Path]:
        return sorted((self.root / "meta" / "episodes").rglob("*.parquet"))

    def episodes(self) -> list[dict]:
        rows = []
        for f in self.episode_files():
            rows.extend(_read(f).select(self._episode_columns(f)).to_pylist())
        return sorted(rows, key=lambda r: int(r["episode_index"]))

    @staticmethod
    def _episode_columns(f: Path) -> list[str]:
        # The per-episode stats columns are large and never needed here.
        return [c for c in pq.read_schema(str(f)).names if not c.startswith("stats/")]

    def update_episode(self, episode_index: int, **fields) -> None:
        """Set columns of one row in meta/episodes, in whichever file holds it."""
        for f in self.episode_files():
            table = _read(f)
            idx = table.column("episode_index").to_pylist()
            if episode_index not in idx:
                continue
            row = idx.index(episode_index)
            for name, value in fields.items():
                col = table.column(name).to_pylist()
                col[row] = value
                table = table.set_column(
                    table.schema.get_field_index(name),
                    name,
                    pa.array(col, table.schema.field(name).type),
                )
            _write(table, f)
            return
        raise KeyError(episode_index)

    def append_episode_row(self, row: dict) -> None:
        """Append one meta/episodes row as a new file (v3 allows several)."""
        template = _read(self.episode_files()[0])
        full = {name: row.get(name) for name in template.schema.names}
        table = pa.Table.from_pylist([full], schema=template.schema)
        _write(
            table,
            self.root
            / "meta"
            / "episodes"
            / "chunk-000"
            / f"file-{self._next_index('meta/episodes'):03d}.parquet",
        )

    def _next_index(self, sub: str) -> int:
        files = list((self.root / sub).rglob("file-*.*"))
        return 1 + max((int(f.stem.split("-")[1]) for f in files), default=-1)

    # ── data ─────────────────────────────────────────────────────────────────

    def data_files(self) -> list[Path]:
        return sorted((self.root / "data").rglob("*.parquet"))

    def read_data(self) -> pa.Table:
        return pa.concat_tables([_read(f) for f in self.data_files()])

    def replace_data(self, table: pa.Table) -> None:
        """Rewrite all data as one file, sorted by (episode_index, frame_index)."""
        for f in self.data_files():
            f.unlink()
        order = np.lexsort(
            (table.column("frame_index").to_numpy(), table.column("episode_index").to_numpy())
        )
        table = table.take(pa.array(order))
        table = table.set_column(
            table.schema.get_field_index("index"),
            "index",
            pa.array(np.arange(len(table)), pa.int64()),
        )
        _write(table, self.root / "data" / "chunk-000" / "file-000.parquet")
        self._sync_ranges(table)

    def append_data(self, table: pa.Table) -> Path:
        path = self.root / "data" / "chunk-000" / f"file-{self._next_index('data'):03d}.parquet"
        _write(table, path)
        return path

    def _sync_ranges(self, table: pa.Table) -> None:
        """Make meta/episodes lengths and dataset ranges match the data."""
        ep = table.column("episode_index").to_numpy()
        for row in self.episodes():
            e = int(row["episode_index"])
            where = np.flatnonzero(ep == e)
            if len(where):
                self.update_episode(
                    e,
                    length=int(len(where)),
                    dataset_from_index=int(where[0]),
                    dataset_to_index=int(where[-1] + 1),
                    **{"data/chunk_index": 0, "data/file_index": 0},
                )
        self.info["total_frames"] = int(len(table))
        self.save_info()

    # ── video ────────────────────────────────────────────────────────────────

    def video_path(self, key: str, chunk: int, file: int) -> Path:
        return self.root / self.info["video_path"].format(
            video_key=key, chunk_index=chunk, file_index=file
        )

    def segment(self, row: dict, key: str) -> tuple[Path, int, int]:
        """(file, first frame, n frames) of an episode's video, as Calibra locates it."""
        path = self.video_path(
            key, row[f"videos/{key}/chunk_index"], row[f"videos/{key}/file_index"]
        )
        first = round(row[f"videos/{key}/from_timestamp"] * self.fps)
        n = round(row[f"videos/{key}/to_timestamp"] * self.fps) - first
        return path, first, n

    def _shape(self, key: str) -> tuple[int, int]:
        h, w, _ = self.info["features"][key]["shape"]
        return int(h), int(w)

    def decode_segment(self, row: dict, key: str) -> np.ndarray:
        path, first, n = self.segment(row, key)
        return decode(path, self._shape(key), first=first, n=n, fps=self.fps)

    def relocate(
        self,
        episode_index: int,
        key: str,
        transform: Callable[[np.ndarray], np.ndarray] = lambda f: f,
        to_timestamp: Optional[float] = None,
        faststart: bool = False,
    ) -> tuple[Path, np.ndarray]:
        """
        Re-encode one episode's video for one camera into its own file after
        `transform` (frames -> frames), and point meta/episodes at it. The span
        written to meta is the transformed length unless `to_timestamp` is given
        (a recorder whose metadata disagrees with its file). Returns the new
        file and the transformed frames.
        """
        row = next(r for r in self.episodes() if int(r["episode_index"]) == episode_index)
        frames = transform(self.decode_segment(row, key))
        file_index = self._next_index(f"videos/{key}")
        out = self.video_path(key, 0, file_index)
        encode(frames, out, self.fps, faststart=faststart)
        self.update_episode(
            episode_index,
            **{
                f"videos/{key}/chunk_index": 0,
                f"videos/{key}/file_index": file_index,
                f"videos/{key}/from_timestamp": 0.0,
                f"videos/{key}/to_timestamp": float(
                    len(frames) / self.fps if to_timestamp is None else to_timestamp
                ),
            },
        )
        return out, frames


def decode(
    path: Path, shape: tuple[int, int], first: int = 0, n: Optional[int] = None, fps: float = 0.0
) -> np.ndarray:
    """Decode frames [first, first + n) as uint8 RGB, frame-accurate."""
    h, w = shape
    cmd = ["ffmpeg", "-nostdin", "-v", "error"]
    if first and fps:
        cmd += ["-ss", f"{first / fps:.6f}"]
    cmd += ["-i", str(path)]
    if n is not None:
        cmd += ["-frames:v", str(n)]
    cmd += ["-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    raw = subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(-1, h, w, 3)


def encode(frames: np.ndarray, out: Path, fps: float, faststart: bool = False) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.is_symlink() or out.exists():
        out.unlink()
    n, h, w, _ = frames.shape
    cmd = [
        "ffmpeg",
        "-nostdin",
        "-v",
        "error",
        "-y",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "rgb24",
        "-s",
        f"{w}x{h}",
        "-r",
        f"{fps:g}",
        "-i",
        "-",
        *ENCODE_ARGS,
    ]
    if faststart:
        cmd += ["-movflags", "+faststart"]
    subprocess.run(
        cmd + [str(out)],
        input=np.ascontiguousarray(frames).tobytes(),
        capture_output=True,
        check=True,
    )
