# Pre-registration — X6: is a memory written by one model usable by another?

**Registered 2026-10-15, before the harness exists.**

## 1. The question, and the version of it that would mislead

Multi-model systems are the norm: a planner on one model, workers on another,
a reviewer on a third, often sharing memory. Whether that sharing works is
unmeasured here and, as far as the prior-art review found, everywhere else.

The obvious test — *does model B do well with model A's memories?* — mostly
measures something else: **whether A writes good lessons**. A clear writer
helps every reader. That is worth knowing, but it is not portability, and
reporting it as portability would credit a good writer's prose to a property of
memory.

The question that decides a product design is narrower: **is the diagonal
special?** Does a model read its *own* memories better than equally-good
memories written by a different model? If it does, a multi-model store has to
record which model wrote each memory and translate on read. If it does not, one
store serves every model and the writer is irrelevant to the reader.

## 2. Design

Three model families at matched size, so that family varies and capacity
roughly does not: **`qwen2.5:3b`**, **`llama3.2:3b`**, **`gemma3:4b`**.

For each seed: the same DepotWorld learning episodes are written up by **each**
model as a writer, giving three corpora of the same underlying facts in three
models' words. Then each model, as a reader, answers the same evaluation
episodes **once with each corpus**. That is a 3 × 3 matrix of task success,
paired by (seed, episode), with retrieval identical in method across cells.

Plus, per reader, an **oracle corpus**: the correct lesson for each fault and
site in a fixed neutral template, read with the same retrieval. It bounds what
any writer could give that reader (8a), and no cell may exceed its reader's
oracle (8b).

## 3. The estimand: the diagonal interaction

Decompose each cell additively:

```
success(reader r, writer w) = mu + reader_r + writer_w + interaction_rw
```

`reader_r` is how well a model uses memory at all; `writer_w` is how good a
model's lessons are for everyone; `interaction_rw` is what is left. **The
diagonal interaction** is the mean of `interaction_rr` over the three
diagonal cells, which is

```
D = mean over r of [ cell(r, r) - row_mean(r) - col_mean(r) + grand_mean ]
```

That is exactly the part of reading your own memory that is not explained by
being a good reader or a good writer. Writer quality lands in `writer_w`, where
it belongs and is reported separately, and cannot masquerade as portability.

## 4. Verdicts, including the one that needs power

Three outcomes, because the product-relevant claim — *memory is portable* — is
a claim of **absence**, and an absence claim needs an equivalence test rather
than a failure to find an effect. [The audit](../results/audit-supported.md)
showed why: a zero from copy recognition at n=30 was consistent with a true
rate up to 9.5%, and nothing had said so.

| verdict | condition |
|---|---|
| **NOT PORTABLE** | the 95% CI on D excludes zero **and** D ≥ 0.05 |
| **PORTABLE** | the 95% CI on D lies entirely within **[−0.05, +0.05]** |
| **INCONCLUSIVE** | neither |

The equivalence margin is ±0.05, the same action threshold X5 used, chosen
because a smaller effect would not change how a multi-model store is built. The
CI comes from a bootstrap over (seed, episode) units, recomputing the whole
matrix and D on each draw, so the dependence between cells sharing an episode
is respected.

**Power.** 5 seeds × 24 episodes = 120 episode units, each contributing all
nine cells. The realised CI half-width on D is reported, so a reader can see
whether the run was able to deliver the PORTABLE verdict at all; if the
half-width exceeds 0.05, PORTABLE is unreachable and the registration says so
rather than letting INCONCLUSIVE be read as a soft yes.

### Amendment, before any model call: D is two thirds of the effect

A known-answer test of the estimand, run before the harness made a single
model call, returned **D = 0.067 for a true own-memory bonus of 0.10**. That is
correct arithmetic, not a bug: a bonus `b` on every diagonal cell also raises
that row's mean, that column's mean and the grand mean, so

```
D = b * (n - 1) / n          (n models)
```

