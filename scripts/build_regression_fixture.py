#!/usr/bin/env python3
"""
Freeze lerobot/pusht (state + actions) into the offline fixture that the
benchmark regression test runs on.

The fixture holds every episode's timestamps, state and actions exactly as the
LeRobot reader returns them, so CI can run the full pipeline and prune path on
real data without network access. PushT is MIT-licensed and the non-image data
is small (~25k steps of 2-D actions and state).

Usage:
    pip install 'calibra[lerobot]'
    python scripts/build_regression_fixture.py --revision 7628202a2180972f291ba1bc6723834921e72c19

The revision is recorded in the fixture; make sure it is the snapshot the
reader actually loaded (the reader logs the cache path it used).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent))

from calibra.ingestion import registry

FIXTURE_DIR = Path(__file__).parent.parent / "tests" / "regression" / "fixtures"


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--dataset", default="lerobot/pusht")
    parser.add_argument("--revision", required=True, help="Hub commit SHA of the loaded snapshot")
    parser.add_argument("--out", default=str(FIXTURE_DIR / "pusht.npz"))
    args = parser.parse_args()

    batch = registry.load(args.dataset)
    episodes = list(batch.episodes)
    tasks = {ep.metadata.task_description for ep in episodes}
    if len(tasks) != 1:
        sys.exit(f"expected one task description, found {len(tasks)}")

    lengths = np.array([ep.n_steps for ep in episodes], dtype=np.int64)
    np.savez_compressed(
        args.out,
        dataset=args.dataset,
        revision=args.revision,
        task=tasks.pop() or "",
        episode_ids=np.array([ep.metadata.episode_id for ep in episodes]),
        lengths=lengths,
        timestamps=np.concatenate([ep.timestamps for ep in episodes]),
        state=np.concatenate([ep.observations["state"] for ep in episodes]),
        actions=np.concatenate([ep.actions for ep in episodes]),
    )
    size_kb = Path(args.out).stat().st_size / 1024
    print(f"{len(episodes)} episodes, {lengths.sum()} steps -> {args.out} ({size_kb:.0f} KB)")


if __name__ == "__main__":
    main()
