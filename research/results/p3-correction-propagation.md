# P3 — correction propagation: plain graph traversal beats the product

**NOT SUPPORTED, on both splits, and not narrowly.** The product's
dependency-aware behaviour — source-root grouping — closes **−150%** of the
measured headroom against a registered bar of 40%: it is substantially *worse*
than the best simple baseline. A five-line rule that withholds anything with a
retracted ancestor is optimal on every family except the one nothing solves.

- **Registration:** [p3-correction-propagation.md](../prereg/p3-correction-propagation.md), written before any arm existed
- **Fixture:** [propagation_v1](../bench/propagation_v1/build.py) — 16 cases, four families, ~205 memories a case, dev 8 / test 8
- **Runs:** 2026-10-11, `python -m experiments.p3_propagation --split {dev,test}`, k=5
- **Deterministic:** no model calls; one retrieval a case, five rules over the same ranking

---

## 1. The numbers

| arm | stale cited / case | stale rate | unnecessary invalidation | sufficient |
|---|---|---|---|---|
| `no_propagation` | 1.375 | 0.750 | 0.000 | 1.000 |
| `blanket_invalidation` | 0.500 | 0.250 | **0.500** | **0.500** |
| **`graph_traversal`** | **0.500** | 0.250 | **0.000** | **1.000** |
| `source_root_grouping` (the product) | 1.250 | 0.750 | 0.000 | 1.000 |
| `oracle_propagation` | 0.000 | 0.000 | 0.000 | 1.000 |

```
best baseline        B = 0.500   (graph_traversal, and blanket ties it)
ceiling              C = 0.000   (oracle, zero by construction)
headroom                 +0.500
threshold            B - 0.40 x headroom = 0.300
source_root_grouping     1.250        ->  NOT SUPPORTED (-150% of headroom)
```

**The frozen split agrees to three decimals** on every arm except
`no_propagation` (1.500 against 1.375). Eight cases a split, so the counts
matter more than the decimals, and they are given beside every rate in the
harness output.

## 2. Graph traversal is optimal everywhere the question is answerable

Stale citations a case, by family — the aggregate hides this entirely:

| arm | `retracted_intermediate` | `deep_chain` | `independent_reconfirmation` | `copied_document` |
|---|---|---|---|---|
| `no_propagation` | 2.000 | 0.000 | 1.500 | 2.000 |
| `blanket_invalidation` | **0.000** | 0.000 | **0.000** | 2.000 |
| `graph_traversal` | **0.000** | 0.000 | **0.000** | 2.000 |
| `source_root_grouping` | 2.000 | 0.000 | 1.000 | 2.000 |
| `oracle_propagation` | 0.000 | 0.000 | 0.000 | 0.000 |

Unnecessary invalidation, which is where the two simple rules part:

| arm | `retracted_intermediate` | `deep_chain` | `independent_reconfirmation` | `copied_document` |
|---|---|---|---|---|
| `blanket_invalidation` | **1.000** | **1.000** | 0.000 | 0.000 |
| every other arm | 0.000 | 0.000 | 0.000 | 0.000 |

So: **the entire residual 0.500 is `copied_document`**, and traversal is exactly
the oracle on the other three families. Blanket invalidation matches it on stale
evidence and pays for it by discarding the standing source in two families out
of four, which halves sufficiency from 1.000 to 0.500 — it answers nothing in
the cases where an answer existed.

That is prediction 1 confirmed, and §4 is about why it took a second fixture to
confirm it.

## 3. What nothing solves, and why it is in the fixture

`copied_document` is 2.000 for **every rule including the product's**. The same
contractor bulletin was ingested twice — once retracted, once as a copy filed by
the site office — and provenance honestly records two roots, because there were
two ingestions. Root identity says the copy is independent. Parent edges say the
copy is independent. Both are right about the provenance and wrong about the
evidence.

`_group_by_root` exists precisely to stop copies counting as corroboration, and
it cannot see this one: it groups by source root, and a re-ingested document is
two roots and two votes. The mechanism's own docstring says it is "not content
deduplication, deliberately", for a good reason — two near-identical memories
can be independently observed, which is real corroboration. The cost of that
correct choice is this case.

It is in the fixture knowing nothing solves it, because a comparison containing
only cases some arm wins is a comparison arranged to have a winner.

## 4. The first run of this experiment was abandoned, and the clause was right

Run against relevance_v2's `shared_root` / `independent_support` pair, P3
**abandoned on both splits**:

| arm | stale cited / case | unnecessary invalidation |
|---|---|---|
| `no_propagation` | 3.333 | 0.000 |
| `blanket_invalidation` | **0.000** | **0.000** |
| `graph_traversal` | **0.000** | **0.000** |
| `source_root_grouping` | 1.000 | 0.000 |
| `oracle_propagation` | 0.000 | 0.000 |

Two one-line baselines scored *exactly the oracle* on both primary metrics, so
`B - C = 0.000` and the registered clause fired on its own.

**That was prediction 1 being wrong.** I predicted blanket invalidation would
win on stale citations and lose on unnecessary invalidation. It won both,
because in `independent_support` the standing load-cell trial has a **different
source root** — so a rule withholding by root identity never touches it. The
registration names the condition in so many words — *"it discards nothing
wrongly only because the standing trial has a different root"* — and I built the
matched pair anyway without the case where that stops being true.

