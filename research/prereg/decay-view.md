# Pre-registration: governed decay view (OptMem-inspired compression)

**Registered after the pilot (seed 0: R and the oracle) and before X or S
ran.** Harness: `experiments/decay_eval.py`. Module: `amberlog/decay.py`.
Evaluation seeds 1–5. Budget **300** estimated tokens for every arm, the
oracle included.

## Question

Does a bounded, query-independent view that summarises older memory carry
more of what is currently true than the same budget of the newest records,
without carrying withdrawn or superseded values?

## Pilot (seed 0)

| arm | current recall | stale answers | tokens |
|---|---|---|---|
| R recency | 0.594 | 0.000 | 300 |
| oracle | 1.000 | 0.000 | 128 |

Headroom over R: 0.406. R does not max the metric.

## Hypotheses (shares of per-seed headroom over R, averaged over seeds 1–5)

- **D1 (extractive decay).** X captures **≥ 0.25** of the headroom, and its
  stale-answer rate is **≤ 0.02** on every seed.
- **D2 (agent-summarised decay).** S captures **≥ 0.75** of the headroom,
  stale answers **≤ 0.02** on every seed. S's agent is a rule-based stand-in,
  not a model; a pass says the mechanism carries what a good summariser
  writes, not that a language model writes it.

`any_arm_beats_oracle` must be empty. Output: `research/results/decay-view.json`.

## Addendum A — replication of the repaired view (registered before seeds 6–10 ran)

The registered run (seeds 1–5) failed D1 and D2 and exposed one harness
defect (the reader crossed sentence boundaries inside summaries) and two
design defects (a revised memory kept its first position, buried in the
coarsest summaries; extractive summaries quoted chatter and cut facts). All
three were repaired by looking at seeds 1–5, so the post-hoc rerun there
confirms nothing. This addendum runs the repaired code, unchanged, on
**seeds 6–10** with **D1 and D2 unchanged**. Output:
`research/results/decay-view-confirm.json`.

## Addendum B — a real language model writes the summaries (registered before it ran)

Arm **M**: `qwen2.5:7b` (Ollama, local, temperature 0) answers the view's
summary requests through `OllamaClient`, which logs every call and its
tokens. Each reply goes through the same submission check as any agent; a
refusal is retried once with the reason, and what is still refused is
counted. Seeds **11–15** (never run before), budget 300, the repaired code.

- **D3.** M captures **≥ 0.75** of the headroom over R (the D2 bar), with
  stale answers **≤ 0.02** on every seed.
- Reported, no threshold: the share of summary requests the check refused
  (summaries stating something their sources do not), and model calls and
  tokens.
- `llama3.1:8b` is run the same way as a second, descriptive model.

Output: `research/results/decay-view-model.json` (and `-llama.json`).
