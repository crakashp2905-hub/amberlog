# Declared relations — a ceiling of 1.000 on dev, and nothing on test

**Given perfect declarations, a typed `QUALIFIES` relation solves `multi_hop_4`
completely on dev — nDCG 1.000, critical recall 1.000, sufficiency 1.000 — and
changes nothing at all on the frozen split.** The reason it does nothing there
is one already on the record: the chain picks the wrong axle rule, and a
qualifier can only attach to a memory the chain actually found.

**This is a ceiling, not a method.** The declarations come from the fixture.
Nothing in the product discovers them, and §4 is about why I did not build a
discoverer.

- **Mechanism:** `memory-fabric/relations.py`, `Memory Fabric.relate()`, `follow_relations=` on `retrieve` and `reconstruct`
- **Harness:** `experiments/relations_ceiling.py`
- **Run:** 2026-10-12, `relevance_v2` `multi_hop_4`, 3 cases a split, k=5
- **Off by default**, and not registered as a method — a ceiling does not ship

---

## 1. The numbers

**dev**

| arm | nDCG@5 | critical recall | sufficient | returned |
|---|---|---|---|---|
| `retrieve` | 0.519 | 0.500 | 0.000 | 5.00 |
| `retrieve` + declared relations | 0.596 | 0.583 | 0.000 | 5.00 |
| `chain` | 0.832 | 0.750 | 0.000 | 3.00 |
| **`chain` + declared relations** | **1.000** | **1.000** | **1.000** | 4.00 |

**test (frozen)**

| arm | nDCG@5 | critical recall | sufficient | returned |
|---|---|---|---|---|
| `retrieve` | 0.502 | 0.500 | 0.000 | 5.00 |
| `retrieve` + declared relations | 0.659 | 0.750 | 0.000 | 5.00 |
| `chain` | 0.520 | 0.417 | 0.000 | 3.00 |
| `chain` + declared relations | 0.520 | 0.417 | 0.000 | 3.00 |

## 2. Why it is exactly the missing piece, and exactly conditional

`multi_hop_4`'s unreachable memory is *"at the depot-12 site, add 0.35 bar to
the axle-set figure as a salt-corrosion margin"*. [P1](p1-evidence-chain-reconstruction.md)
diagnosed why no mechanism could find it:

- it supplies **no query term**, so coverage-greedy selection has nothing to gain from it;
- it links nothing the chain needs, so it is **not a bridge** either;
- and the chain is already complete and connected without it, so the search has no reason to keep looking.

It *modifies* the answer. A declared relation is the only thing in this project
that can express that, and with it the chain goes from 3 of 4 critical memories
to 4 of 4 and from 0.000 sufficiency to **1.000** — the first time any arm has
been sufficient on `multi_hop_4`.

**And it is conditional on the chain being right.** The relation is followed
*from* a selected memory *to* its qualifier, so it can only fire if the memory
being qualified is in the chain. On the frozen split the chain reaches only 1.67
of 4 critical memories because it bridges through the generic tokens *axle* and
*set* and selects the rule for the **wrong axle type** — a failure
[P1 §4 disclosed](p1-evidence-chain-reconstruction.md) after inspecting a
frozen-split case, and deliberately did not fix, because the fix would have been
tuned on that split.

So the dev/test disagreement here is not a new mystery. It is the same known
defect, and it now has a cost attached: **it also blocks the mechanism that
would otherwise close the family.** Fixing it needs a split that is not already
spent.

`retrieve` + relations gains on both splits (+0.077 dev, +0.157 nDCG test) and
reaches sufficiency on neither, because plain retrieval misses the chain hops
whatever the relation adds.

## 3. What `EXCEPTS` cannot do, stated rather than omitted

The other 0.000 family, `implied_by_default`, is **not covered**, and the
relation vocabulary is the reason.

> **Note added 2026-10-13.** "0.000" here is k=3. At k=5 a plain lexical
> baseline solves this family on dev and not on test
> ([facet-v1-implied.md §11](facet-v1-implied.md#11-correction-the-k3-boundary-and-what-it-cost)),
> so it is no longer usable as evidence of a limit of similarity. The point
> below — that `EXCEPTS` relates memories and the exception names sites — is
> unaffected, because it is about the vocabulary rather than the scores.

Its answer is *"all yard vehicles run 3.9 bar in winter, except at the harbour
and quarry sites"*. The exception names **sites**, not memories, and `EXCEPTS`
as defined relates one memory to another — there are no memories for the
excepted sites to relate it to. Deciding that a default applies to a query
means checking a rule's scope against the **query's entities**, which is
entity-scoped applicability and a different mechanism.

So the relation vocabulary covers the modifier case and not the default case,
and `RelationKind.EXCEPTS` currently has no measurement behind it at all. It is
declared because the roadmap names it; by this project's own rule that is not a
reason to keep it, and it should either get a mechanism or go.

## 4. Why there is no extractor, and why that is a measurement decision

Something has to declare that A qualifies B — a caller, or an extraction step
at ingest. I did not build the latter, and the reason is not scheduling.

The two families this targets are text **this project's own generators wrote**.
A pattern matching *"add N bar to the … figure"* or *"except at the … and …
sites"* would pass by construction and measure its own fit to my phrasing,
which is the `facet_trap` mistake in a new place: a mechanism that scores well
on a fixture built to its shape has been told the answer slowly.

So the first measurement is deliberately the ceiling, which is what principle
8a asks for before a threshold is registered: **1.000 on dev says the extractor
is worth building**, and nothing in this document says anything about whether
one can be built. An honest test needs text nobody here wrote — LongMemEval has
knowledge-update and temporal-reasoning questions, though whether it contains
identifiable defaults-with-exceptions is itself unmeasured.

## 5. Design notes worth keeping

**A relation is not a parent edge**, for the same reason a copy is not:
`_group_by_root` spares anything derivation-related to a memory already kept,
because a premise and its conclusion are not duplicates. A qualification
recorded as a parent would inherit that exemption, and the margin memory was
never *derived from* the pressure rule — it modifies it. Separate relation,
separate index, separate retrieval step.

**Only `QUALIFIES` is followed on selection.** `EXCEPTS` deliberately is not: an
exception is a reason *not* to use a rule, so pulling it in alongside would add
a memory arguing against the one next to it. `PRECEDES` is an ordering fact
rather than a completeness requirement.

**A pulled-in qualifier is marked necessary by declaration**, not by
leave-one-out. The chain's own necessity test asks whether coverage or
connectedness breaks without a step, and a qualifier breaks neither — which is
precisely why the search could not find it. Letting the leave-one-out rule judge
it would mark the one memory that changes the answer as optional.

## 6. What this does not establish

1. **Three cases a split.** The dev result is three cases going from 0.000 to 1.000 sufficiency. That is a ceiling worth chasing and not an effect size.
2. **No extractor exists**, so nothing here is a product capability beyond "a caller may declare this".
3. **One relation kind measured.** `EXCEPTS` and `PRECEDES` have no measurement at all, and §3 says `EXCEPTS` cannot address the family it was named for.
4. **No no-regression sweep.** `follow_relations` is off by default and no declarations exist outside this harness, so there is nothing to regress yet — but that also means the cost of following relations at scale is unmeasured.
5. **It compounds with a known defect rather than fixing it.** The frozen-split result is zero because of the wrong-axle failure, so the real-world value depends on a chain correctness problem this measurement does not touch.
