"""
Score a benchmark run (PROTOCOL.md sections 6-9).

    python eval/integrity_fault_injection/score.py results/<run>

Writes results/<run>/summary.json and summary.md. Every rate is reported with
its raw counts; not-evaluated, masked, skipped and errored trials are counted
separately and never as hits or misses.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path

import tomllib

HERE = Path(__file__).resolve().parent
NON_OK = ("WARNING", "CRITICAL")
# Families whose injection re-encodes video; scored against the re-encode control.
REENCODED_FAMILIES = {"frozen_frames", "repeated_frames"}
RANK = {"OK": 0, "WARNING": 1, "CRITICAL": 2}
# Checks with episode attribution: detection is judged per injected unit.
EPISODE_LEVEL = {
    "duplicate_episode_fraction",
    "video_missing_rate",
    "video_decode_failure_rate",
    "video_frame_mismatch_rate",
    "video_fps_mismatch_rate",
}


def objective_checks() -> set[str]:
    """Integrity checks that claim an acquisition fault (motion-review signals excluded)."""
    from calibra.integrity import _INTEGRITY_METRICS, _MOTION_REVIEW_METRICS

    return set(_INTEGRITY_METRICS) - set(_MOTION_REVIEW_METRICS)


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float] | None:
    if n == 0:
        return None
    p = k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return round(max(0.0, centre - half), 4), round(min(1.0, centre + half), 4)


def primary(row: dict) -> tuple[str, dict] | tuple[None, None]:
    for name in ("full", "files"):
        if name in row.get("passes", {}):
            return name, row["passes"][name]
    return None, None


def flagged_units(row: dict, p: dict, check: str) -> set[int]:
    if check == "duplicate_episode_fraction":
        return {int(e) for e in row.get("duplicate_of", {})}
    return {int(e) for e in p.get("video_affected_episodes", {}).get(check, [])}


class Scorer:
    def __init__(self, rows: list[dict], cfg: dict):
        self.rows = rows
        self.cfg = cfg
        self.objective = objective_checks()
        self.baseline = {}  # dataset -> levels on the unmodified copy (full decode)
        # dataset -> worst level per check over the re-encode controls: frame faults
        # are re-encoded, so a check the re-encoding alone trips cannot show them.
        self.reencoded = defaultdict(dict)
        for r in rows:
            if r["variant"] == "clean.copy" and "passes" in r:
                self.baseline[r["dataset"]] = r["passes"]["full"]["levels"]
            if r["variant"] == "clean.reencode" and "passes" in r:
                worst = self.reencoded[r["dataset"]]
                for check, level in r["passes"]["full"]["levels"].items():
                    if RANK.get(level, -1) > RANK.get(worst.get(check), -1):
                        worst[check] = level
        self.native = {
            name: {(f["check"], f["episode"]) for f in d.get("native_faults", [])}
            for name, d in cfg["datasets"].items()
        }

    def base_level(self, dataset: str, check: str) -> str:
        return self.baseline.get(dataset, {}).get(check, "MISSING")

    # ── one check in one pass ───────────────────────────────────────────────

    def judge(self, row: dict, p: dict, check: str, expected: str) -> dict:
        level = p.get("levels", {}).get(check, "MISSING")
        out = {"check": check, "expected": expected, "level": level}
        if level in ("NOT_EVALUATED", "MISSING"):
            out["outcome"] = "not_evaluated"
            return out
        injected = {u["episode"] for u in row["injection"]["units"]}
        if check in EPISODE_LEVEL:
            flagged = flagged_units(row, p, check)
            hit = injected & flagged
            native = {e for (c, e) in self.native[row["dataset"]] if c == check}
            out["units_injected"] = len(injected)
            out["units_flagged"] = len(hit)
            out["episode_false_positives"] = sorted(flagged - injected - native)
            fired = bool(hit) if injected else False
            caught_all = bool(injected) and hit == injected
        else:
            base = self.base_level(row["dataset"], check)
            if (
                row["family"] in REENCODED_FAMILIES
                and self.reencoded[row["dataset"]].get(check) in NON_OK
            ):
                base = self.reencoded[row["dataset"]][check]
            if base in NON_OK:
                out["outcome"] = "masked"  # already non-OK on clean (or re-encoded clean) data
                return out
            fired = caught_all = level in NON_OK
        if expected == "NONE":
            out["outcome"] = "fires_beyond_spec" if fired else "quiet"
        else:
            out["outcome"] = "detected" if caught_all else "missed"
            if expected in RANK:
                out["level_agrees"] = level == expected
        return out

    def collateral(self, row: dict, p: dict) -> list[dict]:
        """Objective checks that went non-OK, were OK on clean data, and are neither expected nor explained."""
        inj = row["injection"]
        skip = set(inj["expected"]) | set(inj["explained"])
        out = []
        for check, level in p.get("levels", {}).items():
            if check in self.objective and check not in skip and level in NON_OK:
                if self.base_level(row["dataset"], check) == "OK":
                    out.append({"check": check, "level": level})
        return out

    # ── clean trials ────────────────────────────────────────────────────────

    def triage_clean(self, row: dict, p: dict) -> list[dict]:
        out = []
        for check, level in p.get("levels", {}).items():
            if check not in self.objective:
                continue
            if level == "NOT_EVALUATED":
                out.append({"check": check, "triage": "not_evaluated"})
            elif level in NON_OK:
                eps = flagged_units(row, p, check) if check in EPISODE_LEVEL else set()
                native = {e for (c, e) in self.native[row["dataset"]] if c == check}
                if eps and eps <= native:
                    triage = "native_fault"
                elif (
                    row["variant"] != "clean.copy"
                    and self.base_level(row["dataset"], check) == "OK"
                ):
                    triage = "harness_artifact"
                elif (
                    row["variant"] != "clean.copy"
                    and self.base_level(row["dataset"], check) == level
                ):
                    continue  # same as unmodified data, triaged there
                else:
                    triage = "false_positive"
                out.append(
                    {"check": check, "level": level, "episodes": sorted(eps), "triage": triage}
                )
        return out

    # ── run ─────────────────────────────────────────────────────────────────

    def score(self) -> dict:
        trials, clean, errors, skipped = [], [], [], []
        for row in self.rows:
            if "error" in row:
                errors.append({"trial_id": row["trial_id"], "error": row["error"]})
                continue
            if row["injection"].get("skipped"):
                skipped.append({"trial_id": row["trial_id"], "reason": row["injection"]["skipped"]})
                continue
            name, p = primary(row)
            if p is None or "levels" not in p:
                errors.append(
                    {"trial_id": row["trial_id"], "error": (p or {}).get("error", "no pass")}
                )
                continue
            if row["family"] == "control":
                clean.append(
                    {
                        "trial_id": row["trial_id"],
                        "dataset": row["dataset"],
                        "variant": row["variant"],
                        "flags": self.triage_clean(row, p),
                        "measured": row["injection"]["measured"],
                    }
                )
                continue
            judged = [self.judge(row, p, c, e) for c, e in row["injection"]["expected"].items()]
            if "default" in row["passes"]:
                d = row["passes"]["default"]
                for j in judged:
                    if j["outcome"] == "detected":
                        jd = self.judge(row, d, j["check"], j["expected"])
                        j["default_pass"] = jd["outcome"]
            trials.append(
                {
                    "trial_id": row["trial_id"],
                    "dataset": row["dataset"],
                    "variant": row["variant"],
                    "family": row["family"],
                    "tier": row["tier"],
                    "pass": name,
                    "checks": judged,
                    "collateral": self.collateral(row, p),
                    "measured": row["injection"]["measured"],
                }
            )
        return {
            "trials": trials,
            "clean": clean,
            "errors": errors,
            "skipped": skipped,
            "recall": self.recall(trials),
            "severity": self.severity(trials),
            "collateral": self.collateral_summary(trials),
            "clean_summary": self.clean_summary(clean),
            "boundary": self.boundary(trials),
            "timing": self.timing(),
        }

    @staticmethod
    def _trial_outcome(t: dict) -> str:
        """A trial is detected when any expected check catches it (ANY rows), else all must."""
        outs = [c["outcome"] for c in t["checks"]]
        if any(o == "detected" for o in outs):
            return "detected"
        for o in ("missed", "masked", "not_evaluated"):
            if o in outs:
                return o
        return "none"

    def recall(self, trials: list[dict]) -> list[dict]:
        groups = defaultdict(list)
        for t in trials:
            if t["tier"] in ("clear", "near", "ambiguous"):
                groups[(t["family"], t["tier"])].append(t)
                groups[(t["family"], t["tier"], t["dataset"])].append(t)
        out = []
        for key, ts in sorted(groups.items()):
            c = Counter(self._trial_outcome(t) for t in ts)
            n = c["detected"] + c["missed"]
            sampling = sum(
                1
                for t in ts
                for ch in t["checks"]
                if ch.get("default_pass") in ("missed", "not_evaluated")
            )
            out.append(
                {
                    "family": key[0],
                    "tier": key[1],
                    "dataset": key[2] if len(key) > 2 else "all",
                    "detected": c["detected"],
                    "missed": c["missed"],
                    "n_scored": n,
                    "recall": round(c["detected"] / n, 4) if n else None,
                    "wilson95": wilson(c["detected"], n),
                    "masked": c["masked"],
                    "not_evaluated": c["not_evaluated"],
                    "sampling_limited": sampling,
                }
            )
        return out

    @staticmethod
    def boundary(trials: list[dict]) -> list[dict]:
        """Sub-threshold and by-design variants: how often a check fired anyway."""
        groups = defaultdict(Counter)
        for t in trials:
            if t["tier"] in ("sub", "by_design"):
                for ch in t["checks"]:
                    groups[(t["variant"], t["tier"], ch["check"])][ch["outcome"]] += 1
        return [
            {"variant": v, "tier": tier, "check": c, **dict(cnt)}
            for (v, tier, c), cnt in sorted(groups.items())
        ]

    @staticmethod
    def severity(trials: list[dict]) -> list[dict]:
        m = Counter()
        for t in trials:
            for ch in t["checks"]:
                if ch["expected"] in RANK and ch["level"] in RANK:
                    m[(t["family"], ch["check"], ch["expected"], ch["level"])] += 1
        return [
            {"family": f, "check": c, "expected": e, "emitted": lvl, "n": n}
            for (f, c, e, lvl), n in sorted(m.items())
        ]

    @staticmethod
    def collateral_summary(trials: list[dict]) -> list[dict]:
        m = Counter()
        n_by_family = Counter(t["family"] for t in trials)
        for t in trials:
            for c in {c["check"] for c in t["collateral"]}:
                m[(t["family"], c)] += 1
        return [
            {"family": f, "check": c, "trials": n, "of": n_by_family[f]}
            for (f, c), n in sorted(m.items())
        ]

    def clean_summary(self, clean: list[dict]) -> list[dict]:
        out = []
        for ds in sorted({c["dataset"] for c in clean}):
            rows = [c for c in clean if c["dataset"] == ds]
            fp = [
                f | {"trial_id": c["trial_id"]}
                for c in rows
                for f in c["flags"]
                if f["triage"] == "false_positive"
            ]
            evaluated = sum(
                1
                for r in self.rows
                if r["dataset"] == ds and r.get("family") == "control" and "passes" in r
                for check, level in primary(r)[1].get("levels", {}).items()
                if check in self.objective and level in RANK
            )
            out.append(
                {
                    "dataset": ds,
                    "clean_trials": len(rows),
                    "evaluated_checks": evaluated,
                    "false_positives": len(fp),
                    "fp_wilson95_upper": (wilson(len(fp), evaluated) or (None, None))[1],
                    "flags": [
                        f | {"trial_id": c["trial_id"]}
                        for c in rows
                        for f in c["flags"]
                        if f["triage"] != "not_evaluated"
                    ],
                    "not_evaluated": sorted(
                        {
                            f["check"]
                            for c in rows
                            for f in c["flags"]
                            if f["triage"] == "not_evaluated"
                        }
                    ),
                }
            )
        return out

    def timing(self) -> list[dict]:
        t = defaultdict(list)
        for r in self.rows:
            if "total_seconds" in r:
                t[(r["dataset"], r["variant"])].append(r["total_seconds"])
        return [
            {"dataset": d, "variant": v, "n": len(s), "mean_seconds": round(sum(s) / len(s), 1)}
            for (d, v), s in sorted(t.items())
        ]


# ── markdown ────────────────────────────────────────────────────────────────


def _table(rows: list[dict], cols: list[str]) -> str:
    if not rows:
        return "_none_\n"
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for r in rows:
        lines.append(
            "| " + " | ".join("" if r.get(c) is None else str(r.get(c)) for c in cols) + " |"
        )
    return "\n".join(lines) + "\n"


def markdown(s: dict, run: str) -> str:
    out = [
        f"# Fault-injection results: `{run}`\n",
        "Generated by `score.py`. Synthetic injection only; see PROTOCOL.md section 14 for limitations.\n",
    ]
    out.append("## Clean data\n")
    out.append(
        _table(
            s["clean_summary"],
            [
                "dataset",
                "clean_trials",
                "evaluated_checks",
                "false_positives",
                "fp_wilson95_upper",
                "not_evaluated",
            ],
        )
    )
    flags = [f | {"dataset": c["dataset"]} for c in s["clean_summary"] for f in c["flags"]]
    out.append("\nNon-OK flags on clean trials, triaged:\n\n")
    out.append(_table(flags, ["dataset", "trial_id", "check", "level", "episodes", "triage"]))
    out.append("\n## Recall (clear and near tiers)\n")
    out.append(
        _table(
            s["recall"],
            [
                "family",
                "tier",
                "dataset",
                "detected",
                "n_scored",
                "recall",
                "wilson95",
                "masked",
                "not_evaluated",
                "sampling_limited",
            ],
        )
    )
    out.append("\n## Sub-threshold and by-design variants\n")
    out.append(
        _table(
            s["boundary"],
            [
                "variant",
                "tier",
                "check",
                "quiet",
                "fires_beyond_spec",
                "detected",
                "missed",
                "not_evaluated",
                "masked",
            ],
        )
    )
    out.append("\n## Severity agreement (expected vs emitted level)\n")
    out.append(_table(s["severity"], ["family", "check", "expected", "emitted", "n"]))
    out.append("\n## Collateral flags\n")
    out.append(_table(s["collateral"], ["family", "check", "trials", "of"]))
    if s["errors"] or s["skipped"]:
        out.append("\n## Errors and skipped trials\n")
        out.append(_table(s["errors"], ["trial_id", "error"]))
        out.append(_table(s["skipped"], ["trial_id", "reason"]))
    out.append("\n## Timing\n")
    out.append(_table(s["timing"], ["dataset", "variant", "n", "mean_seconds"]))
    return "\n".join(out)


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("run_dir")
    args = ap.parse_args()
    run_dir = Path(args.run_dir)
    if not run_dir.is_absolute() and not run_dir.exists():
        run_dir = HERE / run_dir
    rows = [
        json.loads(line) for line in (run_dir / "trials.jsonl").read_text().splitlines() if line
    ]
    cfg = tomllib.loads((HERE / "config.toml").read_text())
    s = Scorer(rows, cfg).score()
    (run_dir / "summary.json").write_text(json.dumps(s, indent=2))
    (run_dir / "summary.md").write_text(markdown(s, run_dir.name))
    print(markdown(s, run_dir.name))


if __name__ == "__main__":
    sys.exit(main())
