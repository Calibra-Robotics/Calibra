# Calibra Score — Formal Specification

The **Calibra Score** is a composite 0–100 quality metric for robot imitation-learning datasets. It measures the properties of a dataset that are predictive of downstream policy training success, organized into four orthogonal dimensions.

The score is computed by `calibra card` and embedded as `calibra_score` YAML frontmatter in every dataset card. It enables cross-dataset comparison and powers the community percentile ranking in `calibra compare --community`.

---

## Dimensions

| Dimension | Weight | Max pts | What it measures |
|-----------|-------:|--------:|-----------------|
| Temporal Stability | 29% | 25 | Timestamp regularity, dropout rate, jitter |
| Control Smoothness | 24% | 20 | Jerk spikes, velocity discontinuities |
| Coverage Diversity | 29% | 25 | Action entropy, state-space coverage |
| Task Structure | 18% | 15 | Contact phase balance, phase completeness |

**Total: 85 points, normalized to 0–100.** Until 2026-10-20 Control Smoothness
was 35 points, 15 of them for LDLJ. LDLJ was dropped: its fault detection is
inconsistent and it shifts with sampling rate alone
([investigation](https://github.com/Calibra-Robotics/Calibra/tree/main/eval/investigations/ldlj)).
Scores computed before and after that change are not comparable.

---

## Score Categories

| Score | Category | Interpretation |
|------:|----------|----------------|
| 90–100 | Excellent | Near-ideal data quality; minimal intervention needed |
| 75–89 | Good | Minor issues; policy should converge reliably |
| 60–74 | Fair | Moderate issues; extra training iterations likely |
| 40–59 | Poor | Significant quality problems; consider recollection |
| 0–39 | Critical | Severe defects; do not train without remediation |

---

## Dimension Details

### 1. Temporal Stability (25 pts)

Measures the regularity of the timestamp stream across episodes.

| Sub-metric | Max pts | Threshold |
|-----------|--------:|-----------|
| Dropout rate | 10 | warn >1%, crit >5% |
| Jitter CV | 10 | warn >5%, crit >20% |
| Timestamp monotonicity | 5 | any backward step = critical |

**Why it matters:** Sequence policies (ACT, Diffusion Policy) learn implicit timing from the action stream. Irregular timestamps teach the policy to produce irregular motions at deployment.

---

### 2. Control Smoothness (20 pts)

Measures the smoothness of the demonstrated joint trajectories.

| Sub-metric | Max pts | Threshold |
|-----------|--------:|-----------|
| Jerk spike rate | 10 | warn >2%, crit >5% |
| Velocity discontinuity rate | 10 | warn >2%, crit >5% |

When the dataset has a profile with flag thresholds, the score uses those
instead, the same bounds as its integrity flags: `pusht` uses 11% / 25% for
spikes and 28% / 40% for velocity discontinuities. Both metrics depend strongly
on sampling rate (the same ALOHA motion reads 1.45% velocity discontinuities at
50 Hz and 15.6% at 10 Hz), so compare scores between datasets recorded at
similar rates.

**Why it matters:** High jerk forces the policy to learn discontinuous action distributions, increasing training variance. (An earlier version of this page cited a correlation with policy success rate, r = 0.71 across 38 datasets; no data in the repository supports it, so it was removed.)

**Profiled datasets.** With profile thresholds, a dataset is judged against its own clean episodes, so clean data of a profiled dataset scores well on smoothness by construction (PushT: 98.3 with its profile, 52.1 without). A profiled score means "clean for its kind" and does not compare directly with unprofiled scores.

---

### 3. Coverage Diversity (25 pts)

Measures how thoroughly the dataset explores the task's state-action space.

| Sub-metric | Max pts | Threshold |
|-----------|--------:|-----------|
| Action entropy (bits/dim) | 15 | warn < 2.5, crit < 1.5 |
| State coverage (coreset fraction) | 10 | warn < 0.4, crit < 0.2 |

**Why it matters:** Low-diversity datasets cause policies to overfit to narrow demonstration modes and fail on even small task variations at deployment.

---

### 4. Task Structure (15 pts)

Measures the presence and balance of semantically distinct task phases.

| Sub-metric | Max pts | Threshold |
|-----------|--------:|-----------|
| Contact/grasp phase fraction | 10 | warn < 10%, crit < 5% |
| Phase transition consistency | 5 | high variance across episodes |

**Why it matters:** Manipulation tasks require distinct approach, grasp, and release phases. Underrepresented contact phases lead to policies that fail at the critical grasp moment even when approach succeeds.

---

## Computing the Score

```bash
# Score is automatically included in every dataset card
calibra card /data/my_demos.h5 --policy act

# Or compute standalone
calibra score /data/my_demos.h5
```

The score is also embedded as YAML frontmatter:

```yaml
calibra_certified: true
calibra_version: "0.6.0"
calibra_n_episodes: 120
calibra_score: 82.3
calibra_score_category: "Good"
```

---

## Community Comparison

Once enough outcomes are recorded in Calibra Cloud, the score percentile for each dimension is available:

```bash
calibra compare /data/my_demos.h5 --community --policy act
```

This shows how your dataset ranks against all datasets in the Calibra community for the same policy family, identifying which dimension is your biggest relative weakness.

---

## Versioning

The scoring formula is versioned alongside Calibra releases. Breaking changes to dimension weights or thresholds increment the minor version and are announced in the changelog. Scores are always tagged with the `calibra_version` that produced them.
