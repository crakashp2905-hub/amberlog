# Pre-registration — M1: state what is relevant before the session starts

**Registered 2026-10-18, after a dev pilot (seeds 100–101, qwen2.5:3b) and
before the test seeds (0–9).** This is task M1 in
[WORKPLAN.md](../../docs/WORKPLAN.md), the user's proposal:

> before we start a session, let's ask something called a memory objective on
> what to be kept as relevant and what to be kept as irrelevant … provided to
> the agents or to the LLMs or to whichever it is needed.

Mechanism: `memory-fabric/objective.py`. Harness: `experiments/m1_objective.py`.

**Disclosed: the pilot changed the mechanism and the primary arm.**

- **Compiled filters were catastrophic on dev.** The model's rules excluded
  the session's own plant and every source, so `filter_only` and `both`
  scored 0.00. Three changes were made:
  - rule values are coerced to the field's type (`"2026"` → 2026);
  - an objective that admits nothing is never applied (`objective.sanity`);
  - the compiler is told, in general terms, to put everything relevant in
    one include alternative and to exclude only what is named irrelevant.
- **Recompiled on the same dev seeds,** qwen's rules have admission
  precision 1.000 and recall 0.727. They drop the plant-wide rules, which is
  the trap the world sets.
- **`prompt_only` scored 0.83 on dev against plain's 0.52,** 65% of the
  headroom. It is now the primary mechanism, and the filter routes are
  secondary. That choice was made on dev; the test seeds have not been run.

## 1. Question

If the session's objective is stated first, saying what is relevant and what
is not, does an agent use the right memory when similarity cannot tell the
candidates apart? And is the objective better given to the agent as rules,
to retrieval as a filter, or to both?

## 2. Design (ObjectiveWorld)

Per seed:

- **Session.** One plant, and the objective in words: approved procedures
  for this plant from the 2026 revision, plus plant-wide safety rules; not
  drafts, other plants, the 2025 revision, or vendor material.
- **16 procedures.** Each has one relevant memory and four near-identical
  distractors (another plant, a draft, the 2025 version, a vendor claim),
  each with a different value.
- **6 plant-wide rules.** Each has one relevant memory (`plant: all`) and
  three distractors.
- **Questions.** Each names the plant, so plain retrieval knows where it is.
  Every arm renders every note with its metadata. Each task is asked in two
  phrasings, giving 44 units per seed and 440 on test.
- **Models.** `qwen2.5:3b` (primary) and `gemma3:4b` (secondary), local,
  temperature 0, k = 5, the same lexical retrieval for every arm.

## 3. Arms

| arm | objective given to |
|---|---|
| `plain` | nobody: the baseline |
| **`prompt_only`** | the agent: the statement and its rules in the system prompt |
| `filter_only` | retrieval: the model-compiled rules (`retrieve(objective=)`) |
| `both` | both |
| `filter_gold` | retrieval, with hand-written rules (exploratory: the filter route without compile loss) |
| `oracle` | only the relevant memory is retrievable; plain prompt |

**Ceiling and baseline on dev (8a, 8c, 8d), measured on accuracy, k = 5:**
`plain` 0.523, `oracle` 1.000. The baseline does not max the metric; the
headroom is 0.477. The test run re-measures both.

## 4. Metrics

- **Primary: accuracy.** The answer equals the relevant memory's value.
- **Used irrelevant:** the answer equals a distractor's value.
- Accuracy by kind (procedure, plant-wide).
- Compile quality per seed: admission precision and recall of the model's
  rules against the truth labels, and whether the sanity guard refused them.

## 5. Hypotheses

- **M1a.** `prompt_only` closes **at least 40%** of the headroom between
  `plain` and the oracle. `memeval.Registration`, 10 seeds, realised MDE
  reported.
- **M1b (secondary, reported either way).** `both` minus `prompt_only` and
  `filter_only` minus `plain`, as paired differences.

## 6. Predictions

1. M1a holds on qwen; dev showed 65%.
2. The filter routes lose the plant-wide tasks. The compiled rules drop
   `plant: all`, a filtered-out memory cannot be recovered by the prompt, and
   so `both` < `prompt_only` overall. `both` ≥ `prompt_only` on procedure
   tasks.
3. `filter_gold` is near the oracle. The filter route is sound and the
   compile step is the loss.
4. On gemma, compile failures trip the sanity guard on some seeds. There
   `filter_only` falls back to plain.

## 7. What this would not establish

A world I generated, with metadata present on every memory. Real memories
often carry no field saying "draft". Small local models only. The objective
is written by the experimenter, in the vocabulary of the metadata. A user's
objective will be vaguer, and how much vaguer matters is untested.
