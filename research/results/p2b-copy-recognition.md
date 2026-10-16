# Copy recognition — the last of P3's residual, closed

**The residual is zero on both splits, and the product now matches the oracle
exactly.** P3's remaining gap was one family: a withdrawn document re-ingested
under its own id, which every rule tested — the product's included — counted as
independent support.

| arm | stale cited / case | unnecessary invalidation | sufficient |
|---|---|---|---|
| **`no_propagation`** (the product as it ships) | **0.000** | **0.000** | **1.000** |
| `blanket_invalidation` | 0.000 | **0.500** | **0.500** |
| `graph_traversal` | 0.000 | 0.000 | 1.000 |
| `source_root_grouping` | 0.000 | 0.000 | 1.000 |
| `oracle_propagation` | 0.000 | 0.000 | 1.000 |

Dev and test identical. P3's registered comparison is now **abandoned by its
own clause** — `C − B = 0.000` — but for the opposite reason to last time: the
headroom is gone because the product reached the ceiling, not because the
fixture could not pose the question.

- **Mechanism:** `memory_fabric/duplicates.py`, wired into `remember`, `source_root` and `quarantine`. Schema 0.8.0
- **Fixture:** [propagation_v1](../bench/propagation_v1/build.py), `copied_document` family
- **Run:** 2026-10-12, `python -m experiments.p3_propagation --split {dev,test}`

---

## 1. The measurement chose the rule, against my first design

I started with Jaccard overlap above 0.75. Measured on real corpora, **that
rule is ordered the wrong way round**:

| pair | Jaccard | containment |
|---|---|---|
| a true re-ingestion (`propagation_v1`, 4 cases) | **0.722** | **1.000** |
| the worst of **152,640** near-miss pairs (`relevance_v2`) | **0.800** | 0.889 |
| a derived restatement of the original | 0.571 | 0.889 |

A copy *adds* a filing note, so Jaccard penalises it for growing. A near-miss
differs by one facet token out of nine, so Jaccard barely notices. **Any
Jaccard threshold that catches real copies catches near-misses first** — it
would have put "swap the tug-8 cable at the estuary site" and "at the harbour
site" under one source root and called it deduplication.

Containment separates, so the shipped rule is the strongest form of it with
nothing to tune: **the shorter memory's content terms are a subset of the
longer's, and the two are within a factor of two in length.** A near-miss can
never satisfy the subset condition, because the token it differs on is absent
from the other side.

That is a better outcome than the last threshold this project defended as "the
midpoint of a bimodal gap", whose tails turned out to overlap
([P2 §7](p2-context-sufficiency.md)). `duplicates.distribution()` reports both
measures for any corpus, and `tests/test_duplicates.py` pins the crossing so
the reason for the choice cannot be forgotten.

## 2. A copy is not a parent, and that was the load-bearing design decision

The obvious implementation records the copy as derived from the original. It is
wrong in a way that would have looked like it worked: `_group_by_root`
deliberately **spares** a memory that is derivation-related to something
already kept, because a premise and the conclusion drawn from it are not
copies. A copy recorded as a child would be exempted from the very grouping
that exists to collapse it.

So a copy gets its own relation, and three things follow:

- `source_root()` resolves through it, so copies share a grouping key and collapse.
- `_derivation_related()` does not, so they are not spared.
- `quarantine(propagate=True)` follows it, so withdrawing a document withdraws its re-ingestions.

## 3. Order-dependence, found three times in one change

Each of these let ingestion order decide the outcome, and each was found by a
test rather than by reading the code.

1. **A copy written after the original was withdrawn** came in contested, while one written before it stayed active — the same two memories and the same finding, opposite results. Fixed by having `quarantine` propagate along copy edges.
2. **The copy relation was walked in one direction.** The recorded edge runs newer → older, but "these are the same document" has no direction, and these corpora are shuffled: when the copy was stored *before* the original, a one-way walk found nothing. The relation is now an **undirected component**.
3. **`derive` did not check what it had just written.** Retraction reached conclusions drawn *before* a withdrawal and not after: deriving from an already-quarantined premise produced an `active` memory. This was **pre-existing**, not introduced here, and it is the same order-dependence one layer up. Fixed by running the recomputation `quarantine` already uses at write time — no second rule about what counts as support.

## 4. Independent knowledge still survives, which is the other half

