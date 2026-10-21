"""
calibra leakage — do validation episodes repeat training episodes?

A held-out episode can pass every integrity check and still be a copy, or
a near-copy, of a training episode. Validation numbers then overstate how
well a policy generalizes. This command compares the two splits:

1. Exact copies: same digest (actions and numeric observations
   byte-identical) on both sides. Always Critical.
2. Near-duplicates: each episode is reduced to a fixed-length fingerprint
   (actions and numeric low-dimensional observations resampled to
   _FINGERPRINT_STEPS points over normalized time, each dimension scaled
   by its training-split std). Distances are RMS in those std units.

Similar is not the same as leaked. Under a random split of a repetitive
task every validation episode has a close training neighbour, so a fixed
distance threshold would flag everything. Instead each validation
episode's nearest-training distance (d_vt) is judged against how close
distinct training episodes are to each other (d_tt, leave-one-out):

- near-identical: d_vt below _NEAR_IDENTICAL_REL x median(d_tt). Float
  rounding, re-encoding or a light-noise copy. Critical.
- suspicious: d_vt below the _SUSPICIOUS_QUANTILE quantile of d_tt. About
  that fraction of validation episodes land here by chance under a random
  split, so the split-level flag is a Warning only when the count is
  improbable under that rate (binomial tail below _SUSPICIOUS_ALPHA).

The thresholds are first choices, not yet measured against planted copies
or clean random splits; treat findings as leads to inspect.

Usage:
    calibra leakage lerobot/my_ds --holdout 0:50          # episode range held out
    calibra leakage lerobot/my_ds --holdout 3,17,40:45
    calibra leakage lerobot/my_ds --holdout-file val.txt  # ids, one per line or JSON list
    calibra leakage lerobot/train_ds lerobot/val_ds       # two separate datasets
    calibra leakage lerobot/my_ds --holdout 0:50 --json

Exit codes:
    0  No exact or near-identical cross-split pairs.
    1  At least one exact or near-identical pair, or a load error.
    2  Bad arguments.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable, Optional

import numpy as np

from calibra.schema.episode import Episode, episode_digest

_FINGERPRINT_STEPS = 32
_NEAR_IDENTICAL_REL = 0.01
_SUSPICIOUS_QUANTILE = 0.01
_SUSPICIOUS_ALPHA = 0.01
# Rows of the validation x training distance matrix computed at once.
_CHUNK = 512


# ── fingerprints ─────────────────────────────────────────────────────────────


def _resample(arr: np.ndarray, k: int) -> np.ndarray:
    """(T, D) -> (k, D) by linear interpolation over normalized time."""
    arr = np.asarray(arr, dtype=np.float64)
    if arr.ndim == 1:
        arr = arr[:, np.newaxis]
    t = arr.shape[0]
    if t == 0:
        return np.full((k, arr.shape[1]), np.nan)
    if t == 1:
        return np.repeat(arr, k, axis=0)
    src = np.linspace(0.0, 1.0, t)
    dst = np.linspace(0.0, 1.0, k)
    return np.stack([np.interp(dst, src, arr[:, d]) for d in range(arr.shape[1])], axis=1)


def _episode_streams(ep: Episode, k: int) -> dict[str, np.ndarray]:
    """Resampled actions and numeric low-dimensional observations, by name."""
    streams = {"actions": _resample(ep.actions, k)}
    for key, arr in ep.observations.items():
        arr = np.asarray(arr)
        if arr.ndim <= 2 and np.issubdtype(arr.dtype, np.number):
            streams[f"obs.{key}"] = _resample(arr, k)
    return streams


@dataclass
class _Side:
    ids: list[str] = field(default_factory=list)
    digests: list[str] = field(default_factory=list)
    streams: list[dict[str, np.ndarray]] = field(default_factory=list)

    def add(self, ep: Episode, k: int) -> None:
        self.ids.append(ep.metadata.episode_id)
        self.digests.append(episode_digest(ep))
        self.streams.append(_episode_streams(ep, k))


def _shared_streams(sides: Iterable[_Side]) -> list[str]:
    """Stream names present with the same shape in every episode of every side."""
    shapes: Optional[dict[str, tuple]] = None
    for side in sides:
        for streams in side.streams:
            here = {name: arr.shape for name, arr in streams.items()}
            if shapes is None:
                shapes = here
            else:
                shapes = {n: s for n, s in shapes.items() if here.get(n) == s}
    return sorted(shapes or {})


def _stack(side: _Side, names: list[str]) -> np.ndarray:
    """(N, k, D_total) array of the named streams."""
    if not side.streams:
        return np.empty((0, 0, 0))
    return np.stack([np.concatenate([s[n] for n in names], axis=1) for s in side.streams], axis=0)


def _nn(query: np.ndarray, ref: np.ndarray, exclude_self: bool = False):
    """Nearest-neighbour RMS distance and index of each query row in ref."""
    ref_sq = np.einsum("ij,ij->i", ref, ref)
    dist = np.empty(len(query))
    idx = np.empty(len(query), dtype=int)
    for start in range(0, len(query), _CHUNK):
        q = query[start : start + _CHUNK]
        sq = np.einsum("ij,ij->i", q, q)[:, None] + ref_sq[None, :] - 2.0 * q @ ref.T
        np.maximum(sq, 0.0, out=sq)
        if exclude_self:
            rows = np.arange(len(q))
            sq[rows, start + rows] = np.inf
        j = np.argmin(sq, axis=1)
        idx[start : start + len(q)] = j
        dist[start : start + len(q)] = np.sqrt(sq[np.arange(len(q)), j])
    return dist / math.sqrt(query.shape[1]), idx


def _binom_tail(n: int, k: int, p: float) -> float:
    """P(X >= k) for X ~ Binomial(n, p)."""
    if k <= 0:
        return 1.0
    if p <= 0.0:
        return 0.0
    log_p, log_q = math.log(p), math.log1p(-p)
    total = 0.0
    for i in range(k, n + 1):
        log_term = (
            math.lgamma(n + 1)
            - math.lgamma(i + 1)
            - math.lgamma(n - i + 1)
            + i * log_p
            + (n - i) * log_q
        )
        total += math.exp(log_term)
    return min(total, 1.0)


# ── result ───────────────────────────────────────────────────────────────────


@dataclass
class LeakagePair:
    val_episode: str
    train_episode: str
    kind: str  # "exact" | "near_identical" | "suspicious"
    distance: Optional[float]  # RMS in train-std units; None for exact
    # Share of distinct-training nearest-neighbour distances below this one.
    train_percentile: Optional[float]


@dataclass
class LeakageResult:
    n_train: int
    n_val: int
    streams: list[str]
    pairs: list[LeakagePair]
    status: str  # "critical" | "warning" | "ok"
    # Split-level statistics; None when the baseline could not be formed.
    median_d_tt: Optional[float] = None
    median_d_vt: Optional[float] = None
    near_identical_threshold: Optional[float] = None
    suspicious_threshold: Optional[float] = None
    n_suspicious: int = 0
    expected_suspicious: float = 0.0
    suspicious_p_value: Optional[float] = None
    notes: list[str] = field(default_factory=list)

    def count(self, kind: str) -> int:
        return sum(p.kind == kind for p in self.pairs)

    def to_dict(self) -> dict:
        return asdict(self)


def find_leakage(
    train: Iterable[Episode],
    val: Iterable[Episode],
    k: int = _FINGERPRINT_STEPS,
) -> LeakageResult:
    """Compare validation episodes against training episodes (see module doc)."""
    tr, va = _Side(), _Side()
    for ep in train:
        tr.add(ep, k)
    for ep in val:
        va.add(ep, k)
    return _compare(tr, va)


def find_leakage_holdout(
    episodes: Iterable[Episode],
    held_ids: set[str],
    k: int = _FINGERPRINT_STEPS,
) -> tuple[LeakageResult, set[str]]:
    """
    One pass over a single dataset, holding out `held_ids` as validation.

    Only fingerprints and digests are kept, so a lazily loaded dataset is
    never materialised. Returns the result and the held-out ids not found.
    """
    tr, va = _Side(), _Side()
    for ep in episodes:
        (va if ep.metadata.episode_id in held_ids else tr).add(ep, k)
    return _compare(tr, va), held_ids - set(va.ids)


def _compare(tr: _Side, va: _Side) -> LeakageResult:
    notes: list[str] = []
    pairs: list[LeakagePair] = []

    # 1. Exact copies.
    # {digest: index of its first training episode}
    first_train: dict[str, int] = {}
    for i, digest in enumerate(tr.digests):
        first_train.setdefault(digest, i)
    exact_val: set[int] = set()
    for i, (eid, digest) in enumerate(zip(va.ids, va.digests)):
        if digest in first_train:
            exact_val.add(i)
            pairs.append(LeakagePair(eid, tr.ids[first_train[digest]], "exact", None, None))

    # 2. Near-duplicates, judged against the training split's own spacing.
    names = _shared_streams([tr, va])
    result = LeakageResult(
        n_train=len(tr.ids), n_val=len(va.ids), streams=names, pairs=pairs, status="ok", notes=notes
    )
    # Exact copies inside training would pin d_tt at 0; the baseline uses one of each.
    distinct = sorted(first_train.values())
    if not names:
        notes.append("No stream shared by every episode; near-duplicate check skipped.")
    elif len(distinct) < 2:
        notes.append("Fewer than 2 distinct training episodes; near-duplicate check skipped.")
    elif va.ids:
        x_tr = _stack(tr, names)
        x_va = _stack(va, names)
        finite = np.isfinite(x_tr).all(axis=(1, 2))
        mean = x_tr[finite].reshape(-1, x_tr.shape[2]).mean(axis=0)
        std = x_tr[finite].reshape(-1, x_tr.shape[2]).std(axis=0)
        std[std == 0] = 1.0
        f_tr = np.nan_to_num(((x_tr - mean) / std).reshape(len(x_tr), -1))
        f_va = np.nan_to_num(((x_va - mean) / std).reshape(len(x_va), -1))

        base = f_tr[distinct]
        d_tt, _ = _nn(base, base, exclude_self=True)
        d_vt, j_vt = _nn(f_va, base)
        med_tt = float(np.median(d_tt))
        near_thr = _NEAR_IDENTICAL_REL * med_tt
        susp_thr = float(np.quantile(d_tt, _SUSPICIOUS_QUANTILE))
        sorted_tt = np.sort(d_tt)

        n_susp = 0
        for i in range(len(va.ids)):
            if i in exact_val:
                continue
            d = float(d_vt[i])
            if d <= near_thr:
                kind = "near_identical"
            elif d < susp_thr:
                kind = "suspicious"
                n_susp += 1
            else:
                continue
            pct = float(np.searchsorted(sorted_tt, d, side="left") / len(sorted_tt))
            pairs.append(LeakagePair(va.ids[i], tr.ids[distinct[j_vt[i]]], kind, d, pct))

        n_tested = len(va.ids) - len(exact_val)
        result.median_d_tt = med_tt
        result.median_d_vt = float(np.median(d_vt))
        result.near_identical_threshold = near_thr
        result.suspicious_threshold = susp_thr
        result.n_suspicious = n_susp
        result.expected_suspicious = n_tested * _SUSPICIOUS_QUANTILE
        result.suspicious_p_value = _binom_tail(n_tested, n_susp, _SUSPICIOUS_QUANTILE)
        if len(distinct) < 100:
            notes.append(
                f"Baseline uses {len(distinct)} distinct training episodes; the "
                f"{_SUSPICIOUS_QUANTILE:.0%} quantile is coarse below ~100."
            )

    order = {"exact": 0, "near_identical": 1, "suspicious": 2}
    pairs.sort(key=lambda p: (order[p.kind], p.distance if p.distance is not None else -1.0))

    if result.count("exact") or result.count("near_identical"):
        result.status = "critical"
    elif result.suspicious_p_value is not None and result.suspicious_p_value < _SUSPICIOUS_ALPHA:
        result.status = "warning"
    return result


# ── CLI ──────────────────────────────────────────────────────────────────────


def _parse_holdout(spec: str) -> list[str]:
    """'0:50,80,90:95' -> ids; ranges are half-open like Python slices."""
    ids: list[str] = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if ":" in part:
            lo, hi = part.split(":", 1)
            ids.extend(str(i) for i in range(int(lo), int(hi)))
        else:
            ids.append(part)
    return ids


def _read_holdout_file(path: str) -> list[str]:
    text = Path(path).read_text()
    stripped = text.strip()
    if stripped.startswith("["):
        return [str(x) for x in json.loads(stripped)]
    return [line.strip() for line in text.splitlines() if line.strip()]


def _load(path: str, fmt: Optional[str]):
    from calibra.ingestion.registry import load

    if path.startswith("hf://"):
        path = path[len("hf://") :]
    reader = None
    if fmt:
        from calibra.__main__ import _get_reader

        reader = _get_reader(fmt)
    return load(path, reader=reader)


def _print_result(result: LeakageResult, top: int) -> None:
    out = print
    out(f"Leakage check: {result.n_val} validation vs {result.n_train} training episodes")
    out(f"  compared: {', '.join(result.streams) or 'nothing'}")
    out("")
    n_exact, n_near = result.count("exact"), result.count("near_identical")
    out(f"  exact copies across splits    {n_exact}")
    out(f"  near-identical                {n_near}")
    if result.suspicious_p_value is not None:
        out(
            f"  closer than {1 - _SUSPICIOUS_QUANTILE:.0%} of train pairs "
            f"{result.n_suspicious}  (about {result.expected_suspicious:.1f} expected by "
            f"chance, p = {result.suspicious_p_value:.3g})"
        )
        ratio = result.median_d_vt / result.median_d_tt if result.median_d_tt else float("nan")
        out(
            f"  median nearest distance       val->train {result.median_d_vt:.3f}, "
            f"train->train {result.median_d_tt:.3f} (ratio {ratio:.2f})"
        )
        if ratio < 0.5:
            out(
                "    Validation sits much closer to training than training does to itself: "
                "the split itself may be leaking (same sessions or setups on both sides)."
            )
    shown = result.pairs[:top]
    if shown:
        out("")
        out("  val episode -> train episode   kind            distance  train pct")
        for p in shown:
            dist = "-" if p.distance is None else f"{p.distance:.4f}"
            pct = "-" if p.train_percentile is None else f"{p.train_percentile:.1%}"
            out(f"  {p.val_episode:>11} -> {p.train_episode:<13} {p.kind:<15} {dist:>8}  {pct:>9}")
        if len(result.pairs) > top:
            out(f"  ... {len(result.pairs) - top} more (use --top or --json)")
    for note in result.notes:
        out(f"  note: {note}")
    out("")
    verdict = {
        "critical": "CRITICAL: validation contains copies of training episodes. Remove them "
        "or re-split by session or setup before trusting validation numbers.",
        "warning": "WARNING: more validation episodes sit unusually close to training than a "
        "random split explains. Inspect the listed pairs.",
        "ok": "OK: no cross-split copies; validation is no closer to training than a random "
        "split would be.",
    }[result.status]
    out(verdict)


def run_leakage(argv: list[str]) -> None:
    p = argparse.ArgumentParser(
        prog="calibra leakage",
        description="Find validation episodes that copy or nearly copy training episodes.",
    )
    p.add_argument("path", help="Dataset (or the training dataset when VAL_PATH is given)")
    p.add_argument("val_path", nargs="?", help="Separate validation dataset")
    p.add_argument("--holdout", help="Held-out episode ids, e.g. '0:50' or '3,17,40:45'")
    p.add_argument("--holdout-file", help="File of held-out episode ids (lines or JSON list)")
    p.add_argument("--format", help="Force a format adapter (default: auto-detect)")
    p.add_argument("--json", action="store_true", help="Print the result as JSON")
    p.add_argument("--top", type=int, default=10, help="Pairs to list (default 10)")
    args = p.parse_args(argv)

    n_modes = sum(x is not None for x in (args.val_path, args.holdout, args.holdout_file))
    if n_modes != 1:
        print("error: give exactly one of VAL_PATH, --holdout or --holdout-file", file=sys.stderr)
        sys.exit(2)

    def log(msg: str) -> None:
        print(msg, file=sys.stderr, flush=True)

    try:
        log(f"Loading {args.path!r} ...")
        batch = _load(args.path, args.format)
        if args.val_path:
            log(f"Loading {args.val_path!r} ...")
            val_batch = _load(args.val_path, args.format)
            log("Comparing splits ...")
            result = find_leakage(batch.episodes, val_batch.episodes)
        else:
            try:
                wanted = (
                    _parse_holdout(args.holdout)
                    if args.holdout
                    else _read_holdout_file(args.holdout_file)
                )
            except (ValueError, OSError) as exc:
                print(f"error reading holdout ids: {exc}", file=sys.stderr)
                sys.exit(2)
            log("Comparing splits ...")
            result, not_found = find_leakage_holdout(batch.episodes, set(wanted))
            if not_found:
                missing = sorted(not_found)
                shown = ", ".join(missing[:10]) + (" ..." if len(missing) > 10 else "")
                print(f"error: holdout ids not in dataset: {shown}", file=sys.stderr)
                sys.exit(2)
    except SystemExit:
        raise
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)

    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
    else:
        _print_result(result, args.top)
    sys.exit(1 if result.status == "critical" else 0)
