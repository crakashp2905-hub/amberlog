# Pre-registration — X1: extraction at ingest

**Registered 2026-10-13, before `amberlog/extraction.py` exists.**

> **Amended 2026-10-13, before any model call of the primary arm — see
> [§8](#8-amendment-the-primary-was-invalid-as-registered).** §4's 8c check is
> wrong. `implied_by_default` is **abandoned** under this registration's own
> abandonment clause, and the primary is `multi_hop_4` alone. The amendment was
> written before the extraction arm ran, from baseline numbers only.

## 1. Why this, and why it was avoided until now

Three measured failures share one boundary, and the write-ups say so
independently:

| failure | measured | what it needs |
|---|---|---|
| `implied_by_default` | **0.000 for every arm**, trained embedder included | knowing a default applies unless an exception says otherwise |
| `multi_hop_4` | 0.000 sufficiency for every arm; **1.000 given declared relations** | knowing one memory *modifies* another |
| abstention | 0–7% externally, four signal families eliminated | knowing whether a memory *asserts* anything about the asked subject |

Similarity cannot express entailment, modification, or assertion. A reranker
without a model has no information the retriever lacks
([R2a](../results/r2a-feature-reranker.md)); relations have the information and
nothing to extract them ([ceiling 1.000](../results/relations-ceiling.md));
abstention has no retrieval-stage signal at all
([four families eliminated](../results/abstention-signals.md)).

[Hindsight](../HINDSIGHT.md)'s `retain` — an LLM extracting entities, relations
and facts at each write — is the one component that addresses all three, and it
is the component this project has most carefully avoided building.

**The reason for avoiding it does not apply here, and noticing that is what
unblocked this.** I declined to build a *pattern* extractor because the target
text is this project's own generated phrasing, so a regex for *"except at the …
and … sites"* would pass by construction and measure its own fit. **A
general-purpose model is not fitted to my phrasing.** The circularity was a
property of the pattern, not of extraction.

## 2. R6 is the standing objection, and it is about a different stage

[R6](../results/r6-downstream.md) put a model in the loop and its dev finding
**did not replicate**. That is the reason to be careful, and it is not a reason
to refuse, because **R6 measured the reading stage and this is the writing
stage**. The difference is not cosmetic:

- A reading-stage model decides **what to answer** from a context. Its output is the result, so a bad call is a wrong answer and variance goes straight into the metric.
- A writing-stage model decides **what structure a memory has**. Its output is an *index*, checked against the retrieval metrics it is supposed to improve, and a bad call costs a missed edge rather than a wrong answer.

So the failure modes differ, and that asymmetry is the registered reason for
expecting a different outcome. If extraction fails the same way R6 did, the
asymmetry is wrong and that is the finding.

## 3. The mechanism

**One model call per write**, producing a structured record — not one call per
*pair*, which would be O(n²) and immediately infeasible. Relations are then
inferred by matching structured records, which is how `retain` makes this
tractable.

Per memory, extract:

- `subject`, `predicate`, `value` — what the memory asserts, if anything;
- `scope` — the entities it applies to;
- `excepts` — entities explicitly outside its scope;
- `modifies` — what it adjusts rather than states, with the adjustment.

Then, structurally and with no further model calls:

- a record with `modifies` matching another's `predicate` yields a **`QUALIFIES`** edge, which `follow_relations` already consumes;
- a record with `excepts` becomes a **scoped default**: applicable to a query whose entities are not excepted, which is the `implied_by_default` case and needs the entity-scoped applicability that `EXCEPTS` could not provide;
- a record with no `subject`/`predicate` **asserts nothing**, which is a candidate abstention signal that is not a surface feature.

**Every call goes through `OllamaClient`**, which logs model, prompt hash,
token counts and tokens-as-cost — AGENTS.md's rule, and the prompt is hashed
rather than stored because it contains memory content.

**A deterministic stub extractor ships alongside**, so CI never calls a model
and the structural inference is testable without one. The stub is **not** an
arm: a stub fitted to my fixtures is the pattern problem again, and it exists
only so the non-model half has tests.

## 4. Primary metric and threshold

**Primary: sufficiency on `implied_by_default` and `multi_hop_4`**, pooled —
the two families where every arm measured scores 0.000.

```
B = max(sufficient) over {lexical, store_lexical, chain, real_vector}   = 0.000
C = oracle                                                              = 1.000
support iff sufficient >= B + 0.40 * (C - B) = 0.400
```

**8c check — is the primary trivially maximised by a baseline?** No: every
baseline is 0.000 on both families, which is why they were chosen. Reported
before the comparison.

**Abandonment clause.** If `C − B <= 0.05`, abandoned rather than
reinterpreted.

**Ceiling check** every run: an arm above the oracle means the ceiling is wrong.

**And a second bar that is not a metric.** `multi_hop_4` reaches 1.000 with
*declared* relations ([relations-ceiling.md](../results/relations-ceiling.md)).
Extraction is only interesting if it recovers a meaningful share of that, so
the result must report **extraction against declaration**, not only against the
baselines. Beating 0.000 while recovering 10% of a known ceiling is a weak
result dressed as a strong one.

## 5. Secondary metrics, reported always, decisive for none

- **Cost, as a first-class metric**: model calls, tokens, wall time per write. A mechanism costing a model call per write is a different product, and the number decides whether it is one worth having.
- **Extraction precision and recall against the declared relations** on `multi_hop_4`, where the ground truth exists. This separates "the model extracted nothing" from "the model extracted the wrong thing".
- **No-regression** on `relevance_v2` (both splits), `facet_v1`, SciFact and LongMemEval's `oracle` split. Extraction adds edges; edges change rankings.
- **The abstention candidate**: share of unanswerable instances where no retrieved memory asserts anything about the asked subject, reported on LongMemEval's 30 and on `relevance_v2`'s 9.
- `must_not_expose_rate` — any non-zero value fails the run.

## 6. Predictions

1. **`multi_hop_4` will recover most of the declared ceiling.** *"At the depot-12 site, add 0.35 bar to the axle-set figure"* is about as clear a modification as text gets, and a model that cannot see it cannot see any.
2. **`implied_by_default` will do worse than `multi_hop_4`**, because it needs both the extraction *and* a new applicability rule, and two new things fail more often than one.
3. **The abstention signal will not work.** Four families are already eliminated and I expect a fifth; the LongMemEval abstention cases are *partially* answerable — "you mentioned the fence but not the cows" — so memories asserting things about the subject **do** exist, and "nothing asserts anything" is the wrong question. Recorded now because it is the prediction I would most like to be wrong about.
4. **Cost will be the finding that matters.** At a second a write, a store ingesting ten thousand memories pays three hours. I expect the measurement to make extraction a batch job rather than an ingest-path step, and that is a product conclusion rather than a disappointment.

## 7. What a pass would not establish

Nothing about a model other than the one measured, and nothing downstream —
whether an agent given a structurally-indexed context answers better is R6's
question with R6's warning attached. Nothing about non-English or adversarial
text. And nothing about an extractor's behaviour on content it finds
ambiguous: these fixtures state things plainly, and a real corpus does not.

## 8. Amendment: the primary was invalid as registered

**Written 2026-10-13, after running the baselines and before any model call of
the primary arm.** Order matters here and is the only reason this is an
amendment rather than a retraction.

### The error

§4 sets the primary as **sufficiency at k=5**, pooled over
`implied_by_default` and `multi_hop_4`, with `B = max(sufficient) over the
baselines = 0.000`, and answers 8c's check: *"No: every baseline is 0.000 on
both families, which is why they were chosen."*

`B` was taken from §1's table, which cites
[`facet-v1-implied.md`](../results/facet-v1-implied.md). **That document reports
nDCG and critical recall at k=3.** The primary is sufficiency at k=5. Both
numbers are "0.000 for every arm", so the substitution went unnoticed.

Re-measured on the registered metric, with the registered `lexical` retrieval:

| family | split | B (baseline sufficiency @ k=5) | C (oracle) | C − B |
|---|---|---|---|---|
| `implied_by_default` | dev | **1.000** | 1.000 | **0.000** |
| `implied_by_default` | test | 0.000 | 1.000 | 1.000 |
| `multi_hop_4` | dev | 0.000 | 1.000 | 1.000 |
| `multi_hop_4` | test | 0.000 | 1.000 | 1.000 |

On dev the default rule ranks **4th of 205**, so it is inside a k=5 budget. It
is outranked by three distractors — the narrower true finding — and it is not
unrankable.

### What follows, by this registration's own rules

- **`implied_by_default` is abandoned**, not reinterpreted: `C − B = 0.000 <= 0.05` on dev, which is the abandonment clause in §4. It is abandoned on both splits rather than kept on test alone, because a family whose premise holds on one split and fails on the other cannot carry a confirmatory test.
- **The primary becomes sufficiency on `multi_hop_4`**, where `B = 0.000` and `C = 1.000` on both splits. §4's formula is unchanged and gives the same bar: `0.000 + 0.40 * 1.000 = ` **0.400**. The threshold is not re-derived after seeing data; the pre-registered formula is applied to a re-measured B.
- **§4's second bar stands unchanged** and now carries more weight, since it is the only remaining family: extraction must be reported against `declared`, not only against the baselines.
- **Prediction 2 is void.** It predicted `implied_by_default` would do worse than `multi_hop_4`; the family is gone. It is not scored either way.
- **§5's no-regression set and cost metrics are unchanged.**

### And a second amendment, about feasibility

§5 makes cost a secondary metric. It is now a constraint on the primary. The
five cases of the two families hold **1,374 unique statements on dev**, and the
only model measured to extract these statements correctly costs **54.5 s each**
on this hardware, which runs it on CPU — **20.8 hours for one arm of one
split**, and neither batching nor concurrency changes a compute-bound number.

The primary is therefore measured on a **reduced store**: fillers sampled to 60
memories a case with a seeded RNG, every labelled memory kept, and **every arm
— baseline, declared and oracle — recomputed on that same store**, so B and C
are measured where the mechanism is measured. 172 unique statements, 2.6 hours.

The store size was chosen **before the extraction arm ran**, by sweeping
60/100/150/200/300/full with the no-model arms and requiring that
`multi_hop_4` retain its registered premise (`B = 0.000`, `C = 1.000`). It
does, at every size tried. The sweep is reported in the result, and it is also
what exposed the 8c error above.

A 60-memory store is an easier store, and the honest direction of that bias is
toward the **baseline**, which may rank a memory it misses at full size. No
full-size number is claimed from it.
