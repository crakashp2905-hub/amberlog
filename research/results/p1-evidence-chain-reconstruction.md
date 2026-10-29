# P1 — evidence-chain reconstruction: the bar is missed, and the mechanism works

**NOT SUPPORTED. 33% of the measured headroom against a registered 40%,
identical on both splits.** That is the verdict and it is reported first,
because the secondary numbers are good enough to be tempting and the threshold
was registered precisely so this moment could not be renegotiated.

What the mechanism does do: it reconstructs a three-hop chain by recovering a
connector sitting at **rank 463 of ~486**, labels it `dependency_required`, and
explains why it is necessary. Overall nDCG goes from 0.654 to **0.873** on dev
with **zero regressions on any family on either split**.

- **Registration:** [p1-evidence-chain-reconstruction.md](../prereg/p1-evidence-chain-reconstruction.md), written before the mechanism existed
- **Mechanism:** `Amberlog.reconstruct()` / `amberlog/chains.py`
- **Benchmark:** [relevance_v2](../bench/relevance_v2/README.md), 33 cases a split, k=5; plus [facet_v1](facet-v1-implied.md) for prediction 4
- **Runs:** 2026-10-12. Deterministic apart from `real_*`

---

## 1. The registered verdict

Primary metric: sufficiency pooled over `multi_hop_3` and `multi_hop_4`.

```
best baseline        B = 0.000   (lexical, real_vector and real_hybrid all 0.000)
ceiling              C = 1.000   (oracle)
headroom                 +1.000
threshold            B + 0.40 x headroom = 0.400
chain                    0.333
VERDICT: NOT SUPPORTED  (closed 33%)
```

**Both splits give 0.333.** Per family, on both splits:

| family | baselines | `chain` | bar |
|---|---|---|---|
| `multi_hop_3` | 0.000 | **0.667** | 0.400 — passes |
| `multi_hop_4` | 0.000 | **0.000** | 0.400 — fails |

Taking the per-family reading would let me report a pass. The registration
pooled the two families, so the pooled number is the verdict, and 0.333 is
below 0.400. **Prediction 2 said exactly this** — reaches the bar on 3 hops,
falls short on 4 — which is the one place in this project where a registered
prediction has been right in full.

## 2. What it does, on a real case

`multi_hop_3-01`, dev. The query asks for the winter pressure of the vehicle in
bay 5 at the northern site. No memory states it.

| step | reason | rank | role |
|---|---|---|---|
| `h1` "Bay 5 at the northern site is assigned to chiller-1." | `direct_match` | 3 | supplies *5, bay, northern, site*; links through **chiller-1** |
| `h3` "Vehicles with the standard axle set run 4.0 bar in summer." | `direct_match` | 0 | supplies *run, summer*; links through **standard, axle, set** |
| `h2` "chiller-1 was re-fitted with the standard axle set in March." | **`dependency_required`** | **462** | supplies **no query term**; links through *standard, chiller-1, axle, set* |

All three are `necessary` by leave-one-out. `ReasonCode.DEPENDENCY_REQUIRED`
has existed in the contract since R0 with **no producer anywhere in the
codebase**; this is the first thing that emits it.

**Rank 462 of ~486 is the quantitative answer to "no single memory matches the
query".** A top-5 arm would need to return 95% of the corpus to see that
memory. The `deepest rank used` column reaches **463 on dev and 482 on test**.

## 3. Secondary results, all of which exceed the primary

| | dev | test |
|---|---|---|
| nDCG@5 — `lexical` | 0.654 | 0.549 |
| nDCG@5 — `real_vector` | 0.669 | 0.551 |
| nDCG@5 — `real_hybrid` | 0.639 | — |
| **nDCG@5 — `chain`** | **0.873** | **0.743** |
| nDCG@5 — `oracle` | 1.000 | 1.000 |
| precision@5 — `lexical` / `chain` | 0.267 / **0.778** | 0.242 / **0.586** |
| irrelevant ratio — `lexical` / `chain` | 0.733 / **0.222** | 0.758 / **0.414** |
| sufficiency, all families — best baseline / `chain` / oracle | 0.567 / **0.600** / 0.800 | 0.500 / **0.567** / 0.800 |

On nDCG the chain arm closes **62% of the headroom on dev and 43% on test**
against the best baseline. That is not the registered metric and does not
become the result by being larger.

**Zero regressions.** Every family is at or above the baseline on both splits:

