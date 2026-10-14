# Pre-registration — X4: the governed store against a pooled one, when memory gets corrected

**Registered 2026-10-14, before the harness exists.**

## 1. The question the product lives on, and why it is still open

[Phase A](../results/phase-a-real-agent-benchmark.md) killed the headline
claim: a governed store scored **0.283** against a pooled vector store's
**0.583**. [PA′](../results/phase-a-prime-attribution.md) confirmed it with
better attribution — real leave-one-out beat naive blame and still lost to
withdrawing nothing, `fabric_loo` **0.483** against `shared_memory` **0.608**
— and the product's response was to **deprecate withdrawal-on-failure** and
warn against it in the CLI.

So every governed arm ever measured used the policy the product now tells you
not to use. Phase A's own §7.3 says so: *"a different governed policy might not
lose."* **The recommended configuration has never been measured against a
pooled store**, and it is the only claim that decides whether there is a
product here.

## 2. Why DepotWorld as it stands cannot answer it

DepotWorld generates a `poison_rate` of misleading diagnoses and makes truth
site-dependent, so a lesson honestly earned at one site is wrong at the next.
That is a world built for one question: **can you detect and remove a bad
memory?** The fabric lost it, twice, and the finding held.

It contains **no retractions, no re-ingested copies and no time-varying
truth** — none of the events the fabric's *supported* results respond to:

| supported result | the event it needs | present in DepotWorld |
|---|---|---|
| [PB2](../results/phase-b-federated-agents.md): acting on origin-retracted memory 17% → **0%** | an origin says its observation was wrong | **no** |
| [H4b](../SCORECARD.md): contested hypotheses, P(correct) 0.905 → **1.000** | two memories in declared conflict | no (implicit only) |
| [copy recognition](../results/p2b-copy-recognition.md): matches the oracle | a withdrawn document re-ingested | **no** |

An experiment with no corrections in it cannot test a product whose measured
strength is handling corrections. So this adds **one** event — an origin
retracting its own lesson — and nothing else.

### The objection, stated rather than waited for

*Adding the event the arm is good at is choosing a favourable world.* Four
things answer it, and if they do not convince, the result should not count:

1. **The rate is swept, not chosen.** 0.0, 0.5 and 1.0. No single value is load-bearing, and the **rate-0 point is the adversarial case**: it measures what governance costs when nothing is ever corrected. P2b set this precedent by measuring a plateau across a 16× range.
2. **The claim being tested is conditional and is stated that way.** Not "the fabric is better" but "**above correction rate X the fabric beats a pooled store, and below it does not**". The deliverable is a crossover point, which is a product statement an engineer can check against their own corpus.
3. **The correction reaches every arm identically**, as a new memory with the same text. The fabric's only extra is the provenance link; it gets no information a pooled store is denied, only a structure for using it.
4. **The strong baseline deletes.** §3's `shared_memory_delete` does what a competent engineer does with a vector store — matches the correction to the original and removes it. If the fabric only beats *ignoring corrections*, the claim is worthless, and that arm is what makes the comparison honest.

### Where the correction comes from

From the same process that produced the poison: DepotWorld already models an
engineer given a misleading diagnosis, and a retraction is that engineer later
discovering the truth. The world therefore knows which lessons are poisoned —
it created them — and a swept fraction of those are retracted.

**This is the handicap risk and it is named here.** The world is telling the
arms which memories were bad. It tells **all** of them, in the same words, so
the comparison is of mechanisms rather than of information. If a reader thinks
the provenance link is itself the handicap, then the claim under test reduces
to *"provenance lets you act on a correction precisely and a pooled store
cannot"* — which is exactly what
[PRIOR_ART.md](../PRIOR_ART.md) identifies as the one claim that survives the
novelty downgrade, and which is worth measuring on its own terms.

## 3. Arms

| arm | memory | corrections | swept |
|---|---|---|---|
| `no_memory` | none | — | no |
| `shared_memory` | pooled, ungoverned | arrive as documents, originals kept | yes |
| **`shared_memory_delete`** | pooled, ungoverned | **best-effort delete by matching the correction to the original** | yes |
| **`fabric_governed`** | the fabric, **no outcome-driven withdrawal** | `receive_retraction` on the provenance link; quarantine, descendants contested | yes |
| `oracle` | the correct lesson | — | no |

