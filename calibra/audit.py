"""
calibra audit — full diagnostic report with Calibra Score, bootstrap CIs,
and per-episode outlier detection.

This is the named equivalent of running ``calibra <path>``; it makes the
two-step quality workflow explicit in the README:

    calibra integrity lerobot/pusht          # step 1 — trust
    calibra audit     lerobot/pusht          # step 2 — quality + outliers

Usage
-----
    calibra audit <path> [--html-out report.html] [--json] [--policy FAMILY]
                         [--format FMT] [--strict] [--no-anomalies]
                         [--cache-dir DIR]
"""

from __future__ import annotations

import argparse
import sys


def run_audit(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(
        prog="calibra audit",
        description=(
            "Full diagnostic report: 0–100 Calibra Score with bootstrap "
            "confidence intervals and per-episode outlier detection."
        ),
    )
    parser.add_argument("path", help="Path or Hub ID of the dataset to audit")
    parser.add_argument(
        "--format",
        "-f",
        metavar="FMT",
        choices=["hdf5", "isaac_lab", "lerobot", "rlds", "mcap"],
        help="Force a format adapter (default: auto-detect)",
    )
    parser.add_argument(
        "--policy",
        "-p",
        metavar="FAMILY",
        help="Target policy family for conditioned hints (e.g. 'diffusion', 'act')",
    )
    parser.add_argument(
        "--json",
        "-j",
        action="store_true",
        help="Print the DiagnosticReport as JSON instead of human-readable text",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit 1 on WARNING in addition to CRITICAL",
    )
    parser.add_argument(
        "--no-anomalies",
        action="store_true",
        help="Skip per-episode outlier detection (faster, aggregate flags only)",
    )
    parser.add_argument(
        "--html-out",
        metavar="PATH",
        help="Save the visual HTML dashboard report to PATH",
    )
    parser.add_argument(
        "--cache-dir",
        metavar="DIR",
        default=None,
        help="Cache directory for incremental analysis (e.g. .calibra/cache)",
    )

    args = parser.parse_args(argv)

    from calibra.pipeline import Pipeline
    from calibra.schema.report import RiskLevel

    reader = None
    if args.format:
        from calibra.__main__ import _get_reader

        reader = _get_reader(args.format)

    cache = None
    if args.cache_dir:
        from calibra.cache import AuditCache

        cache = AuditCache(args.cache_dir)

    pipeline = Pipeline()
    try:
        report = pipeline.analyze_path(
            args.path,
            policy_family=args.policy,
            reader=reader,
            cache=cache,
        )
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)

    outliers = None
    if not args.no_anomalies:
        from calibra.anomalies import find_outliers

        outliers = find_outliers(report)

    if args.html_out:
        from calibra.report_html import generate_html_report

        generate_html_report(report, args.html_out, outliers=outliers)

    if args.json:
        print(report.model_dump_json(indent=2))
    else:
        print(report.summary())
        if outliers:
            from calibra.anomalies import render

            print()
            print(render(outliers, report.n_episodes))

    if report.flags_at_level(RiskLevel.CRITICAL):
        sys.exit(1)
    if args.strict and report.flags_at_level(RiskLevel.WARNING):
        sys.exit(1)
