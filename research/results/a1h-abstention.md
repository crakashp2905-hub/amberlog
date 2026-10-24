# A1-h — answerability and abstention policies, with haiku (A1 Amendment 1)

Registered in [a1-answerability-abstention.md](../prereg/a1-answerability-abstention.md)
before the harness existed. Produced by `python -m experiments.a1_abstention` at commit
`aafc559`; every reply in [a1h-abstention.json](a1h-abstention.json). Model `haiku`
(served: claude-haiku-5-5), seeds [6, 7, 8, 9, 10], 30 questions a seed, k = 5. Mean over
seeds, 95% bootstrap CI over seeds. Cost $0.14.

| arm | correct | abstention recall | false abstention | wrong answer |
|---|---|---|---|---|
| `answer_always` | 0.587 [0.553, 0.613] | 0.017 [0.000, 0.050] | 0.000 [0.000, 0.000] | 0.413 [0.387, 0.447] |
| `instructed` | 0.993 [0.980, 1.000] | 1.000 [1.000, 1.000] | 0.011 [0.000, 0.033] | 0.000 [0.000, 0.000] |
| `structural_gate` | 0.907 [0.900, 0.920] | 1.000 [1.000, 1.000] | 0.156 [0.133, 0.167] | 0.000 [0.000, 0.000] |
| `judge_gate` | 0.567 [0.493, 0.633] | 1.000 [1.000, 1.000] | 0.722 [0.611, 0.844] | 0.000 [0.000, 0.000] |
| `structural_then_judge` | 0.913 [0.900, 0.927] | 1.000 [1.000, 1.000] | 0.144 [0.122, 0.167] | 0.000 [0.000, 0.000] |
| `oracle` | 0.993 [0.980, 1.000] | 1.000 [1.000, 1.000] | 0.011 [0.000, 0.033] | 0.000 [0.000, 0.000] |
| `abstain_all` | 0.400 [0.400, 0.400] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 0.000 [0.000, 0.000] |

Correct by family (pooled):

| arm | answerable | paraphrased | missing_unit | missing_parameter | transposed_id | withdrawn_only |
|---|---|---|---|---|---|---|
| `answer_always` | 0.96 | 1.00 | 0.07 | 0.00 | 0.00 | 0.00 |
| `instructed` | 1.00 | 0.93 | 1.00 | 1.00 | 1.00 | 1.00 |
| `structural_gate` | 1.00 | 0.07 | 1.00 | 1.00 | 1.00 | 1.00 |
| `judge_gate` | 0.32 | 0.07 | 1.00 | 1.00 | 1.00 | 1.00 |
| `structural_then_judge` | 1.00 | 0.13 | 1.00 | 1.00 | 1.00 | 1.00 |
| `oracle` | 1.00 | 0.93 | 1.00 | 1.00 | 1.00 | 1.00 |
| `abstain_all` | 0.00 | 0.00 | 1.00 | 1.00 | 1.00 | 1.00 |

Structural verdict `insufficient` rate by family (before any model call): answerable: 0.0, paraphrased: 0.933, missing_unit: 1.0, missing_parameter: 1.0, transposed_id: 1.0, withdrawn_only: 0.933.

## Verdicts

- B = 0.993 (`instructed`), C = 0.993 (`oracle`), threshold 0.993,
  false-abstention bar 0.111.
- **A1a (`structural_gate`): ABANDONED (headroom <= 0.05)**
- **A1b (`structural_then_judge`): ABANDONED (headroom <= 0.05)**
- Arms above the oracle: none.

## Reading (written after the run)

**ABANDONED again, for the same reason: no headroom.** `instructed` scored
0.993, which the oracle matches. The weaker model also applies the
abstention instruction reliably on this world. So the registration's
question (does a separate verdict improve on instructing the model?) has the
same answer for both models: here, no.

**One new finding: a separate model judge is worse than letting the model
abstain inside its answer.** As a YES/NO judge, `haiku` refused 72% of
answerable questions (`judge_gate` false abstention 0.722), while the same
model, asked to answer or say UNKNOWN, refused 1%. `sonnet` as a judge
refused 7%. The judge prompt asks a different question ("does the evidence
state the value?"), and a smaller model reads it strictly. **An answerability
judge should be the strongest model available, or not used.** That is the
practical advice in `answerability.py`.

**The structural verdict, again:** zero wrong answers in every seed, no model
call, and a false-abstention cost confined to paraphrases (0.07 correct
there). It is the right tool where the model does not follow instructions (it
lifts `answer_always` from 0.587 to 0.907), and the wrong tool to put in
front of a model that does.
