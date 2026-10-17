"""
Run the integrity fault-injection benchmark (PROTOCOL.md).

For each (dataset, variant, rep): build a copy-on-write working copy, inject
the fault with a seed derived from the trial id, run `calibra integrity --json`
as a user would, and append one JSON line with the ground truth and Calibra's
verdict to results/<run>/trials.jsonl.

    python eval/integrity_fault_injection/run.py --datasets h1 --run h1-timing
    python eval/integrity_fault_injection/run.py --datasets h1 --variants freeze. --reps 1

Run from the repository root. Datasets must already be downloaded at the pinned
revision (see README.md).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import tomllib

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from harness import faults  # noqa: E402
from harness.v3 import ENCODE_ARGS, V3Dataset  # noqa: E402

DEFAULT_VIDEO_SAMPLE = 20  # calibra integrity --video-sample default


def load_config() -> dict:
    return tomllib.loads((HERE / "config.toml").read_text())


def check_thresholds(cfg: dict) -> None:
    """Refuse to run if the documented thresholds differ from the Calibra source."""
    import calibra
    from calibra import video_integrity as vi
    from calibra.analyzers import camera_freeze as cf
    from calibra.analyzers import duplicate_frame as df
    from calibra.analyzers import temporal as tp

    t = cfg["thresholds"]
    source = {
        ("duplicate_frame_rate", "warning"): df._DUPLICATE_WARNING,
        ("duplicate_frame_rate", "critical"): df._DUPLICATE_CRITICAL,
        ("camera_freeze_events", "warning"): cf._FREEZE_WARNING_FRACTION,
        ("camera_freeze_events", "critical"): cf._FREEZE_CRITICAL_FRACTION,
        ("camera_freeze_events", "min_run"): cf._MIN_FREEZE_RUN,
        ("timestamp_dropout_rate", "warning"): tp._DROPOUT_WARNING,
        ("timestamp_dropout_rate", "critical"): tp._DROPOUT_CRITICAL,
        ("timestamp_dropout_rate", "gap_k"): tp._DROPOUT_K,
        ("timestamp_jitter_cv", "warning"): tp._JITTER_CV_WARNING,
        ("timestamp_jitter_cv", "critical"): tp._JITTER_CV_CRITICAL,
        ("video_frame_mismatch_rate", "frame_tolerance"): vi._FRAME_TOLERANCE,
        ("video_fps_mismatch_rate", "rel_tolerance"): vi._FPS_REL_TOLERANCE,
    }
    bad = [
        f"{m}.{k}: config {t[m][k]} != source {v}" for (m, k), v in source.items() if t[m][k] != v
    ]
    if calibra.__version__ != cfg["calibra_version"]:
        bad.append(f"calibra {calibra.__version__} != config {cfg['calibra_version']}")
    if bad:
        sys.exit("threshold/version check failed:\n  " + "\n  ".join(bad))
    faults.THRESHOLDS.update(t)


def dataset_revision(root: Path) -> str | None:
    """Commit the local copy was downloaded at, from huggingface_hub's download cache."""
    meta = root / ".cache" / "huggingface" / "download" / "meta" / "info.json.metadata"
    if not meta.exists():
        return None
    return meta.read_text().splitlines()[0].strip()


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def trial_seed(dataset: str, variant: str, rep: int) -> int:
    return int(hashlib.sha256(f"{dataset}|{variant}|{rep}".encode()).hexdigest()[:8], 16)


def git_state() -> dict:
    def git(*a):
        return subprocess.run(["git", *a], capture_output=True, text=True, cwd=HERE).stdout.strip()

    return {
        "commit": git("rev-parse", "HEAD"),
        "dirty": bool(git("status", "--porcelain", "--", "calibra")),
    }


