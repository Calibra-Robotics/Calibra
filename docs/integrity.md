# Integrity Checks

`calibra integrity` answers the first question practitioners ask about a new dataset — before quality, diversity, or optimization matter at all:

> **Can I trust this dataset?**

It runs a fixed, cheap set of checks and groups findings into **Critical / Warnings / Passed**, with a demoted `Integrity Score` as a summary line rather than the headline result — a finding is never collapsed straight to a single number.

```bash
calibra integrity /data/my_demos.h5
calibra integrity /data/my_demos.h5 --format hdf5
calibra integrity /data/my_demos.h5 --json
```

```
─── Dataset Integrity ────────────────────────────────────
my_demos · 120 episodes

Critical (1)
  ❌ camera_freeze_events: 1 of 120 episodes (0.8%) contain a run of ≥5
     consecutive near-identical camera frames (longest: 14 frames in
     episode ep_17), suggesting the camera stopped updating.  [BLOCK]
      A frozen camera segment means the policy would be trained on stale
      visual input during that window — likely to cause visually-triggered
      failures when deployed against a live, moving scene.

Warnings (0)

Passed (8)
  ✅ timestamp_jitter_cv: Step-to-step timing is consistent.
  ✅ timestamp_dropout_rate: Timestamp dropout rate is within acceptable range.
  ✅ action_dropout_rate: Action-dropout rate is within acceptable range.
  ✅ short_episode_fraction: No suspiciously short episodes detected.
  ✅ duplicate_frame_rate: Camera frames show expected frame-to-frame variation.
  ✅ ldlj: Action trajectories are smooth (LDLJ within threshold).
  ✅ jerk_spike_rate: Jerk spike rate is within acceptable range.
  ✅ velocity_discontinuity_rate: Velocity profile is continuous — no sudden reversals.

Integrity Score: 89/100  ·  Status: Warning
CI result: Failed  ·  Reason: 1 CRITICAL block-level finding(s): camera_freeze_events
──────────────────────────────────────────────────────────
```

`Status` and `CI result` are deliberately separate. `Status` is a severity summary across every finding (can read "Warning" even with a CRITICAL present, if enough other checks passed). `CI result`, which is what actually sets the exit code, only fails on **block**-level findings: objective acquisition/format/sync/completeness failures (dropped timestamps, missing frames, a frozen or corrupted camera, incomplete episodes). Findings whose `suggested_action` is `inspect` are a review signal, not proof the dataset is broken, and don't fail CI on their own. These are the two motion-smoothness metrics (`jerk_spike_rate`, `velocity_discontinuity_rate`), which can legitimately hit CRITICAL on a scripted/planner-collected dataset.

```bash
calibra integrity /data/my_demos.h5 --strict
```

Pass `--strict` to fall back to the old, blunter policy: fail on *any* CRITICAL finding, including motion-review ones. Every finding also carries a `suggested_action` (`informational` / `inspect` / `block`) in `--json` output, so a CI pipeline that wants a custom policy can compute its own pass/fail from the raw findings instead of relying on the built-in `ci_result`.

An analyzer that couldn't run at all (e.g. duplicate-frame/camera-freeze/blur on a video-backed LeRobot v2/v3 dataset, or the video file checks on a Hub ID whose videos aren't downloaded) shows up under **Not Evaluated** with a reason, rather than disappearing from the output silently.

### CI Policy Files

The built-in block/inspect split is one reasonable default, not the only one a team might want. A research lab might only want to block on corrupted timestamps; a production team might also block on camera freezes; another team might treat calibration drift as a blocker once they've validated the thresholds against their own hardware. `--policy` lets you configure that per metric, instead of the all-or-nothing choice between the default and `--strict`:

```bash
calibra integrity /data/my_demos.h5 --policy ci_policy.json
```

```json
{
  "timestamp_jitter_cv": "block",
  "camera_freeze_events": "block",
  "joint_offset_max_abs": "inspect",
  "jerk_spike_rate": "inspect"
}
```

