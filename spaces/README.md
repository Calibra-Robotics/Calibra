---
title: Calibra Dataset Decisions
emoji: 🤖
colorFrom: purple
colorTo: blue
sdk: gradio
sdk_version: "5.50.0"
app_file: app.py
pinned: false
license: other
short_description: Decide which robot demos to keep, drop, or annotate
tags:
  - robotics
  - dataset-quality
  - lerobot
  - imitation-learning
  - data-curation
---

# Calibra Dataset Decisions

**What should I train on?**

Calibra is a robotics dataset decision layer. Enter a [LeRobot](https://github.com/huggingface/lerobot)
dataset ID (e.g. `lerobot/pusht`) and get what `calibra analyze` reports:

- **Decision**: noise regime, how many episodes to keep, and a per-episode KEEP / DROP table
  with reasons (annotate mode keeps redundant episodes as ANNOTATE instead)
- **Integrity**: Healthy / Warning / Critical, with the specific checks that failed
- **Calibration context**: detector firing rates compared with known-clean baselines
- **Aggregate scores** (collapsed): Calibra Score, coverage, redundancy. Not yet validated
  against policy performance, so the demo leads with decisions and evidence instead
- **Downloadable JSON** with every episode's disposition and characterization

The demo analyzes up to 50 episodes. Datasets with a known quirk get a dataset profile
automatically (e.g. PushT's 2-D action has no gripper dimension).

## Run locally

```bash
pip install 'calibra-robotics[lerobot]'
calibra analyze lerobot/pusht
calibra prune lerobot/pusht --keep 0.85 --export-dataset ./coreset
```

## About

Powered by [Calibra](https://github.com/Calibra-Robotics/Calibra).