The separating structure is a **retracted non-root**: a derived memory that is
itself retracted, sitting under a root that still carries standing evidence.
Then withholding by root is wrong and following edges is right. `propagation_v1`
exists to supply it, and relevance_v2 was left byte-for-byte as committed
because [its ceiling](relevance-v2-ceiling.md) was measured against those
digests.

## 5. And the second run was wrong too, until the chains were built

The first `propagation_v1` run reported **1.500** stale citations for
`graph_traversal` on `retracted_intermediate`, where it should score 0.000 — the
rule was correct and the fixture had no chain to traverse.

Both this experiment and the shared harness wrote memories in order of
`len(parents)`, which is **not a topological order**. It is correct only for
chains of depth one, which is all relevance_v1 and relevance_v2 contain. In
`root → interim → restatement` the interim and the restatement both have one
parent, so the restatement could be written first, its parent was not yet in the
store, and the edge was dropped in silence — leaving the memory as its own
source root and reading to every rule as independent evidence.

That is the **third** time in this project an absent provenance edge has looked
like a result about a mechanism: v2's bare-string parents, my wrong explanation
of the identical numbers that followed, and now this. `insertion_order()` in
`experiments/relevance_bench.py` raises on a cycle or dangling parent rather
than skipping it, and `tests/test_propagation_v1.py` asserts the full depth of
each chain survives the round trip through the store.

Correcting it changed `blanket_invalidation` and `graph_traversal` from 0.875 to
0.500 and left the product's 1.250 untouched, so the verdict moved from −43% to
−150% of the headroom. The direction never changed; the margin did.

## 6. What this says about the product

The product has **no retraction propagation in the retrieval path at all**.
Source-root grouping is a de-duplication rule that happens to touch derived
memories, and on this question it performs worse than doing nothing much:
1.250 against `no_propagation`'s 1.375. It reduces stale citations by collapsing
*copies* of one root and then keeps the best-ranked survivor, which on
`retracted_intermediate` is still stale.

The concrete gap: nothing asks *does this memory descend from something that was
withdrawn?* at exposure time. The lineage graph that would answer it already
exists and is already used — `_derivation_related` walks it — so this is a rule
the fabric can express and does not.

A caveat on the ceiling, which belongs with the recommendation: the oracle
scores 0.000 **by construction**, because it is handed the labelled stale set.
It bounds the metric and is not a method. And `graph_traversal`'s 0.500 is a
measurement on 16 hand-built cases with my labels, four to a family, two to a
split. It is strong enough to say the product should have the rule and not
strong enough to say the rule is sufficient.

## 7. Predictions, scored

| | prediction | outcome |
|---|---|---|
| 1 | blanket invalidation wins on stale, loses on unnecessary invalidation | **wrong on relevance_v2** (won both), **right on propagation_v1** (0.500 unnecessary invalidation, sufficiency halved). The registration named the condition and the first fixture did not contain it |
| 2 | blanket and traversal mostly coincide, because every derived memory is one hop from the root | **right** — identical on stale citations in every family. They differ only on unnecessary invalidation, which is what the deeper chains were added for |
| 3 | source-root grouping will not reach the oracle, and will close well under 40% | **right, and understated** — it closed −150%, i.e. it is worse than the best baseline rather than merely short of the bar |
| 4 | the product will fail its own registered bar | **right**, and recorded in advance precisely so that −150% could not be renegotiated into "it helps a bit" |

## 8. What this does not establish

1. **Sixteen cases, four to a family, eight to a split.** Every number is a direction with a wide interval. The two splits agreeing is worth more than either split's decimals.
2. **No external check exists for this question**, in this project or, as far as I know, anywhere. SciFact has no provenance. These are my cases and my labels.
3. **One store, one process, no time.** The retraction is already in place when the query runs. "A retraction that arrives after a conclusion was acted on" is a different experiment and needs the event log, not the retrieval path. Federation is untested and its ROADMAP gates still govern it.
4. **No downstream measurement.** Whether a context free of stale evidence changes what a model answers is unmeasured. Given R6, it should not be assumed.
5. **`graph_traversal` is not implemented in the product.** It is an experiment arm. Shipping it needs a decision about what to do when the only support for a needed fact is withdrawn — abstain, or expose it flagged — and that is a product question this experiment does not answer.

## 9. The honest summary

> The product's dependency-aware behaviour **loses to a five-line baseline**,
> and loses to it on both splits by the same margin. Withholding anything with
> a retracted ancestor is exactly optimal on three of four families;
> source-root grouping closes −150% of the headroom against a registered 40%
> bar, which is to say it is worse than the best simple rule.
>
> Blanket invalidation ties traversal on stale evidence and pays 0.500
> unnecessary invalidation for it, halving sufficiency — so the conservative
> rule is not the safe one, which is what the fixture was built to show.
>
> One family defeats everything: a withdrawn document re-ingested under its own
> root. Provenance correctly records two sources and is correctly wrong about
> the evidence, and the mechanism designed to stop copies counting as
> corroboration cannot see it.
>
> Both of the first two runs of this experiment were invalid — the first because
> its fixture could not separate the rules, the second because a non-topological
> write order silently dropped the derivation edges. Both are recorded above
> rather than edited away, because the pattern they share is the one this
> project keeps repeating: an absent provenance edge reads as a result about a
> mechanism.