and for three models **D is two thirds of the bonus**. The thresholds in §4 are
written on D, so they mean larger effects than they appear to:

| registered on D | own-memory bonus it implies |
|---|---|
| NOT PORTABLE at D >= 0.05 | b >= **0.075** |
| PORTABLE within D in [-0.05, +0.05] | b within **[-0.075, +0.075]** |

The thresholds are **not changed** — changing them now, even before data,
would be choosing a bar with knowledge of how the estimand behaves, and the
honest repair is to state what the existing bar means. The harness reports the
implied bonus beside D so the result can be read in the units of the cells.

The same test confirmed the property the design depends on: a matrix with
writer and reader effects and **no** own-memory bonus gives D = 0 exactly,
including one where a single writer's lessons help every reader. That is the
confound the naive off-diagonal measure would have reported as portability.

### Amendment, after the pilot and before the registered run: the oracle may not bound presentation

The pilot (1 seed × 8 episodes) failed the 8b check: **three cells scored above
their reader's oracle**, each by exactly one episode. At n=8 a one-episode
excess is within noise, so nothing is concluded from it. But principle 8b says
an arm above the ceiling is evidence the ceiling is wrong, and the cause is
plausible enough to commit to now, before the data that could test it.

The oracle corpus has **perfect facts** — every lesson correct, against the
writers' measured 88–89% — **in one terse template**: *"Fault E03 at the
coastal site: swap pilot cable."* A model's own lesson may carry phrasing that
is easier to retrieve or to read. If so, the oracle bounds **factual
correctness**, not everything a writer contributes, and §2's claim that it
*"bounds what any writer could give that reader"* overstates it.

Committed in advance:

- If cells still exceed their reader's oracle on the registered run, §2's claim is **withdrawn** and the oracle is reported as a bound on correctness only. It is not redesigned after the fact to restore the bound.
- **The primary verdict is unaffected either way.** D is computed over the model-written corpora only and excludes the oracle column, which a known-answer test pins (`test_the_oracle_column_is_excluded`). An oracle defect can change the headroom display and the 8b check; it cannot change NOT PORTABLE / PORTABLE / INCONCLUSIVE.

## 5. Secondary, reported always

- **The full 3 × 3 matrix** and the oracle row.
- **Reader and writer main effects** — who uses memory well, who writes it well. Probably the most practically useful numbers here, since they say which model to give the writing job.
- **Lesson correctness per writer**: the share of each writer's lessons that assert the correct action for their own site. A writer that garbles facts shows up here and in its writer effect, which separates *wrote it wrong* from *wrote it right in an unreadable way*.
- **Retrieval overlap**: whether the same query retrieves the corresponding lesson from each corpus. Different wording can change what is retrieved, which is part of portability rather than a confound, but it should be visible.
- **Cost** per writer and per reader.

## 6. Predictions

1. **PORTABLE, or INCONCLUSIVE leaning that way.** DepotWorld lessons are short factual statements — fault, site, action — and a 3B model of any family should read *"swap the pilot cable"* the same whoever wrote it.
2. **The writer effect will be larger than the diagonal interaction.** Writing a correct, specific lesson is harder than reading one, and the extraction sweep already showed families differing sharply on structured output.
3. **`llama3.2:3b` will be the weakest writer.** In the extraction sweep it marked 14 of 17 ordinary statements as modifiers under constraint; a model that over-reads structure into text may over-write it too. Stated so the prediction can be wrong in a specific way.
4. **Retrieval will differ more than reading.** If portability fails, I expect it to fail because one model's wording retrieves worse under lexical search, not because another model cannot understand it.

## 7. What a pass would not establish

Nothing about large or frontier models; three small local models only. Nothing
about long, nuanced or procedural memories, where a model's idiosyncratic
phrasing has room to matter. Nothing about embedding-based retrieval, which
could be more sensitive to a writer's style than lexical overlap. And nothing
about a model reading memories written by a *larger* one, which is the
asymmetric case most real systems have and the obvious next experiment.
