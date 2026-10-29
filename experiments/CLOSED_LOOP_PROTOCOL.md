# Closed-Loop Selection Benchmark (P1 research gate)

**Status:** DRAFT, not frozen. Committing this file freezes it. All decision
criteria are fixed below. Two values are set by a fixed rule from Stage 1 timing
(training steps S, rollout count) and are recorded in a dated addendum commit
before any subset model is trained.
**Code revision:** calibra v0.13.1 @ `d1e03b1` (update to the commit that adds the
harness below). lerobot 0.4.4.

**Question:** *Does Calibra improve closed-loop policy success compared with random
selection at the same training-data budget?*

This result decides the research direction. A positive primary result is necessary
for model-aware selection work (Learn) but not sufficient on its own: the Learn
decision also reports the K-Center comparison, effect size, selection runtime and
whether the result held at n = 5 if the extension ran. A negative or inconclusive
primary result does not justify Learn, and we
reconsider where Calibra has a stronger advantage (integrity, fast low-cost
selection). The success criteria below do not change after results are seen.

---

## 1. Fixed setup

| Item | Value |
|---|---|
| Dataset | `lerobot/pusht` (position control, see `calibra/dataset_profiles.py`) |
| Policy | ACT, subject to the Stage 1 gate; fallback Diffusion Policy |
| Retention | 25% of total training frames |
| Seeds | 3 (0, 1, 2), extension rule in §5 |
| Training | Fixed number of optimizer steps S, identical for every arm. Stage 1 uses the LeRobot 0.4.4 default (100,000 steps). The exact S used in Stage 1 is frozen in the addendum and applies to every later run. |
| Checkpoint | Final checkpoint only. No best-of selection on evaluation rollouts. |
| Evaluation | 500 rollouts per trained model, fixed env seeds 100000-100499, identical for every arm. Practicality limit: if Stage 1 shows evaluating one model takes more than 8 hours wall clock, use the largest of 400, 300 or 200 that fits (seeds 100000 upward). The count is frozen in the addendum, never below 200. |
| Success | gym-pusht episode success (goal coverage above the env's success threshold, as LeRobot `pc_success` reports it) |

## 2. Arms

| Arm | Selection | Notes |
|---|---|---|
| Full | All episodes | Reference; success of subsets is reported as % of Full |
| Random | Episodes in random order, new subset per seed | Primary comparison |
| K-Center | Greedy k-center order (`calibra/pruning.py`) | Mandatory secondary comparison (diversity baseline). Never cut. |
| Calibra | `calibra prune` ranking at the pinned revision | Method under test |
| CUPID (fallback DemInf) | Stage 3 only | CUPID, because it reports PushT directly. DemInf only if CUPID cannot be run at the pinned revisions within the Stage 3 budget; the switch and its reason are recorded before any Stage 3 result is seen. Policy training and influence computation count as selection overhead. |

## 3. Data-budget control

Equal training steps do not mean equal data, so the budget is defined in frames.

- **Primary (matched frames):** each method produces an episode ranking. Episodes
  are added in ranked order until cumulative frames reach 25% of total training
  frames. Accepted deviation: ±2% of the budget. Random uses the same rule on a
  shuffled order.
- **Secondary (matched episodes):** the top 25% of episodes by count, same
  rankings.
- Record for every run: episodes kept, frames kept, mean episode length.

Only the primary analysis decides §5. The secondary analysis is reported, and it
is the check on whether a result is an episode-length effect.

## 4. Stages and gates

| Stage | Work | Compute | Budget cap | Gate to continue |
|---|---|---|---|---|
| 0 | Evaluate the pretrained `lerobot/diffusion_pusht` checkpoint with our harness, using the model card's evaluation settings and 500 rollouts | RTX 2080 | $0 | Within ±5 pp of the model card's 65.4% (500 episodes, success = max overlap ≥ 95%), i.e. 60.4-70.4% |
| 1 | Train Full ACT, seed 0. Measure GPU-h/run, wall clock for training and for evaluation. | RTX 2080 | $0 | Full ACT success ≥ 40%. If not, switch to Diffusion Policy, retrain Full, re-time. The policy, S and the rollout count are fixed here (addendum commit), before any subset run. |
| 2 | Full ×2 more seeds, Random, K-Center, Calibra ×3 seeds | 2080 and/or GCP | $80 | Decision rule §5 |
| 3 | CUPID or DemInf ×3 seeds | GCP | $40 | Runs if Stage 2 is positive, or as the Learn test if requested |
| Reserve | §5 extension seeds, reruns after infrastructure failures | GCP | $30 | |
| **Total** | | | **$150** | Remaining $150 of credits is not used by this benchmark |

Evaluation compute counts toward each stage's cap. If the Stage 1 timing shows the
plan exceeds the cap, cut in this order: the Stage 3 baseline, then the rollout
count (down to 200). K-Center is never cut and seeds never go below 3.

## 5. Decision rule (primary analysis, Stage 2)

Let Δ_s = success(Calibra, seed s) − success(Random, seed s), and Δ̄ the mean over seeds.

Δ̄ is computed once, after all nine Stage 2 subset models are evaluated. No interim
looks.

**Primary (Calibra vs Random), the go/no-go:**

- **Positive:** Δ̄ ≥ +5 pp **and** Δ_s > 0 in at least 2 of 3 seeds.
- **Negative:** Δ̄ ≤ 0.
- **Inconclusive:** anything else.

**Extension trigger:** the extension runs if and only if the primary outcome at
n = 3 is inconclusive. Nothing else triggers or blocks it (not the K-Center result,
not the secondary matched-episodes analysis). It runs seeds 3 and 4 for Random,
K-Center and Calibra from the reserve, applies the same rule at n = 5 with "at
least 4 of 5", and happens at most once. Still inconclusive at n = 5 is reported as
inconclusive and does **not** justify Learn.

**Secondary (Calibra vs K-Center), mandatory, does not change the primary outcome:**
let Δᴷ_s = success(Calibra, seed s) − success(K-Center, seed s). A **stronger
exploratory result** is Δ̄ᴷ ≥ +5 pp **and** Δᴷ_s > 0 in at least 2 of 3 seeds (4 of
5 if the extension ran). Otherwise it is reported as Calibra not beating K-Center.

**Exploratory result vs superiority claim.** The outcomes above are exploratory
go/no-go results for our own research direction. Any statement that Calibra
outperforms Random or K-Center in closed-loop success (README, paper, outreach)
additionally needs the two-sided 95% t-interval of the mean paired difference over
seeds to exclude 0. Seeds are the unit of replication, so per-rollout tests are not
used for this. Without it, external wording says "exploratory" and shows per-seed
results.

Reported for every arm: mean and per-seed success, Wilson 95% interval per model,
paired differences vs Random and vs K-Center, % of Full, and variance across seeds.
Selection runtime (wall clock and GPU-h), training GPU-hours and total compute cost
are reported for every arm and are kept separate from the effectiveness gates
above.

## 6. Cloud spending controls

Budget alerts on Google Cloud do not stop spending.

- Every GPU VM is created with a maximum run duration and a delete-on-termination
  action, sized to the measured run time plus a margin.
- Spot VMs where the run can tolerate preemption (checkpoint every N steps).
- Budget alerts at 50%, 90% and 100% of $150 on the project.
- Check for running instances at the end of each working day.
- Before Stage 2: confirm GPU quota on the project and the credits' expiry date.

## 7. Code needed before Stage 2

- Add `kcenter` and the Stage 3 baseline to `CONDITIONS` in `calibra/experiment_log.py`.
- Frame-budget selection helper (ranking → episodes up to a frame budget).
- Closed-loop eval harness that records env seeds, rollout count and checkpoint step.
- Each run logged with `calibra experiment record`, including frames kept.

## 8. Timeline (November 2026 to January 2027)

Scope is fixed to this protocol. Any further benchmark gets its own protocol,
written and committed after this one reports.

| Weeks | Work | GPU budget |
|---|---|---:|
| 1-2 | Commit this protocol, request GPU quota, build eval harness, Stage 0 | $0 |
| 3-4 | Stage 1 on the RTX 2080: Full ACT, timing, policy decision, addendum commit (policy, S, rollout count). Frame-budget helper and `CONDITIONS` update. | $0 |
| 5-7 | Stage 2 as one block: Full, Random, K-Center, Calibra × 3 seeds at matched frames. Apply §5. | ≤ $80 |
| 8-9 | Inconclusive: seeds 3-4 from the reserve. Positive: Stage 3. | ≤ $30 / ≤ $40 |
| 10-12 | Reproducibility package (pinned commit, configs, seeds, raw results, rerun script), one clean rerun of a single cell, write-up, Learn decision | reserve |
| **Total** | | **≤ $150** |

Deliverables: the §5 outcome for Calibra vs Random (positive, negative or
inconclusive); the Stage 3 comparison if it ran, or the reason it did not; the
reproducibility package; the Learn decision that follows from §5.

Design-partner outreach runs alongside every week (target: first active partner
on live data in December 2026) and is not scheduled around experiment work.
