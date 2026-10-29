# What Amberlog should take from Hindsight

An assessment of [vectorize-io/hindsight](https://github.com/vectorize-io/hindsight)
against this project's **measured** gaps, 2026-10-12.

Everything attributed to Hindsight here comes from its public README and is
**vendor description, not verified behaviour** — I have not run it. Its
benchmark claims are its own, with independent reproduction asserted for
LongMemEval; I have not checked that either. What follows is about what the
design points at, not about whose numbers are better.

The ranking is by what this project has measured itself failing at, not by
what is novel.

---

## 1. The one thing already acted on: LongMemEval

**This is the most valuable item by a wide margin, and it is a benchmark rather
than a technique.**

`research/SCORECARD.md` has said for several milestones that SciFact is this
project's only external check, and that **SciFact has no provenance, no
lifecycle, no retraction and no tenants** — so every claim about the things
Amberlog is actually *for* has rested on benchmarks I wrote and labelled
myself. Hindsight evaluates on
[LongMemEval](https://arxiv.org/abs/2410.10813) (Wu et al., ICLR 2025), which
turns out to test four of them directly:

| LongMemEval ability | instances | measured here only internally, until now |
|---|---|---|
| knowledge updates | 78 | P3, P2b — my fixtures |
| temporal reasoning | 133 | `superseded_rev` — mine |
| multi-session reasoning | 133 | `multi_hop_3/4` — mine |
| abstention | 30 | **0.000 on every arm, and no external check at all** |

500 questions, turn-level gold evidence, MIT-licensed code. Integrated as
`experiments/longmemeval_bench.py`; results in
[longmemeval.md](results/longmemeval.md).

It paid for itself immediately, and §2 is what it found.

**One thing it is not.** Hindsight reports end-to-end QA accuracy with a model
reading the retrieved context. The runs here are **retrieval-stage only** —
turn and session recall — so the two sets of numbers are not comparable and
nothing here is a claim about relative quality.

## 2. What the benchmark found in the first hour

**A shipped mechanism, correct on its own terms, is mis-specified for a whole
class of question — and no internal benchmark could have shown it.**

`retrieve(as_of=T)` means *state at a point*: `valid_from <= T < valid_to`. Its
docstring recommended that a caller who knows its task's time should pass it,
and `experiments/relevance_bench._as_of` does so automatically.

On LongMemEval's temporal-reasoning questions — *"which did I do first, fixing
the fence or buying the cows?"* — that is wrong, and measurably:

Reproducible from the committed harness with `--temporal`, by question type:

| `--temporal` | knowledge-update | multi-session | temporal-reasoning |
|---|---|---|---|
| `as_of` (the question's date) | 0.947 | 0.742 | **0.644** |
| `until` (history through it) | 0.947 | 0.742 | **0.644** |
| `none` (no filtering) | **0.968** | 0.742 | **0.834** |

**19 points on temporal reasoning**, because 20.4% of the turns in those
instances are dated *after* the question is asked, and an ordering question
needs the whole history rather than a snapshot of it. `applies_at` is right;
the call was wrong. Knowledge-update loses 2 points to the same cause.

**And `until` is indistinguishable from `as_of` here, which matters for how
much this benchmark is allowed to endorse.** The two differ only when a claim
has been superseded — when `valid_to` is set — and LongMemEval's turns have no
end dates, so supersession never fires and both modes exclude exactly the
turns dated after the question. The measured finding is therefore narrow and
specific: **passing the question's date as a temporal bound at all costs 19
points on ordering questions.** It does not validate the range mode. `until`
rests on `tests/test_bitemporal.py` and on the argument in §2's table, not on
this measurement, and saying otherwise would be borrowing a number for a claim
it does not support.

Every internal benchmark agreed with the old advice, for a reason worth
naming: **none of them ever placed evidence after the task's event time.**
`relevance_v2` sets one event time for every case. That is exactly the blind
spot an external benchmark exists to find.

Fixed, and the fix is a capability rather than a caveat — `retrieve` and
`reconstruct` now take `until` as well as `as_of`, so the three temporal
questions are distinct and the caller picks:

| question | call | behaviour |
|---|---|---|
| what is true now, or was true at T | `as_of=T` | supersession applies |
| what did we know through T | `until=T` | keeps claims since superseded |
| when did things happen | neither | the whole history |

`until` is the shape of Hindsight's **time-range filtering** — one of its four
recall strategies is a range rather than a point — and the measurement above is
what sent me looking at the temporal path, not what justified the range itself.

`tests/test_bitemporal.py` pins all three modes, and **that file did not exist
before**: schema 0.7.0 added bitemporal validity and nothing asserted what the
modes mean. The behaviour was covered incidentally, by a version-skew test and
by `relevance_v1`'s `temporal_drift` family, which is how a mis-specified call
survived in a docstring that recommended it.

## 3. Worth adopting, ranked by the gap each closes

### 3a. A reranking stage — closes a gap this project worked around

Hindsight's recall runs four strategies in parallel and merges them with
**reciprocal-rank fusion followed by a cross-encoder reranker**. Amberlog
does the fusion and stops.

The absence shows up as a rule I derived and measured five times: **do not fuse
a weak arm into a strong one.** SciFact: fusing a hashed vector arm into
lexical costs 6.3 points; with a trained embedder it gains 2.5. `facet_v1`:
fusion drags a strong vector arm down to a weak lexical one. That rule is a
*workaround for having no reranker* — RRF gives every arm equal rank votes and
cannot tell a good candidate from a well-ranked bad one, so the only defence is
choosing which arms to admit.

A reranker scores candidates jointly against the query and does not care how
strong the arm that proposed them was. It would dissolve the problem rather
than manage it.

**Measured, and the cheap version is structurally incapable**
([result](results/r2a-feature-reranker.md)). A feature-based reranker — IDF
coverage, phrase order, proximity, no model — was registered and run. It
**NOT SUPPORTED** at 7.8% of headroom against 40%, and the failure is the
informative part:

- On four benchmarks it **converges both arms to within a point** of each other (LongMemEval 0.707/0.717, SciFact 0.559/0.551, relevance_v2 0.752/0.752). That is literally fusion made safe — which arm fed the pool stops mattering — at a level **below the better arm on three of four**. It removes a risk by capping the upside.
- The mode that keeps the retriever's score and adds only the features it lacks changes **nothing anywhere**. Phrase order and proximity are worth exactly zero.

The reason generalises: `LexicalIndex` already scores with **length-normalised
IDF**, so a surface-feature reranker's features are a subset plus two that
never fire. Replacing substitutes a weaker scorer; tie-breaking substitutes
nothing. **Reranking needs information the retriever lacks**, and for text that
means a cross-encoder — so Hindsight's version is the right one and this is now
an argument for it rather than an assumption.

The convergence is also a measurement about fusion itself: the fused pool
*contains* what the better arm's pool contains, or reranking could not reach
the better arm's neighbourhood. Fusion's damage is entirely in the **ordering**,
which is a sharper statement than five previous measurements produced.

### 3b. Typed graph edges — entity, temporal, causal

Hindsight's `retain` extracts entities and relationships and its recall
traverses entity, temporal and causal links.

Amberlog's `chains.py` bridges on **shared non-query terms**, and I can
say precisely where that heuristic succeeds and fails because it is measured:
it recovered a connector at **rank 462 of ~486** that no top-k arm could reach
([p1](results/p1-evidence-chain-reconstruction.md)), and it fails on
`multi_hop_4` because the missing memory *modifies* the answer without sharing
a term, and on `implied_by_default` — **0.000 for every arm including a trained
embedder** — because a default rule with an exception list is not *similar* to
the query at all.

A typed edge is a declared relation instead of an inferred token overlap.
`qualifies`, `excepts`, `precedes` are exactly the relations those two failures
need. The project already has the machinery: a lineage graph with typed
justification edges (`REQUIRED`, `ALTERNATIVE`), and `_derivation_related`
walks it. What is missing is edges that are not derivation.

**Measured as a ceiling, and it is 1.000**
([result](results/relations-ceiling.md)). `QUALIFIES`, `EXCEPTS` and
`PRECEDES` are implemented, with `relate()` and `follow_relations=`. Given
declarations supplied by the fixture, a `QUALIFIES` edge takes `multi_hop_4`
from 0.832 to **1.000 nDCG** and 0.000 to **1.000 sufficiency** — the first arm
ever sufficient on that family, and exactly the memory P1 showed to be
unreachable by coverage or connectedness.

Three things qualify that:

- **It does nothing on the frozen split**, because the chain picks the wrong axle rule there and a qualifier can only attach to a memory the chain found. The defect [P1 §4](results/p1-evidence-chain-reconstruction.md) disclosed now also blocks the mechanism that would close the family.
- **`EXCEPTS` cannot address `implied_by_default`**, the other 0.000 family. Its exceptions name *sites*, not memories, so a memory-to-memory relation has nothing to attach to. That needs entity-scoped applicability, which is not built.
- **No extractor exists, deliberately.** The target text is this project's own generators' output, so a pattern matching *"add N bar to the … figure"* would pass by construction — the `facet_trap` mistake in a new place. The ceiling says the extractor is worth building; nothing measured says one can be.

**The cost to watch** when it is built: extraction means an LLM call per write,
this project's rule is that those go through one wrapper logging model, prompt
hash, tokens and cost, and R6 is a standing warning that a model in the loop
can make a result less reproducible rather than better.

### 3c. Materialised standing answers

Hindsight's **mental models** are standing answers to recurring questions,
rewritten in the background, and reading one is "a database read — no
retrieval, no LLM call".

This lands directly on a measured wall. [p4-envelope.md](results/p4-envelope.md)
found retrieval **flat to 1,000 memories and linear beyond** — 19 ms at
10,000, so ~190 ms at 100,000. A materialised answer sidesteps the knee
entirely for repeated questions.

And it is a natural fit rather than a bolt-on: this store is **event-sourced
with rebuildable projections**, so a standing answer is another projection —
derivable from the log, invalidated by the events that change its inputs,
rebuildable from scratch. That is a stronger position than a cache.

### 3d. Consolidation into evidence-backed observations

Hindsight consolidates related facts into deduplicated **observations**, each
keeping supporting quotes and a **proof count**, refined rather than
overwritten when new evidence arrives.

Amberlog is arguably **ahead on the hard half** of this: `_group_by_root`,
source-root resolution and copy recognition exist precisely so that copies do
not count as corroboration, and [p2b](results/p2b-copy-recognition.md) measured
that closed to zero against an oracle, including the case where a withdrawn
document is re-ingested under its own id.

What it does not have is **consolidation**. Memories stay atomic; nothing
merges several into one belief with a retained provenance set. The hypothesis
sets and the justification graph are the right substrate, and a proof count is
close to `independent_count`, which `JustificationGraph.recompute` already
computes and nothing surfaces.

### 3e. A wider sensitive-data pattern set

Hindsight's **Memory Defense** claims 45 patterns for secrets and PII at
ingest. `SECURITY.md` records this project's detector as pattern-based with
**no adversarial testing** and a known miss rate on novel formats. Comparing
coverage is a cheap, bounded improvement with a clear test: patterns the
current screen misses.

## 4. Where Amberlog is ahead, from the same README

Stated to keep the comparison honest, and with the caveat that **absence from a
README is not absence from a product**.

- **Retraction.** The README documents no retraction, deletion or invalidation path. This is Amberlog's core, and [P3](results/p3-correction-propagation.md) and [P2b](results/p2b-copy-recognition.md) measure it against an oracle: withdrawing a memory contests its descendants, spares independently-supported conclusions, and reaches re-ingested copies in either storage order. Hindsight's "refined rather than overwritten" is about *strengthening* a belief; nothing described handles a source being **withdrawn as wrong**.
- **The event log as the source of truth**, with every projection rebuildable from it, append-only triggers and a hash chain with external checkpoints.
- **Propensity logging.** Every exposure decision records the probability it was made with, so causal credit can be estimated later. Nothing in the README suggests an equivalent.
- **Authorisation as a boundary**, with tenant filtering applied *before* the index is consulted, signed expiring credentials and per-credential revocation. Hindsight's banks are isolated stores; isolation by partition is a different guarantee from authorisation within a shared store, and [P4](results/p4-envelope.md) measures zero cross-tenant leaks across 1,600 exposures.
- **Crypto-erasure** with a key-provider seam, so destroying a key is real erasure.
- **Pre-registered experiments** with oracle ceilings, thresholds as a share of measured headroom, and abandonment clauses that have fired four times. Hindsight publishes a leaderboard; this project publishes the runs that failed.

## 5. What I would not take

- **Disposition traits** — banks carrying "skepticism" or "empathy" that shape reflection. There is no measurement here that calls for it, and principle 9 says infrastructure follows measured need.
- **`reflect` as a retrieval path.** An LLM reasoning over memories to answer questions needing more than lookup is appealing and is exactly what [R6](results/r6-downstream.md) warns about: its dev finding that better retrieval improves answers **did not replicate**, and a model in the loop made the result less reproducible. If `reflect` arrives here it needs its own pre-registration, not an argument from plausibility.
- **Breadth of integrations.** 60+ integrations and an LLM wrapper are a product-adoption strategy, not a memory-system property.

## 6. The order, and where it got to

1. **LongMemEval** — ✅ done on both splits. It found `as_of` mis-specified within the hour, gave the first controlled demonstration of the fusion rule, and confirmed the abstention gap externally.
2. **A feature-based reranker** — ✅ run, **NOT SUPPORTED**, and §3a is the result. The cheap version is structurally incapable, which makes a cross-encoder the next thing rather than a guess.
3. **Typed non-derivation edges** — 🔶 implemented and measured as a **ceiling of 1.000** on dev. §3b has what it does not cover and why no extractor was built.
4. **Standing answers as a projection** — not started, and still premature: it is a cache, and a cache without a measured hit rate is a liability. There is no repeated-question workload here to measure one.
5. **Pattern-set comparison** for the sensitive-data screen — not started. Small, bounded, and the current screen is on record as untested adversarially. This is the cheapest remaining item.

Consolidation into observations stays last, because the part that matters most —
copies not counting as corroboration — is measured closed
([p2b](results/p2b-copy-recognition.md)), and the rest is presentation.

**What the two measured attempts have in common** is worth stating, because it
is the most useful thing taken from reading Hindsight. Both of this project's
0.000 families, and both failed mechanisms, come back to the same boundary:
similarity and surface features cannot express what a memory *entails*, what it
*modifies*, or whether it *answers a question at all*. A reranker without a
model has no information the retriever lacks; relations have the information and
nothing to extract them; abstention has no retrieval-stage signal at all
([result](results/abstention-signals.md), four families eliminated). Hindsight's
`retain` — an LLM extracting entities, relations and facts at ingest — is the
one component that addresses all three, and it is the component this project
has most carefully avoided building. R6 is the reason, and R6 is about the
*reading* stage rather than the *writing* stage, which is a distinction worth
testing rather than assuming.
