"""
Closed-loop PushT evaluation harness (CLOSED_LOOP_PROTOCOL.md, Stage 0 onward)
=============================================================================
Thin wrapper around `lerobot-eval`. Rollouts are LeRobot's own code; this script
only fixes the settings the protocol pins, times the run, and writes one result
record with the provenance a rerun needs.

Stage 0 validates the pipeline against the reference checkpoint
`lerobot/diffusion_pusht`, whose model card reports 65.4% success over 500
episodes (env seeds 1000-1499, batch size 50, AMP off). With `--stage0` the
script also compares per-seed outcomes against the card's eval_info.json and
applies the protocol gate (|ours - 65.4| <= tolerance). Per-seed agreement is a
diagnostic only: env seeds match, but diffusion sampling noise depends on device
and batch size, so individual episodes can flip while the rate reproduces.

Checkpoints saved before LeRobot 0.4 carry normalization inside the weights and
have no processor files; they are migrated with LeRobot's own
`migrate_policy_normalization` into the output directory first.

    # Stage 0 (on the GPU machine)
    python experiments/closed_loop_eval.py --stage0 --out results/closed_loop/stage0.json

    # Any trained checkpoint, protocol eval seeds
    python experiments/closed_loop_eval.py --policy-path outputs/train/act_full_s0/checkpoints/last/pretrained_model \\
        --start-seed 100000 --n-episodes 500 --out results/closed_loop/act_full_s0.json

    # Print the commands without running anything
    python experiments/closed_loop_eval.py --stage0 --dry-run
"""

from __future__ import annotations

import argparse
import json
import math
import pathlib
import platform
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone

REPO_ROOT = pathlib.Path(__file__).parent.parent

REFERENCE_REPO = "lerobot/diffusion_pusht"
REFERENCE_PC_SUCCESS = 65.4
REFERENCE_N_EPISODES = 500
REFERENCE_START_SEED = 1000
REFERENCE_BATCH_SIZE = 50

# Protocol §4 Stage 0 gate, percentage points.
STAGE0_TOLERANCE_PP = 5.0


