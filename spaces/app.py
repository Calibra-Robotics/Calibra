"""
Calibra: what should I train on?

Public demo of `calibra analyze` on a Hugging Face LeRobot dataset:
integrity, Calibra Score, noise regime, a per-episode decision
(KEEP / DROP, or ANNOTATE in annotate mode), and detector firing rates
checked against known-clean baselines.

The demo runs on up to SAMPLE_EPISODE_CAP episodes. For the whole dataset:
    pip install calibra-robotics && calibra analyze <dataset>
"""

from __future__ import annotations

import html
import json
import os
import tempfile
import threading
from datetime import datetime, timezone

import gradio as gr

SAMPLE_EPISODE_CAP = 50
ANALYSIS_TIMEOUT_S = 120
REPO_URL = "https://github.com/Calibra-Robotics/Calibra"

# ── analysis ──────────────────────────────────────────────────────────────────


def _analyze(dataset_id: str) -> dict:
    from calibra import __version__
    from calibra.analyze import _to_json, run_analysis
    from calibra.anomalies import calibration_dataset_id, find_outliers, firing_rate_summary
    from calibra.ingestion.registry import load
    from calibra.schema.comparison import Disposition

    batch = load(dataset_id)
    n_total = batch.n_episodes
    is_sample = n_total > SAMPLE_EPISODE_CAP
    if is_sample:
        batch.episodes = batch.episodes[:SAMPLE_EPISODE_CAP]
        batch._n_samples_hint = None

    result = run_analysis(batch)
    report = result.report

    curation = annotate_counts = None
    if result.prune_result is not None:
        curation = result.prune_result.to_curation_report(batch, report=report)
        annotate_counts = result.prune_result.to_curation_report(
            batch, redundant_disposition=Disposition.ANNOTATE
        ).disposition_counts()

    outliers = find_outliers(report, dataset=calibration_dataset_id(dataset_id))
    firing = firing_rate_summary(outliers, report.n_episodes)

    payload = _to_json(result)
    payload["sample"] = {"episodes_analyzed": report.n_episodes, "episodes_total": n_total}
    payload["dataset_profile"] = report.dataset_profile
    payload["detector_firing_rates"] = firing
    payload["dispositions"] = (
        [d.model_dump(mode="json") for d in curation.dispositions] if curation else []
    )

    return {
        "result": result,
        "curation": curation,
        "annotate_counts": annotate_counts,
        "firing": firing,
        "n_total": n_total,
        "is_sample": is_sample,
        "version": __version__,
        "report_path": _write_json(payload, dataset_id),
    }


