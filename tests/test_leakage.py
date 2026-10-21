"""Tests for `calibra leakage` (calibra/leakage.py)."""

from __future__ import annotations

import json
from unittest.mock import patch

import numpy as np
import pytest

from calibra.leakage import (
    _binom_tail,
    _parse_holdout,
    find_leakage,
    find_leakage_holdout,
    run_leakage,
)
from calibra.schema.episode import Episode, EpisodeBatch, EpisodeMetadata


def _episode(seed: int, ep_id: str | None = None, n_steps: int = 80) -> Episode:
    """Smooth, seed-specific trajectory: a few random sinusoids per dim."""
    rng = np.random.default_rng(seed)
    t = np.linspace(0.0, 1.0, n_steps)
    freqs = rng.uniform(0.5, 2.0, size=(3, 4))
    phases = rng.uniform(0, 2 * np.pi, size=(3, 4))
    amps = rng.uniform(0.5, 1.5, size=(3, 4))
    acts = sum(amps[i] * np.sin(2 * np.pi * freqs[i] * t[:, None] + phases[i]) for i in range(3))
    return Episode(
        metadata=EpisodeMetadata(episode_id=ep_id or str(seed)),
        timestamps=t * 8.0,
        observations={"proprio": (acts * 0.9 + 0.1).astype(np.float32)},
        actions=acts.astype(np.float32),
    )


def _copy(ep: Episode, ep_id: str, noise: float = 0.0, n_steps: int | None = None) -> Episode:
    rng = np.random.default_rng(1234)

    def tweak(arr: np.ndarray) -> np.ndarray:
        arr = np.asarray(arr, dtype=np.float64)
        if n_steps is not None:
            src = np.linspace(0, 1, len(arr))
            dst = np.linspace(0, 1, n_steps)
            arr = np.stack([np.interp(dst, src, arr[:, d]) for d in range(arr.shape[1])], 1)
        if noise:
            arr = arr + rng.normal(0, noise, arr.shape)
        return arr.astype(np.float32)

    n = n_steps or ep.n_steps
    return Episode(
        metadata=EpisodeMetadata(episode_id=ep_id),
        timestamps=np.linspace(0, 8.0, n),
        observations={k: tweak(v) for k, v in ep.observations.items()},
        actions=tweak(ep.actions),
    )


def _train(n: int = 200) -> list[Episode]:
    return [_episode(i) for i in range(n)]


# ── find_leakage ─────────────────────────────────────────────────────────────


class TestFindLeakage:
    def test_random_split_is_ok(self):
        result = find_leakage(_train(), [_episode(i) for i in range(1000, 1050)])
        assert result.status == "ok"
        assert result.count("exact") == 0
        assert result.count("near_identical") == 0
        assert result.streams == ["actions", "obs.proprio"]
        # Held-out episodes from the same distribution sit about as far from
        # training as training episodes sit from each other.
        assert 0.7 < result.median_d_vt / result.median_d_tt < 1.4

    def test_exact_copy_is_critical_and_named(self):
        train = _train()
        val = [_episode(i) for i in range(1000, 1020)] + [_copy(train[7], "v_copy")]
        result = find_leakage(train, val)
        assert result.status == "critical"
        exact = [p for p in result.pairs if p.kind == "exact"]
        assert [(p.val_episode, p.train_episode) for p in exact] == [("v_copy", "7")]

    def test_float_noise_copy_is_near_identical(self):
        train = _train()
        val = [_episode(i) for i in range(1000, 1020)] + [_copy(train[3], "v", noise=1e-4)]
        result = find_leakage(train, val)
        assert result.status == "critical"
        near = [p for p in result.pairs if p.kind == "near_identical"]
        assert [(p.val_episode, p.train_episode) for p in near] == [("v", "3")]
        assert near[0].train_percentile == 0.0

    def test_resampled_copy_is_near_identical(self):
        # Same demo re-exported at a different length still matches.
        train = _train()
        result = find_leakage(train, [_copy(train[11], "v", n_steps=137)])
        assert [(p.val_episode, p.train_episode, p.kind) for p in result.pairs] == [
            ("v", "11", "near_identical")
        ]

    def test_many_noisy_copies_warn(self):
        train = _train()
        val = [_episode(i) for i in range(1000, 1040)]
        val += [_copy(train[i], f"v{i}", noise=0.03) for i in range(10)]
        result = find_leakage(train, val)
        assert result.status in ("warning", "critical")
        flagged = {p.val_episode for p in result.pairs}
        assert {f"v{i}" for i in range(10)} <= flagged
        assert result.suspicious_p_value is not None

    def test_one_chance_close_episode_does_not_warn(self):
        # About 1% of a random split lands under the threshold by chance.
        result = find_leakage(_train(), [_episode(i) for i in range(1000, 1100)])
        assert result.status == "ok"
        assert result.expected_suspicious == pytest.approx(1.0)

    def test_duplicates_inside_train_do_not_collapse_baseline(self):
        train = _train() + [_copy(_episode(5), "5b")]
        result = find_leakage(train, [_episode(i) for i in range(1000, 1020)])
        assert result.median_d_tt > 0
        assert result.suspicious_threshold > 0
        assert result.status == "ok"

    def test_too_few_train_episodes_skips_near_duplicates(self):
        result = find_leakage([_episode(0)], [_episode(1)])
        assert result.median_d_tt is None
        assert any("Fewer than 2" in n for n in result.notes)
        assert result.status == "ok"

    def test_streams_missing_from_some_episodes_are_dropped(self):
        train = _train(50)
        val = [_episode(1000)]
        val[0].observations["extra"] = np.zeros((80, 2), dtype=np.float32)
        assert find_leakage(train, val).streams == ["actions", "obs.proprio"]

    def test_images_are_not_fingerprinted(self):
        train = _train(20)
        for ep in train:
            ep.observations["camera_rgb"] = np.zeros((80, 4, 4, 3), dtype=np.float32)
        assert "obs.camera_rgb" not in find_leakage(train, [_episode(999)]).streams


