# Scorecard — every registered claim, and what the measurements did to it

Written 2026-10-10, after the simulated milestones (P1–P9), the live agent
phases (A, A′, B, C) and the integrity engineering phases (0–7). The companion
documents are [CRITICAL_REVIEW.md](CRITICAL_REVIEW.md), written before any code
existed, and [RETROSPECTIVE.md](RETROSPECTIVE.md), written when only the
simulations were in.

This file exists because the project's claims now come from three different
kinds of work and the honest summary of each kind is different. Mixing them was
starting to flatter the weakest.

---

## 1. Simulated hypotheses

| | claim | outcome |
|---|---|---|
| **H1** | Causal value of memories is estimable accurately and cheaply | ✅ **supported** — ρ=0.76 against naive 0.47, 8% overhead |
| **H2** | That accuracy improves what to forget | ❌ **killed** — loses to a smoothed success rate; the oracle showed naive already captured 93% of the available gain |
| **H3** | Selective federation beats sharing none or all | ⚠️ **inconclusive** — the registered +0.030 margin exceeded the +0.027 ceiling, so nothing could pass |
| **H4a** | Sparser networks are more often correct, but slower | ⚠️ **inconclusive** — the effect is an inverted U; the registered test point was the extreme |
| **H4b** | Preserving contested hypotheses helps | ✅ **supported** decisively — P(correct) 0.905 → 1.000, recovery 24% → 100%, at *lower* regret |
| **H5** | A small controller can replace LLM memory calls | ⛔ **unaskable** — the memory path makes zero LLM calls, so the denominator is zero |
| **P9** | Distribution is needed | ❌ **declined on measurement** — 25× the memories costs 1.7× the latency |

## 2. Live agent phases

Real models, real episodes, pre-registered thresholds, ≥5 seeds for A, A′ and B.

| | claim | outcome |
|---|---|---|
| **PA** | Governed memory beats an ungoverned vector store | ❌ **killed** — governed 0.283 against pooled 0.583; the target arm lost by 34 points |
| **PA′1** | Some withdrawal policy beats withdrawing nothing | ❌ **killed** as the registration predicted — best withdrawal arm 0.483 against 0.608 |
| **PA′2** | Leave-one-out attribution recovers most of naive blame's damage | ✅ **supported** — closed 71% of a 42.5-point gap, withdrawing 23 memories against blame's 87, at 2.55 model calls per episode |
| **PB1** | Selective sharing beats sharing all or none | ❌ **killed** — +0.008 [−0.042, +0.058], and the worst agent *fell* |
| **PB2** | Retraction propagation helps, under both sharing policies | ✅ **supported** — acting on origin-retracted memory 17% → **0%** under both, with no measurable change in task success |
| **PB3** | Reputation weighting beats uniform | ⚠️ **inconclusive** — not implemented; the data would have supported it |
| **PC** | A population learns what to propagate | 🔬 **exploratory only** — the PB1 gate did not pass, so no verdict is reported. Descriptively: the learner did not beat the fixed policy, and the outcome channel the design requires made the population **worse** (−0.042 [−0.081, −0.005]) rather than merely inert |

## 2a. The contextual relevance track (R0–R6)

Added after the live phases. The pattern repeats: the mechanism works, and the
held-out split declines to confirm it mattered.

| | claim | outcome |
|---|---|---|
| **R1** | A measurable oracle ceiling exists for selection | ✅ **measured** — +0.222 nDCG@3 on dev, refuting a ~5-point prediction carried over from Phase A. The benchmark was **invalid twice** before it measured anything, caught both times by a deliberately broken arm |
| **R4/R5** | Provenance, source roots and recorded time improve retrieval | ⚠️ **marginal** — +0.043 nDCG on dev, −0.013 on the expanded test split, and **no demonstrated downstream benefit** |
| **Embedder** | A trained embedder beats the hashing stub | ✅ **supported, and larger than every mechanism combined** — ~70% of dev headroom |
| **SciFact** | Retrieval quality on an external corpus with third-party labels | ✅ **run** — the hashing embedder scores **0.315 against lexical's 0.621**, where my own benchmark reported an 8% gap. The parameter-free lexical arm lands just under published BM25; a trained embedder fused with it reaches **0.726, above published BM25**, which is what makes `hybrid` the recommendation there and `lexical` the default |
| **R6** | Better retrieval produces better answers | 🔶 **dev inconclusive** (20% of a registered 40% bar) · ⛔ **test ABANDONED** — perfect selection worth +0.000, and the dev result **did not replicate** |

Two things survived R6's frozen split: a **~3× token saving** for no measured
quality loss, and **stuffing the context making a model less willing to say it
cannot tell**. Both are real and neither is a quality claim.

