# A1 — answerability verdicts and abstention policies

Registered in [a1-answerability-abstention.md](../prereg/a1-answerability-abstention.md)
before the harness existed. Produced by `python -m experiments.a1_abstention` at commit
`2c4e9a1`; every reply in [a1-abstention.json](a1-abstention.json). Model `sonnet`
(served: claude-sonnet-5-5), seeds [1, 2, 3, 4, 5], 30 questions a seed, k = 5. Mean over
seeds, 95% bootstrap CI over seeds. Cost $2.71.

| arm | correct | abstention recall | false abstention | wrong answer |
|---|---|---|---|---|
| `answer_always` | 0.600 [0.600, 0.600] | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 0.400 [0.400, 0.400] |
| `instructed` | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] |
| `structural_gate` | 0.927 [0.907, 0.947] | 1.000 [1.000, 1.000] | 0.122 [0.089, 0.156] | 0.000 [0.000, 0.000] |
| `judge_gate` | 0.960 [0.927, 0.987] | 1.000 [1.000, 1.000] | 0.067 [0.022, 0.122] | 0.000 [0.000, 0.000] |
| `structural_then_judge` | 0.993 [0.980, 1.000] | 1.000 [1.000, 1.000] | 0.011 [0.000, 0.033] | 0.000 [0.000, 0.000] |
| `oracle` | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] |
| `abstain_all` | 0.400 [0.400, 0.400] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 0.000 [0.000, 0.000] |

Correct by family (pooled):

| arm | answerable | paraphrased | missing_unit | missing_parameter | transposed_id | withdrawn_only |
|---|---|---|---|---|---|---|
| `answer_always` | 1.00 | 1.00 | 0.00 | 0.00 | 0.00 | 0.00 |
| `instructed` | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |
| `structural_gate` | 1.00 | 0.27 | 1.00 | 1.00 | 1.00 | 1.00 |
| `judge_gate` | 0.99 | 0.67 | 1.00 | 1.00 | 1.00 | 1.00 |
| `structural_then_judge` | 1.00 | 0.93 | 1.00 | 1.00 | 1.00 | 1.00 |
| `oracle` | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |
| `abstain_all` | 0.00 | 0.00 | 1.00 | 1.00 | 1.00 | 1.00 |

Structural verdict `insufficient` rate by family (before any model call): answerable: 0.0, paraphrased: 0.733, missing_unit: 1.0, missing_parameter: 1.0, transposed_id: 1.0, withdrawn_only: 1.0.

## Verdicts

- B = 1.000 (`instructed`), C = 1.000 (`oracle`), threshold 1.000,
  false-abstention bar 0.100.
- **A1a (`structural_gate`): ABANDONED (headroom <= 0.05)**
- **A1b (`structural_then_judge`): ABANDONED (headroom <= 0.05)**
- Arms above the oracle: none.

## Reading (written after the run)

**ABANDONED as registered, because there was no headroom: the instruction
alone was perfect.** `instructed` scored 1.000 on every unanswerable family,
including the near-misses built to fool it (transposed identifiers, the right
unit with another parameter, a missing unit with siblings present). The oracle
cannot do better, so `C - B = 0` and §5's clause applies. No gated arm is
reported as better or worse than the bar.

**What this changes in the project's account of abstention.** Every earlier
abstention failure in this repository (0.000 on relevance_v2, F1 0.206 from
retrieval signals, X2's miscalibrated small model) asked the *retrieval
stage* or a *small model* to decide. A1 is the first test with a capable
model reading the evidence under an explicit abstention instruction, and on
this world the failure disappears. Without the instruction the same model
answers every unanswerable question with a neighbour's value: `answer_always`
gets 0.000 on all four unanswerable families. So the abstention policy is what
matters, and here the model applies it reliably.

**What the structural verdict is still for.**
- **It never produced a wrong answer** (wrong-answer rate 0.000 in every
  seed), with no model call. Against `answer_always`, the policy a model or
  agent that ignores the instruction falls back to, it lifts correct from 0.600
  to 0.927.
- **It costs false abstention on paraphrases** (0.27 correct there, as
  predicted). `structural_then_judge` recovers most of it (0.93) at one extra
  call, but still sits below the instruction alone.
- **Therefore it ships as a reported verdict, not an enforced gate**:
  `RetrievalResult.answerability()` and the agent API's `answerability` field.
  An agent or host can log it, show it, or gate on it when the model in use is
  weak, cheap or untrusted. Nothing abstains by default.

**Not shown.** A weaker or local model, questions without identifiers
(`undetermined`), and real traffic. The world's identifiers are where the
structural check is strongest, and where a capable model is, too.
