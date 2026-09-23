"""
Duplicate Frame Analyzer.

Detects camera frames that are near-identical to the frame immediately
preceding them — a signal that the capture pipeline logged the same image
twice (dropped grab, buffered frame re-emitted, or a stalled sensor driver)
rather than a genuinely new observation.

A transition is a duplicate when (almost) no pixel changed beyond a small
noise tolerance (`repeated_transitions`). This deliberately does *not* use
the mean absolute pixel difference: a small object moving in a low-resolution
frame (e.g. the PushT agent at 96×96) changes only ~0.2% of pixels, which
averages to near zero even though the camera is live, whereas a re-emitted
frame changes no pixels at all. This is a single-frame signal — a *sustained
run* of duplicates is the separate, more severe `CameraFreezeAnalyzer` finding.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np

from calibra.analyzers.base import Analyzer
from calibra.analyzers.task_structure import _threshold_level_upper
from calibra.analyzers.temporal import _bootstrap_ci
from calibra.schema.episode import Episode, EpisodeBatch
from calibra.schema.report import AnalyzerResult, ObservedValue, RiskFlag, RiskLevel

_VISUAL_KEYS = frozenset(["camera", "image", "rgb", "depth", "visual"])

# A pixel "changed" if any channel moved by more than this (0–255 scale). Kept
# low on purpose: sensor noise on a live camera changes most pixels by a few
# levels even when the scene is still, and that noise is what distinguishes a
# live static view from a re-emitted frame. This only absorbs rounding jitter.
_PIXEL_TOLERANCE = 2.0
# A transition is a repeat when fewer than this fraction of pixels changed
# (0.05% ≈ 5 pixels at 96×96, ≈ 150 at 640×480).
_MIN_CHANGED_FRACTION = 5e-4
_DUPLICATE_WARNING = 0.05  # 5% of transitions duplicated
_DUPLICATE_CRITICAL = 0.15  # 15%


def _find_image_obs(ep: Episode) -> Optional[np.ndarray]:
    for key in ep.observations:
        if any(kw in key.lower() for kw in _VISUAL_KEYS):
            candidate = ep.observations[key]
            if candidate.ndim in (3, 4) and len(candidate) >= 2:  # (T, H, W) or (T, H, W, C)
                return candidate
    return None


def repeated_transitions(
    images: np.ndarray,
    pixel_tolerance: float = _PIXEL_TOLERANCE,
    min_changed_fraction: float = _MIN_CHANGED_FRACTION,
) -> np.ndarray:
    """
    Boolean mask, one entry per frame transition: True where the next frame
    repeats the previous one (fewer than `min_changed_fraction` of pixels
    changed by more than `pixel_tolerance` on a 0–255 scale).

    Float images in [0, 1] are rescaled to 0–255. Frames are compared one
    transition at a time so large (T, H, W, C) arrays are never duplicated.
    """
    imgs = np.asarray(images)
    scale = 255.0 if imgs.dtype.kind == "f" and float(imgs.max(initial=0.0)) <= 1.0 else 1.0
    repeated = np.empty(len(imgs) - 1, dtype=bool)
    for t in range(len(imgs) - 1):
        diff = np.abs(imgs[t + 1].astype(np.float32) - imgs[t].astype(np.float32)) * scale
        changed = diff > pixel_tolerance
        if changed.ndim == 3:  # (H, W, C): a pixel changed if any channel did
            changed = changed.any(axis=-1)
        repeated[t] = changed.mean() < min_changed_fraction
    return repeated


def _episode_duplicate_fraction(
    ep: Episode, pixel_tolerance: float, min_changed_fraction: float
) -> Optional[float]:
    images = _find_image_obs(ep)
    if images is None:
        return None
    return float(np.mean(repeated_transitions(images, pixel_tolerance, min_changed_fraction)))


@dataclass
class DuplicateFrameAnalyzer(Analyzer):
    """
    Detects camera frames that are near-identical repeats of the previous frame.

    Parameters
    ----------
    pixel_tolerance      : per-pixel change (0–255 scale) that counts as a real
                           change rather than codec noise.
    min_changed_fraction : a transition with fewer changed pixels than this
                           fraction is a duplicate. Provisional defaults —
                           tune against your own camera if this over- or
                           under-fires.
    warning, critical   : duplicate-frame-rate thresholds for risk level.
    n_bootstrap, ci_level : bootstrap CI parameters, matching TemporalAnalyzer.
    """

    requires = frozenset({"images"})

    pixel_tolerance: float = _PIXEL_TOLERANCE
    min_changed_fraction: float = _MIN_CHANGED_FRACTION
    warning: float = _DUPLICATE_WARNING
    critical: float = _DUPLICATE_CRITICAL
    n_bootstrap: int = 1000
    ci_level: float = 0.95

    @property
    def name(self) -> str:
        return "duplicate_frame"

    def analyze(
        self,
        batch: EpisodeBatch,
        policy_family: Optional[str] = None,
    ) -> AnalyzerResult:
        if batch.n_episodes == 0:
            return AnalyzerResult(analyzer_name=self.name)

        ep_values: list[Optional[float]] = [
            _episode_duplicate_fraction(ep, self.pixel_tolerance, self.min_changed_fraction)
            for ep in batch.episodes
        ]
        checked = [(ep, v) for ep, v in zip(batch.episodes, ep_values) if v is not None]

        if not checked:
            return AnalyzerResult(
                analyzer_name=self.name,
                flags=[
                    RiskFlag(
                        level=RiskLevel.INFO,
                        metric="duplicate_frame_rate",
                        observed=ObservedValue(value=None),
                        interpretation="No decodable camera frames found for this dataset.",
                        implication="Duplicate-frame detection was skipped.",
                    )
                ],
                raw_metrics={"skipped": "no image observations", "episode_values": ep_values},
            )

        arr = np.array([v for _, v in checked])
        stat, lo, hi = _bootstrap_ci(arr, np.mean, self.n_bootstrap, self.ci_level)
        outlier_ids = [
            ep.metadata.episode_id for ep, v in checked if v is not None and v >= self.warning
        ]
        raw = {
            "duplicate_frame_rate": float(stat),
            "ci_lower": float(lo),
            "ci_upper": float(hi),
            "n_episodes_checked": len(checked),
            "episode_values": ep_values,
            "outlier_episode_ids": outlier_ids[:20],
        }

        level = _threshold_level_upper(stat, self.warning, self.critical)
        if level == RiskLevel.OK:
            flag = RiskFlag(
                level=RiskLevel.OK,
                metric="duplicate_frame_rate",
                observed=ObservedValue(
                    value=stat,
                    unit="fraction",
                    ci_lower=lo,
                    ci_upper=hi,
                    ci_level=self.ci_level,
                    ci_method="bootstrap",
                ),
                threshold=self.warning,
                interpretation="Camera frames show expected frame-to-frame variation.",
                implication="No duplicate-frame risk detected.",
                affected_fraction=float(stat),
            )
        else:
            flag = RiskFlag(
                level=level,
                metric="duplicate_frame_rate",
                observed=ObservedValue(
                    value=stat,
                    unit="fraction",
                    ci_lower=lo,
                    ci_upper=hi,
                    ci_level=self.ci_level,
                    ci_method="bootstrap",
                ),
                threshold=self.warning,
                interpretation=(
                    f"{stat:.1%} of camera frame transitions are near-identical to the "
                    f"previous frame, across {len(checked)} episodes with image data."
                ),
                implication=(
                    "Duplicate frames mean the camera pipeline is not capturing a new "
                    "image every control step. Policies trained on repeated frames may "
                    "learn to associate a stale visual observation with the wrong action, "
                    "or waste model capacity encoding redundant frames."
                ),
                affected_fraction=float(stat),
            )

        return AnalyzerResult(analyzer_name=self.name, flags=[flag], raw_metrics=raw)
