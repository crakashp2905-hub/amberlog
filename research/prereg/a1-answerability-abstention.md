# Pre-registration — A1: answerability verdicts and abstention policies with a real model

**Registered 2026-10-24**, before `experiments/a1_abstention.py` existed and
before any model call. `memory-fabric/answerability.py` exists and has unit
tests. It was not tuned on the world below, which does not exist yet.

## 1. Question

Every earlier attempt to abstain from a **retrieval** signal failed. A
threshold on match quality reached F1 0.206; a small model's typed confidence
was badly calibrated (X2). A1 tests the separation instead. Retrieval returns
neighbours; a verdict on the evidence (`answerability.assess`) decides whether
they answer the question; the model answers only when they do. Does that
improve outcomes over telling the model to abstain, on questions built to have
convincing near-miss evidence?

## 2. World (held out; `experiments/a1_abstention.py`)

Seeds 1–5, 30 questions a seed, all against one governed store a seed. The
store holds 14 units, each with 2 recorded parameters, in code formats `H-14`,
`K/31` and `PMP_0012`, with some memories withdrawn.

| family | n | evidence | correct outcome |
|---|---|---|---|
| `answerable` | 15 | the asked unit and parameter, stated in the question's words | the value |
| `paraphrased` | 3 | the asked unit and parameter, with the parameter named by a synonym that shares no word ("coolant flow" against "cooling water rate") | the value |
| `missing_unit` | 3 | siblings of the same kind exist; this unit was never recorded | abstain |
| `missing_parameter` | 3 | the unit exists with other parameters | abstain |
| `transposed_id` | 3 | the parameter is recorded for the transposed identifier (`K-13` for `K-31`) | abstain |
| `withdrawn_only` | 3 | the only statement was withdrawn | abstain |

`paraphrased` is the registered **false-abstention risk** of the structural
check. It shares no parameter word by construction, so the structural arm is
expected to abstain wrongly there.

## 3. Arms

Every arm gets the same governed retrieval (`k = 5`), the same rendering and
the same model (`sonnet`, through Claude Code headless).

| arm | policy |
|---|---|
| `answer_always` | "reply with the value"; no abstention instruction |
| `instructed` | the D1 instruction: reply with the value, or UNKNOWN if the evidence does not establish it |
| `structural_gate` | `answerability.assess`. `insufficient` returns UNKNOWN with no model call; otherwise as `instructed` |
| `judge_gate` | a model judge (one extra call: does the evidence state the asked value? YES/NO) decides; then as `instructed` |
| `structural_then_judge` | structural verdict. When it is `insufficient`, the judge decides instead of abstaining at once |
| `oracle` | knows the family. It abstains exactly on the unanswerable ones, and otherwise is as `instructed` |
| `abstain_all` | always UNKNOWN (degenerate, reported) |

## 4. Metrics

- **correct** (primary): the value on answerable families, UNKNOWN on
  unanswerable ones.
- **abstention recall:** UNKNOWN on unanswerable.
- **false abstention:** UNKNOWN on answerable.
- **wrong answer:** a value given on an unanswerable question, or a wrong value
  on an answerable one.

## 5. Thresholds

```
B = max(correct) over {answer_always, instructed}
C = correct(oracle)
```

- **A1a (primary arm `structural_gate`):** `correct >= B + 0.40 (C - B)` **and**
  `false_abstention <= false_abstention(instructed) + 0.10`. The +0.10 allows
  the three registered `paraphrased` cases out of 18 answerable (0.167). The
  check fails if the arm abstains wrongly beyond those.
- **A1b (secondary, `structural_then_judge`):** same bar.
- `judge_gate` is reported and decides nothing.
- **Abandonment:** `C - B <= 0.05`, which would mean the instruction alone
  already abstains as well as the oracle.
- **8c / 8d:** `abstain_all` scores 12/30 = 0.400 by construction. Before any
  model call, the harness prints the structural verdict for every family, and
  `B` is measured in this run on this metric, never quoted.
- **8b:** any arm above `oracle` is reported as a defect in the oracle.

## 6. Predictions

1. `instructed` will abstain on most `withdrawn_only` cases (D1 saw 100%) and
   miss many `transposed_id` and `missing_parameter` cases, because the
   evidence looks close.
2. `structural_gate` will abstain correctly on all four unanswerable families
   and abstain wrongly on most `paraphrased` cases.
3. `structural_then_judge` recovers `paraphrased` at some cost in abstention
   recall.

## 7. What a pass would not establish

- The world and templates are mine. Code-style identifiers are where the
  structural check is strongest, and questions with no identifier are
  `undetermined`, so this world does not exercise them.
- It is one model.
- Unanswerable questions are 40% of the world by design; in real traffic the
  share is unknown.

## Amendment 1 — 2026-10-24, after the sonnet run, before any haiku number

The `sonnet` run was abandoned for lack of headroom: `instructed` was
perfect. **A1-h** repeats §2–§5 unchanged with `haiku` on fresh seeds 6–10,
to test whether a weaker, cheaper model leaves headroom that the verdict can
close. It is the same world, arms, metrics and thresholds, with results in
`a1h-abstention.md`.
