"""Collect the real data the demo video draws on. Read-only w.r.t. the repo.

Outputs demo-video/build/data.json with:
  - per-episode frame ranges and downsampled 2-D action traces (lerobot/pusht local copy)
  - the CLI coreset (calibra prune pusht --keep 0.25 --strategy diversity), in selection order
  - the benchmark train/test split, rebuilt exactly as experiments/lerobot_coreset_benchmark.py
    does it (np.random.default_rng(42) permutation, first 20% held out)
  - a 25% coreset on that training split, re-selected with the current code
    (CoresetSelector(strategy="diversity"), no dataset profile, as in the benchmark)
  - the benchmark numbers, copied verbatim from experiments/figures/*.json

Run from the repo root:
    PYTHONPATH=. python demo-video/scripts/prepare_data.py
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "demo-video" / "build"
OUT.mkdir(parents=True, exist_ok=True)


def main() -> None:
    from calibra.ingestion.registry import load
    from calibra.pipeline import Pipeline
    from calibra.pruning import CoresetSelector
    from calibra.schema.episode import EpisodeBatch

    batch = load(str(ROOT / "pusht"))
    eps = list(batch.episodes)
    n = len(eps)
    print("episodes", n)

    # Frame ranges in the concatenated video come from meta/episodes.
    import pyarrow.parquet as pq

    meta = pq.read_table(
        next((ROOT / "pusht/meta/episodes").glob("*/*.parquet")),
        columns=["episode_index", "dataset_from_index", "dataset_to_index", "length"],
    ).to_pylist()
    ranges = {m["episode_index"]: [m["dataset_from_index"], m["dataset_to_index"]] for m in meta}

    traces = {}
    for ep in eps:
        a = np.asarray(ep.actions, dtype=float)
        step = max(1, len(a) // 60)
        traces[ep.metadata.episode_id] = np.round(a[::step], 1).tolist()

    # Benchmark split, identical to lerobot_coreset_benchmark.py
    rng = np.random.default_rng(42)
    perm = rng.permutation(n)
    n_test = max(1, int(n * 0.2))
    test_idx = set(perm[:n_test].tolist())
    train_eps = [eps[i] for i in range(n) if i not in test_idx]
    test_eps = [eps[i] for i in sorted(test_idx)]
    train_batch = EpisodeBatch(
        episodes=train_eps, dataset_name="lerobot/pusht", format="lerobot-v2", source_path="pusht"
    )
    diag = Pipeline().run(train_batch)
    prune = CoresetSelector(keep_fraction=0.25, strategy="diversity").select(train_batch, diag)
    train_ids = {e.metadata.episode_id for e in train_eps}
    bench_kept = [e for e in prune.keep_episode_ids if e in train_ids]
    print("train", len(train_eps), "test", len(test_eps), "bench_kept", len(bench_kept))

    cli = json.loads((ROOT / "demo-video/evidence/coreset_pusht_25.json").read_text())
    bench = json.loads((ROOT / "experiments/figures/benchmark_lerobot_pusht.json").read_text())
    targeted = json.loads((ROOT / "experiments/figures/targeted_lerobot_pusht.json").read_text())

    data = {
        "episode_ids": [e.metadata.episode_id for e in eps],
        "ranges": {str(k): v for k, v in ranges.items()},
        "traces": traces,
        "cli_kept": cli["keep_episode_ids"],
        "cli_method": cli["method"],
        "bench_train_ids": [e.metadata.episode_id for e in train_eps],
        "bench_test_ids": [e.metadata.episode_id for e in test_eps],
        "bench_kept_reselected": bench_kept,
        "benchmark": bench,
        "targeted_25": targeted["fractions"]["0.25"],
        "targeted_full": targeted["full_unfiltered"],
        "targeted_meta": {k: targeted[k] for k in ("n_seeds", "n_epochs", "n_train", "n_test")},
    }
    (OUT / "data.json").write_text(json.dumps(data))
    print("wrote", OUT / "data.json")


if __name__ == "__main__":
    main()