A policy file is a flat JSON object mapping a **metric name** — the exact names shown in the `metric` field of `--json` output, e.g. `camera_freeze_events`, `blurry_episode_fraction`, `joint_offset_max_abs` — to `"block"` or `"inspect"`. It only overrides the CI consequence of a **CRITICAL** finding on that metric; OK and WARNING findings are unaffected — a WARNING never fails CI, policy or not. Metrics not listed keep the built-in default. An unrecognized metric name in the file prints a warning to stderr and is otherwise ignored, so a policy written against an older or newer Calibra version doesn't hard-fail.

`--policy` and `--strict` are mutually exclusive — once you're configuring per-metric behavior, that fully replaces the blunt "fail on anything" fallback rather than the two combining in some precedence order.

---

## Checks

### Timestamp consistency

**Detects:** irregular step-to-step timing (`timestamp_jitter_cv`) and dropped/missed ticks (`timestamp_dropout_rate`), via coefficient of variation and gap-vs-median-delta analysis.

**Why it matters:** irregular control-loop timing degrades time-series policies (transformers, diffusion) that assume fixed-frequency data. Dropout creates artificial velocity discontinuities that BC policies learn as spurious high-jerk transitions.

**Example output:**
```
⚠️  timestamp_jitter_cv: High coefficient of variation in inter-step timing
    (18.3% mean CV across 120 episodes).
     Irregular control-loop timing degrades time-series policies that
     assume fixed-frequency data. Consider resampling to a uniform
     frequency before training.
```

### Sensor synchronization

**Detects:** camera-timestamp lag relative to the master clock (`camera_lag_std[<camera>]`), action/observation timestamp misalignment (`action_obs_misalignment`), and camera-to-proprioception render lag (`camera_physics_drift`, primarily relevant to simulated data).

**Why it matters:** closed-loop policies that fuse camera and proprioception observations will experience systematic desync, especially around contact transitions where precise timing matters most.

### Episode completeness

**Detects:** episodes with a step count far below the dataset's typical length (`short_episode_fraction`, IQR-outlier test). The spread used for the fence is at least 25% of the median length, so datasets recorded at a few fixed lengths (IQR = 0) don't flag every episode of the shorter setting; an episode must then be below about 62% of the typical length to count as short.

**Why it matters:** short-outlier episodes are usually failed demonstrations that were never filtered out — an operator abort, a safety-limit trip, or early termination. Training on them teaches the policy to abort tasks prematurely.

### Duplicate episodes

**Detects:** episodes whose actions and numeric observations are byte-identical to another episode (`duplicate_episode_fraction`). Any duplicate is CRITICAL and block-level; the finding names each copy and its original.

**Why it matters:** an exact copy double-weights one demonstration and can land the same data in both training and validation splits. It comes from export or merge mistakes, not from recording, so the fix is to delete the copies. Found in practice: episode 26 of `lerobot/unitreeh1_rearrange_objects` @ `e874d89b` is a copy of episode 6 (`eval/real_faults/batches/batch-002`).

### Duplicate frames

**Detects:** camera frames that are near-identical to the frame immediately before them (`duplicate_frame_rate`) — a dropped grab or re-emitted buffer rather than a genuinely new observation.

**Why it matters:** a policy trained on repeated frames can learn to associate a stale visual observation with the wrong action, or waste model capacity encoding redundant input.

**Example output:**
```
⚠️  duplicate_frame_rate: 7.2% of camera frame transitions are near-identical
    to the previous frame, across 118 episodes with image data.
     Duplicate frames mean the camera pipeline is not capturing a new
     image every control step.
```

### Camera freeze

**Detects:** a *sustained run* (default: 5+ consecutive frames) of near-identical camera frames within an episode — the camera stopped updating entirely, not just a single dropped grab (`camera_freeze_events`).

**Why it matters:** a frozen camera segment trains the policy on stale visual input for that whole window, which shows up as visually-triggered failures once deployed against a real, moving scene. This is a stronger signal than an isolated duplicate frame, which is why it's tracked as a separate, more severe check.

### Blur

