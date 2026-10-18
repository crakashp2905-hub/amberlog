# M1 result — the memory objective

Registration: [prereg/m1-memory-objective.md](../prereg/m1-memory-objective.md)
(`adaf615`, after a disclosed dev pilot). Mechanism:
`memory_fabric/objective.py`. Harness: `experiments/m1_objective.py`.

| run | status |
|---|---|
| qwen2.5:3b, registered, seeds 0–9, at `adaf615` | **done**: [m1-qwen.json](m1-qwen.json) |
| gemma3:4b, registered, seeds 0–9, at `adaf615` | **running** |
| qwen2.5:3b, corrected compile cache, at `e13d63b` | **queued** behind M2 |

## qwen2.5:3b (registered run): M1a **SUPPORTED**

| arm | accuracy | used an irrelevant memory | procedure tasks | plant-wide tasks |
|---|---|---|---|---|
| `plain` | 0.484 | 0.493 | 0.525 | 0.375 |
| **`prompt_only`** | **0.784** | **0.216** | 0.794 | 0.758 |
| `filter_only` | 0.366 | 0.557 | 0.394 | 0.292 |
| `both` | 0.607 | 0.341 | 0.613 | 0.592 |
| `filter_gold` (hand-written rules) | 0.998 | 0.002 | 1.000 | 0.992 |
| `oracle` | 0.998 | 0.002 | 1.000 | 0.992 |

440 paired units, and no arm beats the oracle.

- **M1a: SUPPORTED.** Stating the objective to the agent closes **58%** of the
  headroom against a registered 40%: +0.300, 95% CI +0.245 to +0.350,
  realised MDE 0.084. Answers that used an irrelevant memory fall from 49% to
  22%. It works on the plant-wide tasks too (0.38 → 0.76), the trap that a
  "this plant only" reading falls into.
- **M1b, the filter routes, measured as registered: both hurt.**
  - `filter_only` is **−0.118 against plain**, CI −0.150 to −0.086.
  - `both` is **−0.177 against `prompt_only`**, CI −0.214 to −0.143.
  - The filter route itself is sound: `filter_gold`, the same mechanism with
    hand-written rules, reaches the oracle (0.998).
  - All of the loss is **compilation**.

### A harness defect, disclosed: stale compilations

The compiled rules were cached under (model, statement) only. For the two
plants the dev pilot had seen, the test run therefore reused the pilot's
compilations from **before** the compiler was fixed, the ones whose year
rules were dropped as "value '2026' not seen". The fixed compiler ran fresh
only for Brook. The test then compiled the objective badly on every seed:

| outcome | seeds |
|---|---|
| refused by the admits-nothing guard (`objective.sanity`), so the filter fell back to plain retrieval | 8 |
| admitted only distractors | 2 |

That accounts for `relevant_shown` falling to 0.80 in the filter arms.
Even the fresh Brook compilation was self-defeating: an exclusion
`revision in [2025, 2026]` rules out every memory.

The defect touches every objective arm, `prompt_only` included, because it
renders the compiled rules into the prompt beside the statement. So M1a's
pass was measured with the *stale* rules in the prompt. The verdict above is
the registered one. The corrected run, with the cache keyed on the
compiler's source (`e13d63b`), is a replication, labelled as such, and will
be reported here beside it.

## What this already says

**Telling the agent what the session is for works, and compiling it into
filters does not, yet.** A small model reads "approved procedures for this
plant from the 2026 revision, and plant-wide safety rules" and uses the right
note far more often. Asked to turn the same sentence into rules, it writes
exclusions that contradict its own inclusions. The guard keeps such a filter
from blanking retrieval, but the filter route needs rules written or reviewed
by a person. `MemoryObjective` can hold those rules, and `filter_gold`
measures what they are worth: everything.

## Predictions (qwen)

1. *M1a holds.* **Held**: 58%.
2. *The filter routes lose the plant-wide tasks, and `both` < `prompt_only`.*
   **Held, and worse than predicted.** They lose the procedure tasks too,
   because compilation failed on every seed rather than only dropping the
   plant-wide alternative.
3. *`filter_gold` is near the oracle.* **Held**: 0.998.
4. *On gemma, the guard trips on some seeds.* Gemma's run is still in
   progress. On qwen it tripped on 8 of 10.
