# P2 — context sufficiency: abandoned, and the metric is why

**ABANDONED on both splits, as registered.** `full_context` scores **0.800**
sufficiency — *exactly* the oracle — so `C − B = 0.000` and there is no headroom
to divide. I registered a primary metric that one of my own registered
baselines maximises trivially: handing over the entire corpus contains every
satisfier by definition.

And the selector I built to compete for that headroom does not work. It scores
**0.000 on both multi-hop families**, the families it was designed for, and its
sufficiency is identical to budget-matched top-k on every family on dev. The
diagnosis is in §4 and it is structural, not a matter of tuning.

- **Registration:** [p2-context-sufficiency.md](../prereg/p2-context-sufficiency.md), written before the selector existed
- **Benchmark:** [relevance_v2](../bench/relevance_v2/README.md), 33 cases a split, k=5
- **Runs:** 2026-10-11, `python -m experiments.p2_sufficiency --split {dev,test}`
- **Deterministic:** no model calls

---

## 1. The numbers

**dev**

| arm | sufficient | req. recall | abstention precision | false abstention | stale cited | prompt tokens |
|---|---|---|---|---|---|---|
| `top_k` | 0.533 | 0.650 | 0.000 | 0.000 | 1.000 | 54 |
| `budget_matched_top_k` | 0.533 | 0.614 | 0.000 | 0.000 | 0.833 | 29 |
| **`full_context`** | **0.800** | 0.800 | 0.000 | 0.000 | **3.500** | **6,344** |
| `sufficiency_aware` | 0.533 | 0.611 | 0.000 | 0.042 | **0.000** | 29 |
| `oracle_evidence` | **0.800** | 0.800 | 1.000 | 0.000 | 0.000 | 16 |

**test (frozen)**

| arm | sufficient | req. recall | abstention precision | stale cited | prompt tokens |
|---|---|---|---|---|---|
| `top_k` | 0.433 | 0.556 | 0.000 | 1.000 | 52 |
| `budget_matched_top_k` | 0.400 | 0.503 | 0.000 | 1.000 | 30 |
| `full_context` | **0.800** | 0.800 | 0.000 | 3.500 | 6,339 |
| `sufficiency_aware` | 0.500 | 0.586 | 0.000 | **0.000** | 32 |
| `oracle_evidence` | **0.800** | 0.800 | 1.000 | 0.000 | 15 |

```
best baseline  B = 0.800   (full_context)
ceiling        C = 0.800   (oracle_evidence)
headroom           +0.000  <= 0.05  ->  ABANDONED
```

## 2. The registered metric was the wrong one, and the registration said so

Prediction 1 was: *"`full_context` will beat `top_k` on sufficiency and lose on
tokens. It contains every satisfier by definition."* That is exactly what
happened — 0.800 against 0.533, at **6,344 tokens against 29**, a 219× ratio.

What I did not follow through is the consequence. If `full_context` is a
registered baseline and sufficiency is the registered primary metric, then
`B = max(baselines)` is the ceiling and the threshold is unreachable before any
method is written. The clause fired correctly and the fault is in the
registration, not in the run.

**Sufficiency alone is a degenerate objective: it can always be bought with
tokens.** The non-degenerate question is sufficiency *at a fixed budget*, which
the registration already contained as `budget_matched_top_k` and then made
decisive for nothing. A primary metric has to be one the baselines cannot
trivially max, and checking that is now a step this project owes every future
registration — the same role principle 8a's ceiling plays for thresholds.

At equal budget the answer is: **no reliable gain.** 0.533 against 0.533 on dev,
0.500 against 0.400 on test. Two splits disagreeing on a 0.1 difference over 33
cases means I do not know, and the dev tie is the less flattering of the two.

## 3. Nothing survived both splits — and the effect I claimed did was an artifact

> **Corrected 2026-10-12.** This section reported that `sufficiency_aware` cites
> zero stale evidence against 1.000 a case for top-k and 3.500 for
> `full_context`, calling it "the only effect here that replicates". Both
> comparison figures were artifacts and the claim is withdrawn.

