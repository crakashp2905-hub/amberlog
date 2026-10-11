# Pre-registration — P3: evidence dependence and correction propagation

**Registered 2026-10-11, before any comparative propagation arm is written and
before the relevance_v2 test split has been opened.** The dev numbers in
[relevance-v2-ceiling.md](../results/relevance-v2-ceiling.md) §7 are the basis
for the thresholds and are in scope for me to have seen. Nothing here may be
revised after a test-split number is read.

## 1. The question

A conclusion has four apparent supports. All four derive from one survey, and
the survey is retracted. What should happen?

Counting supports gives four. Counting distinct standing source roots gives
zero. The provenance machinery was built for exactly this and has never been
measured on it, because v1's `copied_evidence` family had three cases and
18-memory corpora.

The question has a trap, and the benchmark is built around it: **the obviously
safe answer is wrong half the time.** `shared_root` and `independent_support`
are a matched pair with identical surface — the same retracted survey, the same
three derived restatements — differing only in whether one further measurement
descends from the survey. Blanket invalidation gets the first right and the
second wrong, by discarding a standing load-cell trial and abstaining when the
answer was available. A method cannot win here by being conservative.

## 2. Arms

| arm | rule |
|---|---|
`no_propagation` | retraction affects only the retracted memory. `store_plain`.
`blanket_invalidation` | anything sharing a source root with a retracted memory is withheld. The conservative baseline, and the one the matched pair is built to catch.
`graph_traversal` | anything reachable from a retracted memory through parent edges is withheld, regardless of whether an independent root also supports it.
`source_root_grouping` | the product: keep the best-ranked memory per source root, sparing a premise of something already kept. `store_roots`.
`oracle_propagation` | the labels: withhold exactly the `stale` set, expose exactly the standing support. Same gates, same k, same mechanisms — principle 8b.

`oracle_propagation` scores 0.000 stale citations **by construction**, because
it is told which memories are stale. It bounds the metric; it is not a method,
and the write-up must say so wherever the number appears.

## 3. Primary metrics — two, and a method must not trade them

This is the one place in the project where a single primary metric would be
wrong, because the failure modes are opposed and either can be driven to zero
alone.

1. **`stale_citations_mean`** — the mean number of returned memories whose own lifecycle is active but whose source root is retracted. Driven to zero by withholding everything.
2. **`unnecessary_invalidation`** — on `independent_support`, the share of cases where the standing measurement (`r2` or `d4`) was *not* returned although it was reachable. Driven to zero by withholding nothing.

**A method must improve the first without worsening the second.** Registered
thresholds, with headroom measured on the evaluation split at run time:

```
B_stale = min(stale_citations_mean) over the three baseline arms
C_stale = stale_citations_mean(oracle_propagation)        # 0.000 by construction
support iff  stale_citations_mean <= B_stale - 0.40 * (B_stale - C_stale)
        and  unnecessary_invalidation <= min over the three baseline arms
```

On dev: `no_propagation` 1.500, `source_root_grouping` 1.000, and on the
lexical arm 3.333 → 1.000. The *rule* is registered, not those numbers.

**Abandonment clause.** If `B_stale - C_stale <= 0.25` citations a case, the
comparison is **abandoned, not reinterpreted**: there is too little stale
evidence reaching the context for a propagation rule to show anything, and a
threshold on it would be the H3 mistake. R6's clause fired on its own and the
harness printed it unasked; this one must too.

## 4. The secondary metric that is really a warning

**`stale_citation_rate`** — the share of cases citing *any* stale memory. On dev
it is **1.000 for every real arm, including the product's**, while the mean
falls from 3.333 to 1.000. Grouping reduces how much stale evidence reaches a
context and **never eliminates it**.

So a rate of 1.000 with an improved mean is the expected outcome, not a
failure, and reporting only the rate would have hidden a 70% reduction — which
is what happened: the first version of this metric was the rate alone, and it
showed grouping doing nothing. A binary that cannot tell four wrong citations
from one is not measuring the mechanism.

Also reported: `sufficient`, `abstention_precision` on `shared_root` (where
abstention is the only correct answer), `latency_ms`, and
`must_not_expose_rate` — any non-zero value fails the run outright.

## 5. Predictions

1. **`blanket_invalidation` will win on stale citations and lose on unnecessary invalidation**, and the loss will be concentrated entirely in `independent_support`. If it wins both, the matched pair does not work and the benchmark is at fault, not the arm.
2. **`graph_traversal` will be close to blanket invalidation**, because in these cases every derived memory is one hop from the root, so the two rules mostly coincide. The families do not yet contain a deep chain where they diverge; if prediction 2 holds, building one is the next benchmark change rather than a ranker.
3. **`source_root_grouping` will not reach the oracle**, because it reduces copies rather than reasoning about standing support: it keeps the best-ranked derived memory, and on `shared_root` that memory is still stale. I expect it to close well under half the headroom, and the registered bar is 40%.
4. **The product will fail prediction 3's bar.** Recorded because I would rather have the shortfall on record in advance than discover a reason to call 30% "most of the way there" afterwards. R6 closed 20% against a 40% bar and was reported inconclusive; this is the same discipline applied before the fact.

## 6. What a pass would not establish

- **Nothing about distributed propagation.** Every case is one store, one process. The federation path is not under test and P-gates in ROADMAP.md still govern it.
- **Nothing about delayed retraction in time.** The retraction is already in place when the query runs. "A retraction that arrives after a conclusion was acted on" is a different experiment and needs the event log, not the retrieval path.
- **Nothing external.** SciFact has no provenance. This is my benchmark and my labels, and no external check for this question exists in this project or, as far as I know, anywhere.
- **Three cases a family a split.** Six total across both splits. Any effect here is a direction with a wide interval, and the write-up must give the counts beside every rate.

Minimum 5 seeds for any arm with a stochastic component; the arms above are
deterministic and will be reported as such.
