# M2 result — reflective rulebooks: M2a **NOT SUPPORTED**, M2b **SUPPORTED**

Registration: [prereg/m2-reflective-rulebooks.md](../prereg/m2-reflective-rulebooks.md)
(`5d79e4f`). Run: `python -m experiments.m2_rulebook --split test` in a
worktree pinned at `5d79e4f`. Seeds 200–204, qwen2.5:3b, 4 rounds of 8
training tasks, a 22-task test set asked after every round. Raw output:
[m2-qwen.json](m2-qwen.json). Status: **experimental**. `rulebook.py` is
opt-in and nothing uses it by default.

| arm | test accuracy, rounds 0 → 4 | final | test regressions |
|---|---|---|---|
| `no_rulebook` | 0.50 · 0.50 · 0.50 · 0.50 · 0.50 | 0.500 | 0 |
| `reflexion_append` | 0.50 · 0.53 · 0.49 · 0.53 · 0.55 | 0.545 (best baseline) | **8** |
| `ungated_rewrite` | 0.50 · 0.37 · 0.47 · 0.36 · 0.45 | 0.445 | 3 |
| **`gated_rewrite`** | 0.50 · 0.46 · 0.65 · 0.66 · 0.66 | **0.664** | **1** |
| `oracle_rulebook` | 1.00 at every round | 1.000 | 0 |

Regressions are summed over seeds and rounds. No arm beats the oracle.
The gate adopted **6 of 20** proposals.

- **M2a: NOT SUPPORTED.** The gated rulebook closes **26%** of the headroom
  over the best baseline (0.664 against 0.545, ceiling 1.000), against a
  registered 40%. Predicted: the pilot showed 12%.
- **M2b: SUPPORTED.** It had 1 test regression, against 3 for ungated
  rewriting and 8 for Reflexion-style lessons.

## What was learned

- **Self-revision without a gate makes the agent worse.** Ungated rewrites
  end *below* having no rulebook at all (0.445 against 0.500). Every
  revision is adopted, including the ones that hurt.
- **Free-text lessons drift.** Reflexion-style advice wanders up and down,
  with the most regressions (8), and ends barely above no rulebook.
- **A gate on held-out, verified outcomes is what makes the improvement
  real.** It is the only arm that improves and keeps most of its gain
  (+0.16 over no rulebook). But it is slow: a gate scored on 8 tasks blocks
  ties and noise as well as harm, so it falls well short of the gold rules.
- **Do the gains compound?** Not shown. The gated trajectory rises over
  rounds 1–2 and then plateaus at 0.66 for rounds 3–4.

## What this does not establish

- One small model, four rounds, and a world whose relevance structure fits
  the metadata fields.
- The gate's error rate depends on its batch size, which was not varied.