def wilson_interval(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """95% Wilson score interval for a binomial proportion, as fractions."""
    if n == 0:
        return (float("nan"), float("nan"))
    p = successes / n
    denom = 1 + z**2 / n
    centre = (p + z**2 / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z**2 / (4 * n**2)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def mcnemar_exact_p(b: int, c: int) -> float:
    """Two-sided exact McNemar p-value from the discordant counts b and c."""
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    tail = sum(math.comb(n, i) for i in range(k + 1)) / 2**n
    return min(1.0, 2 * tail)


def per_episode_outcomes(eval_info: dict, start_seed: int) -> dict[int, bool]:
    """Map env seed -> success from a LeRobot eval_info.json.

    Handles both layouts: the pre-0.4 one with `per_episode` entries that carry
    their seed, and the 0.4 one with `per_task[*].metrics.successes`, where
    seeds are start_seed + index (LeRobot increments the seed per rollout).
    """
    if "per_episode" in eval_info:
        return {int(ep["seed"]): bool(ep["success"]) for ep in eval_info["per_episode"]}
    tasks = eval_info.get("per_task", [])
    if len(tasks) != 1:
        raise ValueError(f"expected exactly one task in eval_info.json, found {len(tasks)}")
    successes = tasks[0]["metrics"]["successes"]
    return {start_seed + i: bool(s) for i, s in enumerate(successes)}


def compare_to_reference(ours: dict[int, bool], ref: dict[int, bool]) -> dict:
    """Per-seed agreement with the reference rollouts on the shared seeds."""
    shared = sorted(set(ours) & set(ref))
    b = sum(1 for s in shared if ours[s] and not ref[s])
    c = sum(1 for s in shared if ref[s] and not ours[s])
    agree = len(shared) - b - c
    return {
        "n_shared_seeds": len(shared),
        "agreement": agree / len(shared) if shared else float("nan"),
        "ours_only_success": b,
        "reference_only_success": c,
        "mcnemar_exact_p": mcnemar_exact_p(b, c),
    }


def summarize(outcomes: dict[int, bool]) -> dict:
    n = len(outcomes)
    k = sum(outcomes.values())
    lo, hi = wilson_interval(k, n)
    return {
        "n_episodes": n,
        "n_success": k,
        "pc_success": 100.0 * k / n if n else float("nan"),
        "wilson95_pc": [100.0 * lo, 100.0 * hi],
    }


def _git_revision() -> dict:
    def _run(*args: str) -> str:
        return subprocess.run(
            ["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, check=False
        ).stdout.strip()

    return {"commit": _run("rev-parse", "HEAD"), "dirty": bool(_run("status", "--porcelain"))}


def _environment() -> dict:
    env = {"python": platform.python_version(), "platform": platform.platform()}
    try:
        import lerobot

        env["lerobot"] = getattr(lerobot, "__version__", "unknown")
    except ImportError:
        env["lerobot"] = None
    try:
        import torch

        env["torch"] = torch.__version__
        env["cuda_device"] = torch.cuda.get_device_name(0) if torch.cuda.is_available() else None
    except ImportError:
        env["torch"] = None
    return env


def _needs_migration(policy_path: str) -> bool:
    """True for checkpoints without LeRobot 0.4 processor files."""
    local = pathlib.Path(policy_path)
    if local.is_dir():
        return not (local / "policy_preprocessor.json").exists()
    from huggingface_hub import list_repo_files

    return "policy_preprocessor.json" not in list_repo_files(policy_path)


def _run(cmd: list[str], dry_run: bool) -> None:
    print("$ " + " ".join(cmd), flush=True)
    if not dry_run:
        subprocess.run(cmd, check=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--policy-path", help="Hub repo id or local pretrained_model directory")
    ap.add_argument("--stage0", action="store_true", help=f"Evaluate {REFERENCE_REPO} with the model-card settings and apply the Stage 0 gate")
    ap.add_argument("--n-episodes", type=int, default=REFERENCE_N_EPISODES)
    ap.add_argument("--batch-size", type=int, default=REFERENCE_BATCH_SIZE)
    ap.add_argument("--start-seed", type=int, default=REFERENCE_START_SEED)
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--tolerance", type=float, default=STAGE0_TOLERANCE_PP)
    ap.add_argument("--work-dir", type=pathlib.Path, default=REPO_ROOT / "outputs" / "closed_loop_eval")
    ap.add_argument("--out", type=pathlib.Path, help="Result JSON path")
    ap.add_argument("--dry-run", action="store_true", help="Print commands only")
    args = ap.parse_args()

    if args.stage0:
        if args.policy_path or args.n_episodes != REFERENCE_N_EPISODES or args.start_seed != REFERENCE_START_SEED:
            ap.error("--stage0 fixes the policy, episode count and seeds to the model card's settings")
        args.policy_path = REFERENCE_REPO
    if not args.policy_path:
        ap.error("--policy-path is required unless --stage0 is given")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = args.work_dir / f"{args.policy_path.replace('/', '_')}_{stamp}"

    policy_path = args.policy_path
    if args.dry_run or _needs_migration(policy_path):
        migrated = run_dir / "migrated_policy"
        _run(
            [sys.executable, "-m", "lerobot.processor.migrate_policy_normalization",
             "--pretrained-path", policy_path, "--output-dir", str(migrated)],
            args.dry_run,
        )
        policy_path = str(migrated)

    eval_dir = run_dir / "eval"
    lerobot_eval = shutil.which("lerobot-eval") or "lerobot-eval"
    started = time.time()
    _run(
        [lerobot_eval,
         f"--policy.path={policy_path}",
         "--env.type=pusht",
         f"--eval.n_episodes={args.n_episodes}",
         f"--eval.batch_size={args.batch_size}",
         f"--seed={args.start_seed}",
         f"--policy.device={args.device}",
         "--policy.use_amp=false",
         f"--output_dir={eval_dir}"],
        args.dry_run,
    )
    wall_clock_s = time.time() - started
    if args.dry_run:
        return 0

    eval_info = json.loads((eval_dir / "eval_info.json").read_text())
    outcomes = per_episode_outcomes(eval_info, args.start_seed)
    expected = set(range(args.start_seed, args.start_seed + args.n_episodes))
    if set(outcomes) != expected:
        raise RuntimeError(f"got {len(outcomes)} episodes, expected seeds {args.start_seed}..{args.start_seed + args.n_episodes - 1}")

    record = {
        "protocol": "experiments/CLOSED_LOOP_PROTOCOL.md",
        "created_utc": stamp,
        "policy_path": args.policy_path,
        "eval_settings": {
            "env": "pusht",
            "n_episodes": args.n_episodes,
            "batch_size": args.batch_size,
            "start_seed": args.start_seed,
            "use_amp": False,
            "device": args.device,
        },
        "result": summarize(outcomes),
        "timing": {"wall_clock_s": wall_clock_s, "eval_s": eval_info.get("overall", {}).get("eval_s")},
        "revision": _git_revision(),
        "environment": _environment(),
        "eval_dir": str(eval_dir),
    }

    if args.stage0:
        from huggingface_hub import hf_hub_download

        ref_info = json.loads(pathlib.Path(hf_hub_download(REFERENCE_REPO, "eval_info.json")).read_text())
        ref = per_episode_outcomes(ref_info, REFERENCE_START_SEED)
        gap = record["result"]["pc_success"] - REFERENCE_PC_SUCCESS
        record["stage0"] = {
            "reference_pc_success": REFERENCE_PC_SUCCESS,
            "difference_pp": gap,
            "tolerance_pp": args.tolerance,
            "passed": abs(gap) <= args.tolerance,
            "per_seed_vs_reference": compare_to_reference(outcomes, ref),
        }

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(record, indent=2) + "\n")
        print(f"wrote {args.out}")

    res = record["result"]
    lo, hi = res["wilson95_pc"]
    print(f"success {res['pc_success']:.1f}% ({res['n_success']}/{res['n_episodes']}), 95% CI [{lo:.1f}, {hi:.1f}]")
    print(f"wall clock {wall_clock_s / 60:.1f} min ({wall_clock_s / args.n_episodes:.2f} s/episode)")
    if args.stage0:
        s0 = record["stage0"]
        verdict = "PASS" if s0["passed"] else "FAIL"
        print(f"Stage 0 {verdict}: {s0['difference_pp']:+.1f} pp vs {REFERENCE_PC_SUCCESS}% (tolerance ±{args.tolerance} pp)")
        print(f"per-seed agreement with reference: {s0['per_seed_vs_reference']['agreement']:.1%}")
        return 0 if s0["passed"] else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
