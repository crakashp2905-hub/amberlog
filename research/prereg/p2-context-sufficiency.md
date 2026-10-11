# Pre-registration — P2: does the assembled context contain enough to decide?

**Registered 2026-10-11, before any sufficiency-aware selector exists and
before the relevance_v2 test split has been opened.** The dev numbers in
[relevance-v2-ceiling.md](../results/relevance-v2-ceiling.md) §5 are the basis
for the thresholds below and are therefore *in scope for me to have seen*;
nothing in this document may be revised after a test-split number is read.

## 1. The question

Ranking asks whether an arm ordered the corpus well. This asks the question a
decision turns on: **does the returned set contain enough evidence to answer
defensibly?** The two come apart by construction on relevance_v2. A 4-hop chain
missing one hop scores 0.75 recall and is worth nothing, because the conclusion
cannot be reached. A `conflicting` case holding one of two contradictory
sources scores 0.5 recall and is *worse* than nothing, because it looks
complete.

## 2. Why now, and not before

Because v1 could not ask it. Its corpora were 18 memories, its `all_memory`
baseline cost 294 prompt tokens, and R6's frozen split measured perfect
selection at **+0.000** against simply handing the model everything. A budget
that does not bind cannot test budget-aware assembly. relevance_v2's
`budget_pressure` family costs ~25,000 tokens for the full corpus against ~400
for a selection, so the comparison is between selecting and *paying*.

## 3. Arms

| arm | what it is |
|---|---|
`top_k` | the product as it ships: `retrieval="lexical"`, mechanisms on, k=5. The baseline to beat.
`full_context` | the entire reachable corpus. The thing retrieval must justify itself against.
`budget_matched_top_k` | `top_k` with k raised until it spends the same tokens as the selector under test. Prevents a selector winning on budget rather than on selection.
`sufficiency_aware` | the method under test: assembles against the case's declared requirement *structure* (not its labels) and may abstain. Does not exist yet.
`oracle_evidence` | the labelled satisfiers, through the same gates, at the same k, with the same mechanisms. Principle 8b: no handicap.

`oracle_evidence` is capped at **0.800** on dev and that is correct, not a bug:
`gated` and `shared_root` are built so the only satisfier of their critical
requirement is a memory the gates refuse. Any arm above the oracle has exposed
something it may not, and is a failure however it scored.

## 4. Primary metric and threshold

Primary: **`sufficient`** — the share of cases where every critical requirement
is met by a memory the gates allowed.

The threshold is a share of the headroom measured *on the evaluation split at
run time*, never an absolute margin (principle 8a, from H3 registering +0.030
when at most +0.027 existed):

```
B = max(sufficient) over {top_k, full_context, budget_matched_top_k}
C = sufficient(oracle_evidence)
support sufficiency_aware iff  sufficient >= B + 0.40 * (C - B)
```

**Abandonment clause.** If `C - B <= 0.05` the comparison is **abandoned, not
reinterpreted** — there is no headroom to divide and a threshold on it would be
the H3 mistake. On dev, B = 0.533 and C = 0.800, so the headroom is +0.267 and
the dev threshold would be 0.640. The frozen split may differ and the rule, not
the number, is what is registered. R6's abandonment clause fired on its own and
the harness printed it unasked; this one must do the same.

**Ceiling check.** Every run reports whether any arm exceeded
`oracle_evidence`. An arm above the ceiling is a proof the ceiling is wrong
(principle 8b), not a result.

## 5. Secondary metrics, reported always, decisive for none

- `requirement_recall` — the share of all requirements met, critical or not.
- **`abstention_precision`** on the 9 cases a split where abstention is the only correct answer. Every arm measured so far scores **0.000**: top-k retrieval over ~495 memories always has a candidate and always returns one. A sufficiency-aware method that cannot abstain has not addressed the question.
- `false_abstention` — abstaining on an answerable case. The failure mode a method chasing abstention precision will reach for, so it is registered alongside it.
- `prompt_tokens` and `latency_ms`. A selector that wins on sufficiency and costs 500 ms a query has not won; P9 was declined on a figure later found to be the wrong embedder's.
- `must_not_expose_rate`. **Any non-zero value fails the run** regardless of every other number.

## 6. Predictions, recorded to be wrong in public

1. **`full_context` will beat `top_k` on sufficiency and lose on tokens.** It contains every satisfier by definition, so its only losses are the `gated` and `shared_root` cases where no reachable satisfier exists. If this is wrong, sufficiency is not measuring what I think it is.
2. **`budget_matched_top_k` will close most of the gap to `sufficiency_aware`.** On dev, sufficiency rises with k mechanically. If a sufficiency-aware method cannot beat top-k at equal budget, it is a more expensive way to spend the same tokens and should be reported as one.
3. **Abstention will be where the method earns its keep, not sufficiency.** The 0.000 abstention precision across every arm is the largest single gap in the current product, and I expect the registered primary metric to move less than the secondary one. Registered in advance precisely because it would otherwise be a post-hoc rescue.

## 7. What a pass would and would not establish

A pass establishes that assembling against requirement structure beats ordering
by relevance **on my own benchmark, on retrieval metrics, with my labels**. It
would not establish a downstream effect: that is R6's question, re-asked on a
corpus that can finally pose it, and it needs its own registration. It would
not transfer to SciFact, which has no requirements, no provenance and no gates.

Minimum 5 seeds for any arm with a stochastic component; the deterministic arms
need none and will be reported as deterministic.
