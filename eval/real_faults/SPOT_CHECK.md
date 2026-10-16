# Human spot-check of the AI first-pass labels

All three batches were labeled by an AI first pass. Checking these 24 episodes (about 15
minutes) is enough to call the batches human-verified or to find where the labels are wrong.
They cover every non-clean label, the borderline cases, and a few plain clean ones per batch.

For each episode: open it, decide the label yourself **before** reading the AI label in
`sheet.csv`, then compare. If you disagree, edit `label` / `notes` in that batch's
`sheet.csv` and replace the `[AI first pass, needs human check]` prefix with
`[human-checked]`. Then re-run `score` for the batch.

Viewer (needs LeRobot installed; `--root` points at the local copy):

```bash
lerobot-dataset-viz --repo-id <repo> --root <root> --episode-index <N>
```

| Batch | Repo / root | Episode | AI label | What to check |
|---|---|---|---|---|
| 001 | `lerobot/pusht` / `./pusht` | 3 | unusual_valid | fast 104 px reposition: deliberate, or a glitch? |
| 001 | | 4 | unusual_valid | same, 81 px jump |
| 001 | | 174 | unusual_valid | longest episode (246 steps): valid multi-attempt push? |
| 001 | | 45 | clean | lowest final reward (0.83): T really on target? |
| 001 | | 141 | clean | direction-changing jump; T on target at the end? |
| 001 | | 120 | clean | idle start, then fast move |
| 001 | | 60 | clean | image change lags state by up to 3 frames (desync?) |
| 001 | | 112 | clean | plain control |
| 002 | `lerobot/unitreeh1_rearrange_objects` / `./data/unitreeh1_rearrange_objects` | 26 | acquisition_fault | duplicate of ep 6 (also verified bit-identical by script) |
| 002 | | 6 | clean | the original of 26 |
| 002 | | 0 | unsure | ~6 Hz oscillation in state[4]: can you see joint chatter? |
| 002 | | 21 | unsure | same group, strongest oscillation share |
| 002 | | 7 | clean | 200-step episode: task really completed? |
| 002 | | 12 | clean | 200-step episode |
| 002 | | 29 | clean | 200-step episode |
| 002 | | 10 | clean | plain control |
| 002 | | 25 | clean | final frame ambiguous at thumbnail size (white + blue objects) |
| 003 | `lerobot/aloha_static_battery` / `./data/aloha_static_battery` | 17 | clean | ends while arm still moving: battery seated? |
| 003 | | 37 | clean | same |
| 003 | | 48 | clean | same |
| 003 | | 0 | clean | plain control |
| 003 | | 24 | clean | plain control |
| 003 | | 30 | clean | plain control |
| 003 | | 41 | clean | plain control |

After checking, also say in each batch's `LABELING.md` who checked which rows and when.
