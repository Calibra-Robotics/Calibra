"""
Why is velocity_discontinuity_rate CRITICAL on clean datasets?

    python eval/investigations/vel_disc/probe.py [pusht_root h1_root aloha_root]

See FINDINGS.md next to this file.
"""

import sys

import numpy as np

from calibra.analyzers.smoothness import _episode_vel_disc_fraction
from calibra.schema.episode import Episode, EpisodeMetadata


def ep_from(pos, fps):
    return Episode(
        metadata=EpisodeMetadata(episode_id="x"),
        timestamps=np.arange(len(pos)) / fps,
        observations={"state": pos.astype(np.float32)},
        actions=pos.astype(np.float64),
    )


def min_jerk_chain(n_seg, seg_s, fps, dims=6, seed=0, noise=0.0, hold=1):
    rng = np.random.default_rng(seed)
    t = np.linspace(0, 1, int(seg_s * fps), endpoint=False)
    s = 10 * t**3 - 15 * t**4 + 6 * t**5
    p, out = np.zeros(dims), []
    for _ in range(n_seg):
        d = rng.normal(size=dims)
        d *= 0.2 / np.linalg.norm(d)
        out.append(p + s[:, None] * d)
        p = p + d
    pos = np.vstack(out + [p[None]])
    if hold > 1:  # command updated every `hold` steps, held in between
        pos = pos[(np.arange(len(pos)) // hold) * hold]
    if noise:
        pos = pos + rng.normal(0, noise, pos.shape)
    return pos


def rate(pos, fps):
    return _episode_vel_disc_fraction(ep_from(pos, fps), "position", list(range(pos.shape[1])))


print("A) perfectly smooth minimum-jerk movements, by sampling rate and movement duration")
for fps in (5, 10, 15, 30, 50):
    row = [f"{rate(min_jerk_chain(10, d, fps), fps):6.1%}" for d in (0.5, 1.0, 2.0)]
    print(f"   {fps:3d} Hz  movement 0.5 s / 1 s / 2 s: " + "  ".join(row))

print("B) smooth 1 s movements + position noise (movement size 0.2)")
for fps in (10, 50):
    row = [f"{rate(min_jerk_chain(10, 1.0, fps, noise=n), fps):6.1%}" for n in (0, 1e-4, 1e-3)]
    print(f"   {fps:3d} Hz  noise 0 / 1e-4 / 1e-3: " + "  ".join(row))

print("C) smooth 1 s movements at 50 Hz, command held for k steps (slower teleop)")
print("   " + "  ".join(f"k={k}: {rate(min_jerk_chain(10, 1.0, 50, hold=k), 50):6.1%}" for k in (1, 2, 3, 5)))

if len(sys.argv) > 1:
    from calibra.ingestion.registry import load

    print("D) real data: rate, share of steps with zero action change, flagged steps next to one")
    for root in sys.argv[1:]:
        b = load(root)
        rates, zero, near = [], [], []
        for e in b.episodes:
            a = np.asarray(e.actions, float)
            dt = float(np.median(np.diff(e.timestamps)))
            v = np.diff(a, axis=0) / dt
            sp = np.linalg.norm(v, axis=1)
            dv = np.linalg.norm(np.diff(v, axis=0), axis=1)
            flag = dv > 0.2 * sp.max()
            still = sp < 1e-9
            rates.append(flag.mean())
            zero.append(still.mean())
            if flag.any():
                adj = still[:-1] | still[1:]
                near.append((flag & adj).sum() / flag.sum())
        print(
            f"   {root}: {1 / dt:.0f} Hz, vel_disc {np.mean(rates):.1%}, zero-change steps "
            f"{np.mean(zero):.1%}, flagged steps adjacent to a zero-change step {np.mean(near):.0%}"
        )
