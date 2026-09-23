"""Unit tests for the visual HTML report generator."""

from __future__ import annotations

import tempfile
from pathlib import Path

import numpy as np

from calibra.anomalies import EpisodeAnomaly, EpisodeFlag
from calibra.pipeline import Pipeline
from calibra.report_html import generate_html_report
from calibra.schema.episode import Episode, EpisodeBatch, EpisodeMetadata
from calibra.schema.report import RiskLevel


def _make_batch(
    n_eps: int = 3, n_steps: int = 20, dataset_name: str = "html_test_ds"
) -> EpisodeBatch:
    rng = np.random.default_rng(42)
    episodes = []
    for i in range(n_eps):
        ts = np.arange(n_steps, dtype=np.float64) * 0.1
        acts = rng.uniform(-1, 1, (n_steps, 2)).astype(np.float32)
        obs = {
            "proprio": rng.uniform(-1, 1, (n_steps, 4)).astype(np.float32),
            "force_torque": rng.normal(0, 1, (n_steps, 6)).astype(np.float32),
            "contact_sensor": rng.uniform(0, 1, n_steps).astype(np.float32),
        }
        episodes.append(
            Episode(
                metadata=EpisodeMetadata(episode_id=f"ep_{i}"),
                timestamps=ts,
                observations=obs,
                actions=acts,
            )
        )
    return EpisodeBatch(
        episodes=episodes,
        dataset_name=dataset_name,
        format="hdf5",
        source_path="/tmp/html_test.h5",
    )


class TestReportHTML:
    def test_generate_html_report_creates_file(self):
        batch = _make_batch()
        report = Pipeline().run(batch)

        with tempfile.TemporaryDirectory() as tmpdir:
            out_file = Path(tmpdir) / "report.html"

            # Build a fake anomaly using the new EpisodeAnomaly interface
            flag = EpisodeFlag(
                episode_idx=0,
                episode_id="ep_0",
                metric="ldlj",
                observed=-15.0,
                median=-5.0,
                deviation_mads=4.5,
                higher_is_worse=False,
            )
            anomaly = EpisodeAnomaly(episode_idx=0, episode_id="ep_0", flags=[flag])

            # Run generator
            generate_html_report(report, str(out_file), outliers=[anomaly])

            # Check file exists and has content
            assert out_file.exists()
            content = out_file.read_text(encoding="utf-8")

            # Assert Tailwind, Chart.js, and dataset name are embedded
            assert "<!DOCTYPE html>" in content
            assert "tailwindcss" in content
            assert "Chart.js" in content
            assert "html_test_ds" in content
            assert "ep_0" in content
            assert "ssl_trajectory_outliers" in content
            assert "contact_dropout" in content

    def test_untrusted_text_is_escaped(self):
        batch = _make_batch(dataset_name="<img src=x onerror=alert(1)>")
        report = Pipeline().run(batch)

        flag = EpisodeFlag(
            episode_idx=0,
            episode_id="</script><script>alert(1)</script>",
            metric="ldlj",
            observed=-15.0,
            median=-5.0,
            deviation_mads=4.5,
            higher_is_worse=False,
        )
        anomaly = EpisodeAnomaly(episode_idx=0, episode_id=flag.episode_id, flags=[flag])

        with tempfile.TemporaryDirectory() as tmpdir:
            out_file = Path(tmpdir) / "report.html"
            generate_html_report(report, str(out_file), outliers=[anomaly])
            content = out_file.read_text(encoding="utf-8")

        assert "<img src=x" not in content
        assert "&lt;img src=x" in content
        assert "</script><script>alert" not in content
        assert "function esc(" in content

    def test_finding_count_excludes_ok_and_info(self):
        report = Pipeline().run(_make_batch())
        n_findings = len(report.flags_at_level(RiskLevel.CRITICAL)) + len(
            report.flags_at_level(RiskLevel.WARNING)
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            out_file = Path(tmpdir) / "report.html"
            generate_html_report(report, str(out_file))
            content = out_file.read_text(encoding="utf-8")

        assert (
            f"{n_findings} warning or critical finding(s) out of {len(report.flags)} checks"
            in content
        )
        assert "Calibra Report —" not in content