Re-measured, every arm cites **0.000** stale evidence on both splits, including
`top_k` and `full_context`:

| arm | stale cited / case (was) | stale cited / case (corrected) |
|---|---|---|
| `top_k` | 1.000 | **0.000** |
| `full_context` | 3.500 | **0.000** |
| `sufficiency_aware` | 0.000 | 0.000 |

Two separate defects, both mine. `top_k`'s 1.000 came from the fixture
quarantining inside the write loop, so the product's own propagation never ran
([P3](p3-correction-propagation.md)). `full_context`'s 3.500 came from this
module: the candidate pool's tail was filtered by the *benchmark's*
`lifecycle_state` rather than by what the store considers exposable, which put
contested descendants back into a pool the store had already excluded them from.

So the selector's apparent advantage was the product's own behaviour, measured
twice with it switched off. **No effect in this experiment replicates**, and the
reframing of `full_context` that I drew from it — sufficiency-optimal but
unsound — is withdrawn with it. `full_context` is sufficiency-optimal and costs
219× the tokens, which is the whole of the finding.

## 4. Why the selector fails, which is structural

Sufficiency by family, dev — the selector against the equal-budget baseline:

| arm | `multi_hop_3` | `multi_hop_4` | `direct` | `facet_trap` | `conflicting` | `superseded_rev` |
|---|---|---|---|---|---|---|
| `budget_matched_top_k` | 0.000 | 0.000 | 1.000 | 1.000 | 0.667 | 1.000 |
| `sufficiency_aware` | 0.000 | 0.000 | 1.000 | 1.000 | 0.667 | 1.000 |
| `oracle_evidence` | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |

Identical, everywhere. The bridging mechanism never fires, and the reason is a
contradiction in its own objective:

> The selector greedily adds whichever candidate covers the most **uncovered
> query terms**. An intermediate hop covers **none**.

In a `multi_hop_3` case the query asks about bay 7 at the coastal site in
winter. Hop 1 names the bay and the site. Hop 3 names the season and the
pressure. Hop 2 — *"tug-3 was re-fitted with the heavy axle set"* — contains no
query term at all. Its entire value is connecting the other two, so its marginal
coverage gain is zero and a coverage-greedy rule can never select it.

Valuing it requires treating assembly as **path-finding over an entity graph**,
where a node with no query overlap is worth adding when it joins two nodes that
have it. That is a different algorithm, not a parameter, and relevance_v2 says
it is where the headroom is: `multi_hop_4` at 0.519 nDCG against a ceiling of
1.000.

## 5. Abstention: the registered gap is still open, and worse than that

Prediction 3 was that abstention, not sufficiency, is where a method would earn
its keep — relevance_v2 having found that **no arm abstains even once** on the
nine cases where abstention is the only correct answer.

It is still open. `abstention_precision` is **0.000** for `sufficiency_aware` on
both splits: it abstains on 1 of 33 dev cases, and that one is answerable.

The honest account is that there is **no setting of this mechanism that
abstains correctly**, and the first run proves the other side of it. Before the
coverage fix in §6, the selector abstained on **79% of the answerable cases**
and scored a perfect 1.000 abstention precision. The two runs bracket the
failure: demanding full lexical coverage abstains on everything, and demanding
coverage of only the terms the corpus contains abstains on nothing.

Neither is a signal about the asked question, because **token presence is not
evidence about a conjunction**. On an `unanswerable` case the asked facet tuple
is absent while every one of its terms appears somewhere — "winter" in a
different topic's sentence about oil temperature, "coastal" in four hundred
others. Coverage completes from memories that are not about the question. The
restatement test blocks a bridge between two near-misses of the same predicate
and cannot block a bridge to an unrelated sentence that merely carries the
token.

## 6. Two invalid runs before these, both recorded

