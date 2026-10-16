"""
Probe Calibra's LDLJ on synthetic minimum-jerk chains and on real PushT.

    python eval/investigations/ldlj/probe.py                      # synthetic only
    python eval/investigations/ldlj/probe.py ./pusht eval/real_faults/batches/batch-001/sheet.csv

See FINDINGS.md next to this file.
"""

import csv
import sys

import numpy as np

from calibra.analyzers.smoothness import _episode_ldlj
from calibra.schema.episode import Episode, EpisodeMetadata


def ep_from(pos, fps):
    n = len(pos)
    return Episode(
        metadata=EpisodeMetadata(episode_id="x"),
        timestamps=np.arange(n) / fps,
        observations={"state": pos.astype(np.float32)},
        actions=pos.astype(np.float32),
    )


def min_jerk_chain(n_seg, seg_s, fps, amp=0.2, dims=6, seed=0, noise=0.0):
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


print(
    "A) perfectly smooth minimum-jerk chains (Calibra's _episode_ldlj; dims=6, gripper excluded by default)"
)
print("   N  fps   LDLJ    predicted(-5.9-4lnN)")
for fps in (10, 50):
    for n in (1, 3, 10, 30):
        v = _episode_ldlj(
            ep_from(min_jerk_chain(n, 1.0, fps, dims=7), fps), "position", list(range(6))
        )
        print(f"  {n:3d} {fps:4d}  {v:6.2f}   {-5.9 - 4 * np.log(n):6.2f}")

print("B) same N=10 chain + tiny position noise (std, in units where each move is 0.2)")
for fps in (10, 50):
    for noise in (0.0, 1e-4, 1e-3):
        v = _episode_ldlj(
            ep_from(min_jerk_chain(10, 1.0, fps, dims=7, noise=noise), fps),
            "position",
            list(range(6)),
        )
        print(f"   fps={fps:3d} noise={noise:<6g} LDLJ={v:6.2f}")

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
        e = Episode(
            metadata=EpisodeMetadata(episode_id=str(ep)),
            timestamps=np.arange(len(a)) / 10,
            observations={"state": a.astype(np.float32)},
            actions=a.astype(np.float32),
        )
        rows.append((ep, len(a), _episode_ldlj(e, "position", [0, 1])))
    L = np.array([r[1] for r in rows])
    V = np.array([r[2] for r in rows])
    print(
        f"C) PushT real (206 eps): LDLJ median {np.median(V):.2f}, range {V.min():.2f}..{V.max():.2f}; "
        f"<-15 (CRITICAL band): {(V < -15).sum()}  <-10: {(V < -10).sum()}"
    )
    print(f"   corr(LDLJ, ln length) = {np.corrcoef(V, np.log(L))[0, 1]:+.2f}")
    lab = [(labels[e], v) for e, n, v in rows if e in labels]
    for name in ("clean", "unusual_valid"):
        vs = [v for label, v in lab if label == name]
        print(
            f"   batch-001 {name:13s} n={len(vs):2d}  LDLJ median {np.median(vs):6.2f}  all < -10: {all(v < -10 for v in vs)}"
        )
