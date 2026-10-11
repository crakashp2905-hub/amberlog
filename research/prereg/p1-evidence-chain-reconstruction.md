# Pre-registration — P1: evidence-chain reconstruction

**Registered 2026-10-12, before the mechanism exists.** The ceiling below is
already measured and is why this is worth building; the threshold is a share of
it (principle 8a), the metric has been checked against its own baselines
(principle 8c), and the oracle gets the same budget and the same `k` as the arms
it bounds (principle 8b).

## 1. The question, and why selecting by individual relevance cannot answer it

Can the fabric reconstruct a **sufficient, currently valid** chain of evidence
when **no single memory matches the query**, and say why each intermediate
memory is necessary?

Three measurements say the current answer is no, and locate the reason
precisely:

| | measured |
|---|---|
| `multi_hop_4` sufficiency, every non-oracle arm | **0.000** ([P2](../results/p2-context-sufficiency.md)) |
| `multi_hop_4` nDCG@5 — lexical / mechanisms / oracle | 0.330 / 0.519 / 1.000 ([v2 ceiling](../results/relevance-v2-ceiling.md)) |
| `implied_by_default` nDCG@3, every arm including a trained embedder | **0.000** ([facet_v1](../results/facet-v1-implied.md)) |

The cause is not a weak similarity function. A chain's middle hop has **zero
query-term overlap**: in a `multi_hop_3` case the query names a bay, a site and
a season, and hop 2 says *"tug-3 was re-fitted with the heavy axle set"* — no
query token at all. Its entire value is connecting hop 1 to hop 3. So:

- **Ranking by individual relevance** cannot surface it, because it is not relevant on its own.
- **Coverage-greedy assembly** cannot select it either, which P2 measured: its marginal coverage gain is zero, so the selector scored 0.000 on both chain families and was identical to budget-matched top-k everywhere else.
- **`expand_lineage`** promotes a premise one hop *when the conclusion already ranked*. It lifts `multi_hop_4` from 0.330 to 0.519 and cannot start from a query that matches nothing.

What is missing is search over the graph the memories induce. That is the
mechanism this registration is about.

## 2. The mechanism under test

`chain` — a **bounded** search for a connected set of currently valid memories
that jointly cover the query's reachable terms. Bounded is part of the claim,
not a caveat: an unbounded graph search over ~500 memories is not a retrieval
mechanism, and `nodes_explored` is reported on every run.

It may use only what a deployment has: the query, the candidate memories'
content, the derivation edges, and the gates. It **may not** read labels,
`requirements`, `critical`, or `stale`. A test asserts the module never
references them.

**Validity is by construction, not by filtering afterwards.** The search runs
over the eligible set `_eligible_ids` and `_applicable_at` produce, so a
retracted memory, a contested descendant, a wrong-tenant memory, an
unauthorised one and a memory outside its validity interval are never nodes in
the graph. This is the one part of the question the fabric already answers, and
the mechanism must not weaken it: `must_not_expose_rate` above zero fails the
run outright, whatever else it scores.

**Necessity is defined so it can be checked, not asserted.** A step is
`necessary` iff removing it from the returned chain either leaves a query term
uncovered or disconnects the remaining set. Leave-one-out, computed from the
chain itself. Each step carries a `ReasonCode` — `DIRECT_MATCH` for a step that
supplies query terms, `DEPENDENCY_REQUIRED` for a connector — and
`DEPENDENCY_REQUIRED` currently has no producer anywhere in the codebase, which
is the shape of the gap.

## 3. Arms

| arm | what it is |
|---|---|
`lexical` | the product as it ships, `retrieval="lexical"` with mechanisms on. The baseline to beat.
`real_vector` | trained embedder (`nomic-embed-text`), the strongest similarity arm available.
`real_hybrid` | RRF of the two. Included because the fusion rule has four confirmations and a fifth costs nothing.
`chain` | the mechanism under test.
`oracle` | the labelled relevant set, **same gates, same k, same budget**.

All arms are capped at k=5 and at relevance_v2's declared 400-token budget,
including the oracle.

