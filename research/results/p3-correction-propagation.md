# P3 — correction propagation: the product was right and my fixture was wrong

> ## Correction, 2026-10-12
>
> **An earlier version of this document concluded that "plain graph traversal
> beats the product" and that the product has "no retraction propagation in the
> retrieval path at all". Both claims were false, and they were false because
> of a defect in my fixture.**
>
> `quarantine(propagate=True)` contests the descendants of a retracted memory,
> and CONTESTED is excluded from `_eligible_ids` unless a caller asks for it. My
> fixture quarantined **inside the write loop**, so when a parent was retracted
> its children did not exist yet, there was nothing to propagate to, and the
> store was left in a state the product never produces: a retracted parent with
> active descendants. Every arm was then measured against that state.
>
> With the quarantine applied after the corpus is written — which is what any
> real caller does — the product withholds exactly the right memories, and the
> arm said to beat it adds nothing. The original numbers and conclusions are
> preserved in §6 so the overclaim stays visible rather than being edited away.
>
> This is the **fifth** time in this project that a measurement artifact has
> looked like a result about a mechanism, and the first time one produced a
> false negative result about shipped behaviour.

- **Registration:** [p3-correction-propagation.md](../prereg/p3-correction-propagation.md), written before any arm existed
- **Fixture:** [propagation_v1](../bench/propagation_v1/build.py) — 16 cases, four families, ~205 memories a case, dev 8 / test 8
- **Runs:** 2026-10-12, `python -m experiments.p3_propagation --split {dev,test}`
- **Deterministic:** no model calls; one retrieval a case, five rules over the same ranking

---

## 1. The numbers, corrected

**dev and test are identical on every cell**, which is worth more than either
split's decimals at eight cases a split.