**Detects:** episodes whose camera frames are anomalously blurry *relative to the rest of the dataset* (`blurry_episode_fraction`), via an IQR-outlier test on per-episode mean Laplacian variance — the standard, dependency-free sharpness proxy.

**Why it matters:** motion blur, defocus, or a dirty/misconfigured lens gives the policy a degraded or misleading visual observation for that episode.

**Example output:**
```
⚠️  blurry_episode_fraction: 14.3% of episodes (1/7) have camera frames
    markedly blurrier than the rest of the dataset (mean Laplacian
    variance below the IQR lower fence). IDs: ['episode_3']
     Inspect the flagged episodes before training.
```

!!! note "Relative, not absolute"
    Laplacian variance has no universal "blurry" cutoff — it depends on camera resolution, exposure, and scene content. This check flags episodes that are outliers *within their own dataset*, the same statistical approach used for episode completeness above. A dataset that's uniformly blurry throughout won't self-flag; there's nothing anomalous to compare against.

!!! note "Format coverage"
    Duplicate-frame, camera-freeze, and blur detection all need decoded image arrays. They work on HDF5-format datasets (Isaac Lab, robomimic-style exports) by default, and on **LeRobot v1** datasets (HuggingFace `Image`-feature columns) via the opt-in `--decode-images` flag — off by default since decoding increases load time and memory use. **LeRobot v2/v3** datasets store frames as encoded mp4 video rather than per-frame images. Pass `--decode-video` to decode a sample of episodes (default 20, evenly spaced; `--video-sample N`) and run duplicate-frame and camera-freeze on every camera, with the same measure and thresholds as for image datasets. Frames are processed at full resolution in 64-frame chunks, so memory stays bounded; the verdict uses the worst camera and lists all of them. Without the flag, and for blur in any case, these checks show under **Not Evaluated** (not an error). The video files themselves are always checked; see [Video files](#video-files-lerobot-v2v3) below.

    Example: on `lerobot/aloha_static_battery`, `--decode-video` reports 30% repeated frames on `cam_high` (11–21% on the other cameras): the cameras run slower than the 50 Hz recording and frames are padded by repetition. Rendered simulations repeat frames legitimately when nothing in view moves (PushT: about 1.5%, below the 5% warning).

### Video files (LeRobot v2/v3)

**Detects:** per episode and camera, whether the mp4 referenced from `meta/` is usable for training:

| Metric | Fails when |
|--------|------------|
| `video_missing_rate` | the referenced mp4 does not exist |
| `video_decode_failure_rate` | the file cannot be opened, or the episode's first or last frame does not decode (truncated or corrupt file) |
| `video_frame_mismatch_rate` | the video does not cover the episode's frames: v2 compares the file's frame count with the episode length, v3 checks the episode's `from_timestamp`/`to_timestamp` span against its length and the file's duration. A one-frame difference is tolerated. |
| `video_fps_mismatch_rate` | the stream fps differs from `info.json` by more than 1% (counted per file) |

All four are objective format failures, so a CRITICAL finding is `block`-level. `--json` output lists the affected episode indices per metric under `video_affected_episodes`, ready to drop or re-encode.

**Why it matters:** the Parquet data can be perfect while the videos are not. LeRobot looks frames up by timestamp, so a missing, short, or wrong-fps video either crashes training when that episode is sampled or silently pairs actions with the wrong frames.

**Requirements:** the check runs automatically on **local** v2/v3 datasets and needs OpenCV (`pip install 'calibra-robotics[video]'`). It reads only container metadata and two frames per episode, not whole videos. Hub IDs are listed under Not Evaluated, because the Parquet loader does not download videos; download first with `hf download --repo-type dataset <repo_id> --local-dir <dir>` and run on the directory.

### Jittery / jerky motion

**Detects:** physically jittery recorded motion via two metrics: abrupt jerk spikes (`jerk_spike_rate`) and sudden velocity reversals (`velocity_discontinuity_rate`).

**Not an integrity check: `ldlj`.** Calibra still computes LDLJ (Logarithmic Dimensionless Jerk) for the Calibra Score, but it is not part of `calibra integrity`, its score or its CI result. Injecting jerk spikes into ALOHA data makes LDLJ score the corrupted copy as *smoother*, and on the same trajectories it moves by about 4 units between 50 Hz and 10 Hz ([spike injection](https://github.com/Calibra-Robotics/Calibra/blob/main/eval/investigations/ldlj/SPIKE_INJECTION.md), [sampling rate](https://github.com/Calibra-Robotics/Calibra/blob/main/eval/investigations/ldlj/SUBSAMPLING.md)).

**Sampling rate matters for both checks too.** The same ALOHA trajectories read 1.45% velocity discontinuities at 50 Hz and 15.6% at 10 Hz. Compare motion results only between datasets recorded at similar rates.

**Why it matters:** high jerk in demonstration data forces the policy to learn discontinuous action transitions; BC policies trained on jerky data produce jerky rollouts that stress hardware and reduce task success, especially on contact-rich tasks.

**Example output:**
```
⚠️  jerk_spike_rate: 3.1% of steps have jerk > 5.0× median jerk:
    anomalous discontinuities in action sequence.
     Jerk spikes are typically caused by dropped frames, bad episode
     boundaries, or incorrect time alignment. They create spurious
     high-gradient targets that BC policies overfit to, producing
     unstable rollouts.
```

!!! note "Integrity vs. Quality split for motion"
    `calibra integrity` only checks whether the recorded motion is *physically jittery*, with the same two metrics regardless of why. It does not check action-state tracking error or scripted-vs-teleoperated collection signature; those are collection-method questions, not a trust check, and stay under `calibra audit` (Motion Quality dimension).

### Leader/follower calibration drift

**Detects:** a systematic, consistent per-motor offset between the commanded action and the observed joint state (`action - observation.state`), measured only during sustained stationary "hold" frames — not during motion, where the gap is dominated by ordinary tracking lag rather than a calibration issue (`joint_offset_max_abs`).

**Why it matters:** a stale leader/follower calibration — e.g. the arms were re-zeroed differently, or a joint offset drifted between sessions — produces exactly this signature: a *stable*, motor-specific bias that's invisible in training loss (the policy just learns the biased mapping) but shows up as consistent under/overshoot at deployment. This is the failure mode described in [LeRobot issue #3758](https://github.com/huggingface/lerobot/issues/3758): an unnoticed ~17° offset on one joint produced roughly a 6cm Cartesian gripper error. The check is post-hoc and read-only — it uses `action` and a paired state observation already present in most teleoperation datasets, no new data collection required.

**Example output:**
```
⚠️  joint_offset_max_abs: Motor/dim 2 shows a consistent action-state offset
    of 0.31 (12.4% of its observed range) across 340 pooled stationary
    frames, stable across holds (|mean|/std = 4.2).  [INSPECT]
     A stable per-motor action/state offset during holds — not during
     motion — is the signature of a leader/follower calibration drift.
     This is a review signal, not proof of a broken dataset: verify the
     leader/follower zero-offset calibration before relying on this data
     for precision manipulation.
```

!!! note "Uncalibrated thresholds — capped at WARNING"
    Unlike `action_state_divergence` (calibrated from 12 reference hardware profiles), this check has not yet been validated against a dataset with a known injected offset. It never reports CRITICAL, and `suggested_action` is always `inspect`, until real-world calibration data is available. The offset threshold is expressed as a fraction of each motor's own observed range (not an absolute unit like radians), since state units vary by dataset and have no universal scale — the same reasoning the [Blur](#blur) check applies to Laplacian variance.

---

## Demo recording

`docs/demo.tape` is a [VHS](https://github.com/charmbracelet/vhs) script that reproduces the full workflow end-to-end — `calibra integrity` on a small synthetic dataset (generated by `docs/demo_fixture.py`, no external data needed), then a peek at `audit`/`review`/`prune`. Generate the GIF locally with:

```bash
brew install vhs
vhs docs/demo.tape   # writes docs/figures/integrity_demo.gif
```

---

## How reliable are the checks?

### Detector calibration

Calibra flags episodes that look unusual relative to the rest of the dataset. Not every flag is corruption; some episodes are just at the tail of a clean distribution. The table below shows, for each detector, how often it fires on **ground-truth-clean data** (benign firing rate) and how often it catches **synthetically-corrupted episodes** (episode detection rate). Both measured on real LeRobot datasets via `experiments/benign_firing_rate_benchmark.py`.

| Detector | Benign firing rate | Episode detection rate | Signal ratio |
|---|---:|---:|---:|
| `jitter_cv` | 0.0% | 37.1% | n/a |
| `dropout_rate` | 0.0% | 18.8% | n/a |
| `spike_rate` | 6.9% | 62.9% | 9× |
| `vel_disc_rate` | 1.0% | 31.0% | 32× |
| `ldlj` | 0.5% | 42.9% | 88× |

Averaged across `lerobot/pusht` (n=206) and `lerobot/aloha_sim_insertion_scripted` (n=50) with 95% Wilson CIs. Signal ratio is undefined (n/a) when the benign rate is 0%. PushT is measured with its `pusht` dataset profile (both action axes scored) and ALOHA with its `aloha` profile (both grippers excluded); last re-measured 2026-10-20.

`ldlj` is the least consistent detector: it catches 6 of 7 corrupted ALOHA episodes but 0 of 30 on PushT, it scores some spike-injected data as *smoother*, and it shifts with sampling rate alone ([investigation](https://github.com/Calibra-Robotics/Calibra/tree/main/eval/investigations/ldlj)). It is therefore not part of `calibra integrity`; it only feeds the Calibra Score.

**A detected anomaly is not the same as confirmed corruption.** Use `calibra review` to inspect flagged episodes before deciding to drop, downweight, or annotate them.

[Full per-dataset tables with confidence intervals](https://github.com/Calibra-Robotics/Calibra/blob/main/experiments/results/benign_firing_rates.md)

### Fault injection

We injected controlled acquisition faults into on-disk copies of three LeRobot v3.0 datasets (`unitreeh1_rearrange_objects`, `pusht`, `aloha_static_battery`) and ran `calibra integrity` on each copy: 981 trials on v0.13.0 and 471 after the fixes it led to, protocol pre-registered.

| Fault (clearly above threshold) | v0.13.0 | Current |
|---|---:|---:|
| Duplicate episodes | 105/105 | 105/105 |
| Missing, truncated, or wrong-fps video | 96/96 | 96/96 |
| Dropped video frames | 60/60 | 60/60 |
| Frozen camera stream (every episode decoded) | 60/60 | 60/60 |
| Repeated frames (10% to 30%) | n/a | 3/3 |
| Timestamp dropout, jitter, swaps, and unit errors | 150/180 | 210/210 |

On unmodified data, 1 of 300 evaluated checks fired: `duplicate_frame_rate` on ALOHA, which detects real repeated frames (most likely cameras slower than the 50 Hz recording rate), an anomaly rather than confirmed corruption. Known limits: on AV1 video, `duplicate_frame_rate` sees only repeats coded as predicted frames, so it reports about half the true rate; frozen cameras are missed when the frozen episode is outside the default 20-episode video sample (19/60), which the output now says. All three datasets have synthetic timestamps, so timing results show the detectors respond to injected faults, not to real clock faults. These are synthetic injections: they show what Calibra can detect, not how often faults occur in real data.

[Report, findings, and limitations](https://github.com/Calibra-Robotics/Calibra/blob/main/eval/integrity_fault_injection/REPORT.md)

## Next steps

Once a dataset passes Integrity, move to:

- `calibra audit` / `calibra score` — is the data *clean*? (action-state tracking error, scripted-vs-teleop signature, task structure)
- `calibra review` — is it *diverse* enough, and which episodes are worth a human look?
- `calibra prune` — build a smaller, high-quality coreset for training

See the [full command reference](commands.md) for all of the above.
