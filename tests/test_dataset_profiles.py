"""Tests for calibra.dataset_profiles (per-dataset analyzer settings)."""

from __future__ import annotations

import argparse

import numpy as np
import pytest

from calibra.analyzers.calibration_drift import CalibrationDriftAnalyzer
from calibra.analyzers.smoothness import ControlSmoothnessAnalyzer
from calibra.analyzers.temporal import TemporalAnalyzer
from calibra.dataset_profiles import (
    PROFILES,
    add_profile_argument,
    apply_profile,
    get_profile,
    profile_for_path,
)
from calibra.pipeline import Pipeline
from calibra.schema.episode import Episode, EpisodeBatch, EpisodeMetadata


def _batch(source_path: str, n: int = 6, T: int = 120) -> EpisodeBatch:
    """2-D (x, y) actions: x is smooth, y has jerk spikes (PushT-shaped)."""
    t = np.arange(T, dtype=np.float64) * 0.1
    episodes = []
    for i in range(n):
        acts = np.stack([np.sin(t), np.cos(t)], axis=1) * 100.0
        acts[20::15, 1] += 30.0  # spikes on the y axis only
        episodes.append(
            Episode(
                metadata=EpisodeMetadata(episode_id=str(i)),
                timestamps=t,
                observations={"state": acts.copy()},
                actions=acts,
            )
        )
    return EpisodeBatch(
        episodes=episodes, dataset_name="pusht", format="lerobot", source_path=source_path
    )


def _spike_rate(report) -> float:
    result = next(r for r in report.analyzer_results if r.analyzer_name == "control_smoothness")
    return result.raw_metrics["jerk_spikes"]["mean_spike_fraction"]


class TestResolution:
    @pytest.mark.parametrize("path", ["lerobot/pusht", "hf://lerobot/pusht", "lerobot/pusht_image"])
    def test_pusht_hub_ids(self, path):
        assert profile_for_path(path) is PROFILES["pusht"]

    @pytest.mark.parametrize(
        "path", ["./datasets/pusht", "lerobot/aloha_sim_insertion_human", "demos.hdf5"]
    )
    def test_no_profile(self, path):
        assert profile_for_path(path) is None

    def test_unknown_name(self):
        with pytest.raises(ValueError, match="Available"):
            get_profile("nope")

    def test_cli_argument(self):
        p = argparse.ArgumentParser()
        add_profile_argument(p)
        assert p.parse_args(["--profile", "pusht"]).profile == "pusht"
        assert p.parse_args([]).profile is None
        with pytest.raises(SystemExit):
            p.parse_args(["--profile", "nope"])


class TestApplyProfile:
    def test_overrides_defaults_only(self):
        explicit = ControlSmoothnessAnalyzer(gripper_dims=[0])
        default = ControlSmoothnessAnalyzer()
        drift = CalibrationDriftAnalyzer()
        temporal = TemporalAnalyzer()
        out = apply_profile([explicit, default, drift, temporal], PROFILES["pusht"])
        assert out[0].gripper_dims == [0]  # caller's explicit choice wins
        assert out[1].gripper_dims == []
        assert out[2].gripper_dims == []
        assert out[3] is temporal  # no gripper_dims: untouched
        assert default.gripper_dims == [-1]  # originals are not mutated

    def test_no_profile_is_identity(self):
        a = ControlSmoothnessAnalyzer()
        assert apply_profile([a], None) == [a]


class TestPipeline:
    def test_hub_id_applies_profile(self):
        # With the default gripper_dims=[-1], the y axis (and its spikes) is ignored.
        with_profile = Pipeline().run(_batch("lerobot/pusht"))
        without = Pipeline().run(_batch("./datasets/pusht"))
        assert with_profile.dataset_profile == "pusht"
        assert without.dataset_profile is None
        assert _spike_rate(without) == 0.0
        assert _spike_rate(with_profile) > 0.0
        assert with_profile.config_hash != without.config_hash

    def test_explicit_profile_for_local_copy(self):
        hub = Pipeline().run(_batch("lerobot/pusht"))
        local = Pipeline(profile="pusht").run(_batch("./datasets/pusht"))
        assert local.dataset_profile == "pusht"
        assert _spike_rate(local) == _spike_rate(hub)

    def test_profile_is_part_of_cache_key(self, tmp_path):
        from calibra.cache import AuditCache

        cache = AuditCache(str(tmp_path))
        batch = _batch("./datasets/pusht")
        plain = Pipeline().run(batch, cache=cache)
        profiled = Pipeline(profile="pusht").run(batch, cache=cache)
        assert plain.dataset_profile is None
        assert profiled.dataset_profile == "pusht"