`fabric_governed` is the recommended configuration: provenance, bitemporal
validity, copy recognition and contested-on-conflict **on**; quarantine on
outcome evidence **off**, because PA and PA′ measured it losing and the
product now warns against it.

## 4. Primary metric and threshold

**Primary: task success**, the same metric Phase A and PA′ used, paired by
(seed, episode), 5 seeds × 24 evaluation episodes, bootstrap 95% CIs.

```
B = max(success) over {shared_memory, shared_memory_delete} at the same rate
C = oracle
support iff, at some swept rate, fabric_governed >= B + 0.40 * (C - B)
    AND the rate-0 point shows no loss worse than 0.05 against B
```

The second clause matters as much as the first. A mechanism that wins when
corrections are frequent and **hurts** when they are not is a liability a
reader must be told about, so the registration requires the adversarial point
to be near-neutral, not merely reported.

**8d check — are the baselines measured on the primary metric, at the primary
budget, in this run?** Yes, both of them, at every rate. Phase A's 0.583 and
PA′'s 0.608 are **not** carried over: `shared_memory` is re-measured here.

**8c check — is the primary trivially maximised by a baseline?** To be
reported at rate 0 before the comparison. PA′ puts `shared_memory` at 0.608
against an oracle the Phase A amendment could not quote, so the headroom is
real but unmeasured, and §5 of this registration makes measuring it a
precondition rather than a result.

**8b check** — no arm may exceed the oracle, checked every run by
`experiments/checks.py`.

**Abandonment clause.** If the measured `C − B` at any rate is `<= 0.05`, that
rate is abandoned rather than reinterpreted. If **every** rate is abandoned,
the experiment is, and the product claim is then unfalsifiable in this world
rather than false.

## 5. Secondary metrics, reported always, decisive for none

- **Correct lesson reached the prompt** — Phase A's own diagnostic, and the one that exposed blame-withdrawal cutting it from 60% to 18%.
- **Acted on a retracted memory** — PB2's metric, directly comparable: it measured 17% → 0% across a federation boundary, and this measures it inside one store against a pooled baseline that has the same text.
- **Wrongly removed**: memories `shared_memory_delete` deletes that were not the retracted one. The failure mode of matching without provenance, and the quantity the fabric's link is supposed to avoid.
- **Cost**: model calls, tokens, wall time, per arm and per rate.
- **`must_not_expose_rate`** — any non-zero value fails the run.

## 6. Predictions

1. **At rate 0, `fabric_governed` ties `shared_memory` within noise.** There is nothing to act on, so the arms differ only by overhead. A loss here would mean governance costs something real even when idle, which is a finding I would rather have than not.
2. **`fabric_governed` beats both pooled arms at rate 1.0.** Its store ends clean; the pooled arms keep a poisoned lesson competing with its own correction, and the poisoned lesson is the *more* similar text to the query because it names the fault code.
3. **`shared_memory_delete` beats `shared_memory`** and still loses to the fabric, because matching a correction to its target without provenance will delete the wrong memory sometimes — `wrongly_removed` is the metric that shows it.
4. **The crossover is near rate 0**, not halfway. One correction acted on precisely should pay for itself immediately, and if the crossover is high the mechanism needs a correction rate no real corpus has.
5. **This will not revive Phase A's claim.** Phase A asked whether governance beats pooling at *detecting* bad memory, and the answer is still no. X4 asks a narrower question and a pass means only what §7 says it means.

## 7. What a pass would not establish

Nothing about withdrawal-on-failure, which stays dead. Nothing about
DepotWorld without corrections — that is PA and PA′, and they stand. Nothing
about a corpus where corrections never arrive, which §4's second clause
measures rather than assumes. Nothing about H4b's contested hypotheses or copy
recognition, which this world still does not contain. And nothing about
whether a *team* does better, which is
[P3b](../results/p3b-agent-teams.md)'s question and already supported at 86%
of its headroom.