def environment() -> dict:
    import cv2
    import pyarrow

    ffmpeg = subprocess.run(
        ["ffmpeg", "-version"], capture_output=True, text=True
    ).stdout.splitlines()[0]
    return {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "numpy": np.__version__,
        "pyarrow": pyarrow.__version__,
        "opencv": cv2.__version__,
        "ffmpeg": ffmpeg,
        "encode_args": ENCODE_ARGS,
    }


# ── one calibra run ─────────────────────────────────────────────────────────


def run_integrity(root: Path, video_sample: int | None) -> dict:
    argv = [sys.executable, "-m", "calibra", "integrity", str(root), "--json"]
    if video_sample is not None:
        argv += ["--decode-video", "--video-sample", str(video_sample)]
    t0 = time.monotonic()
    proc = subprocess.run(argv, stdin=subprocess.DEVNULL, capture_output=True, text=True)
    seconds = time.monotonic() - t0
    result = {"argv": argv[2:], "seconds": round(seconds, 2), "exit_code": proc.returncode}
    try:
        out = json.loads(proc.stdout)
    except json.JSONDecodeError:
        result["error"] = proc.stderr[-2000:]
        return result
    levels = {}
    for key, level in (("critical", "CRITICAL"), ("warnings", "WARNING"), ("passed", "OK")):
        for f in out[key]:
            levels[f["metric"]] = level
            result.setdefault("observed", {})[f["metric"]] = f["observed_value"]
    for item in out["not_evaluated"]:
        levels.setdefault(item["check"], "NOT_EVALUATED")
    result["levels"] = levels
    result["video_affected_episodes"] = out.get("video_affected_episodes", {})
    return result


def duplicate_attribution(root: Path) -> dict:
    """Episode-level duplicate verdicts: {copy episode: original}, same digest Calibra uses."""
    from calibra.analyzers.task_structure import _episode_digest
    from calibra.ingestion.registry import load

    first, copies = {}, {}
    for ep in load(str(root)).episodes:
        d = _episode_digest(ep)
        eid = int(ep.metadata.episode_id)
        if d in first:
            copies[eid] = first[d]
        else:
            first[d] = eid
    return copies


# ── trials ──────────────────────────────────────────────────────────────────