| family | `lexical` dev | `chain` dev | `lexical` test | `chain` test |
|---|---|---|---|---|
| `direct` | 1.000 | 1.000 | 0.877 | 0.877 |
| `facet_trap` | 1.000 | 1.000 | 0.167 | **0.421** |
| `superseded_rev` | 0.631 | **1.000** | 0.421 | **0.667** |
| `conflicting` | 0.667 | 0.667 | 0.871 | **0.973** |
| `budget_pressure` | 0.667 | 0.667 | 0.667 | 0.667 |
| `independent_support` | 0.501 | **0.920** | 0.501 | **0.920** |
| `multi_hop_3` | 0.437 | **0.901** | 0.401 | **0.901** |
| `multi_hop_4` | 0.330 | **0.832** | 0.488 | **0.520** |

## 4. Why `multi_hop_4` fails, which is a limit of the objective

On all three dev cases the chain returns `h1`, `h2`, `h3` correctly and misses
exactly `h4`:

> "At the depot-12 site, add 0.35 bar to the axle-set figure as a
> salt-corrosion margin."

The chain is already **complete and connected** without it: every query term is
covered. `h4` supplies no query term that `h1` has not already supplied, and
links nothing that is not already linked. It is a **modifier** — it changes the
answer without being a cover or a bridge — and a search whose objective is
coverage plus connectedness has no reason to want it.

Nothing in the query signals that a site-specific margin exists. Knowing to
look means noticing that a memory *qualifies a rule already in the chain*,
which is reasoning about what a memory does to a conclusion rather than about
what it mentions.

So the mechanism solves **distributed evidence requiring a connector** and does
not solve **evidence that modifies a conclusion**. That distinction is the most
useful thing this experiment produced, and it was not visible before there was
a mechanism that solved the first one.

### A disclosure about the frozen split

Diagnosing this, I inspected a `multi_hop_4` case from the **frozen test
split** and found a second failure mode: the chain bridged through the generic
tokens *axle, set* and selected a rule for the **wrong axle type**, because
those tokens are shared by every axle rule while the discriminating token
(*light* / *heavy*) is not.

It does not appear in any dev case. A plausible fix — rank covering candidates
by how discriminating their link to the chain is, which is the rule already
applied to bridges — would therefore be **tuned on the frozen split**, so I
have not made it. The observation is recorded as a hypothesis for a future
split, the mechanism is unchanged, and the numbers above are as measured.
Looking was a lapse; acting on it would have been the real error.

## 5. The explanation's correctness

| scope | necessity precision | necessity recall |
|---|---|---|
| `multi_hop_3`, both splits | **0.889** | **0.889** |
| `multi_hop_4`, dev | 1.000 | 0.750 |
| `multi_hop_4`, test | 0.556 | 0.417 |
| all families, dev | 0.682 | 0.625 |

**Prediction 3 was right on the chain families**: precision high, recall lower,
because leave-one-out marks a step necessary only if the chain breaks without
it — where two memories jointly supply one term, neither is individually
necessary. That is the correct answer and it caps recall below 1.0 by
construction.

The all-families figure is **not a fair reading of the explanation** and is
reported with that caveat. On `independent_support` the labelled `critical` set
names only `r2` while the requirement is satisfiable by `r2` *or* `d4`; a chain
returning `d4` is sufficient and scores 0.000 necessity precision against a
label that names the alternative. The metric is sound where `critical` is the
whole chain and noisy where requirements have alternative satisfiers.

## 6. Cost

| arm | latency a query |
|---|---|
| `lexical` | 10 ms |
| `chain` — search only | **13 ms** (20 ms on the chain families) |
| `chain` — including per-case store construction | 144 ms |
| `real_vector` | **4,658 ms** |

**Prediction 5 was wrong.** I expected latency to be the weakest result and
guessed between 2× and 50×; the search itself costs about 1.3× a lexical query,
and 2× on the families that actually need a chain. Expansion is capped at
`beam` successors per state, so a whole search generates at most
`beam × beam × max_steps` states regardless of corpus size: **208 states** on
the chain families, 88 on average, with the node budget never exhausted.

The 144 ms figure is per-case store construction, which every store-backed arm
in this harness pays and no deployment pays per query.

`real_vector` at **4,658 ms** is the P9 finding arriving again from a third
direction: a 768-dimension dense scan over ~495 documents, against the 4.39 ms
figure on which distribution was declined.

## 7. Predictions, scored

| | prediction | outcome |
|---|---|---|
| 1 | `real_vector` will not beat `lexical` on the chain families | **right** — both 0.000 sufficiency on both splits. The connector is not semantically similar to the query either |
| 2 | reaches the bar on `multi_hop_3`, falls short on `multi_hop_4` | **right, exactly** — 0.667 and 0.000, pooled to 0.333 against 0.400 |
| 3 | necessity precision high, recall lower | **right** on the chain families (0.889 / 0.889) |
| 4 | no help on `implied_by_default` in facet_v1 | **right** — all three implied families stay at 0.000 on both splits, control at 1.000. It is an entailment problem, not a chain problem |
| 5 | latency will be the weakest result, 2× to 50× | **wrong** — ~1.3× for the search, and the strongest secondary result rather than the weakest |