Correction that destroys corroboration is the failure `blanket_invalidation`
commits, and it still does: **0.500 unnecessary invalidation and sufficiency
halved to 0.500**, on both splits. The matched-pair structure in
`propagation_v1` catches it, and the product does not commit it.

Specifically asserted in `tests/test_duplicates.py`:

- An independent measurement of the same quantity is untouched by the original's withdrawal and keeps its own source root.
- A conclusion resting on two **alternative** premises survives losing one.
- A derivation from a surviving premise, written *after* a withdrawal, arrives active.

The third matters because the `derive` fix could easily have over-withheld. It
does not: the verdict is about whether support survives, not about whether a
premise is unusual.

## 5. The cost, and one measured side-effect

**Cost:** a linear scan of held content per write. Switchable via
`recognise_copies=False` for a store that ingests in bulk and would rather run
the check as a batch job. Default **on**, because the alternative is measured
to be wrong rather than merely unmeasured.

**Side-effect, on a published number.** Copy recognition fires exactly once
across all of `relevance_v1`: in `temporal_drift-03`, on

> "The yard speed limit is 8 km/h." and
> "The yard speed limit is 8 km/h for all vehicles."

Those are two statements of one fact, so treating them as one source is
right — and it moves `store_all` on that benchmark from 0.8025 to **0.7991**, a
fall of 0.0034. A test asserting `store_all >= store_roots` broke, and I
removed that assertion rather than the mechanism: a 0.003 gap on 30 cases is
not an ordering, it has now broken twice for reasons that were each correct,
and what the milestone claims — that the mechanisms beat plain retrieval — is
still asserted.

Recording the direction plainly: **a published relevance_v1 figure moved
because the product got better.** The number in
[relevance-v1-ceiling.md](relevance-v1-ceiling.md) was measured at schema 0.7.0
and is correct for it.

## 6. What this does not establish

1. **Four cases.** The `copied_document` family is four cases, two a split. The mechanism's correctness rests more on `tests/test_duplicates.py` and on the 152,640-pair false-positive scan than on the benchmark number.
2. **Subset containment is strict, so copies will be missed.** *(2026-10-16: encoding noise is no longer one of the misses. Zero-width characters, soft hyphens, ligatures, full-width forms and non-ASCII hyphens are normalised before comparison, after four of seven such variants of a withdrawn document were found re-entering as active evidence. See `duplicates.canonical` and `tests/test_duplicates.py::EncodingNoise`.)* An OCR error, a re-typed document or a translation defeats it. The direction of error is deliberate: a missed copy leaves the status quo, while a false match puts unrelated memories under one root. Nothing here measures the miss rate on real-world re-ingestion.
3. **The oracle is 0.000 by construction** — it is handed the labelled stale set. The product matching it is the strongest available statement and is not proof of correctness in general.
4. **One store, one process.** Federation imports are already treated as copies of their origin by `kind_of`; whether content-level recognition should apply across stores is unmeasured and ROADMAP's P-gates still govern it.
5. **No downstream measurement.** Whether an agent given a context free of re-ingested withdrawals acts better is unmeasured.

## 7. The honest summary

> P3's entire residual was one case, and it is closed. A withdrawn document
> re-ingested under its own id is now recognised at **write** time, shares its
> original's source root, arrives `contested` rather than `active`, and is
> reached by the original's withdrawal whichever of the two was stored first.
> The product's default now matches the oracle on both splits: **0.000 stale
> citations, 0.000 unnecessary invalidation, 1.000 sufficiency.**
>
> The rule is subset containment, and **measurement chose it against my first
> design**: Jaccard scores a real copy at 0.722 and the worst of 152,640
> near-miss pairs at 0.800, so any Jaccard threshold catching copies catches
> near-misses first. The orders cross, and nothing but measuring it would have
> shown that.
>
> Three order-dependences were found and fixed inside one change, one of them
> pre-existing: `derive` had been producing `active` conclusions from
> already-withdrawn premises. Retraction now reaches conclusions drawn after a
> withdrawal as well as before.
>
> And a published figure moved. `relevance_v1`'s `store_all` falls 0.0034
> because the mechanism correctly collapses two statements of one speed limit.
> I removed the test that asserted an ordering across that 0.003 gap rather
> than the mechanism, and said so here.