def run_trial(cfg, ds_name, ds_cfg, variant, rep, work: Path, keep: bool) -> dict:
    trial_id = f"{ds_name}/{variant['id']}/r{rep}"
    seed = trial_seed(ds_name, variant["id"], rep)
    rng = np.random.default_rng(seed)
    root = work / trial_id.replace("/", "__")
    row = {
        "trial_id": trial_id,
        "dataset": ds_name,
        "variant": variant["id"],
        "family": variant["family"],
        "tier": variant["tier"],
        "rep": rep,
        "seed": seed,
        "params": variant.get("params", {}),
    }
    t0 = time.monotonic()
    ds = V3Dataset.working_copy(Path(ds_cfg["root"]), root)
    inj = faults.INJECTORS[variant["injector"]](ds, rng, **variant.get("params", {}))
    row["inject_seconds"] = round(time.monotonic() - t0, 2)
    row["n_episodes"] = len(ds.episodes())
    row["injection"] = {
        "units": inj.units,
        "expected": inj.expected,
        "explained": inj.explained,
        "measured": inj.measured,
        "skipped": inj.skipped,
    }
    if inj.skipped:
        if not keep:
            shutil.rmtree(root)
        return row
    row["modified_files"] = {
        str(p.relative_to(root)): sha256(p)
        for p in sorted(root.rglob("*"))
        if p.is_file() and not p.is_symlink() and p.suffix in (".parquet", ".mp4", ".json")
    }
    passes = {}
    if variant.get("decode"):
        passes["full"] = run_integrity(root, row["n_episodes"])
        injected_eps = {u["episode"] for u in inj.units}
        # When every episode is injected, sampling cannot hide the fault.
        if row["n_episodes"] > DEFAULT_VIDEO_SAMPLE and len(injected_eps) < row["n_episodes"]:
            passes["default"] = run_integrity(root, DEFAULT_VIDEO_SAMPLE)
    else:
        passes["files"] = run_integrity(root, None)
    row["passes"] = passes
    if variant["family"] in ("duplicate_episode", "control"):
        row["duplicate_of"] = duplicate_attribution(root)
    if not keep:
        shutil.rmtree(root)
    return row


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--datasets", default="h1,aloha,pusht", help="comma-separated dataset keys")
    ap.add_argument(
        "--variants", default="", help="comma-separated variant id prefixes (default: all)"
    )
    ap.add_argument(
        "--reps", type=int, help="override reps for every variant (e.g. 1 for a timing pass)"
    )
    ap.add_argument(
        "--run", default=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"), help="run name"
    )
    ap.add_argument("--work", default=str(HERE / "work"), help="scratch dir for working copies")
    ap.add_argument("--keep", action="store_true", help="keep working copies")
    ap.add_argument(
        "--allow-unverified",
        action="store_true",
        help="run on copies whose revision cannot be read",
    )
    args = ap.parse_args()

    cfg = load_config()
    check_thresholds(cfg)
    out_dir = HERE / "results" / args.run
    out_dir.mkdir(parents=True, exist_ok=True)
    work = Path(args.work)

    prefixes = [p for p in args.variants.split(",") if p]
    variants = [
        v for v in cfg["variants"] if not prefixes or any(v["id"].startswith(p) for p in prefixes)
    ]

    datasets = {}
    for name in args.datasets.split(","):
        d = cfg["datasets"][name]
        rev = dataset_revision(Path(d["root"]))
        if rev != d["revision"] and not args.allow_unverified:
            sys.exit(f"{name}: local copy is at revision {rev}, config pins {d['revision']}")
        datasets[name] = {
            **d,
            "local_revision": rev,
            "info_sha256": sha256(Path(d["root"]) / "meta" / "info.json"),
        }

    manifest = {
        "run": args.run,
        "started": datetime.now(timezone.utc).isoformat(),
        "calibra_version": cfg["calibra_version"],
        "git": git_state(),
        "environment": environment(),
        "datasets": datasets,
        "argv": sys.argv,
        "config_sha256": sha256(HERE / "config.toml"),
        "protocol_sha256": sha256(HERE / "PROTOCOL.md"),
    }
    # One manifest per invocation: a resumed or extended run keeps every argv.
    stamp = manifest["started"].replace(":", "").split(".")[0]
    (out_dir / "manifests").mkdir(exist_ok=True)
    (out_dir / "manifests" / f"{stamp}.json").write_text(json.dumps(manifest, indent=2))

    trials_path = out_dir / "trials.jsonl"
    done = set()
    if trials_path.exists():  # resume
        done = {
            json.loads(line)["trial_id"] for line in trials_path.read_text().splitlines() if line
        }

    for name, d in datasets.items():
        for v in variants:
            reps = (
                args.reps
                or v.get("reps")
                or cfg["reps"]["reencode" if v.get("reencode") else "default"]
            )
            for rep in range(reps):
                tid = f"{name}/{v['id']}/r{rep}"
                if tid in done:
                    continue
                t0 = time.monotonic()
                try:
                    row = run_trial(cfg, name, d, v, rep, work, args.keep)
                except Exception as exc:  # recorded, never silently dropped
                    row = {
                        "trial_id": tid,
                        "dataset": name,
                        "variant": v["id"],
                        "family": v["family"],
                        "tier": v["tier"],
                        "rep": rep,
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                row["total_seconds"] = round(time.monotonic() - t0, 2)
                with open(trials_path, "a") as f:
                    f.write(json.dumps(row) + "\n")
                status = row.get("error") or row.get("injection", {}).get("skipped") or "ok"
                print(f"{tid:45s} {row['total_seconds']:7.1f}s  {status}", flush=True)


if __name__ == "__main__":
    main()
