"""
Camera View Mismatch Analyzer.

Detects camera streams whose *declared name* contradicts how the footage
actually behaves — the classic case being a stream named `images.laptop`
(or `camera_top`) that is physically an eye-in-hand / wrist camera, or a
stream named `camera_wrist` that is really a fixed third-person view.

Why this matters: the viewpoint a policy expects is encoded in the feature
name. A downstream training run that maps `observation.images.top` to "the
static overhead view" will silently learn from egomotion-dominated wrist
footage if the name lies, and the mismatch only surfaces as poor real-world
transfer much later.

Detection primitive (dependency-free, numpy only)
-------------------------------------------------
A wrist / eye-in-hand camera is rigidly attached to the arm, so when the arm
moves the *entire frame* shifts — its per-frame visual activity (mean absolute
inter-frame pixel difference, `compute_visual_activity`) is strongly correlated
with the magnitude of the robot's action. A fixed camera only sees a small,
local region change (the gripper / object), so its whole-frame activity tracks
arm motion much more weakly. We call this per-camera scalar the *egomotion
correlation* r ∈ [-1, 1].

The check is deliberately built to avoid a universal "wrist means r > X"
magic number — the same pitfall `BlurAnalyzer` and `CalibrationDriftAnalyzer`
call out. The primary signal is *relative*: within one dataset the eye-in-hand
camera must track arm motion more than any fixed camera, so a static-named
camera whose r exceeds a wrist-named camera's r is an internal contradiction
that needs no calibration. Absolute advisory bands only backstop cases the
relative check can't see (a single-camera dataset, or an ambiguously named
stream like `laptop`/`webcam`).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

import numpy as np

from calibra.analyzers.base import Analyzer
from calibra.schema.episode import Episode, EpisodeBatch
from calibra.schema.report import AnalyzerResult, ObservedValue, RiskFlag, RiskLevel

# Image-like observation keys (mirrors EpisodeBatch._IMAGE_TOKENS).
_IMAGE_TOKENS = ("camera", "image", "rgb", "depth", "visual", "cam")

# Name tokens that assert a viewpoint. Matched as whole tokens (not substrings)
# so that "laptop" is NOT read as static via the "top" it contains — that stream
# is exactly the ambiguous case we want the signal, not the name, to classify.
_MOVING_TOKENS = frozenset(
    {"wrist", "gripper", "hand", "eih", "eyeinhand", "inhand", "eye", "handeye"}
)
_STATIC_TOKENS = frozenset(
    {
        "top",
        "bottom",
        "front",
        "back",
        "rear",
        "left",
        "right",
        "side",
        "overhead",
        "birdview",
        "bird",
        "high",
        "low",
        "center",
        "centre",
        "angled",
        "angle",
        "diagonal",
        "agentview",
        "external",
        "exo",
        "exterior",
        "third",
        "thirdperson",
        "fixed",
        "base",
        "scene",
        "room",
        "table",
        "corner",
    }
)
# Non-informative words stripped before classification; a key made only of these
# (e.g. "camera_main", "images.rgb") is left UNKNOWN for the signal to resolve.
_GENERIC_TOKENS = frozenset(
    {
        "camera",
        "cam",
        "image",
        "images",
        "img",
        "obs",
        "observation",
        "observations",
        "rgb",
        "depth",
        "color",
        "colour",
        "video",
        "main",
        "default",
        "0",
        "1",
        "2",
        "3",
    }
)

_MOVING = "moving"
_STATIC = "static"
_UNKNOWN = "unknown"

_MIN_FRAMES = 6  # frames needed in a stream to estimate egomotion correlation
_MIN_TRANSITIONS = 5  # aligned frame/action transitions needed for a correlation
_MIN_EPISODES = 3  # episodes contributing a correlation before a camera is judged

# Advisory absolute bands (provisional — the relative check is the primary,
# calibration-free signal; these only backstop single-camera / ambiguous cases).
_HIGH_CORR = 0.5  # a supposedly fixed camera this coupled to arm motion looks wrist-mounted
_LOW_CORR = 0.15  # a supposedly wrist camera this decoupled looks fixed
_RELATIVE_MARGIN = 0.1  # min r gap before a static>moving ordering is called a contradiction

_METRIC = "camera_view_name_mismatch"


def _tokenize(key: str) -> list[str]:
    return [t for t in re.split(r"[^a-z0-9]+", key.lower()) if t]


def declared_viewpoint(key: str) -> str:
    """Classify a camera key's *declared* viewpoint from its name alone.

    Returns "moving" (wrist / eye-in-hand), "static" (fixed mount), or
    "unknown" (name carries no viewpoint, e.g. `camera_main`, `images.laptop`).
    Moving wins ties — an eye-in-hand designation is the stronger claim.
    """
    tokens = set(_tokenize(key)) - _GENERIC_TOKENS
    if tokens & _MOVING_TOKENS:
        return _MOVING
    if tokens & _STATIC_TOKENS:
        return _STATIC
    return _UNKNOWN


def _iter_camera_obs(ep: Episode):
    """Yield (key, images) for every image-like observation stream in `ep`."""
    for key, arr in ep.observations.items():
        if any(tok in key.lower() for tok in _IMAGE_TOKENS):
            if isinstance(arr, np.ndarray) and arr.ndim in (3, 4) and len(arr) >= 2:
                yield key, arr


def compute_egomotion_correlation(images: np.ndarray, actions: np.ndarray) -> Optional[float]:
    """Pearson correlation between whole-frame visual activity and action motion.

    High when the frame moves with the arm (wrist / eye-in-hand camera), low
    when the camera is fixed. Returns None when there is too little data or
    either signal is constant (no motion to correlate against).
    """
    from calibra.temporal.drift import compute_visual_activity

    imgs = np.asarray(images)
    if imgs.ndim not in (3, 4) or len(imgs) < _MIN_FRAMES:
        return None

    act = np.asarray(actions, dtype=np.float64)
    if act.ndim == 1:
        act = act[:, None]
    if act.ndim != 2 or len(act) < 2:
        return None

    visual = compute_visual_activity(imgs)  # (T-1,)
    action_motion = np.linalg.norm(np.diff(act, axis=0), axis=1)  # (T'-1,)

    n = min(len(visual), len(action_motion))
    if n < _MIN_TRANSITIONS:
        return None
    visual = visual[:n]
    action_motion = action_motion[:n]

    if np.std(visual) < 1e-9 or np.std(action_motion) < 1e-9:
        return None
    r = float(np.corrcoef(visual, action_motion)[0, 1])
    return r if np.isfinite(r) else None


def _skip(reason: str) -> AnalyzerResult:
    return AnalyzerResult(
        analyzer_name="camera_view",
        flags=[
            RiskFlag(
                level=RiskLevel.INFO,
                metric=_METRIC,
                observed=ObservedValue(value=None),
                interpretation=reason,
                implication="Camera-view naming check was skipped.",
            )
        ],
        raw_metrics={"skipped": reason},
    )


@dataclass
class CameraViewMismatchAnalyzer(Analyzer):
    """
    Flags camera streams whose declared viewpoint (from the feature name)
    contradicts their motion signature — e.g. a `camera_top` stream that moves
    with the arm like a wrist camera, or vice-versa.

    Parameters
    ----------
    min_episodes  : episodes that must yield a valid correlation before a
                    camera is judged (guards against a one-off noisy episode).
    high_corr,
    low_corr      : advisory absolute bands (provisional). Only used to backstop
                    cases the relative check can't see (single-camera datasets,
                    ambiguously named streams).
    relative_margin : minimum r gap before a static-named camera outscoring a
                    wrist-named one is reported as a naming contradiction.
    """

    requires = frozenset({"images"})

    min_episodes: int = _MIN_EPISODES
    high_corr: float = _HIGH_CORR
    low_corr: float = _LOW_CORR
    relative_margin: float = _RELATIVE_MARGIN

    @property
    def name(self) -> str:
        return "camera_view"

    def analyze(
        self,
        batch: EpisodeBatch,
        policy_family: Optional[str] = None,
    ) -> AnalyzerResult:
        if batch.n_episodes == 0:
            return AnalyzerResult(analyzer_name=self.name)

        # Gather per-camera egomotion correlations across episodes.
        per_camera: dict[str, list[float]] = {}
        for ep in batch.episodes:
            for key, images in _iter_camera_obs(ep):
                r = compute_egomotion_correlation(images, ep.actions)
                if r is not None:
                    per_camera.setdefault(key, []).append(r)

        if not per_camera:
            return _skip("No camera stream had enough moving frames to judge viewpoint.")

        cameras = [
            {
                "key": key,
                "declared": declared_viewpoint(key),
                "corr": float(np.median(rs)),
                "n_episodes": len(rs),
            }
            for key, rs in per_camera.items()
            if len(rs) >= self.min_episodes
        ]
        if not cameras:
            return _skip(
                f"No camera stream had ≥{self.min_episodes} episodes with usable "
                "motion to estimate a viewpoint."
            )

        raw = {
            "cameras": cameras,
            "n_cameras_checked": len(cameras),
        }

        flags: list[RiskFlag] = []
        flagged_keys: set[str] = set()

        # ── 1. Relative check (primary, calibration-free) ─────────────────────
        # Within one dataset the wrist camera must track arm motion more than any
        # fixed camera. A static-named camera outscoring a wrist-named one by more
        # than the margin is an internal contradiction — no absolute cutoff needed.
        moving = [c for c in cameras if c["declared"] == _MOVING]
        static = [c for c in cameras if c["declared"] == _STATIC]
        if moving and static:
            worst_moving = min(moving, key=lambda c: c["corr"])
            best_static = max(static, key=lambda c: c["corr"])
            if best_static["corr"] > worst_moving["corr"] + self.relative_margin:
                flagged_keys.update({best_static["key"], worst_moving["key"]})
                flags.append(
                    RiskFlag(
                        level=RiskLevel.WARNING,
                        metric=_METRIC,
                        observed=ObservedValue(value=best_static["corr"], unit="correlation"),
                        threshold=worst_moving["corr"],
                        interpretation=(
                            f"Stream '{best_static['key']}' is named as a fixed view but its "
                            f"footage tracks arm motion more strongly (r={best_static['corr']:.2f}) "
                            f"than the wrist-named stream '{worst_moving['key']}' "
                            f"(r={worst_moving['corr']:.2f}). Within one rig the eye-in-hand "
                            f"camera should be the most motion-coupled — these names look swapped "
                            f"or mislabeled."
                        ),
                        implication=(
                            "A policy that expects '{s}' to be a static viewpoint would be "
                            "trained on egomotion-dominated footage instead, degrading real-world "
                            "transfer. Verify the camera-to-name assignment.".format(
                                s=best_static["key"]
                            )
                        ),
                    )
                )

        # ── 2. Absolute advisory bands (backstop) ─────────────────────────────
        for c in cameras:
            if c["key"] in flagged_keys:
                continue
            key, declared, r = c["key"], c["declared"], c["corr"]
            if declared == _STATIC and r >= self.high_corr:
                flags.append(
                    RiskFlag(
                        level=RiskLevel.WARNING,
                        metric=_METRIC,
                        observed=ObservedValue(value=r, unit="correlation"),
                        threshold=self.high_corr,
                        interpretation=(
                            f"Stream '{key}' is named as a fixed/overhead view, but its whole "
                            f"frame moves with the arm (egomotion correlation r={r:.2f}). That is "
                            f"the signature of a wrist / eye-in-hand camera, not a fixed one."
                        ),
                        implication=(
                            "The feature name likely misrepresents the mounting. Confirm whether "
                            "this is actually a wrist camera before training a viewpoint-sensitive "
                            "policy on it."
                        ),
                    )
                )
                flagged_keys.add(key)
            elif declared == _UNKNOWN and r >= self.high_corr:
                flags.append(
                    RiskFlag(
                        level=RiskLevel.INFO,
                        metric=_METRIC,
                        observed=ObservedValue(value=r, unit="correlation"),
                        threshold=self.high_corr,
                        interpretation=(
                            f"Stream '{key}' has a name that carries no viewpoint, but its footage "
                            f"tracks arm motion (r={r:.2f}) like a wrist / eye-in-hand camera."
                        ),
                        implication=(
                            f"Consider renaming '{key}' to a canonical wrist name (e.g. "
                            "camera_wrist) so downstream tooling reads the viewpoint correctly."
                        ),
                    )
                )
                flagged_keys.add(key)
            elif declared == _MOVING and r <= self.low_corr:
                flags.append(
                    RiskFlag(
                        level=RiskLevel.INFO,
                        metric=_METRIC,
                        observed=ObservedValue(value=r, unit="correlation"),
                        threshold=self.low_corr,
                        interpretation=(
                            f"Stream '{key}' is named as a wrist / eye-in-hand camera, but its "
                            f"frame barely tracks arm motion (r={r:.2f})."
                        ),
                        implication=(
                            "This may be a fixed camera mislabeled as a wrist view — or simply an "
                            "episode set where the arm rarely moves. Inspect before relying on the "
                            "viewpoint implied by the name."
                        ),
                    )
                )
                flagged_keys.add(key)

        if not flags:
            return AnalyzerResult(
                analyzer_name=self.name,
                flags=[
                    RiskFlag(
                        level=RiskLevel.OK,
                        metric=_METRIC,
                        observed=ObservedValue(value=0.0, unit="fraction"),
                        interpretation=(
                            f"All {len(cameras)} camera stream(s) behave consistently with the "
                            f"viewpoint implied by their names."
                        ),
                        implication="No camera-view naming mismatch detected.",
                        affected_fraction=0.0,
                    )
                ],
                raw_metrics=raw,
            )

        affected_fraction = len(flagged_keys) / len(cameras)
        for flag in flags:
            flag.affected_fraction = affected_fraction
        raw["flagged_camera_keys"] = sorted(flagged_keys)
        return AnalyzerResult(analyzer_name=self.name, flags=flags, raw_metrics=raw)