**The strongest conclusion of the whole track is about measurement.** An
external benchmark showed my own one flattering the shipped embedder by a
factor of four in the size of the gap; R6 showed a corpus a model can simply
read does not pose a retrieval problem at all. The product default changed from
`hybrid` to `lexical` on that evidence — the first time an external benchmark
has overruled an internal one here.

## 3. Integrity engineering (roadmap phases 0–7)

Not hypotheses. Deterministic guarantees, so the unit is "tested or not", and a
reproducible counterexample is a bug rather than a statistic.

| | at Phase 0 | now |
|---|---|---|
| Invariants implemented **and tested** | 4 | **14** |
| Invariants partial | 7 | 0 |
| Invariants with no route to a test | 3 | 0 |

965 unit/integration/property tests, 17 deterministic multi-store fault
scenarios, eleven testing layers. Full matrix in
[docs/INVARIANTS.md](../docs/INVARIANTS.md).

---

## What the three kinds of result add up to

**The performance thesis did not survive.** Of nine pre-registered performance
claims across simulation and live agents, two were supported, four were killed,
and three were inconclusive or unaskable. The two that survived — H1 (value is
estimable) and H4b/PA′2 (preserving disagreement, and attribution beating naive
blame) — are real, and neither of them is "governed memory makes an agent
better".

**One finding explains most of the failures.** Across Phase A and PA′, success
tracked a single quantity: whether a correct memory reached the prompt.
Conversion given one was 93–98% in *every* arm, and the coverage-to-success rank
correlation across arms was **+0.975**. Everything the memory layer does —
ranking, governance, lifecycle — can only move the outcome through that one
channel, and every withdrawal policy moved it downwards. Perfect selection over
the corpus was worth **+5 points**; the rest of the gap is corpus *coverage*,
which is memory construction and not something this project does.

**The integrity thesis did survive, and it is the one worth selling.** The
measurements that held are all about *correctness of the record* rather than
quality of the answer:

- A retraction follows a memory across a store boundary and drives acting-on-withdrawn-knowledge to zero (PB2) — and no adjacent paper in [PRIOR_ART.md](PRIOR_ART.md) carries provenance across a boundary at all. It now follows one past the *first* boundary too, to stores the origin has never heard of (Phase D), which PB2 did not test because its recipients never re-shared.
- Preserving contradiction converts confident error into flagged uncertainty (H4b, live multi-agent).
- A premise can be invalidated without destroying independently justified conclusions (Phase 4) — the question this project was ultimately asked.
- Content can be erased while the accountability survives (Phase 6).
- None of it costs anything measurable: 0.2 ms per episode and 1.16× tokens.

**And one metaphor did not survive either.** Phase C measured whether propagation
tracks a memory's value — the "memories selected for, inherited, going extinct"
picture from the founding document. It does not: the correlation is ~0 wherever
it is computable and undefined elsewhere, because both learners converged on
sharing with everyone. Whatever those populations do, it is not selection.

## Three things that went wrong in the method, and what fixed them

Worth recording because they recurred, and because each fix is now mechanical
rather than a matter of remembering.

**Mis-specified ceilings, three times.** H3 registered a margin larger than its
own ceiling. Phase A's oracle showed *one* memory where every other arm showed
three. Phase B's oracle shared memories correct at a lesson's own site to
recipients working several sites. Each looked unimpeachable until an arm beat
it. AGENTS.md principle 8a made the ceiling mandatory after the first and did not
prevent the next two; **principle 8b** now states the common cause — the oracle
must get no handicap the competing arms lack — and `stats.check_ceiling` runs it
automatically in every phase verdict, with a test that fails if a verdict stops
calling it.

**One bug class, twice, from the data model.** `derive` inherits its parent's
context including the federation origin record, so a locally derived memory looks
like an import. It made `descendants_of` quarantine a recipient's own conclusions
in Phase B prep, and then made `_imports_of` do the same in Phase 1 — caught by
the deterministic fault matrix. Anything asking "is this an import?" must check
the provenance *method*, not the origin key.

**Harness bugs outnumbered product bugs.** Three of four simulated hypotheses
were mis-operationalised, and in every case the fault was in the measurement:
H1's largest effect was a scoring bug, H3's `full` arm was penalised by a
round-trip the harness created, and PA′'s first analyser scored every withdrawal
rule as "100% justified" because it compared actions without comparing faults.
`tests/test_experiment_harnesses.py` now runs every arm offline against a
stubbed model and would have caught two of the four.

## What a reader should take from this

> The strongest claim this project has earned is **not** that agents remember
> better. It is that when shared knowledge changes or is withdrawn, the system
> can trace its origin, propagate the correction, enforce it at recipients,
> recompute what still stands, and show what has and has not been verified —
> at a cost too small to measure.
>
> The accuracy claim was tested properly and failed. That is recorded here
> rather than buried, because the measurements that killed it are the most
> reusable thing in the repository: **more memory is better, removal is
> expensive, and the binding constraint is coverage rather than selection.**