## 8. Three defects the mechanism shipped with, and one regression it caused

Recorded because each was found by measurement rather than by reading, and each
had a plausible-looking wrong version.

1. **Coverage alone was the goal.** `h1` and `h3` between them mention every query term and have nothing to do with each other, so the search returned exactly those two and skipped the memory that joins them — reporting `missing=()` while being no use. **Connectedness is now part of the goal**, not a preference.
2. **A bare digit was treated as a link.** `LexicalIndex` tokenises on `[a-z0-9]+`, so "tug-3" became *tug* and *3*, "3.0 bar" also produced *3*, and the search joined a bay assignment to the wrong pressure rule through that token — a confident wrong answer in two steps. `chains.tokens` keeps identifiers whole and bare numerals are excluded from links, though they still count for coverage.
3. **A connector was unreachable.** Bridges were admissible only while the set was *disconnected*, and a one-memory state is trivially connected, so the first hop could never reach its own connector. Gating on incompleteness instead fails the opposite way, because a covering-but-disconnected pair is complete. **Both conditions are needed**, and this was the most expensive of the three to see: the node budget was also consumed mid-round by scanning every candidate for every state, so the search reported `budget_exhausted` and a one-memory chain, which looked like a bound problem rather than a rule problem.
4. **It broke `conflicting`**, 0.667 → 0.000, because one memory covered every query term alone and a search for *a* sufficient set stops at the first one. Fixed by adding any candidate with **equal** query coverage that says something different — a rival answer rather than a near-miss, which covers strictly less. `conflicting` is now 0.667 on dev and 0.973 on test.

## 9. What this does not establish

1. **The registered bar was not met.** 33% against 40%, on both splits. Everything in §3 is secondary and does not change that.
2. **Three cases a family a split.** The chain families are 3 cases each; 0.667 is two of three.
3. **Not wired into `retrieve`.** `reconstruct` is a separate, opt-in method. A mechanism that misses its registered bar does not become a default, and chain reconstruction is a different operation from ranking — callers that want an ordering still want `retrieve`.
4. **Abstention is still unsolved.** The chain abstained on 1 of 9 dev cases where abstention is the only correct answer and 0 of 9 on test, and reports `complete` on `unanswerable` cases, because token coverage can be completed from memories that are not about the question. Same diagnosis as P2 §5.
5. **No downstream measurement.** Whether a model handed a reconstructed chain with its necessity annotations answers better is unmeasured. Given R6, it must not be assumed.
6. **My labels, my benchmark.** No external corpus has chains, provenance and gates together. SciFact cannot test this.
7. **One store, one process, ~495 memories.** Nothing here speaks to the operational envelope.

## 10. The honest summary

> **Not supported: 33% of the headroom against a registered 40%, the same on
> both splits.** `multi_hop_3` passes on its own and `multi_hop_4` scores
> zero, and because the registration pooled the two families the pooled number
> is the verdict. Prediction 2 called that outcome exactly.
>
> The mechanism nonetheless does the thing the question asked about. It
> reconstructs a three-hop chain by recovering a connector at **rank 462 of
> ~486** — a memory containing no query term at all, which no top-k arm could
> reach — marks it `dependency_required`, and justifies it by leave-one-out.
> That reason code had sat in the contract with no producer since R0.
>
> nDCG rises from 0.654 to 0.873 on dev and 0.549 to 0.743 on test with **no
> family regressing on either split**, and the search costs about **1.3× a
> lexical query**, which refutes my own prediction that cost would be the
> problem.
>
> `multi_hop_4` fails for a reason worth more than the pass would have been.
> The missing memory says *"add 0.35 bar as a salt-corrosion margin"*: it
> supplies no query term and links nothing, so a chain that is already
> complete and connected has no reason to want it. It **modifies** the answer.
> So the mechanism solves distributed evidence needing a connector and does
> not solve evidence that qualifies a conclusion — and `implied_by_default` in
> facet_v1, still 0.000 for every arm, is the same gap seen from another
> angle.
>
> Answering the original question directly: the fabric can now reconstruct a
> sufficient, currently valid chain when no single memory matches, and say why
> each intermediate is necessary — for three-hop evidence, two times in three,
> at 1.3× the cost of a ranked query. It cannot yet do it when a fourth memory
> changes the answer without mentioning the question.
