"""Tests for calibra.fault_eval (real-fault eval set: snapshot / mine / score)."""

from __future__ import annotations

import pytest

from calibra import fault_eval
from calibra.fault_eval import SHEET_FIELDS, mine, score, wilson


def _ep(eid, *, stage1=False, video=(), qr=0.0, an=0.0, cov=None):
    return {
        "episode_id": str(eid),
        "n_steps": 50,
        "stage1_fail": stage1,
        "stage1_reasons": ["jerk_spike"] if stage1 else [],
        "video_faults": list(video),
        "quality_risk": qr,
        "anomaly_score": an,
        "anomaly_reasons": [],
        "coverage_value": cov,
    }


def _snap(dataset="org/ds", revision="abc", version="0.12.0", episodes=None):
    if episodes is None:
        episodes = (
            [_ep(0, stage1=True), _ep(1, video=["video_missing_rate"])]
            + [_ep(i, qr=0.9 - i / 100) for i in range(2, 6)]
            + [_ep(i) for i in range(6, 46)]
        )
    return {
        "dataset": dataset,
        "revision": revision,
        "calibra_version": version,
        "episodes": episodes,
    }


# ── mine ──────────────────────────────────────────────────────────────────────


def test_mine_strata_and_probabilities():
    sheet, key = mine([_snap()], top_k=3, n_controls=8, seed=1)
    strata = {}
    for k in key:
        strata.setdefault(k["stratum"], []).append(k)
    assert sorted(k["episode_id"] for k in strata["flagged"]) == ["0", "1"]
    assert sorted(k["episode_id"] for k in strata["review_top"]) == ["2", "3", "4"]
    assert len(strata["control"]) == 8
    # 44 unflagged - 3 review = 41 in the control pool
    assert all(k["inclusion_prob"] == pytest.approx(8 / 41) for k in strata["control"])
    assert all(k["inclusion_prob"] == 1.0 for k in strata["flagged"] + strata["review_top"])
    assert len(sheet) == len(key) == 13


def test_mine_sheet_is_blinded_and_deterministic():
    sheet, key = mine([_snap()], top_k=3, n_controls=8, seed=1)
    assert set(sheet[0]) == set(SHEET_FIELDS)
    assert all(row["label"] == "" for row in sheet)
    assert [r["item_id"] for r in sheet] == [k["item_id"] for k in key]
    # Flagged items are not simply listed first.
    assert [k["stratum"] for k in key][:2] != ["flagged", "flagged"]
    again, _ = mine([_snap()], top_k=3, n_controls=8, seed=1)
    assert again == sheet


def test_mine_small_dataset_takes_whole_pool():
    snap = _snap(episodes=[_ep(0, stage1=True), _ep(1), _ep(2)])
    _, key = mine([snap], top_k=1, n_controls=20)
    controls = [k for k in key if k["stratum"] == "control"]
    assert len(controls) == 1 and controls[0]["inclusion_prob"] == 1.0


# ── score ─────────────────────────────────────────────────────────────────────


def _label(sheet, key, labels_by_episode):
    out = []
    for row, k in zip(sheet, key):
        out.append({**row, "label": labels_by_episode.get(k["episode_id"], "clean")})
    return out


def test_score_precision_recall_and_unusual_valid():
    snap = _snap()
    sheet, key = mine([snap], top_k=3, n_controls=8, seed=1)
    control_ids = [k["episode_id"] for k in key if k["stratum"] == "control"]
    labels = _label(
        sheet,
        key,
        {
            "0": "acquisition_fault",  # blocked, real fault
            "1": "unusual_valid",  # blocked, but legitimate
            "2": "unusual_valid",  # high quality_risk, legitimate
            control_ids[0]: "acquisition_fault",  # missed by Calibra
        },
    )
    result = score(labels, key, [snap], quality_risk_threshold=0.5)
    blocked = result["detectors"]["blocked (stage1 or video)"]
    assert blocked["precision"] == pytest.approx(0.5)
    # Weighted: 1 found (w=1) vs 1 missed control (w=41/8).
    assert blocked["recall"] == pytest.approx(1 / (1 + 41 / 8))
    assert blocked["raw"]["tp"] == 1 and blocked["raw"]["fn"] == 1
    assert blocked["raw"]["unusual_valid_flagged"] == 1
    assert blocked["fires_on_unusual_valid"] == pytest.approx(0.5)

    qr = result["detectors"]["quality_risk>=0.5"]
    assert qr["raw"]["tp"] == 0 and qr["raw"]["unusual_valid_flagged"] == 1
    assert result["n_scored"] == len(sheet)


