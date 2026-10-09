"""
calibra_ee.community — community context and dataset badges from Calibra Cloud.

Moved from calibra.predict and calibra.card (ADR-012). Both talk to the hosted
service without the user asking for it, so they run only when calibra_ee is
installed.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request
from typing import Optional

from calibra_ee.sync import sync_disabled

_BADGE_BASE = "https://outcomes.calibra.ai"


# ── community context after recording an outcome ─────────────────────────────


def _estimate_pct(val: float, p: dict) -> Optional[float]:
    """Linear interpolation of percentile rank from p25/p50/p75/p90 landmarks."""
    p25, p50, p75, p90 = p.get("p25"), p.get("p50"), p.get("p75"), p.get("p90")
    if None in (p25, p50, p75, p90):
        return None
    if val <= p25:
        return max(0.0, 25.0 * val / p25) if p25 != 0 else 25.0
    if val <= p50:
        return 25.0 + 25.0 * (val - p25) / max(p50 - p25, 1e-9)
    if val <= p75:
        return 50.0 + 25.0 * (val - p50) / max(p75 - p50, 1e-9)
    if val <= p90:
        return 75.0 + 15.0 * (val - p75) / max(p90 - p75, 1e-9)
    return 90.0


def print_community_context(metrics: dict[str, float], policy_family: str) -> None:
    """Fetch community percentiles and print a 1-2 line community comparison to stderr."""
    base = os.environ.get("CALIBRA_CLOUD_URL", "https://app.calibra.io")
    url = f"{base}/v1/percentiles?policy_family={policy_family}"
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read())
    except Exception:
        return

    n_community = data.get("n", 0)
    if n_community < 5:
        return

    percentiles = data.get("percentiles", {})
    # For each metric, estimate percentile rank (direction-aware)
    _lower_better = {"spike_rate", "vel_disc_rate", "dropout_rate", "jitter_cv", "jepa_surprise"}
    # ldlj, action_entropy, contact_phase_fraction: higher = better

    highlights: list[tuple[str, float]] = []
    for key, val in metrics.items():
        p = percentiles.get(key)
        if p is None or val is None:
            continue
        pct = _estimate_pct(val, p)
        if pct is None:
            continue
        # Convert raw percentile to "better than X%" framing
        better_pct = 100.0 - pct if key in _lower_better else pct
        highlights.append((key, better_pct))

    if not highlights:
        return

    highlights.sort(key=lambda x: abs(x[1] - 50), reverse=True)
    print(
        f"  Community: {n_community} datasets in Calibra Cloud for '{policy_family}'.",
        file=sys.stderr,
    )
    for key, better_pct in highlights[:2]:
        rank_str = (
            f"better than {better_pct:.0f}%"
            if better_pct >= 50
            else f"worse than {100 - better_pct:.0f}%"
        )
        print(f"    {key}: {rank_str} of community", file=sys.stderr)


# ── dataset card badges ───────────────────────────────────────────────────────


def badge_url(dataset_id: str, status_key: str) -> Optional[str]:
    """Live badge served by the hosted badge endpoint (kept current by register_badge)."""
    return f"{_BADGE_BASE}/badge/{dataset_id}"


def register_badge(dataset_id: str, status_key: str) -> None:
    """POST certification status to the Calibra badge server (silent, non-blocking)."""
    if sync_disabled():
        return

    from calibra import __version__

    endpoint = os.environ.get("CALIBRA_CLOUD_ENDPOINT", _BADGE_BASE).rstrip("/") + "/v1/badge"
    try:
        payload = json.dumps(
            {"dataset_id": dataset_id, "status": status_key, "calibra_version": __version__}
        ).encode("utf-8")
        req = urllib.request.Request(
            endpoint,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=3):
            pass
    except Exception:
        pass
