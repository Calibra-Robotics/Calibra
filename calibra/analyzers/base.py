"""
Analyzer base class. Every diagnostic module implements this contract.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from calibra.schema.episode import EpisodeBatch
from calibra.schema.report import AnalyzerResult


class DefaultGripperDims(list):
    """
    The default ``gripper_dims`` ([-1], the last action dim), marked as such.

    It behaves exactly like ``[-1]``; the distinct type only lets a dataset
    profile (calibra.dataset_profiles.apply_profile) replace a default the
    caller never chose while leaving an explicit ``[-1]`` alone.
    """


def default_gripper_dims() -> list[int]:
    return DefaultGripperDims([-1])


def parse_gripper_dims(raw: Optional[str]) -> list[int]:
    """
    Parse a ``--gripper-dims`` value: ``None`` (flag omitted) keeps the default,
    ``""`` means no gripper, ``"6,13"`` lists the dims to exclude.
    """
    if raw is None:
        return default_gripper_dims()
    return [int(x) for x in raw.split(",") if x.strip()]


class Analyzer(ABC):
    """
    Stateless diagnostic unit.

    Each analyzer receives an EpisodeBatch, computes metrics, and returns
    an AnalyzerResult containing RiskFlags and optional CompatibilityHints.

    Analyzers must not modify the EpisodeBatch or retain state between calls.
    """

    #: Capability tags (see EpisodeBatch.capabilities) this analyzer needs to
    #: produce anything beyond a no-op. Empty means "always run" — the default
    #: for analyzers that degrade gracefully or report on absence itself.
    requires: frozenset[str] = frozenset()

    #: Bump when this analyzer's metric definitions or thresholds change in a
    #: way that could shift its output on the same input data. Stamped into
    #: DiagnosticReport.analyzer_versions / config_hash so two reports can be
    #: checked for "same analysis logic" before comparing their numbers.
    version: str = "1"

    @abstractmethod
    def analyze(
        self,
        batch: EpisodeBatch,
        policy_family: Optional[str] = None,
    ) -> AnalyzerResult:
        """
        Run diagnostics on `batch`.

        Parameters
        ----------
        batch         : normalized dataset from the ingestion layer.
        policy_family : optional target policy (e.g. "diffusion", "act",
                        "transformer"). When provided, emit CompatibilityHints
                        tailored to that policy's inductive biases.
        """
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        """Short identifier for this analyzer, used in AnalyzerResult."""
        ...