## 4. Primary metric, ceiling, and the 8c check

**Primary: `sufficient`** — the share of cases where every critical evidence
requirement is met by a memory the gates allowed — **on the chain families
only**: `multi_hop_3`, `multi_hop_4` from relevance_v2.

Measured before registering:

| family | best non-oracle arm | oracle | headroom |
|---|---|---|---|
| `multi_hop_3` | 0.000 | 1.000 | **+1.000** |
| `multi_hop_4` | 0.000 | 1.000 | **+1.000** |

**8c check — does any registered baseline max it?** No. Every baseline is at
0.000, which is the opposite failure from P2's, where `full_context` sat on the
ceiling. `full_context` is excluded here by the 400-token budget, which it
exceeds 16-fold; it is reported as non-compliant rather than silently dropped.

```
B = max(sufficient) over {lexical, real_vector, real_hybrid}
C = sufficient(oracle)
support chain iff  sufficient >= B + 0.40 * (C - B)
```

On the dev numbers above that is a bar of **0.400**. The rule, not the number,
is what is registered; headroom is recomputed on the evaluation split at run
time.

**Abandonment clause.** If `C - B <= 0.05`, abandoned rather than
reinterpreted.

**Ceiling check** every run: any arm above the oracle means the ceiling is
wrong (8b), not that the arm is good.

## 5. Secondary metrics — reported always, decisive for none

- **`necessity_precision`**: of the steps the chain calls `necessary`, the share that are in the labelled `critical` set. This is the explanation's correctness and it is *not* primary, because a mechanism could score well by returning one-step chains.
- **`necessity_recall`**: of the labelled critical memories, the share the chain both returned and called necessary.
- `nDCG@5`, `critical_recall`, `requirement_recall`.
- **`nodes_explored`** and `latency_ms`. A chain search that wins by exploring the whole corpus has not won; P9 was declined on a 4.39 ms figure that turned out to be the wrong embedder's.
- **No-regression on the other nine relevance_v2 families.** A mechanism that fixes chains and breaks `direct` is not an improvement. Reported, and a fall of more than 0.05 nDCG on any family is called out.
- `must_not_expose_rate` — **any non-zero value fails the run.**

## 6. Predictions

1. **`real_vector` will not beat `lexical` on the chain families.** Both will stay at or near 0.000 sufficiency. The connector hop is not semantically similar to the query either, so a better embedding should not help, and if it does my account of why chains fail is wrong.
2. **`chain` will reach the 0.400 bar on `multi_hop_3` and fall short on `multi_hop_4`.** The 4-hop case needs the site-margin memory, which shares only the site token with the query and sits behind two other hops, so it is the deepest thing the bound has to reach.
3. **Necessity precision will be high and recall lower.** Leave-one-out marks a step necessary only if the chain breaks without it; where two memories jointly cover one term, neither is individually necessary, so true critical memories will be missed. If recall is high I should check whether the chains are trivially short.
4. **`chain` will not help `implied_by_default` in facet_v1.** The default rule shares no entity with any other memory, so there is no edge to traverse to it — it is not a chain problem but an entailment problem, and this mechanism should leave it at 0.000. Registered because it is the honest limit of the approach and I would rather state it now than explain it afterwards.
5. **Latency will be the weakest result.** A bounded search over ~500 candidates will cost more than the ~10 ms a lexical query costs, and the question is whether it is 2× or 50×.

## 7. What a pass would not establish

- **Nothing downstream.** Whether a model handed a reconstructed chain answers better is R6's question, whose dev finding did not replicate. It needs its own registration.
- **Nothing external.** SciFact has no chains, no provenance and no gates. These are my cases and my labels, and the chain families are 3 cases a split.
- **Nothing about entailment.** Prediction 4 is that the hardest measured family stays unsolved. A pass here closes the chain gap and leaves the `implied_by_default` gap open.
- **Nothing about scale.** One store, one process, ~500 memories. The operational envelope is a separate question with its own gates in ROADMAP.md.

Deterministic apart from `real_*`; no seeds needed and the runs will be reported
as byte-identical across two invocations of one commit.
