"""
calibra.dataset_profiles — per-dataset analyzer settings for known datasets.

Some analyzer defaults encode assumptions that do not hold for every dataset.
The main one: smoothness and calibration-drift checks exclude the *last* action
dimension as a gripper (``gripper_dims=[-1]``), which is right for most arm
datasets but wrong for PushT, whose 2-D action is an (x, y) target with no
gripper, so the default silently ignores the y axis.

Rather than change the global default (which would shift every dataset's
scores and published benchmarks), a profile overrides it for the datasets it
names. A profile only replaces analyzer *defaults*: an analyzer explicitly
configured by the caller (e.g. ``calibra compare --gripper-dims``) is left as is.

A profile can also set regime thresholds (``regime_thresholds``), which
``calibra.strategy.diagnose_regime`` applies to reports whose
``dataset_profile`` names it. The global thresholds were calibrated on 50 Hz
arm datasets (ALOHA, DROID-100); PushT's mouse-teleoperated position targets at
10 Hz have a clean velocity-discontinuity rate (16.7%) that is itself above the
global HIGH NOISE cutoff.

Resolution
----------
* Hub IDs listed in a profile (``lerobot/pusht``, ``hf://lerobot/pusht``) get
  it automatically.
* Local copies carry no reliable dataset identity, so pass it explicitly:
  ``calibra prune ./datasets/pusht --profile pusht``.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from typing import Optional

from calibra.analyzers.base import Analyzer


@dataclass(frozen=True)
class DatasetProfile:
    name: str
    datasets: frozenset[str]  # Hub IDs that use this profile automatically
    gripper_dims: Optional[tuple[int, ...]] = None  # None = keep analyzer default
    # Overrides for diagnose_regime thresholds (spike_low, spike_high, disc_low,
    # disc_high); keys left out keep the global values.
    regime_thresholds: dict = field(default_factory=dict, compare=False)
    # Defaults for `calibra prune` Stage 1 limits (max_spike_rate,
    # max_vel_disc_rate) when the user does not pass the matching --max-* flag.
    prune_thresholds: dict = field(default_factory=dict, compare=False)
    notes: str = field(default="", compare=False)


PROFILES: dict[str, DatasetProfile] = {
    "pusht": DatasetProfile(
        name="pusht",
        datasets=frozenset({"lerobot/pusht", "lerobot/pusht_image"}),
        gripper_dims=(),
        # 16.7% velocity discontinuities is PushT's measured clean rate, a property
        # of mouse teleop at 10 Hz (calibra/references/README.md), not corruption.
        # HIGH NOISE starts at ~1.5x that (the reference's own "above 25% is
        # outlying" line) instead of the global 0.13.
        regime_thresholds={"disc_high": 0.25},
        # The global prune limits (spike 0.10, vel_disc 0.25) sit at PushT's own
        # clean p95 (10.4%, 27.5%), so they cut 27 known-clean episodes. Use the
        # limits `analyze` applies to PushT (MODERATE NOISE regime), which clear
        # its clean maximum (16.1%, 37.5%).
        prune_thresholds={"max_spike_rate": 0.25, "max_vel_disc_rate": 0.40},
        notes=(
            "2-D absolute (x, y) target position, no gripper: score smoothness on both "
            "axes, and judge velocity discontinuities against PushT's own clean rate."
        ),
    ),
}


def get_profile(name: str) -> DatasetProfile:
    """Look up a profile by name, with an error listing the valid names."""
    try:
        return PROFILES[name]
    except KeyError:
        raise ValueError(
            f"Unknown dataset profile {name!r}. Available: {sorted(PROFILES)}"
        ) from None


def profile_for_path(path: str) -> Optional[DatasetProfile]:
    """The profile a Hub ID uses automatically, or None (including local paths)."""
    from calibra.anomalies import calibration_dataset_id

    dataset_id = calibration_dataset_id(path)
    if dataset_id is None:
        return None
    return next((p for p in PROFILES.values() if dataset_id in p.datasets), None)


def apply_profile(analyzers: list[Analyzer], profile: Optional[DatasetProfile]) -> list[Analyzer]:
    """
    Return analyzers with the profile's settings applied to any analyzer still
    at its default. Analyzers are copied, never mutated.
    """
    if profile is None or profile.gripper_dims is None:
        return list(analyzers)
    out: list[Analyzer] = []
    for analyzer in analyzers:
        if _is_default(analyzer, "gripper_dims"):
            analyzer = dataclasses.replace(analyzer, gripper_dims=list(profile.gripper_dims))
        out.append(analyzer)
    return out


def add_profile_argument(parser) -> None:
    """Add the shared ``--profile NAME`` option to a command's parser."""
    parser.add_argument(
        "--profile",
        metavar="NAME",
        default=None,
        choices=sorted(PROFILES),
        help=(
            "Dataset profile with analyzer settings for a known dataset "
            f"({', '.join(sorted(PROFILES))}). Applied automatically for its Hub IDs; "
            "pass it for a local copy, e.g. --profile pusht for ./datasets/pusht."
        ),
    )


def _is_default(analyzer: Analyzer, name: str) -> bool:
    if not dataclasses.is_dataclass(analyzer):
        return False
    fld = next((f for f in dataclasses.fields(analyzer) if f.name == name), None)
    if fld is None:
        return False
    if fld.default_factory is not dataclasses.MISSING:
        default = fld.default_factory()
    else:
        default = fld.default
    return getattr(analyzer, name) == default
