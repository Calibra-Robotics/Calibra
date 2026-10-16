"""
calibra.fault_eval — score Calibra's detectors against human-labeled real faults.

Synthetic corruption (`calibra corrupt`) shows a detector *can* react to a
fault. It cannot show whether a flag on real data means a broken recording
or an unusual-but-valid demonstration. This module measures that, in three
steps that keep labels reusable across Calibra versions:

  snapshot  Compute every per-episode signal for one dataset at a pinned
            revision: Stage 1 quality failures (exactly as `calibra prune`
            decides them), video file faults, quality_risk, anomaly_score
            with reasons, coverage_value.

  mine      Sample episodes to label from one or more snapshots, in three
            strata: every Stage-1/video-flagged episode, the top-K of the
            review queue, and a seeded random sample of the rest (controls).
            Writes a *blinded* sheet (dataset, revision, episode only; no
            stratum, no signals) plus a separate key with each item's
            stratum and inclusion probability.

  score     Join filled-in labels with the key and any snapshot of the same
            revision (e.g. a newer Calibra version) and report, per detector:
            precision and recall for acquisition faults, and how often it
            fires on unusual-but-valid episodes. Counts are weighted by
            1 / inclusion probability so oversampling flagged episodes does
            not inflate recall; raw counts and Wilson 95% intervals are
            reported alongside, since n is small.

Labels
------
  acquisition_fault  the recording is broken: frozen/missing camera frames,
                     timestamp gaps, sensor glitches, desync, truncation
  execution_failure  the recording is intact but the demonstration is bad:
                     task failed, operator error, aborted attempt
  unusual_valid      unusual motion that is a legitimate demonstration:
                     recovery, rare state, different strategy
  clean              nothing notable
  unsure             excluded from scoring

See eval/real_faults/README.md for the labeling protocol.
"""

from __future__ import annotations

import csv
import json
import math
import random
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable, Optional

LABELS = ("acquisition_fault", "execution_failure", "unusual_valid", "clean", "unsure")
SHEET_FIELDS = ("item_id", "dataset", "revision", "episode_id", "label", "fault_type", "notes")


@dataclass
class EpisodeSignals:
    episode_id: str
    n_steps: int
    stage1_fail: bool
    stage1_reasons: list[str] = field(default_factory=list)
    video_faults: list[str] = field(default_factory=list)
    quality_risk: float = 0.0
    anomaly_score: float = 0.0
    anomaly_reasons: list[str] = field(default_factory=list)
    coverage_value: Optional[float] = None
    # Below the task_structure analyzer's lower IQR length fence (the episodes
    # behind integrity's block-level short_episode_fraction finding).
    short_outlier: bool = False

    @property
    def blocked(self) -> bool:
        """Calibra would drop or block this episode without human review."""
        return self.stage1_fail or bool(self.video_faults)

    @property
    def flagged(self) -> bool:
        """Any objective per-episode flag: blocked, or a short-length outlier."""
        return self.blocked or self.short_outlier

    @property
    def review_priority(self) -> float:
        # Same combination as calibra.assessment.EpisodeAssessment.review_priority.
        score = 0.5 * self.quality_risk + 0.5 * self.anomaly_score
        if self.coverage_value is not None:
            score -= 0.3 * self.coverage_value
        return round(score, 6)


# ── snapshot ──────────────────────────────────────────────────────────────────


def snapshot(
    path: str,
    *,
    dataset: Optional[str] = None,
    revision: Optional[str] = None,
    profile: Optional[str] = None,
    log: Callable[[str], None] = lambda msg: None,
) -> dict:
    """Compute per-episode Calibra signals for one dataset."""
    from calibra import __version__
    from calibra.assessment import compute_episode_assessments
    from calibra.ingestion.registry import load
    from calibra.pipeline import Pipeline
    from calibra.prune import resolve_stage1_limits
    from calibra.pruning import CoresetSelector

    log(f"Loading {path!r} ...")
    batch = load(path)
    log(f"  {batch.n_episodes} episodes · running pipeline ...")
    report = Pipeline(profile=profile).run(batch)

    limits = resolve_stage1_limits(report, log=log)
    stage1 = CoresetSelector(
        quality_only=True,
        max_spike_rate=limits["max_spike_rate"],
        max_vel_disc_rate=limits["max_vel_disc_rate"],
        max_dropout_fraction=limits["max_dropout_fraction"],
    ).select(batch, report)
    failed = set(stage1.quality_fail_ids)

    video_by_episode = _video_faults_by_episode(path, batch)
    assessments = {a.episode_id: a for a in compute_episode_assessments(report, batch=batch)}
    short_fence = _short_episode_fence(report)

    episodes = []
    for ep in batch.episodes:
        eid = ep.metadata.episode_id
        a = assessments.get(eid)
        episodes.append(
            EpisodeSignals(
                episode_id=eid,
                n_steps=ep.n_steps,
                stage1_fail=eid in failed,
                stage1_reasons=list(stage1.fail_reasons.get(eid, [])),
                video_faults=video_by_episode.get(eid, []),
                quality_risk=a.quality_risk if a else 0.0,
                anomaly_score=a.anomaly_score if a else 0.0,
                anomaly_reasons=[r.metric for r in a.reasons] if a else [],
                coverage_value=a.coverage_value if a else None,
                short_outlier=short_fence is not None and ep.n_steps < short_fence,
            )
        )

    return {
        "dataset": dataset or path,
        "revision": revision,
        "calibra_version": __version__,
        "profile": report.dataset_profile,
        "stage1_limits": limits,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "episodes": [asdict(e) for e in episodes],
    }


