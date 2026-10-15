# X5 — the governed rendering costs 7 points, and the security control is not why

**SUPPORTED.** Rendering the same retrieved memories with the shipped
`build_context` costs **7.0 points of task success** against plain text —
95% CI **+4.7 to +9.4**, over 640 paired episodes, above the registered action
threshold of 0.05.

**And the trade I registered in advance does not exist.** The registration's
§2 warned that if the prompt-injection preamble were the costly component, the
finding would be a trade against a documented security control. It is not:
the preamble and delimiters on their own cost **0.6 points, indistinguishable
from zero**. The cost is in the per-memory evidence labels, and most of all in
the instruction to weigh them.

- **Registration:** [x5-context-rendering.md](../prereg/x5-context-rendering.md) — the first experiment here with a pre-registered minimum detectable effect
- **Harness:** `experiments/x5_context_rendering.py`
- **Run:** 2026-10-15, `qwen2.5:3b`, 5 seeds × 128 episodes, **2,722 calls, 851,831 tokens, 9,104 s (2.53 h)**
- **Raw:** [x5-run.json](x5-run.json) · all checks passed

---

## 1. The table

One retrieval per episode, the same exposed memories rendered four ways, so
rendering is the only variable. Correct lesson in context: **0.658**,
identical across arms by construction.

| rendering | preamble | delimiters | labels | success | prompt words |
|---|---|---|---|---|---|
| `plain` | — | — | — | **0.598** | 48.5 |
| `delimited` | ✓ | ✓ | — | **0.592** | 80.5 |
| `annotated` | — | ✓ | ✓ | **0.564** | 57.5 |
| `full` (shipped) | ✓ | ✓ | ✓ | **0.528** | 122.5 |

| comparison | mean | 95% CI | excludes 0 | discordance |
|---|---|---|---|---|
| **total** (`plain − full`) | **+0.070** | [+0.047, +0.094] | yes | 0.111 |
| labels, given the preamble (`delimited − full`) | +0.064 | [+0.041, +0.088] | yes | 0.095 |
| preamble, given labels (`annotated − full`) | +0.036 | [+0.017, +0.056] | yes | 0.073 |
| **preamble alone** (`plain − delimited`) | **+0.006** | **[−0.009, +0.022]** | **no** | 0.044 |

## 2. The cost is not additive, and the shape says what it is

| | cost against `plain` |
|---|---|
| the security preamble + delimiters alone | **0.6** |
| the labels alone, with no instruction to weigh them | **3.4** |
| both, **with** the instruction to prefer well-evidenced memories | **7.0** |

The parts sum to 4.0 and the whole is 7.0. About **3 points are interaction**,
and the arms locate it. `delimited` carries the security text *without* the
evidence sentence — removed because it pointed at labels that arm does not have, a confound the harness documents —
and costs nothing. `annotated` carries the labels *without* any instruction
about them, and costs 3.4. `full` carries the labels **and** the sentence
*"Each memory carries how well it is evidenced — prefer well-evidenced ones,
treat contested ones as open questions"*.

In a cold store nearly every label reads **"unevaluated"**. So the shipped
rendering shows a model a block of memories, labels every one of them as
unproven, and tells it to prefer proven ones. The model does what it is told
and discounts what it was shown. The security control is innocent; the
**honest annotation of uncertainty is what costs accuracy**, because the model
is asked to act on an absence of evidence as though it were evidence of
absence.

That is a mechanistic reading of three arms, not a fourth measured one: X5 did
not include an arm with labels plus the instruction but no security text. It
is consistent with every comparison in §1, and it predicts the next
experiment rather than concluding it.

## 3. The predictions, scored

1. **"`plain` beats `full`, by less than 0.05 — NOT SUPPORTED."** **Refuted, in the direction I hedged against.** The effect was 0.070 and the verdict SUPPORTED. I registered the cautious outcome so that no result could look anticipated, and the data did not oblige.
2. **"The annotations cost more than the preamble."** **Confirmed**: 0.064 against 0.036, and the preamble alone 0.006.
3. **"The mechanism is hedging, not accuracy."** **Refuted.** The hedge detector fired on **zero of 2,560** generations — it was checked to work on hedged text before the run — so `qwen2.5:3b` never declined to commit under any rendering. The labels did not make the model more careful; they made it **wrong more often while equally sure**.
4. **"Token cost is the finding that survives."** It survives — the shipped rendering is **2.5×** plain — but it is not the headline, because accuracy moved too.

## 4. Power, which is why this run exists at this size

Registered MDE 0.05; **realised 0.037**, because discordance came in at 0.11
against the assumed 0.15–0.20. So the power held with margin.

For comparison, [X4](x4-governed-vs-pooled.md) had an MDE of 0.10–0.14 against
an observed 0.04. **X4 could not have detected the effect it reported**, and X5
was sized to fix exactly that. This result is also what X4's §4 dissociation
was: the governed arm got the right lesson into context more often and
converted it less often, and the conversion loss was the rendering.

## 5. What changed in the product because of it

**MCP recall now renders `compact` by default**: the security preamble and
delimiters kept, the per-memory labels and the instruction to weigh them
dropped. `MemoryContext.render_compact()` lives in `adapters/context.py`, and
`memory-fabric mcp --context full` restores the original.

One component of `compact` is **not** measured and is said so in its
docstring. Dropping every label would also drop *"contradicts …"*, which is
H4b's mechanism — P(correct) 0.905 → 1.000. So `compact` names a declared
disagreement in one line after the block, and only when one exists, rather than
labelling every memory to say it is not contested. That is a design choice
informed by X5, not a finding of it, and it is the obvious next measurement.

**The library's `render()` is unchanged.** It is what every result before this
one was measured with, and changing it would silently alter what those numbers
mean.

## 6. What this does not establish

- **One model, 3B.** A model that parses metadata more easily may pay nothing for the labels. This is a statement about small local models, and it should be re-measured before it is taken as a statement about rendering.
- **One world.** DepotWorld scores a single named action, so it cannot reward a model for *expressing* uncertainty. With hedging at zero this turned out not to matter here, but a world that scores calibrated uncertainty might reverse the cost of honest labels.
- **A cold store.** Nearly every label was "unevaluated". In a store where most memories carry measured value the labels say something, and §2's mechanism predicts they would then help rather than hurt. That is testable and untested.
- **Nothing about removing the preamble.** It costs nothing, so there is nothing to trade.
