"""
fault_eval.py — build and score the labeled real-fault eval set.

    # 1. Snapshot per-episode signals (pin the revision you downloaded)
    python scripts/fault_eval.py snapshot ./pusht --dataset lerobot/pusht \\
        --revision <sha> --out eval/real_faults/snapshots/

    # 2. Sample a blinded labeling sheet from one or more snapshots
    python scripts/fault_eval.py mine eval/real_faults/snapshots/*.json \\
        --out eval/real_faults/batches/batch-001

    # 3. Fill in batch-001/sheet.csv, then score any snapshot of those revisions
    python scripts/fault_eval.py score eval/real_faults/batches/batch-001 \\
        eval/real_faults/snapshots/*.json

See eval/real_faults/README.md for the labeling protocol and
calibra/fault_eval.py for what is measured.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from calibra import fault_eval


def _log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def cmd_snapshot(args) -> None:
    revision = args.revision
    if revision is None and not Path(args.path).expanduser().exists():
        from calibra.card import fetch_dataset_revision

        revision = fetch_dataset_revision(args.path)
    if revision is None:
        _log("warning: no --revision given; labels from this snapshot won't be reproducible")
    snap = fault_eval.snapshot(
        args.path, dataset=args.dataset, revision=revision, profile=args.profile, log=_log
    )
    out = Path(args.out)
    if out.is_dir() or args.out.endswith("/"):
        out.mkdir(parents=True, exist_ok=True)
        name = snap["dataset"].replace("/", "__")
        out = out / f"{name}__{snap['calibra_version']}.json"
    out.write_text(json.dumps(snap, indent=1), encoding="utf-8")
    n = len(snap["episodes"])
    blocked = sum(1 for e in snap["episodes"] if fault_eval.EpisodeSignals(**e).blocked)
    _log(f"Snapshot written to {out} ({n} episodes, {blocked} blocked)")


def cmd_mine(args) -> None:
    snaps = [fault_eval.load_snapshot(Path(p)) for p in args.snapshots]
    sheet, key = fault_eval.mine(
        snaps,
        top_k=args.top_k,
        n_controls=args.controls,
        max_flagged=args.max_flagged,
        seed=args.seed,
    )
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    if (out / "sheet.csv").exists() and not args.force:
        sys.exit(f"error: {out / 'sheet.csv'} exists; refusing to overwrite labels (--force)")
    fault_eval.write_sheet(sheet, out / "sheet.csv")
    fault_eval.write_jsonl(key, out / "key.jsonl")
    strata: dict[str, int] = {}
    for k in key:
        strata[k["stratum"]] = strata.get(k["stratum"], 0) + 1
    _log(f"{len(sheet)} items to label → {out / 'sheet.csv'}  ({strata})")
    _log(f"Key (do not open while labeling) → {out / 'key.jsonl'}")


def cmd_score(args) -> None:
    batch = Path(args.batch)
    labels = fault_eval.read_sheet(batch / "sheet.csv")
    if not any((row.get("label") or "").strip() for row in labels):
        sys.exit(
            f"No labels yet in {batch / 'sheet.csv'}: fill the 'label' column "
            f"({', '.join(fault_eval.LABELS)}) and run score again."
        )
    key = fault_eval.read_jsonl(batch / "key.jsonl")
    snaps = [fault_eval.load_snapshot(Path(p)) for p in args.snapshots]
    try:
        result = fault_eval.score(
            labels,
            key,
            snaps,
            quality_risk_threshold=args.quality_risk_threshold,
            anomaly_threshold=args.anomaly_threshold,
        )
    except ValueError as exc:
        sys.exit(f"error: {exc}")
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(fault_eval.render_markdown(result))


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="fault_eval.py", description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("snapshot", help="compute per-episode signals for one dataset")
    s.add_argument("path", help="local dataset path (or Hub ID)")
    s.add_argument("--dataset", help="dataset name to record (e.g. lerobot/pusht)")
    s.add_argument("--revision", help="Hub commit SHA of the analyzed data")
    s.add_argument("--profile", default=None, help="calibra dataset profile")
    s.add_argument("--out", required=True, help="output JSON file or directory")
    s.set_defaults(func=cmd_snapshot)

    m = sub.add_parser("mine", help="sample a blinded labeling sheet")
    m.add_argument("snapshots", nargs="+")
    m.add_argument("--out", required=True, help="batch directory")
    m.add_argument("--top-k", type=int, default=10, help="review-queue episodes per dataset")
    m.add_argument("--controls", type=int, default=20, help="random controls per dataset")
    m.add_argument(
        "--max-flagged",
        type=int,
        default=None,
        help="sample at most this many flagged episodes per dataset (default: all)",
    )
    m.add_argument("--seed", type=int, default=0)
    m.add_argument("--force", action="store_true", help="overwrite an existing sheet")
    m.set_defaults(func=cmd_mine)

    c = sub.add_parser("score", help="score snapshots against a labeled batch")
    c.add_argument("batch", help="batch directory with sheet.csv and key.jsonl")
    c.add_argument("snapshots", nargs="+")
    c.add_argument("--quality-risk-threshold", type=float, default=0.5)
    c.add_argument("--anomaly-threshold", type=float, default=0.8)
    c.add_argument("--json", action="store_true")
    c.set_defaults(func=cmd_score)

    args = p.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