| arm | stale cited / case | stale rate | unnecessary invalidation | sufficient |
|---|---|---|---|---|
| `no_propagation` (the product's default) | **0.500** | 0.250 | 0.000 | 1.000 |
| `blanket_invalidation` | 0.500 | 0.250 | **0.500** | **0.500** |
| `graph_traversal` | 0.500 | 0.250 | 0.000 | 1.000 |
| `source_root_grouping` | 0.500 | 0.250 | 0.000 | 1.000 |
| `oracle_propagation` | 0.000 | 0.000 | 0.000 | 1.000 |

`no_propagation` is a misleading name now that the fixture is correct: it means
*no additional rule at exposure time*, and the propagation has already happened
at quarantine time. It is the product as it ships.

## 2. What the product actually does, and it is the right thing

On `retracted_intermediate` — the case this fixture was built to supply, where a
**derived** memory is retracted while its root still carries standing evidence:

| memory | role | state after `quarantine(s1)` | exposed? |
|---|---|---|---|
| `r1` | the survey, standing | active | yes |
| `s1` | interim analysis, **retracted** | quarantined | no |
| `d1`, `d2` | restatements of `s1` | **contested** | no |
| `g1` | final analysis, drawn from `r1` | active | **yes** |

That is exactly correct, and it is the discrimination the whole fixture exists
to test. `g1` shares a source root with the retracted memory and does not
descend from it, so withholding by root identity loses the answer and following
edges keeps it. **The product follows edges**, at write time, through the
lineage graph whose `descendants()` docstring has always called it "the
retraction set".

Adding a traversal rule at exposure time, which is what next-step 1 proposed,
**would be redundant with this**. `graph_traversal` and the product's default
score identically on every metric in §1 because they are computing the same
thing twice.

## 3. Blanket invalidation is still wrong, and the fixture still catches it

The one arm the corrected run separates:

| arm | `retracted_intermediate` | `deep_chain` | `independent_reconfirmation` | `copied_document` |
|---|---|---|---|---|
| `blanket_invalidation` | **1.000** | **1.000** | 0.000 | 0.000 |
| every other arm | 0.000 | 0.000 | 0.000 | 0.000 |

(unnecessary invalidation — the share of cases where a standing, reachable
measurement was withheld)

Withholding everything that shares a root with a retracted memory discards the
standing conclusion in two families out of four, and sufficiency falls from
1.000 to **0.500**: it answers nothing in half the cases where an answer
existed. So the conservative rule is not the safe one, which is what the matched
structure was built to show, and that part of the design worked.

## 4. The whole remaining gap is one family, and it is real

Stale citations a case, by family:

| arm | `retracted_intermediate` | `deep_chain` | `independent_reconfirmation` | `copied_document` |
|---|---|---|---|---|
| every arm except the oracle | 0.000 | 0.000 | 0.000 | **2.000** |
| `oracle_propagation` | 0.000 | 0.000 | 0.000 | 0.000 |

**`copied_document` accounts for 100% of the residual 0.500.** A withdrawn
contractor bulletin was re-ingested months later under its own root, and
provenance honestly records two sources because there were two ingestions. Root
identity says the copy is independent. Parent edges say the copy is independent.
Both are right about the provenance and wrong about the evidence.

`_group_by_root` cannot see it and should not be expected to: its docstring says
it is "not content deduplication, deliberately", because two near-identical
memories can be independently observed and that is real corroboration. The cost
of that correct choice is this case.

**This is the only actionable finding in this experiment**, and it is a
different problem from the one the experiment was registered to study: it needs
content-level identity between an incoming memory and a withdrawn one, at
ingestion rather than at retrieval, and a policy decision about what to do when
they match. It is not a propagation rule.

## 5. The verdict, applied as registered

```
best baseline        B = 0.500   (every baseline ties)
ceiling              C = 0.000   (oracle, zero by construction)
headroom                 +0.500
threshold            B - 0.40 x headroom = 0.300
source_root_grouping     0.500        ->  NOT SUPPORTED (closed 0%)
```

Technically correct and substantively uninteresting. `source_root_grouping`
closes 0% of the headroom because **the headroom is entirely `copied_document`**
and no arm under test addresses it, the product's included. The registered
comparison was between propagation rules, and the propagation question turns out
to be already solved; what is left is an identity question nobody registered.

A cleaner reading of the same numbers: every rule that follows derivation edges
is at the floor this fixture can reach, one rule that ignores them pays 0.500
unnecessary invalidation for no gain, and the oracle's remaining 0.500 of
headroom is a problem of a different kind.

## 6. The original run, preserved

The numbers this document reported before the fixture was fixed, with the
quarantine applied inside the write loop:

| arm | stale cited / case | unnecessary invalidation | sufficient |
|---|---|---|---|
| `no_propagation` | 1.375 | 0.000 | 1.000 |
| `blanket_invalidation` | 0.500 | 0.500 | 0.500 |
| `graph_traversal` | 0.500 | 0.000 | 1.000 |
| `source_root_grouping` | 1.250 | 0.000 | 1.000 |
| `oracle_propagation` | 0.000 | 0.000 | 1.000 |

From which I concluded that graph traversal beat the product by 150% of the
headroom and that the retrieval path had no propagation. The 1.375 and the 1.250
are both artifacts: they are what the product does when its own retraction
propagation has been prevented from running.

**What that run got right**, and the corrected run confirms: blanket
invalidation's 0.500 unnecessary invalidation, the sufficiency halving, the
prediction that blanket and traversal coincide on stale evidence, and
`copied_document` defeating everything.

**What it got wrong**: the entire headline, and the recommendation that followed
from it.

Two earlier invalid runs are also on the record. The first used relevance_v2's
`shared_root` / `independent_support` pair and abandoned on both splits, because
that pair's standing source has a different root so blanket invalidation scored
the oracle — prediction 1 wrong, and the registration had named the exact
condition I then failed to build. The second wrote memories in order of
`len(parents)`, which is not a topological order, so a two-level chain lost its
edges and a correct arm looked wrong.

So: **three invalid runs before a valid one**, and all three failed the same
way. A fixture that does not reproduce the state the product actually puts
itself in measures the fixture.

## 7. Predictions, scored against the corrected run

| | prediction | outcome |
|---|---|---|
| 1 | blanket invalidation wins on stale, loses on unnecessary invalidation | **right** — 0.500 unnecessary invalidation, sufficiency halved to 0.500, concentrated in the two families with a retracted non-root. Wrong on the first fixture, which lacked that structure |
| 2 | blanket and traversal mostly coincide, every derived memory being one hop from the root | **right** — identical on stale citations in every family |
| 3 | source-root grouping will not reach the oracle | **right, for a different reason than I gave.** I predicted it would keep the best-ranked stale restatement; in fact no stale restatement is exposed at all, and the gap to the oracle is one family nothing addresses |
| 4 | the product will fail its own registered bar | **right on the arithmetic, wrong in substance.** It fails because the remaining headroom is not a propagation problem, not because its propagation is poor |

## 8. What this does not establish

1. **Sixteen cases, four to a family, eight to a split.** The two splits agreeing exactly is worth more than the decimals.
2. **No external check exists for this question**, here or, as far as I know, anywhere. These are my cases and my labels.
3. **One store, one process, no time.** The retraction is in place before the query. "A retraction arriving after a conclusion was acted on" is a different experiment and needs the event log.
4. **Nothing about weak withdrawal bases.** Every quarantine here uses `contradicted`. `WithdrawalBasis` distinguishes bases that undermine content from ones Phase A measured as harmful withdrawal rules, and whether propagation *should* depend on the basis is unmeasured — the product propagates regardless.
5. **No downstream measurement.** Whether a context free of stale evidence changes what a model answers is unmeasured, and given R6 it must not be assumed.

## 9. The honest summary

> **The product already propagates retraction correctly, and I published a
> result saying it does not.** Quarantining a memory contests its descendants,
> contested memories are withheld by default, and a sibling conclusion that
> shares the root but does not descend from the retracted memory is correctly
> kept. On the case this fixture was built to supply, that is exactly right.
>
> The reason I measured otherwise is that my fixture quarantined inside the
> write loop, before the children existed, leaving a retracted parent with
> active descendants — a state the product never produces. Every arm was
> measured against it, and the two arms that looked bad were the two that rely
> on the propagation having run.
>
> So **next-step 1 is withdrawn**: adding an ancestor-check at exposure time
> would duplicate work already done at write time, and `graph_traversal` scores
> identically to the product on every metric here because it computes the same
> thing twice.
>
> Blanket invalidation is still wrong, by 0.500 unnecessary invalidation and
> half its sufficiency, so the matched structure earned its place.
>
> And the one real gap is not a propagation rule at all: **a withdrawn document
> re-ingested under its own root** is 100% of the remaining headroom, defeats
> every arm including the product, and needs content identity at ingestion plus
> a policy for what to do on a match.