def _write_json(payload: dict, dataset_id: str) -> str:
    slug = dataset_id.replace("/", "_")
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = os.path.join(tempfile.gettempdir(), f"calibra_analyze_{slug}_{ts}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, default=str)
    return path


def run(dataset_id: str, progress=gr.Progress()):
    dataset_id = dataset_id.strip().removeprefix("hf://")
    if not dataset_id:
        raise gr.Error("Enter a dataset ID, e.g. lerobot/pusht")
    parts = dataset_id.split("/")
    if len(parts) != 2 or not all(parts):
        raise gr.Error(
            f"'{dataset_id}' doesn't look like a Hugging Face dataset ID. "
            "Expected org/name, e.g. lerobot/pusht"
        )

    progress(0.05, desc=f"Loading {dataset_id} ...")
    out: dict = {}
    error: list = []

    def _worker():
        try:
            out.update(_analyze(dataset_id))
        except Exception as exc:
            error.append(str(exc))

    thread = threading.Thread(target=_worker, daemon=True)
    thread.start()
    elapsed = 0
    while thread.is_alive() and elapsed < ANALYSIS_TIMEOUT_S:
        thread.join(timeout=3)
        elapsed += 3
        progress(
            min(0.1 + elapsed / ANALYSIS_TIMEOUT_S * 0.8, 0.9),
            desc=f"Analyzing ({elapsed}s) ...",
        )

    if thread.is_alive():
        raise gr.Error(
            f"Analysis timed out after {ANALYSIS_TIMEOUT_S}s; the dataset may be too large "
            f"for the demo. Run locally: calibra analyze {dataset_id}"
        )
    if error:
        msg = error[0]
        low = msg.lower()
        if "not found" in low or "404" in low:
            raise gr.Error(f"Dataset '{dataset_id}' not found on the Hugging Face Hub.")
        if any(k in low for k in ("lerobot", "parquet", "episode_index")):
            raise gr.Error(
                f"'{dataset_id}' doesn't look like a LeRobot dataset. "
                "The demo reads LeRobot-format datasets only."
            )
        raise gr.Error(f"Analysis failed: {msg[:300]}")

    progress(0.95, desc="Rendering ...")
    return _render(dataset_id, out), out["report_path"], _episode_rows(out["curation"])


# ── rendering ─────────────────────────────────────────────────────────────────

_GREEN, _AMBER, _RED, _BLUE, _MUTED = "#22c55e", "#f59e0b", "#ef4444", "#89b4fa", "#6c7086"
_STATUS_COLOR = {"Healthy": _GREEN, "Warning": _AMBER, "Critical": _RED}
_LEVEL_STYLE = {"critical": ("✗", _RED), "warning": ("⚠", _AMBER), "ok": ("✓", _GREEN)}
_REGIME_NOTE = {
    "LOW NOISE": "Clean data: selection focuses on removing redundancy.",
    "MODERATE NOISE": "Some noisy episodes: filter the worst, then select for coverage.",
    "HIGH NOISE": "Widespread noise: quality filtering matters most.",
}
_DISPOSITION_COLOR = {
    "KEEP": _GREEN,
    "ANNOTATE": _BLUE,
    "DOWNWEIGHT": "#cba6f7",
    "REVIEW": _AMBER,
    "DROP": _RED,
}


def _esc(s) -> str:
    return html.escape(str(s))


def _label(text: str) -> str:
    return (
        f'<div style="font-size:11px;color:{_MUTED};text-transform:uppercase;'
        f'letter-spacing:.06em;margin-bottom:8px">{text}</div>'
    )


_RULE = '<div style="border-top:1px solid #313244;margin:16px 0"></div>'


def _header_html(dataset_id: str, out: dict) -> str:
    r = out["result"].report
    tags = []
    if out["is_sample"]:
        tags.append(f"first {r.n_episodes} of {out['n_total']:,} episodes")
    if r.dataset_profile:
        tags.append(f"profile: {_esc(r.dataset_profile)}")
    tag_html = "".join(
        f'<span style="font-size:11px;background:#313244;padding:2px 8px;border-radius:10px;'
        f'color:#a6adc8;margin-left:6px">{t}</span>'
        for t in tags
    )
    return f"""
<div style="font-size:20px;font-weight:700;color:#cdd6f4">{_esc(dataset_id)}{tag_html}</div>
<div style="font-size:13px;color:{_MUTED};margin-top:4px">
  {r.n_episodes:,} episodes analyzed &nbsp;·&nbsp; {r.n_samples:,} frames &nbsp;·&nbsp; {_esc(r.format)}
</div>
"""


def _integrity_html(res) -> str:
    from calibra.analyze import _worst_level

    color = _STATUS_COLOR.get(res.integrity_status, _MUTED)
    rows = ""
    for category, flags in res.integrity_by_category.items():
        level = _worst_level(flags)
        if level is None:
            rows += (
                f'<div style="margin:5px 0;color:{_MUTED};font-size:14px">'
                f"⬚ {category} <span style='font-size:12px'>(not evaluated)</span></div>"
            )
            continue
        icon, c = _LEVEL_STYLE[level.value.lower()]
        details = "".join(
            f'<div style="color:{_MUTED};font-size:12px;margin:2px 0 0 24px">'
            f"{_esc(f.interpretation)}</div>"
            for f in flags
            if f.level.value not in ("OK", "INFO")
        )
        rows += (
            f'<div style="margin:5px 0;font-size:14px;color:#cdd6f4">'
            f'<span style="color:{c};display:inline-block;width:20px">{icon}</span>{category}'
            f"{details}</div>"
        )
    return f"""
<div style="display:flex;justify-content:space-between;align-items:baseline">
  {_label("2 · Integrity: can I trust it?")}
  <span style="padding:2px 10px;border-radius:10px;font-size:12px;font-weight:700;
               background:{color}22;border:1px solid {color};color:{color}">
    {_esc(res.integrity_status)}</span>
</div>
{rows}
"""


def _details_html(res) -> str:
    """Aggregate scores, collapsed on purpose: they are not yet validated
    against training outcomes and shift between Calibra versions, so the
    card leads with decisions and baseline comparisons instead."""
    q = res.score_result
    cov = q["dimensions"]["coverage_diversity"]
    cov_pct = cov["score"] / cov["max"] * 100 if cov["max"] else 0.0
    redundancy = f"{res.redundancy:.1%}" if res.redundancy is not None else "n/a"
    rows = [
        ("Calibra Score", f"{q['total_score']:.1f} / 100 ({_esc(q['category'])})"),
        ("Coverage", f"{cov_pct:.1f} / 100"),
        ("Redundancy (estimated)", f"{redundancy} of state space in duplicate regions"),
        ("Integrity score", f"{res.integrity_score} / 100"),
    ]
    items = "".join(
        f'<div style="display:flex;justify-content:space-between;padding:4px 0;'
        f'border-bottom:1px solid #313244;font-size:13px">'
        f'<span style="color:#a6adc8">{k}</span><span style="color:#cdd6f4">{v}</span></div>'
        for k, v in rows
    )
    return f"""
<details>
  <summary style="cursor:pointer;font-size:12px;color:{_MUTED}">Aggregate scores</summary>
  <div style="margin-top:8px">{items}</div>
  <div style="font-size:12px;color:{_MUTED};margin-top:8px">
    These summarize many signals into one number. They are not yet validated against
    policy performance and change between Calibra versions, so compare datasets with
    the decisions and baseline rates above, not with these scores.
  </div>
</details>
"""


def _decision_html(dataset_id: str, out: dict) -> str:
    res = out["result"]
    pr, curation = res.prune_result, out["curation"]
    if pr is None or curation is None:
        return (
            _label("1 · Decision: what should I train on?")
            + f'<div style="color:{_MUTED};font-size:14px">Needs at least 5 episodes '
            "to diagnose a regime and recommend a training set.</div>"
        )

    regime = ""
    if res.regime_diagnosis is not None:
        from calibra.strategy import _REGIME_LABELS

        name = _REGIME_LABELS[res.regime_diagnosis.regime]
        regime = (
            f'<div style="font-size:13px;color:#a6adc8;margin-bottom:10px">'
            f'Regime <b style="color:#cdd6f4">{name}</b>: {_REGIME_NOTE.get(name, "")}</div>'
        )

    counts = curation.disposition_counts()
    n = sum(counts.values()) or 1
    bar = "".join(
        f'<div title="{k}: {v}" style="width:{v / n * 100:.2f}%;background:{_DISPOSITION_COLOR.get(k, _MUTED)}"></div>'
        for k, v in sorted(counts.items(), key=lambda kv: kv[0] != "KEEP")
    )
    legend = " &nbsp; ".join(
        f'<span style="color:{_DISPOSITION_COLOR.get(k, _MUTED)}">■</span> {k} {v}'
        for k, v in sorted(counts.items(), key=lambda kv: kv[0] != "KEEP")
    )

    reasons = []
    if pr.n_quality_failures:
        reasons.append(f"{pr.n_quality_failures} fail quality limits (noise, spikes, dropouts)")
    if pr.n_diversity_pruned:
        reasons.append(f"{pr.n_diversity_pruned} are redundant with episodes already kept")
    reasons_html = "".join(
        f'<div style="font-size:13px;color:#a6adc8;margin:2px 0">• DROP: {r}</div>' for r in reasons
    )

    annotate_note = ""
    ann = out["annotate_counts"] or {}
    if ann.get("ANNOTATE"):
        annotate_note = (
            f'<div style="font-size:13px;color:#a6adc8;margin-top:8px">'
            f'<span style="color:{_BLUE}">Annotate mode</span> keeps the {ann["ANNOTATE"]} '
            f"redundant episodes in the training set, tagged with their characterization "
            f"for a metadata-aware trainer, and drops only the {ann.get('DROP', 0)} "
            f"quality failures.</div>"
        )

    keep = f"{res.keep_fraction:.2f}"
    return f"""
{_label("1 · Decision: what should I train on?")}
{regime}
<div style="font-size:30px;font-weight:800;color:#cdd6f4">
  {pr.n_kept:,} <span style="font-size:16px;color:{_MUTED};font-weight:400">
  of {pr.n_original:,} episodes kept ({pr.keep_fraction_actual:.0%})</span></div>
<div style="display:flex;height:10px;border-radius:5px;overflow:hidden;margin:10px 0 6px">{bar}</div>
<div style="font-size:12px;color:#a6adc8;margin-bottom:8px">{legend}</div>
{reasons_html}
{annotate_note}
<div style="font-size:12px;color:{_MUTED};margin-top:10px">
  A heuristic starting point (about 1 minus measured redundancy), not a validated retention
  curve. The per-episode table below shows every decision and its reason.
</div>
<div style="background:#181825;border-radius:8px;padding:10px 14px;margin-top:12px;
            font-size:12px;font-family:monospace;color:#cdd6f4;line-height:1.7">
  calibra prune {_esc(dataset_id)} --keep {keep} --export-dataset ./coreset<br>
  calibra prune {_esc(dataset_id)} --keep {keep} --annotate ./annotations
</div>
"""


def _signal(entry: dict) -> tuple[str, str]:
    """Same wording as `calibra audit`'s calibration context table."""
    baseline = entry["benign_baseline_rate"]
    if baseline is None:
        return "no clean baseline yet", _MUTED
    ratio = entry["fraction"] / baseline if baseline > 0 else float("inf")
    if abs(entry["fraction"] - baseline) < 0.005:
        return "within normal range", _GREEN
    if ratio >= 2.0:
        return f"{ratio:.1f}× above baseline", _AMBER
    if ratio <= 0.5:
        return "below baseline", _GREEN
    return "near baseline", _GREEN


def _calibration_html(out: dict) -> str:
    firing = out["firing"]
    if not firing:
        return (
            _label("3 · Unusual episodes vs. clean baselines")
            + f'<div style="color:{_GREEN};font-size:14px">✓ No episode is a statistical '
            "outlier within this dataset.</div>"
        )
    rows = ""
    for e in firing:
        text, color = _signal(e)
        base = (
            f"{e['benign_baseline_rate']:.1%}" if e["benign_baseline_rate"] is not None else "n/a"
        )
        rows += (
            f"<tr><td style='padding:4px 8px 4px 0'>{_esc(e['detector'])}</td>"
            f"<td style='text-align:right;padding:4px 8px'>{e['fraction']:.1%}</td>"
            f"<td style='text-align:right;padding:4px 8px'>{base}</td>"
            f"<td style='padding:4px 0 4px 8px;color:{color}'>{text}</td></tr>"
        )
    return f"""
{_label("3 · Unusual episodes vs. clean baselines")}
<table style="width:100%;font-size:13px;color:#cdd6f4;border-collapse:collapse">
  <tr style="color:{_MUTED};font-size:11px;text-align:left">
    <th style="padding:4px 8px 4px 0">Detector</th><th style="text-align:right;padding:4px 8px">Flagged</th>
    <th style="text-align:right;padding:4px 8px">Clean baseline</th><th style="padding:4px 0 4px 8px">Signal</th>
  </tr>
  {rows}
</table>
<div style="font-size:12px;color:{_MUTED};margin-top:8px">
  A flag means an episode is unusual within this dataset, not that it is corrupted.
  Baselines are firing rates measured on known-clean datasets (PushT, ALOHA so far).
</div>
"""


def _footer_html(dataset_id: str, out: dict) -> str:
    full = (
        f"Demo analyzed the first {out['result'].report.n_episodes} episodes. "
        if out["is_sample"]
        else ""
    )
    return f"""
<div style="font-size:13px;color:#a6adc8">{full}Run it on the whole dataset or your own data:</div>
<div style="background:#181825;border-radius:8px;padding:10px 14px;margin-top:8px;
            font-size:13px;font-family:monospace;color:#cdd6f4">
  pip install 'calibra-robotics[lerobot]'<br>calibra analyze {_esc(dataset_id)}
</div>
<div style="margin-top:14px;font-size:11px;color:#45475a">
  Calibra v{_esc(out["version"])} ·
  <a href="{REPO_URL}" style="color:{_MUTED}">github.com/Calibra-Robotics/Calibra</a>
</div>
"""


def _render(dataset_id: str, out: dict) -> str:
    res = out["result"]
    inner = (
        _header_html(dataset_id, out)
        + _RULE
        + _decision_html(dataset_id, out)
        + _RULE
        + _integrity_html(res)
        + _RULE
        + _calibration_html(out)
        + _RULE
        + _details_html(res)
        + _RULE
        + _footer_html(dataset_id, out)
    )
    return (
        "<div style=\"font-family:'Inter','Segoe UI',sans-serif;background:#1e1e2e;"
        'border-radius:14px;padding:24px 28px;color:#cdd6f4;max-width:820px">' + inner + "</div>"
    )


_REASON_TEXT = {"diversity_pruned": "redundant with kept episodes"}
_EPISODE_COLUMNS = ["episode", "decision", "reason", "quality_risk", "coverage_value", "anomaly"]


def _episode_rows(curation) -> list[list]:
    if curation is None:
        return []

    def fmt(x):
        return None if x is None else round(x, 3)

    rows = [
        [
            d.episode_id,
            d.disposition.value,
            "; ".join(_REASON_TEXT.get(r, r) for r in d.reasons),
            fmt(d.quality_risk),
            fmt(d.coverage_value),
            fmt(d.anomaly_score),
        ]
        for d in curation.dispositions
    ]
    # Decisions that remove an episode first, then by quality risk.
    rows.sort(key=lambda r: (r[1] == "KEEP", -(r[3] or 0)))
    return rows


# ── UI ────────────────────────────────────────────────────────────────────────

EXAMPLES = [
    ["lerobot/pusht"],
    ["lerobot/aloha_sim_insertion_human"],
    ["lerobot/xarm_lift_medium"],
    ["lerobot/droid_100"],
]

with gr.Blocks(
    title="Calibra Dataset Decisions",
    theme=gr.themes.Default(primary_hue="violet"),
    css="""
    .gr-button-primary { background: #7c3aed !important; border-color: #7c3aed !important; }
    footer { display: none !important; }
    """,
) as demo:
    gr.Markdown(f"""
# Calibra Dataset Decisions

**What should I train on?** Calibra is a robotics dataset decision layer. Enter a LeRobot dataset ID and it decides,
for every episode, whether to **keep, drop, or annotate** it before training, and shows the
evidence: **integrity** checks and detector rates compared with **known-clean baselines**. The demo analyzes up to
{SAMPLE_EPISODE_CAP} episodes.
""")

    with gr.Row():
        inp = gr.Textbox(label="LeRobot dataset ID", placeholder="lerobot/pusht", scale=5)
        btn = gr.Button("Analyze", variant="primary", scale=1, min_width=140)

    gr.Examples(examples=EXAMPLES, inputs=inp, label="Try these")

    out_html = gr.HTML()
    out_table = gr.Dataframe(
        headers=_EPISODE_COLUMNS,
        label="Per-episode decisions (removed episodes first)",
        interactive=False,
        wrap=True,
    )
    out_file = gr.File(label="Download full analysis (JSON)")

    gr.Markdown(f"""
---
**How it works**

| Step | Question | Command |
|---|---|---|
| 1. Integrity | Can I trust this dataset? | `calibra integrity` |
| 2. Quality | Which episodes are clean? | `calibra audit` |
| 3. Coverage | Which episodes are distinct? | `calibra review` |
| 4. Decide | Keep, drop, downweight, review, or annotate, then export. | `calibra prune` |

`calibra analyze` runs all four and is what this demo shows. Datasets with a known
quirk get a **dataset profile** automatically (e.g. PushT's 2-D action has no gripper).

[GitHub]({REPO_URL}) · `pip install calibra-robotics`
""")

    btn.click(fn=run, inputs=inp, outputs=[out_html, out_file, out_table])
    inp.submit(fn=run, inputs=inp, outputs=[out_html, out_file, out_table])

if __name__ == "__main__":
    demo.launch()
