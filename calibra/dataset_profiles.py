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

The same arm calibration sets the jerk-spike and velocity-discontinuity flag
thresholds, under which clean PushT reads as Critical. A
profile's ``flag_thresholds`` replace those defaults, so integrity severity is
judged against the dataset's own clean episodes.

Resolution
----------
* Hub IDs listed in a profile (``lerobot/pusht``, ``hf://lerobot/pusht``) get
  it automatically.
* Local copies carry no dataset ID. A profile is applied automatically when the
  copy can be identified with confidence (``detect_local_profile``): its
  ``hf download`` revision is the one the profile was measured on, or its
  dataset card links a covered Hub ID. A matching directory name alone only
  prints a hint. Otherwise pass it explicitly:
  ``calibra prune ./datasets/pusht --profile pusht``.

Evidence
--------
Every profile carries a ``ProfileEvidence`` record: the dataset revision it was
measured on, sampling rate, action space, the clean baseline behind its
thresholds, and the command that reproduces that baseline. The baseline must
match the reference file under ``calibra/references/`` it cites, and each
threshold must clear the clean data it was set on.
``tests/test_dataset_profiles.py`` enforces all of this, so a profile cannot be
added on intuition alone.
"""

from __future__ import annotations

import dataclasses
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from calibra.analyzers.base import Analyzer, DefaultGripperDims, DefaultThreshold


@dataclass(frozen=True)
class ProfileEvidence:
    """The measurements a profile's settings rest on."""

    # Hub revision (commit SHA or tag) the baseline was measured on.
    dataset_revision: str
    sampling_rate_hz: float
    action_space: str
    # Reference file in calibra/references/ holding the full baseline run.
    reference: str
    # Clean per-episode rates from that reference, as
    # {metric: {stat: value}}, e.g. {"vel_disc_rate": {"mean": 0.167, "max": 0.375}}.
    clean_baseline: dict
    # Why each setting departs from the global default.
    justification: str
    # Command that regenerates the reference file.
    reproduce: str


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
    # Overrides for flag severity thresholds, keyed by analyzer field name
    # (ldlj_warning, jerk_spike_critical, vel_disc_warning, ...). Replaces only
    # thresholds still at their default (DefaultThreshold).
    flag_thresholds: dict = field(default_factory=dict, compare=False)
    notes: str = field(default="", compare=False)
    evidence: Optional[ProfileEvidence] = field(default=None, compare=False)


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
        # clean p95 (10.4%, 27.5%), so they remove clean PushT episodes. Use the
        # limits `analyze` applies to PushT (MODERATE NOISE regime), which clear
        # its clean maximum (16.1%, 37.5%).
        prune_thresholds={"max_spike_rate": 0.25, "max_vel_disc_rate": 0.40},
        # The global spike / vel_disc flag thresholds were set on 50 Hz arm data,
        # so clean PushT reads as Critical (vel_disc 16.7%). Judge the dataset
        # mean against PushT's own clean episodes instead: Warning once it is as
        # rough as the clean p95 episode, Critical once it is past the roughest
        # clean episode (the prune limits). LDLJ keeps the global thresholds:
        # per sub-movement, clean PushT is already OK.
        flag_thresholds={
            "jerk_spike_warning": 0.11,
            "jerk_spike_critical": 0.25,
            "vel_disc_warning": 0.28,
            "vel_disc_critical": 0.40,
        },
        notes=(
            "2-D absolute (x, y) target position, no gripper: score smoothness on both "
            "axes, and judge velocity discontinuities against PushT's own clean rate."
        ),
        evidence=ProfileEvidence(
            dataset_revision="7628202a2180972f291ba1bc6723834921e72c19",
            sampling_rate_hz=10.0,
            action_space="2-D absolute (x, y) target position in pixels, mouse teleop, no gripper",
            reference="pusht_velocity_command.json",
            clean_baseline={
                "spike_rate": {"mean": 0.049462, "p95": 0.104099, "max": 0.16129},
                "vel_disc_rate": {"mean": 0.166956, "p95": 0.275348, "max": 0.375},
            },
            justification=(
                "gripper_dims=(): the last action dim is the y target, not a gripper. "
                "disc_high=0.25: the clean mean (16.7%) is above the global 0.13, so "
                "HIGH NOISE starts at ~1.5x the clean mean. Prune limits: the global "
                "limits sit at the clean p95 and remove clean episodes; 0.25/0.40 "
                "clear the clean max (16.1%, 37.5%). Flag thresholds: the global "
                "spike / vel_disc thresholds rate clean PushT Critical; Warning sits "
                "at the clean p95 episode, Critical past the clean max."
            ),
            reproduce=(
                "python scripts/profile_pusht.py --dataset lerobot/pusht "
                "--out calibra/references/pusht_velocity_command.json"
            ),
        ),
    ),
    "aloha": DatasetProfile(
        name="aloha",
        # The ALOHA references measured with both grippers excluded (2026-10-19).
        # Other ALOHA datasets share the layout; pass --profile aloha for them.
        datasets=frozenset(
            {
                "lerobot/aloha_mobile_cabinet",
                "lerobot/aloha_mobile_shrimp",
                "lerobot/aloha_sim_insertion_human",
                "lerobot/aloha_sim_insertion_scripted",
                "lerobot/aloha_sim_transfer_cube_human",
                "lerobot/aloha_sim_transfer_cube_scripted",
                "lerobot/aloha_static_battery",
                "lerobot/aloha_static_candy",
                "lerobot/aloha_static_coffee",
                "lerobot/aloha_static_cups_open",
            }
        ),
        # 14-D action = 6 joints + gripper per arm: grippers at 6 and 13. The
        # default [-1] excludes only the right gripper and scores the left one
        # as a joint.
        gripper_dims=(6, 13),
        notes=(
            "Bimanual ALOHA: 6 joints + gripper per arm. Exclude both grippers "
            "(dims 6 and 13) from smoothness and calibration-drift checks."
        ),
        evidence=ProfileEvidence(
            dataset_revision="cc571a3c661df81b566dbfde3d5c1e85fcdf7884",
            sampling_rate_hz=50.0,
            action_space=(
                "14-D joint positions: [left 6 joints, left gripper, right 6 joints, right gripper]"
            ),
            reference="aloha_sim_insertion_human.json",
            clean_baseline={
                "spike_rate": {"mean": 0.003541, "p95": 0.010262, "max": 0.020121},
                "vel_disc_rate": {"mean": 0.014538, "p95": 0.035241, "max": 0.048193},
            },
            justification=(
                "gripper_dims=(6, 13): in the ALOHA/ACT action layout dims 6 and 13 are "
                "the grippers; in aloha_sim_insertion_human they span 0..1 and sit at "
                "their ends far more often than the joint dims (26% and 33% of steps vs "
                "3-11%). No thresholds are changed."
            ),
            reproduce=(
                "python scripts/profile_dataset.py lerobot/aloha_sim_insertion_human "
                "--control-mode position --gripper-dims 6,13 "
                "--out calibra/references/aloha_sim_insertion_human.json"
            ),
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
    """
    The profile a dataset uses automatically: by Hub ID, or for a local copy
    when ``detect_local_profile`` identifies it with confidence. None otherwise.
    """
    from calibra.anomalies import calibration_dataset_id

    dataset_id = calibration_dataset_id(path)
    if dataset_id is not None:
        return next((p for p in PROFILES.values() if dataset_id in p.datasets), None)
    return detect_local_profile(path).profile


@dataclass(frozen=True)
class LocalProfileDetection:
    profile: Optional[DatasetProfile] = None  # set only for a confident match
    reason: Optional[str] = None  # why the profile applies, or a hint when it does not


_CARD_REPO_RE = re.compile(
    r"(?:huggingface\.co/datasets/|[?&]path=)([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)"
)


def detect_local_profile(path: str) -> LocalProfileDetection:
    """
    Identify a known dataset from a local copy's own files.

    Local copies carry no dataset ID, so a profile used to be silently skipped
    for them (on lerobot/pusht that meant 48 Stage-1 drops instead of 0). Two
    signals are confident enough to apply a profile:

    1. ``hf download`` cache: the commit SHA recorded for the downloaded files
       equals the revision a profile's evidence was measured on.
    2. The dataset card (README.md) links a Hub ID the profile covers
       (``huggingface.co/datasets/<org>/<name>`` or ``path=<org>/<name>``).

    A directory named like a profiled dataset (e.g. ``pusht``) is only a hint:
    nothing is applied and the reason suggests ``--profile``.
    """
    root = Path(path).expanduser()
    if not root.is_dir():
        return LocalProfileDetection()

    revisions = _downloaded_revisions(root)
    for profile in PROFILES.values():
        ev = profile.evidence
        if ev is not None and ev.dataset_revision in revisions:
            return LocalProfileDetection(
                profile,
                f"downloaded at revision {ev.dataset_revision[:8]}, the revision the "
                f"'{profile.name}' profile was measured on",
            )

    card = root / "README.md"
    if card.is_file():
        try:
            text = card.read_text(encoding="utf-8", errors="replace")
        except OSError:
            text = ""
        for repo in _CARD_REPO_RE.findall(text):
            for profile in PROFILES.values():
                if repo in profile.datasets:
                    return LocalProfileDetection(
                        profile,
                        f"dataset card names {repo}, covered by the '{profile.name}' profile",
                    )

    name = root.resolve().name.lower()
    for profile in PROFILES.values():
        if any(ds.split("/")[-1].lower() == name for ds in profile.datasets):
            return LocalProfileDetection(
                None,
                f"directory '{root.name}' looks like a dataset covered by the "
                f"'{profile.name}' profile; if it is, pass --profile {profile.name}",
            )
    return LocalProfileDetection()


def _downloaded_revisions(root: Path) -> set[str]:
    """Commit SHAs recorded by `hf download` for files in a local copy."""
    revisions: set[str] = set()
    download = root / ".cache" / "huggingface" / "download"
    if not download.is_dir():
        return revisions
    for meta in download.rglob("*.metadata"):
        try:
            first = meta.read_text(encoding="utf-8").splitlines()[0].strip()
        except (OSError, IndexError, UnicodeDecodeError):
            continue
        if re.fullmatch(r"[0-9a-f]{40}", first):
            revisions.add(first)
    return revisions


def apply_profile(analyzers: list[Analyzer], profile: Optional[DatasetProfile]) -> list[Analyzer]:
    """
    Return analyzers with the profile's settings applied to any analyzer still
    at its default. Analyzers are copied, never mutated.
    """
    if profile is None:
        return list(analyzers)
    out: list[Analyzer] = []
    for analyzer in analyzers:
        # Only marked defaults are replaced: an explicit gripper_dims or
        # threshold, even one equal to the default, is the caller's choice.
        changes: dict = {}
        if profile.gripper_dims is not None and isinstance(
            getattr(analyzer, "gripper_dims", None), DefaultGripperDims
        ):
            changes["gripper_dims"] = list(profile.gripper_dims)
        for name, value in profile.flag_thresholds.items():
            if isinstance(getattr(analyzer, name, None), DefaultThreshold):
                changes[name] = value
        if changes:
            analyzer = dataclasses.replace(analyzer, **changes)
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