class TestRegimeThresholds:
    """The profile's regime thresholds apply only to reports that carry it."""

    @staticmethod
    def _report(profile=None, spike=0.049, disc=0.167):
        from calibra.schema.report import AnalyzerResult, DiagnosticReport

        smooth = AnalyzerResult(
            analyzer_name="control_smoothness",
            raw_metrics={
                "jerk_spikes": {"mean_spike_fraction": spike},
                "vel_discontinuities": {"mean_disc_fraction": disc},
            },
        )
        return DiagnosticReport(
            dataset_name="pusht",
            source_path="lerobot/pusht",
            format="lerobot",
            n_episodes=206,
            n_samples=25650,
            analyzer_results=[smooth],
            dataset_profile=profile,
        )

    def test_global_thresholds_call_pusht_high_noise(self):
        from calibra.strategy import SelectionRegime, diagnose_regime

        diagnosis = diagnose_regime(self._report())
        assert diagnosis.regime == SelectionRegime.HIGH_NOISE
        assert diagnosis.evidence["thresholds"]["disc_high"] == 0.13

    def test_pusht_profile_judges_against_its_clean_rate(self):
        from calibra.strategy import SelectionRegime, diagnose_regime

        diagnosis = diagnose_regime(self._report(profile="pusht"))
        assert diagnosis.regime == SelectionRegime.MODERATE_NOISE
        assert diagnosis.evidence["thresholds"]["disc_high"] == 0.25
        assert "dataset profile 'pusht'" in diagnosis.explanation
        # Well above PushT's own clean rate is still HIGH NOISE.
        noisy = diagnose_regime(self._report(profile="pusht", disc=0.30))
        assert noisy.regime == SelectionRegime.HIGH_NOISE

    def test_explicit_thresholds_override_profile(self):
        from calibra.strategy import SelectionRegime, diagnose_regime

        diagnosis = diagnose_regime(
            self._report(profile="pusht"), custom_thresholds={"disc_high": 0.10}
        )
        assert diagnosis.regime == SelectionRegime.HIGH_NOISE

    def test_global_thresholds_unchanged(self):
        from calibra.strategy import _NOISE_DISC_HIGH, _NOISE_SPIKE_HIGH

        assert (_NOISE_SPIKE_HIGH, _NOISE_DISC_HIGH) == (0.090, 0.130)


class TestProfileReachesAllSmoothnessChecks:
    def test_pi0_smoothness_uses_profile(self):
        # Pi0CompatibilityAnalyzer runs its own smoothness check internally.
        report = Pipeline().run(_batch("lerobot/pusht"), policy_family="pi0")
        by_name = {r.analyzer_name: r.raw_metrics for r in report.analyzer_results}
        pi0 = next(v for k, v in by_name.items() if "pi0" in k)
        assert pi0["mean_ldlj"] == by_name["control_smoothness"]["ldlj"]["mean_ldlj"]

    def test_serve_accepts_profile_for_local_path(self, monkeypatch):
        pytest.importorskip("fastapi")
        pytest.importorskip("httpx")
        from fastapi.testclient import TestClient

        import calibra.ingestion.registry as registry
        from calibra.serve import _make_app

        monkeypatch.setattr(registry, "load", lambda path, reader=None: _batch(path))
        client = TestClient(_make_app())

        def spike_pct(**body):
            resp = client.post("/analyze", json={"path": "./datasets/pusht", **body})
            assert resp.status_code == 200, resp.text
            return resp.json()

        plain, profiled = spike_pct(), spike_pct(profile="pusht")
        assert plain != profiled  # y-axis spikes only count with the profile


def test_serve_post_endpoints_read_json_bodies():
    # `from __future__ import annotations` in serve.py once turned every request
    # model (defined inside _make_app) into an unresolvable string, so FastAPI
    # expected a `req` query parameter and every POST returned 422.
    pytest.importorskip("fastapi")
    from calibra.serve import _make_app

    app = _make_app()
    posts = [r for r in app.routes if "POST" in getattr(r, "methods", set())]
    assert posts
    for route in posts:
        query = [p.name for p in route.dependant.query_params]
        assert query == [], f"{route.path} expects query params {query}"
        assert route.dependant.body_params, f"{route.path} has no JSON body"


class TestPruneLimits:
    @staticmethod
    def _limits(monkeypatch, tmp_path, capsys, *argv):
        import calibra.ingestion.registry as registry
        from calibra.prune import run_prune

        monkeypatch.setattr(registry, "load", lambda path, reader=None: _batch(path))
        run_prune([*argv, "--keep", "0.5", "--policy", "act", "--out", str(tmp_path / "c.json")])
        return capsys.readouterr().err

    def test_profile_sets_stage1_limits(self, monkeypatch, tmp_path, capsys):
        err = self._limits(monkeypatch, tmp_path, capsys, "lerobot/pusht")
        assert "[profile pusht] Stage 1 limits: max_spike_rate=0.25, max_vel_disc_rate=0.40" in err

    def test_explicit_flag_beats_profile(self, monkeypatch, tmp_path, capsys):
        err = self._limits(
            monkeypatch, tmp_path, capsys, "lerobot/pusht", "--max-vel-disc-rate", "0.2"
        )
        assert "max_spike_rate=0.25, max_vel_disc_rate=0.20" in err

    def test_no_profile_keeps_global_limits(self, monkeypatch, tmp_path, capsys):
        err = self._limits(monkeypatch, tmp_path, capsys, "./datasets/pusht")
        assert "[profile" not in err