def test_score_newer_snapshot_same_revision():
    """Labels outlive a Calibra version: re-score with a new snapshot."""
    old = _snap()
    sheet, key = mine([old], top_k=3, n_controls=8, seed=1)
    labels = _label(sheet, key, {"2": "acquisition_fault"})
    eps = [dict(e) for e in old["episodes"]]
    eps[2]["stage1_fail"] = True  # the new version catches episode 2
    new = _snap(version="0.13.0", episodes=eps)
    assert score(labels, key, [old])["detectors"]["stage1_fail"]["raw"]["tp"] == 0
    result = score(labels, key, [new])
    assert result["detectors"]["stage1_fail"]["raw"]["tp"] == 1
    assert result["calibra_versions"] == ["0.13.0"]


def test_score_skips_blank_and_unsure_rejects_unknown():
    snap = _snap()
    sheet, key = mine([snap], top_k=3, n_controls=8, seed=1)
    labels = [dict(r) for r in sheet]
    labels[0]["label"] = "unsure"
    labels[1]["label"] = "acquisition_fault"
    result = score(labels, key, [snap])
    assert result["n_scored"] == 1
    assert result["label_counts"] == {"unsure": 1, "acquisition_fault": 1}
    labels[2]["label"] = "broken"
    with pytest.raises(ValueError, match="unknown label"):
        score(labels, key, [snap])


def test_score_rejects_revision_mismatch():
    snap = _snap()
    sheet, key = mine([snap], top_k=3, n_controls=8, seed=1)
    labels = _label(sheet, key, {})
    with pytest.raises(ValueError, match="revision"):
        score(labels, key, [_snap(revision="def")])


def test_wilson():
    assert wilson(0, 0) is None
    lo, hi = wilson(5, 10)
    assert lo < 0.5 < hi
    lo, hi = wilson(10, 10)
    assert hi == 1.0 and lo > 0.6


def test_render_markdown():
    snap = _snap()
    sheet, key = mine([snap], top_k=3, n_controls=8, seed=1)
    md = fault_eval.render_markdown(
        score(_label(sheet, key, {"0": "acquisition_fault"}), key, [snap])
    )
    assert "| blocked (stage1 or video) |" in md
    assert "acquisition_fault=1" in md


# ── snapshot on a real on-disk dataset ────────────────────────────────────────


def test_snapshot_lerobot_v2_with_missing_video(tmp_path):
    pytest.importorskip("cv2")
    pytest.importorskip("pyarrow")
    from tests.test_video_integrity import _make_v2, _v2_video

    root = _make_v2(tmp_path, {i: 40 for i in range(12)})
    _v2_video(root, 5).unlink()
    snap = fault_eval.snapshot(str(root), dataset="local/v2", revision="r1")
    assert snap["dataset"] == "local/v2" and snap["revision"] == "r1"
    assert len(snap["episodes"]) == 12
    by_id = {e["episode_id"]: e for e in snap["episodes"]}
    assert by_id["5"]["video_faults"] == ["video_missing_rate"]
    assert sum(1 for e in snap["episodes"] if e["video_faults"]) == 1
    assert set(snap["stage1_limits"]) == {
        "max_spike_rate",
        "max_vel_disc_rate",
        "max_dropout_fraction",
    }
    _, key = mine([snap], top_k=2, n_controls=3)
    assert {"5"} <= {k["episode_id"] for k in key if k["stratum"] == "flagged"}


def test_cli_roundtrip(tmp_path):
    import json

    from scripts.fault_eval import main

    snap_path = tmp_path / "snap.json"
    snap_path.write_text(json.dumps(_snap()))
    batch = tmp_path / "batch"
    main(["mine", str(snap_path), "--out", str(batch), "--top-k", "3", "--controls", "8"])
    rows = fault_eval.read_sheet(batch / "sheet.csv")
    key = fault_eval.read_jsonl(batch / "key.jsonl")
    for row, k in zip(rows, key):
        row["label"] = "acquisition_fault" if k["episode_id"] == "0" else "clean"
    fault_eval.write_sheet(rows, batch / "sheet.csv")
    with pytest.raises(SystemExit, match="refusing to overwrite"):
        main(["mine", str(snap_path), "--out", str(batch)])
    main(["score", str(batch), str(snap_path), "--json"])


def test_mine_max_flagged_samples_with_probability():
    eps = [_ep(i, stage1=True) for i in range(30)] + [_ep(i) for i in range(30, 60)]
    _, key = mine([_snap(episodes=eps)], top_k=2, n_controls=5, max_flagged=10, seed=3)
    flagged = [k for k in key if k["stratum"] == "flagged"]
    assert len(flagged) == 10
    assert all(k["inclusion_prob"] == pytest.approx(10 / 30) for k in flagged)


def test_cli_score_without_labels_explains(tmp_path):
    import json

    from scripts.fault_eval import main

    snap_path = tmp_path / "snap.json"
    snap_path.write_text(json.dumps(_snap()))
    batch = tmp_path / "batch"
    main(["mine", str(snap_path), "--out", str(batch)])
    with pytest.raises(SystemExit, match="No labels yet"):
        main(["score", str(batch), str(snap_path)])