**The first run's oracle scored 0.000 on both multi-hop families** — impossible
for an arm handed the answers, and under principle 8b an impossible oracle means
the ceiling is wrong rather than the task being hard. `retrieve` returns what
the lexical index scored, and hop 2 shares no term with the query, so it was
never a candidate for *any* arm. A chain whose middle link cannot be retrieved
is not a hard retrieval problem, it is an absent candidate — and bridging to
exactly that link was the mechanism under test. Retrieval now supplies the
order and the corpus supplies the pool.

**The same run abstained on 79% of answerable cases**, because coverage demanded
every content term of the query including interrogatives and morphological
variants: *"How often is the X cable swapped at Y?"* asks for "often" and
"swapped" where the corpus says "swap … every 90 days". Neither token exists
anywhere, so coverage could never reach 1.0. Filtering to terms with a document
frequency of at least one is label-free and removes both classes without a
stop-list to maintain.

Both are here because the pattern is this project's most frequent failure: a
measurement that looks like a result about a mechanism. That is now four
instances across R1, P3 and this experiment.

## 7. The restatement threshold does not separate as cleanly as claimed

`RESTATEMENT = 0.6`, justified as the midpoint of a bimodal gap. Measured on
dev, over the top 12 candidates a case:

| pair kind | n | mean Jaccard | max |
|---|---|---|---|
| differing by ≤ 2 tokens (restatements) | 115 | 0.797 | 0.889 |
| everything else | 2,063 | 0.396 | **0.727** |

The means are far apart and **the distributions overlap**: non-restatement pairs
reach 0.727, above the 0.6 threshold, so some legitimate bridges are blocked by
a rule written to block near-misses. The claim in the module docstring that
different predicates "score below 0.3" is true of the mean and false of the
tail, and is corrected there.

It is not the cause of §4 — the mechanism fails on marginal gain, before the
restatement test is consulted — but a threshold defended as sitting in a clean
gap should be shown not sitting in one.

## 8. What this does not establish

1. **No method was fairly tested.** The registered comparison was abandoned on a metric flaw, and the selector has a structural defect. Nothing here is evidence about whether sufficiency-aware assembly can work.
2. **33 cases a split, three a family.** Every per-family figure is three cases.
3. **No downstream measurement.** Whether a sufficient context changes what a model answers is R6's question. Given R6, it must not be assumed.
4. **`full_context` at 6,344 tokens is cheap by modern standards.** The `budget_pressure` family at ~25,000 is the regime where it stops being an option, and this experiment did not isolate it.
5. **The labels are mine**, and sufficiency is defined by requirement slots I wrote. A different decomposition of "enough evidence" could order the arms differently.

## 9. The honest summary

> **Abandoned, because I registered a metric a baseline maximises for free.**
> Handing over the whole corpus scores exactly the oracle's 0.800 sufficiency,
> so the headroom was 0.000 before any method existed. Prediction 1 said
> `full_context` would win on sufficiency and lose on tokens; it did, by 219× in
> tokens, and I did not follow that through to the fact that it made the
> threshold unreachable. **Sufficiency can always be bought with context, so the
> metric has to be sufficiency at a fixed budget** — which the registration
> contained and made decisive for nothing.
>
> At equal budget there is no reliable gain: a tie on dev, +0.100 on test, over
> 33 cases.
>
> **The selector does not work, and the reason is structural.** It greedily adds
> whatever covers the most uncovered query terms, and a chain's middle hop
> covers none — its whole value is connecting the other two. Assembly for
> multi-hop evidence is path-finding over an entity graph, not coverage
> maximisation, and that is a different algorithm rather than a parameter.
>
> **Abstention is still at zero and now has a diagnosis.** Demanding full
> lexical coverage abstains on 79% of answerable cases; demanding coverage of
> only the terms the corpus contains abstains on none. Token presence is not
> evidence about a conjunction, and nothing between those two settings is
> either.
>
> **Nothing here replicates.** An earlier version of this summary claimed the
> selector's zero stale citations as the one surviving effect; every arm scores
> zero once the fixture lets the product's retraction propagation run and this
> module stops re-admitting memories the store had excluded. The comparison was
> the product's own behaviour measured twice with it switched off.
