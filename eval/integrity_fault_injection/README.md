# Integrity fault-injection benchmark

Injects controlled acquisition faults into real LeRobot v3 datasets and measures
whether `calibra integrity` flags them, at the right severity, without flagging
clean data. The pre-registered design is in [PROTOCOL.md](PROTOCOL.md).

## Requirements

- Calibra installed from this repository (`pip install -e '.[video]'`)
- `ffmpeg` with `libsvtav1` on `PATH`
- The three datasets downloaded at the pinned revisions (see `config.toml`):

```bash
hf download --repo-type dataset lerobot/unitreeh1_rearrange_objects \
    --revision e874d89b9024bad414deb45d7da82fa93601c260 --local-dir data/unitreeh1_rearrange_objects
hf download --repo-type dataset lerobot/aloha_static_battery \
    --revision 06dc3da83c4fd3d1889b00f1dfd3780da8421f64 --local-dir data/aloha_static_battery
hf download --repo-type dataset lerobot/pusht \
    --revision 7628202a2180972f291ba1bc6723834921e72c19 --local-dir pusht
```

`run.py` reads each copy's revision from the Hugging Face download cache and
refuses to run if it differs from `config.toml`.

## Run

From the repository root:

```bash
# everything (hours; resumable: rerun the same command to continue)
python eval/integrity_fault_injection/run.py --run v0.13.0

# one dataset, a subset of variants, one rep
python eval/integrity_fault_injection/run.py --datasets h1 --variants freeze.,dup. --reps 1 --run try

# tables
python eval/integrity_fault_injection/score.py results/v0.13.0
```

`run.py` checks that the thresholds in `config.toml` equal the ones in the
Calibra source and that the installed version matches, then for each trial
builds a working copy under `work/` (symlinks; the source dataset is never
written), injects the fault with a seed derived from the trial id, and runs
`calibra integrity --json` as a user would. Each trial appends one line to
`results/<run>/trials.jsonl` with the ground truth and the verdict; the run's
environment is in `results/<run>/manifest.json`.

`score.py` writes `summary.json` and `summary.md`: clean-data triage, recall
per fault family and tier, sub-threshold and by-design behaviour, severity
agreement and collateral flags.

## Layout

```
config.toml          datasets, revisions, thresholds, variants, tiers, reps
harness/v3.py        copy-on-write LeRobot v3 working copies, episode relocation
harness/faults.py    injectors: ground truth and expected levels per variant
run.py               trials -> results/<run>/trials.jsonl
score.py             trials.jsonl -> summary.json, summary.md
results/<run>/       committed results of published runs
work/                scratch working copies (ignored)
```
