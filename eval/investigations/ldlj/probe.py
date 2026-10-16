"""
Probe Calibra's LDLJ on synthetic minimum-jerk chains and on real PushT,
comparing the legacy whole-episode formula with the per-sub-movement one.

    python eval/investigations/ldlj/probe.py                      # synthetic only
    python eval/investigations/ldlj/probe.py ./pusht eval/real_faults/batches/batch-001/sheet.csv

See FINDINGS.md next to this file.
"""

import csv
import sys

import numpy as np

from calibra.analyzers.smoothness import _episode_ldlj, _episode_ldlj_whole_episode
from calibra.schema.episode import Episode, EpisodeMetadata

DIMS = list(range(6))


def ep_from(pos, fps):
    return Episode(
        metadata=EpisodeMetadata(episode_id="x"),
        timestamps=np.arange(len(pos)) / fps,
        observations={"state": pos.astype(np.float32)},
        actions=pos.astype(np.float32),
    )


def min_jerk_chain(n_seg, seg_s, fps, amp=0.2, dims=7, seed=0, noise=0.0):
    rng = np.random.default_rng(seed)
    t = np.linspace(0, 1, int(seg_s * fps), endpoint=False)
    s = 10 * t**3 - 15 * t**4 + 6 * t**5  # minimum-jerk profile
    p, out = np.zeros(dims), []
    for _ in range(n_seg):
        d = rng.normal(size=dims)
        d *= amp / np.linalg.norm(d)
        out.append(p + s[:, None] * d)
        p = p + d
    pos = np.vstack(out + [p[None]])
    if noise:
        pos = pos + rng.normal(0, noise, pos.shape)
    return pos


def both(ep, dims=DIMS):
    return _episode_ldlj_whole_episode(ep, "position", dims), _episode_ldlj(ep, "position", dims)


print("A) perfectly smooth minimum-jerk chains of N movements")
print("    N  fps   old(whole)  new(per-movement)")
for fps in (10, 50):
    for n in (1, 3, 10, 30):
        old, new = both(ep_from(min_jerk_chain(n, 1.0, fps), fps))
        print(f"  {n:3d} {fps:4d}   {old:8.2f}   {new:8.2f}")

print("B) N=10 chain + position noise (std; each movement has size 0.2)")
for fps in (10, 50):
    for noise in (0.0, 1e-4, 1e-3):
        old, new = both(ep_from(min_jerk_chain(10, 1.0, fps, noise=noise), fps))
        print(f"   fps={fps:3d} noise={noise:<6g} old={old:7.2f} new={new:7.2f}")

print("D) real faults still score worse: N=10 chain with 3 single-step position glitches")
for fps in (10, 50):
    for glitch in (0.0, 0.05, 0.2):
        pos = min_jerk_chain(10, 1.0, fps)
        for frac in (0.25, 0.5, 0.8):
            pos[int(frac * len(pos))] += glitch
        old, new = both(ep_from(pos, fps))
        print(f"   fps={fps:3d} glitch={glitch:<5g} old={old:7.2f} new={new:7.2f}")

if len(sys.argv) > 1:
    import pyarrow.parquet as pq

    root, sheet = sys.argv[1], sys.argv[2]
    d = pq.read_table(
        f"{root}/data/chunk-000/file-000.parquet",
        columns=["episode_index", "frame_index", "action"],
    ).to_pandas()
    labels = {int(r["episode_id"]): r["label"] for r in csv.DictReader(open(sheet))}
    rows = []
    for ep, g in d.sort_values(["episode_index", "frame_index"]).groupby("episode_index"):
        a = np.stack(g.action.to_numpy()).astype(np.float64)
        rows.append((ep, len(a), *both(ep_from(a, 10), [0, 1])))
    L = np.array([r[1] for r in rows])
    for col, name in ((2, "old"), (3, "new")):
        V = np.array([r[col] for r in rows], dtype=float)
        print(
            f"C) PushT {name}: median {np.nanmedian(V):.2f} range {np.nanmin(V):.2f}..{np.nanmax(V):.2f}"
            f"  <-10: {(V < -10).sum()}  <-15: {(V < -15).sum()}"
            f"  corr(LDLJ, ln length) {np.corrcoef(V, np.log(L))[0, 1]:+.2f}"
        )
        for label in ("clean", "unusual_valid"):
            vs = [r[col] for r in rows if labels.get(r[0]) == label]
            print(f"     batch-001 {label:13s} n={len(vs):2d} median {np.median(vs):6.2f}")