def _short_episode_fence(report) -> Optional[float]:
    """The task_structure analyzer's lower IQR length fence, if it ran."""
    for result in report.analyzer_results:
        fence = result.raw_metrics.get("short_episodes", {}).get("lower_fence_steps")
        if fence is not None:
            return float(fence)
    return None


def _video_faults_by_episode(path: str, batch) -> dict[str, list[str]]:
    root = Path(path).expanduser()
    info = root / "meta" / "info.json"
    if not info.exists():
        return {}
    from calibra.video_integrity import check_video_integrity, has_video_features

    if not has_video_features(json.loads(info.read_text(encoding="utf-8"))):
        return {}
    try:
        lengths = {int(ep.metadata.episode_id): ep.n_steps for ep in batch.episodes}
    except ValueError:
        lengths = None
    result = check_video_integrity(root, lengths)
    out: dict[str, list[str]] = {}
    for metric, eps in result.affected.items():
        for ep in eps:
            out.setdefault(str(ep), []).append(metric)
    return out


def load_snapshot(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _signals(snap: dict) -> dict[str, EpisodeSignals]:
    return {e["episode_id"]: EpisodeSignals(**e) for e in snap["episodes"]}


# ── mine ──────────────────────────────────────────────────────────────────────


def mine(
    snapshots: Iterable[dict],
    *,
    top_k: int = 10,
    n_controls: int = 20,
    max_flagged: Optional[int] = None,
    seed: int = 0,
) -> tuple[list[dict], list[dict]]:
    """
    Sample episodes to label. Returns (blinded sheet rows, key rows).

    Strata per dataset: "flagged" (Stage 1 or video fault; all of them, or a
    seeded sample of max_flagged), "review_top" (top_k remaining by review
    priority, all included) and "control" (seeded random sample of the rest,
    inclusion probability n_controls / remaining).
    """
    rng = random.Random(seed)
    items: list[dict] = []
    for snap in snapshots:
        signals = sorted(_signals(snap).values(), key=lambda s: s.episode_id)
        all_flagged = [s for s in signals if s.flagged]
        flagged = all_flagged
        if max_flagged is not None and len(all_flagged) > max_flagged:
            flagged = rng.sample(all_flagged, max_flagged)
        p_flagged = len(flagged) / len(all_flagged) if all_flagged else 0.0
        rest = [s for s in signals if not s.flagged]
        rest.sort(key=lambda s: (-s.review_priority, s.episode_id))
        review = rest[:top_k]
        pool = rest[top_k:]
        controls = rng.sample(pool, min(n_controls, len(pool)))
        p_control = len(controls) / len(pool) if pool else 0.0

        for stratum, group, p in (
            ("flagged", flagged, p_flagged),
            ("review_top", review, 1.0),
            ("control", controls, p_control),
        ):
            for s in group:
                items.append(
                    {
                        "dataset": snap["dataset"],
                        "revision": snap.get("revision"),
                        "episode_id": s.episode_id,
                        "stratum": stratum,
                        "inclusion_prob": p,
                    }
                )

    # Blind the order so strata can't be inferred from position.
    rng.shuffle(items)
    sheet, key = [], []
    for i, item in enumerate(items):
        item_id = f"i{i:04d}"
        sheet.append(
            {
                "item_id": item_id,
                "dataset": item["dataset"],
                "revision": item["revision"] or "",
                "episode_id": item["episode_id"],
                "label": "",
                "fault_type": "",
                "notes": "",
            }
        )
        key.append({"item_id": item_id, **item})
    return sheet, key


def write_sheet(rows: list[dict], path: Path) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=SHEET_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def read_sheet(path: Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_jsonl(rows: list[dict], path: Path) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.writelines(json.dumps(r) + "\n" for r in rows)


def read_jsonl(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


# ── score ─────────────────────────────────────────────────────────────────────


def detectors(quality_risk_threshold: float, anomaly_threshold: float) -> dict[str, Callable]:
    """Boolean per-episode decisions to score. Thresholds are for reporting, not calibrated."""
    return {
        "flagged (stage1, video or short)": lambda s: s.flagged,
        "blocked (stage1 or video)": lambda s: s.blocked,
        "short_outlier": lambda s: s.short_outlier,
        "stage1_fail": lambda s: s.stage1_fail,
        "video_fault": lambda s: bool(s.video_faults),
        f"quality_risk>={quality_risk_threshold:g}": lambda s: (
            s.quality_risk >= quality_risk_threshold
        ),
        f"anomaly_score>={anomaly_threshold:g}": lambda s: s.anomaly_score >= anomaly_threshold,
    }


def wilson(k: int, n: int, z: float = 1.96) -> Optional[tuple[float, float]]:
    if n == 0:
        return None
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def score(
    labels: list[dict],
    key: list[dict],
    snapshots: Iterable[dict],
    *,
    quality_risk_threshold: float = 0.5,
    anomaly_threshold: float = 0.8,
) -> dict:
    """Score detectors in `snapshots` against labeled items."""
    by_dataset = {}
    for snap in snapshots:
        by_dataset[snap["dataset"]] = snap
    key_by_id = {k["item_id"]: k for k in key}

    rows = []
    label_counts: dict[str, int] = {}
    for lab in labels:
        label = (lab.get("label") or "").strip()
        if not label:
            continue
        if label not in LABELS:
            raise ValueError(f"item {lab['item_id']}: unknown label {label!r}; use one of {LABELS}")
        label_counts[label] = label_counts.get(label, 0) + 1
        if label == "unsure":
            continue
        k = key_by_id.get(lab["item_id"])
        if k is None:
            raise ValueError(f"item {lab['item_id']} is not in the key file")
        found = by_dataset.get(k["dataset"])
        if found is None:
            raise ValueError(f"no snapshot for dataset {k['dataset']!r}")
        snap = found
        if (snap.get("revision") or None) != (k.get("revision") or None):
            raise ValueError(
                f"{k['dataset']}: labels are for revision {k.get('revision')!r} but the "
                f"snapshot is for {snap.get('revision')!r}; snapshot the labeled revision"
            )
        sig = _signals(snap).get(k["episode_id"])
        if sig is None:
            raise ValueError(f"{k['dataset']}: episode {k['episode_id']} missing from snapshot")
        p = float(k["inclusion_prob"])
        rows.append((label, sig, 1.0 / p if p > 0 else 0.0))

    results = {}
    for name, fires in detectors(quality_risk_threshold, anomaly_threshold).items():
        results[name] = _detector_stats(rows, fires)

    versions = sorted({s.get("calibra_version", "?") for s in by_dataset.values()})
    return {
        "calibra_versions": versions,
        "datasets": sorted(by_dataset),
        "label_counts": label_counts,
        "n_scored": len(rows),
        "positive_class": "acquisition_fault",
        "detectors": results,
    }


def _detector_stats(rows, fires) -> dict:
    tp = fp = fn = 0
    w_tp = w_fp = w_fn = 0.0
    valid_n = valid_hit = 0
    w_valid_n = w_valid_hit = 0.0
    for label, sig, w in rows:
        hit = bool(fires(sig))
        positive = label == "acquisition_fault"
        if positive and hit:
            tp, w_tp = tp + 1, w_tp + w
        elif positive:
            fn, w_fn = fn + 1, w_fn + w
        elif hit:
            fp, w_fp = fp + 1, w_fp + w
        if label == "unusual_valid":
            valid_n, w_valid_n = valid_n + 1, w_valid_n + w
            if hit:
                valid_hit, w_valid_hit = valid_hit + 1, w_valid_hit + w

    def ratio(a: float, b: float) -> Optional[float]:
        return a / b if b else None

    return {
        "precision": ratio(w_tp, w_tp + w_fp),
        "recall": ratio(w_tp, w_tp + w_fn),
        "fires_on_unusual_valid": ratio(w_valid_hit, w_valid_n),
        "raw": {
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "precision_ci95": wilson(tp, tp + fp),
            "recall_ci95": wilson(tp, tp + fn),
            "unusual_valid_n": valid_n,
            "unusual_valid_flagged": valid_hit,
        },
    }


def render_markdown(result: dict) -> str:
    def pct(v: Optional[float]) -> str:
        return "n/a" if v is None else f"{v:.0%}"

    def ci(v) -> str:
        return "" if v is None else f" ({v[0]:.0%}-{v[1]:.0%})"

    lines = [
        f"Calibra {', '.join(result['calibra_versions'])} · "
        f"{len(result['datasets'])} dataset(s) · {result['n_scored']} labeled episodes scored",
        "",
        "Labels: " + ", ".join(f"{k}={v}" for k, v in sorted(result["label_counts"].items())),
        "",
        "| Detector | Precision (raw 95% CI) | Recall (raw 95% CI) | Fires on unusual_valid | "
        "TP/FP/FN |",
        "|---|---|---|---|---|",
    ]
    for name, d in result["detectors"].items():
        raw = d["raw"]
        lines.append(
            f"| {name} | {pct(d['precision'])}{ci(raw['precision_ci95'])} | "
            f"{pct(d['recall'])}{ci(raw['recall_ci95'])} | "
            f"{pct(d['fires_on_unusual_valid'])} ({raw['unusual_valid_flagged']}/"
            f"{raw['unusual_valid_n']}) | {raw['tp']}/{raw['fp']}/{raw['fn']} |"
        )
    lines += [
        "",
        "Precision/recall are weighted by 1/inclusion probability (estimates for the whole "
        "dataset); intervals are Wilson intervals on the raw labeled counts. Positive class: "
        "acquisition_fault.",
    ]
    return "\n".join(lines)
