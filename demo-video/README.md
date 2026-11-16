# Calibra demo video

`calibra-demo.mp4`: 59 s, 1920x1080, 30 fps, H.264 with a silent AAC track. English captions are burned in and also provided as `calibra-demo.srt`.

## Storyboard

| Time | Scene | Content |
|---|---|---|
| 0-8 s | Hook | "Do you need all your robotics training data?" over all 206 real `lerobot/pusht` demonstrations playing |
| 8-22 s | Audit and select | Real `calibra analyze` and `calibra prune` output, with the 206 action traces and the 52 picks highlighted in selection order |
| 22-30 s | Benchmark setup | 165 training episodes vs. the 41-episode coreset (real demonstration clips) |
| 30-42 s | Benchmark results | Retention sweep (Calibra vs. random, 5-100%) and rare-behavior coverage at 25% |
| 42-52 s | Key result | 25% of the data, only 0.8% higher prediction error than full-data training |
| 52-59 s | Call to action | "Have a robotics dataset? Let's test Calibra on it.", github.com/Calibra-Robotics/Calibra |

## The 99.5% claim was not used

The brief asked for "25% retained, reaching 99.5% of full-dataset performance". The repository does not support that number:

- `CHANGELOG.md` (Unreleased, "Docs site Home page and README results corrected") records that the README's "99.5% of full" was wrong and replaced it with the result-file value.
- `experiments/figures/benchmark_lerobot_pusht.json` at 25% retention: Calibra held-out MSE 423.92 vs. full-data 420.67, i.e. **0.77% higher error** (`calibra_mse_relative` 1.0077). Inverted, that is 99.2%, not 99.5%. Random 25% subsets: 429.77, **2.16% higher** (mean of 5 seeds).
- It is not a "performance" or success-rate number. It is offline action-prediction error.

The video therefore states the result-file number as "75% less training data. Only 0.8% higher prediction error than full-data training." (the website, `web/src/App.jsx`, says "within 0.8% of full-data training"; same number, reworded so 0.8% does not read as an error rate).

## What the headline measures

| Item | Value |
|---|---|
| Dataset | `lerobot/pusht`, 206 episodes; split by `np.random.default_rng(42)`: 165 train, 41 held out |
| Selection | `CoresetSelector(keep_fraction=0.25, strategy="diversity")`: quality filter + greedy max-coverage, 41 episodes |
| Model | BC-MLP (3 layers, hidden 256), 120 epochs, AdamW, cosine LR |
| Metric | Action-prediction MSE on the 41 held-out episodes. **Not closed-loop policy success.** |
| Seeds | Full and Calibra: one training run each (selection is deterministic). Random: mean of 5 seeds |
| Code version | Calibra v0.8.0 run, committed 2026-09-01 (`762aa19`) |
| Script | `experiments/lerobot_coreset_benchmark.py` |

The scene 4 secondary line ("Separate 10-seed run: Calibra beats random at 25%, paired t-test p = 0.004") comes from `experiments/figures/targeted_lerobot_pusht.json` (`fractions["0.25"].methods.calibra.overall.p_paired` = 0.0040, n = 10, `experiments/lerobot_targeted_benchmark.py`). The rare-behavior bars (52% vs. 34%) are `calibra_rare_coverage` / `random_rare_coverage` at 25% in the benchmark JSON.

## Evidence sources

| On screen | Source |
|---|---|
| All video tiles | `pusht/videos/observation.image/chunk-000/file-000.mp4` (96x96 dataset camera, upscaled), with episode frame ranges from `pusht/meta/episodes` |
| Terminal output | `evidence/analyze_pusht.txt` and `evidence/prune_pusht_25.txt`: real stdout captured 2026-11-16 with Calibra 0.13.1 on the local copy. Analyze shows lines 1-23 (the default 85% recommendation section is omitted). Prune shows lines 1-16, with the long episode list wrapped. |
| Action traces and 52 picks | `pusht/data` actions; `evidence/coreset_pusht_25.json` (selection order preserved) |
| Chart, key numbers | `experiments/figures/benchmark_lerobot_pusht.json`, `targeted_lerobot_pusht.json`. The renderer asserts 0.8% / 2.2% / 165 / 41 before drawing |

## Limitations

- **No policy rollouts.** The repo has no trained policy checkpoints or rollout recordings. The closed-loop benchmark (`experiments/CLOSED_LOOP_PROTOCOL.md`) is still a draft with no results. Every clip is a real training demonstration and is labelled "not policy rollouts". Producing real rollouts would mean training ACT/Diffusion Policy (about 100k steps per arm) on a GPU, which was not run.
- **The coreset tiles in scene 3 were re-selected.** The benchmark result files do not store the 41 selected episode IDs. `scripts/prepare_data.py` rebuilds the exact split and re-runs the same selector with current code (0.13.1). The benchmark itself ran on 0.8.0, so the tiles may differ slightly from the episodes that produced the numbers. The counts (165 / 41) and all metrics are from the original run.
- **Scene 2 runs on all 206 episodes** (CLI usage: 52 kept), while the benchmark uses the 165-episode training split (41 kept). The video labels each set.
- **Old version, single run.** The headline is a single BC-MLP run per arm on Calibra v0.8.0, and the quality score has changed since (76.7 then, 98.3 now with the `pusht` profile). The video shows only the current score from the live CLI run.
- The trace panel shows raw x/y target positions. It illustrates spread, not the exact feature space the selector uses.

## Reproduce

```bash
# Python with numpy, pydantic, pyarrow, duckdb, pillow; ffmpeg with libdav1d + libx264
PYTHONPATH=. python -m calibra analyze pusht --profile pusht > demo-video/evidence/analyze_pusht.txt
PYTHONPATH=. python -m calibra prune pusht --keep 0.25 --strategy diversity --profile pusht \
    --out demo-video/evidence/coreset_pusht_25.json > demo-video/evidence/prune_pusht_25.txt
PYTHONPATH=. python demo-video/scripts/prepare_data.py
ffmpeg -i pusht/videos/observation.image/chunk-000/file-000.mp4 -f rawvideo -pix_fmt rgb24 "$TMPDIR/pusht_frames.rgb"
python demo-video/scripts/render.py --frames "$TMPDIR/pusht_frames.rgb"              # ~1 min on 8 cores
python demo-video/scripts/render.py --frames "$TMPDIR/pusht_frames.rgb" --stills 5 21 38.5   # PNG checks
```

No production code was modified, and no training was run.
