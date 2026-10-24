# Pre-registration — M2: reflective rulebooks, improvement that is measured rather than self-assessed

**Registered 2026-10-18, after two dev pilots (seed 300, qwen2.5:3b) and
before the test seeds (200–204).** This is task M2 in
[WORKPLAN.md](../../docs/WORKPLAN.md), requested by the user as
"memory based recursive self improvement through reflective rulebooks".
Mechanism: `memory_fabric/rulebook.py`. Harness: `experiments/m2_rulebook.py`,
on M1's ObjectiveWorld.

**Disclosed: the first pilot invalidated the ceiling.** Rules were applied as
prompt text only, and `ungated_rewrite` scored 0.95 against the hand-written
"oracle" rulebook's 0.86. By AGENTS.md 8b, an arm above the ceiling proves the
ceiling wrong. Every rule-based arm now applies its rules as a retrieval
filter (never one that admits nothing) as well as in the prompt, and so does
the oracle, whose gold rules then reach 1.0. Reflexion's free-text lessons
cannot filter, so that baseline stays text-only. The second pilot is the one
reported below.

## 1. Question

Can an agent improve its own rules from verified outcomes over rounds, so
that the gains hold rather than drift? Does adopting a revision only on
held-out evidence beat adopting every revision, and beat Reflexion-style
lessons?

## 2. Design

Each seed is one plant. The agent is **not told the objective**; that is what
the rulebook must learn.

- **Rounds.** Four. Each round has 8 training tasks from a fresh world at
  that plant, and then the correct values are revealed.
- **Reflection.** The agent reflects on its misses (the notes it saw, its
  answer and the correct one) and writes a revision.
- **Testing.** The test set is a separate fixed world of 22 tasks, asked
  after every round, starting from round 0.
- **The gate.** It scores incumbent and candidate on 8 held-out validation
  tasks from another fresh world, using environment outcomes.
- **Seeds.** 5 test seeds (200–204). `qwen2.5:3b`, temperature 0, k = 5.

## 3. Arms

| arm | per round |
|---|---|
| `no_rulebook` | nothing |
| `reflexion_append` | a free-text lesson from its misses, appended to the prompt, never checked |
| `ungated_rewrite` | rewrites its rules (validated JSON); always adopted |
| **`gated_rewrite`** | the same kind of rewrite, adopted only if held-out accuracy beats the incumbent (`Rulebook.adopt`, verified by the environment) |
| `oracle_rulebook` | the hand-written rules, from round 0 |

**Ceiling and baselines on the second pilot (8a–8d), final test accuracy:**

| arm | final test accuracy |
|---|---|
| `no_rulebook` | 0.636 (best baseline) |
| `reflexion_append` | 0.591 |
| `ungated_rewrite` | 0.591 |
| `oracle_rulebook` | 1.000 |

No baseline maxes the metric, and no arm beat the oracle. `gated_rewrite`
reached 0.682, adopting 1 of 4 revisions.

## 4. Metrics

- **Primary: final test accuracy** after round 4.
- Trajectory: test accuracy after every round.
- **Test regressions:** rounds whose test accuracy fell below the previous
  round's.
- Adoptions by the gate.

## 5. Hypotheses

- **M2a.** `gated_rewrite` closes **at least 40%** of the headroom between the
  best baseline and `oracle_rulebook` on final test accuracy.
  `memeval.Registration`, 5 seeds.
- **M2b.** `gated_rewrite` has **no more test regressions** than
  `ungated_rewrite`, and no more than `reflexion_append`, summed over seeds and
  rounds.

## 6. Predictions

1. **M2a fails.** The pilot closed 12%. A gate scored on 8 tasks blocks ties
   and noise as well as harm, so the gated rulebook improves slowly.
2. **M2b holds.** The gate's job is to stop the collapses the ungated arm
   showed, a round at 0.27.
3. `reflexion_append` is no better than `no_rulebook`. Free-text lessons
   drift, as in the pilot.
4. The ungated arm's best round can exceed the gated arm's, but its final
   round is less reliable.

## 7. What this would not establish

- **Gains do not compound.** Four rounds is too few to say whether they
  would.
- **One small model.**
- **A world whose relevance structure is expressible in the metadata
  fields.** A rulebook over free text is untested.
- **The validation batch is small**, so the gate's error rate is part of the
  result. A larger batch costs model calls in proportion.