def test_holdout_is_one_pass_and_reports_missing_ids():
    # A generator can only be read once, so this fails if episodes are revisited.
    train = _train(60)
    episodes = (ep for ep in train + [_copy(train[4], "60")])
    result, missing = find_leakage_holdout(episodes, {"55", "56", "60", "999"})
    assert missing == {"999"}
    assert (result.n_train, result.n_val) == (58, 3)
    assert [(p.val_episode, p.train_episode, p.kind) for p in result.pairs][:1] == [
        ("60", "4", "exact")
    ]


def test_binom_tail():
    assert _binom_tail(100, 0, 0.01) == 1.0
    assert _binom_tail(100, 1, 0.01) == pytest.approx(1 - 0.99**100)
    assert _binom_tail(100, 10, 0.01) < 1e-6


def test_parse_holdout():
    assert _parse_holdout("0:3, 7,9:11") == ["0", "1", "2", "7", "9", "10"]


# ── CLI ──────────────────────────────────────────────────────────────────────


def _batch(eps: list[Episode]) -> EpisodeBatch:
    return EpisodeBatch(episodes=eps, dataset_name="t", format="lerobot", source_path="t")


class TestCli:
    def test_holdout_split_with_copy_exits_1(self, capsys):
        eps = _train(60) + [_copy(_episode(4), "60")]
        with patch("calibra.leakage._load", return_value=_batch(eps)):
            with pytest.raises(SystemExit) as exc:
                run_leakage(["ds", "--holdout", "55:61", "--json"])
        assert exc.value.code == 1
        out = json.loads(capsys.readouterr().out)
        assert out["n_val"] == 6 and out["n_train"] == 55
        assert out["status"] == "critical"
        assert out["pairs"][0]["kind"] == "exact"
        assert out["pairs"][0]["val_episode"] == "60"

    def test_clean_holdout_exits_0_and_prints_ok(self, capsys):
        with patch("calibra.leakage._load", return_value=_batch(_train(60))):
            with pytest.raises(SystemExit) as exc:
                run_leakage(["ds", "--holdout", "50:60"])
        assert exc.value.code == 0
        assert "OK:" in capsys.readouterr().out

    def test_two_datasets(self, capsys):
        batches = [_batch(_train(40)), _batch([_episode(500)])]
        with patch("calibra.leakage._load", side_effect=batches):
            with pytest.raises(SystemExit) as exc:
                run_leakage(["train_ds", "val_ds", "--json"])
        assert exc.value.code == 0
        assert json.loads(capsys.readouterr().out)["n_val"] == 1

    def test_holdout_file(self, tmp_path, capsys):
        f = tmp_path / "val.json"
        f.write_text(json.dumps([1, 2, 3]))
        with patch("calibra.leakage._load", return_value=_batch(_train(30))):
            with pytest.raises(SystemExit):
                run_leakage(["ds", "--holdout-file", str(f), "--json"])
        assert json.loads(capsys.readouterr().out)["n_val"] == 3

    def test_unknown_holdout_id_exits_2(self, capsys):
        with patch("calibra.leakage._load", return_value=_batch(_train(10))):
            with pytest.raises(SystemExit) as exc:
                run_leakage(["ds", "--holdout", "8:12"])
        assert exc.value.code == 2
        assert "10, 11" in capsys.readouterr().err

    @pytest.mark.parametrize(
        "argv",
        [
            ["ds"],
            ["ds", "val", "--holdout", "0:2"],
            ["ds", "--holdout", "0", "--holdout-file", "x"],
        ],
    )
    def test_needs_exactly_one_split_source(self, argv):
        with pytest.raises(SystemExit) as exc:
            run_leakage(argv)
        assert exc.value.code == 2
