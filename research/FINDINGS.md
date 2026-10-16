# Research findings, in narrative form

The long-form account of what was measured and what it changed, moved here
from the README on 2026-10-16 so the README can serve as a project overview.
The text is unchanged from that date: it is a snapshot, and where a later
result supersedes a sentence here, the result file and
[SCORECARD.md](SCORECARD.md) are authoritative.

Links below are relative to the repository root in the original; they have
been rewritten to work from this directory.

## The accuracy claim failed, and that is the useful part

Five live phases, pre-registered thresholds, real models, ≥5 seeds for three of
them. Full detail in [research/SCORECARD.md](SCORECARD.md).

| | claim | outcome |
|---|---|---|
| **A** | Governed memory beats an ungoverned vector store | ❌ **killed** — 0.283 against 0.583 |
| **A′1** | Some withdrawal policy beats withdrawing nothing | ❌ **killed**, as registered in advance |
| **A′2** | Leave-one-out attribution recovers most of naive blame's damage | ✅ supported — 71% of the gap, at 2.55 model calls per episode |
| **B1** | Selective sharing beats sharing all or none | ❌ **killed** — +0.008 [−0.042, +0.058], and the worst agent *fell* |
| **B2** | Retraction propagation works, under both policies | ✅ **supported** — 17% → 0% |
| **C** | A population learns what to propagate | 🔬 exploratory; the outcome channel made it **worse**, −0.042 [−0.081, −0.005] |

**One measurement explains nearly all of it.** Success tracked a single
quantity: whether a correct memory reached the prompt. Conversion given one was
**93–98% in every arm**, and coverage-to-success correlated at **+0.975** across
arms. Everything the memory layer does — ranking, governance, lifecycle — can
only move the outcome through that one channel, and **every withdrawal policy
moved it downwards**. Perfect selection over the corpus was worth **+5 points**;
the rest of the gap is corpus *coverage*, which is memory construction and not
something this project does.

Three consequences, all acted on in the product rather than left in a paper:

1. **Do not withdraw memories because they were in context when something failed.** Of naive blame's 87 withdrawals, **57 were memories about a completely different fault**. `quarantine` now records *why*, and the attention list flags a withdrawal made on weak evidence as the finding — pointing an operator at releasing it rather than at the memory.
2. **Do not filter at share time.** A memory wrong at one of a recipient's contexts is right at another, and which dominates is not knowable before the episode. Perfect sharing scored five points *below* sharing everything indiscriminately.
3. **The value gate the default firewall ships is not a safety feature here.** It reduced federation to 42 imports of a possible 630, scored identically to isolation, and left the weakest agent worse than if it had never joined.

## What simulation established

**H1 supported** — a propensity-corrected estimator recovers true memory value
at ρ=0.76 against a naive baseline's 0.47, on 8% exploration overhead
([result](results/h1-causal-credit.md)). The confound is real and
severe: a memory with *exactly zero* true effect scores 0.84 under naive
usage-success and ≈0.00 under the corrected estimator.

**H2 killed, H3 and H4a inconclusive, H5 unaskable, P9 declined on
measurement.** The estimator's accuracy did not transfer to retention (H2),
and three further live attempts to use it — exposure, withdrawal, sharing —
each lost to a cheap baseline. **The product default is `naive_usage` for that
reason, and value-ranked exposure is not recommended on current evidence.**

H3's threshold exceeded its own ceiling and H4a tested the wrong point on an
inverted-U curve; both are recorded as method failures rather than as results.
That happened three times in this project, which is why
[AGENTS.md](../AGENTS.md) principle 8b now requires the oracle to carry no handicap
the competing arms lack, and why `stats.check_ceiling` runs that check
automatically in every phase verdict.

## Novelty, checked rather than claimed

[research/PRIOR_ART.md](PRIOR_ART.md) verified four papers that each
remove one claim: learned value scoring, lifecycle management, causal
attribution for clearance, and attributed memory construction are **not novel**.

What survives, and is now measured rather than asserted: **provenance and
retraction that cross a store boundary.** None of the four carries provenance
across a boundary at all, so none can retract across one. Plus contradiction
preservation, and the negative results themselves.

## Phase A is killed, and it is the most important result here

Everything above is simulation or a single-mechanism live check. Put on a real
task against a real baseline — 8 arms, 5 seeds, 960 verified decisions through a
live model — **this project's governance made the agent worse.**

| arm | success |
|---|---|
| no memory | 0.075 |
| pooled vector store | 0.558 |
| pooled + the fabric's prompt framing, no governance | **0.583** |
| **governed (contested marking + quarantine on contradiction)** | **0.283** |
| **governed + causal value selection** | **0.242** |
| oracle | 0.633 |

Not through cost — retrieval was 1.7 ms and the token gate passed. The mechanism
is sharper than that. Every arm turned a correct memory into a correct answer
**95%** of the time and failed **95%** of the time without one; the model was
never the variable. Governance cut how often a correct memory arrived from 60% of
episodes to 18%, because **withdrawing the memories blamed for a failure withdrew
the correct ones.** Six actions span six fault codes, so the memory that asserted
what the agent wrongly said was usually a *correct* memory about a different
fault — quarantined for agreeing with a mistake it had nothing to do with.

Principle 1 of [AGENTS.md](../AGENTS.md) says value is not relevance. Phase A adds:
**agreement is not causation.** [Result](results/phase-a-real-agent-benchmark.md)

**PA′ then asked what to do instead, and the answer is nothing.** Real
counterfactual attribution — re-asking without each memory — withdraws a quarter
as much as naive blame and recovers 71% of the lost accuracy, at 2.55 model calls
per episode, and **still loses to withdrawing nothing**. Two thirds of what naive
blame destroyed was about a completely different fault. Perfect selection over
the corpus was worth only +5 points, so the binding constraint is whether a
correct memory *exists* yet — a coverage problem, not a governance one.
[Result](results/phase-a-prime-attribution.md)

The product consequence is immediate and is not a research note:
quarantine-on-contradiction should not be recommended, and the attention list
that invites an operator to withdraw memories needs to say what the evidence
actually is.

| Phase | Question | State |
|---|---|---|
| **A** | Governed memory against an ungoverned vector store | ❌ **Killed** — [result](results/phase-a-real-agent-benchmark.md) · [prereg](prereg/phase-a-real-agent-benchmark.md) |
| **A′** | If not blame, then what? | ❌ **PA′1 killed**, ✅ **PA′2 supported** — [result](results/phase-a-prime-attribution.md) · [prereg](prereg/phase-a-prime-attribution.md) |
| **B** | What should cross a federation boundary, and must retraction follow it | ❌ **PB1 killed** · ✅ **PB2 supported** — [result](results/phase-b-federated-agents.md) · [prereg](prereg/phase-b-federated-agents.md) |
| **C** | Can a population learn what should propagate | 🔬 **Exploratory, no verdict** — gate not passed — [result](results/phase-c-memory-ecology.md) · [prereg](prereg/phase-c-memory-ecology.md) |

Two decisions made before the run are why the result is usable. The decisive
baseline was not a strawman — a pooled store that deletes what was in context at
a failure, one line of code that reacts to outcomes, because governance beating a
*naive* store would establish nothing and
[H2](results/h2-credit-driven-retention.md) is the precedent for the
cheap baseline winning. And an ablation arm was added when the pilot exposed a
confound: the fabric arms rendered memories in a provenance-and-caveats framing
while the vector arms got plain text. That arm won. Without it, a prompt's effect
would have been scored as governance.

## What is being built next

A **contextual relevance** layer, sequenced so the thing that could falsify it
comes first: the contract and its invariants ([docs/RELEVANCE_SPEC.md](../docs/RELEVANCE_SPEC.md),
done), then the benchmark with a measured oracle ceiling, then a ranker — not
the other way round.

The benchmark exists and the ceiling is measured: **+0.222 nDCG@3** over the
best simple baseline, with critical-memory omission going from 28.6% to zero
([result](results/relevance-v1-ceiling.md)). That **contradicts** the
~5-point prediction registered beforehand, and the prediction is left on record
rather than edited away.

**An external benchmark changed the product.** SciFact — 300 queries, 5,183
abstracts, labels written by someone else — put the shipped hashing embedder at
**0.315 nDCG@10 against plain lexical retrieval's 0.621**, where my own
benchmark had reported an 8% gap rather than a 2× one
([result](results/scifact-external.md)). The default retrieval mode is
now `lexical`. The parameter-free lexical arm landing just under published BM25
is the most reassuring number here — it says the harness behaves as a third
party would expect.

Swap in a **trained** embedder on the same 300 queries and the picture inverts:
`real_vector` scores **0.701** and fusing it with lexical scores **0.726**,
*above* published BM25. So fusion is not good or bad in itself — **do not fuse
a weak arm into a strong one**. Both halves of the recommendation are now
measured: `lexical` by default, `hybrid` once `embedder=` is a real model.

**Whether retrieval changes answers is still unresolved, and the honest
version is less flattering than the first draft of this paragraph.** R6 ran a
real model over the benchmark. On dev, selected context beat handing the model
the whole corpus at a third of the tokens — which the pre-registration
predicted would *not* happen. **On the frozen split that reversed**, and
perfect selection was worth **+0.000**, so the registered abandonment clause
fired: a corpus a model can simply read does not pose a retrieval problem.

Two effects survived both splits: a **~3× token saving** for no measured
quality loss, and — the one nobody asked for — **stuffing the context makes the
model less willing to say it cannot tell**. The mechanisms' dev-only +0.076
correctness gain did not replicate, so **they have no demonstrated downstream
benefit** ([result](results/r6-downstream.md)).

The biggest lever turned out to be the embedder, and it is bigger than
everything else here: a trained model (`nomic-embed-text`) closes **~70% of the
dev headroom** and matches bounded premise promotion with no lineage machinery
([result](results/relevance-v1-real-embedder.md)). On the frozen split
the gain is +0.045, and the two splits disagree about whether to fuse it with
lexical retrieval — so **sample size is now the binding constraint**, ahead of
any mechanism and ahead of a ranker. The hashing default stays, because
zero-dependency is a commitment; switching is one line.

Both of R1's findings have been acted on and re-measured. Hybrid retrieval took the product
arm from 0.485 to 0.658 nDCG on the frozen split, with critical-memory omission
going from 40% to zero; wiring in **source roots, premise promotion and
bitemporal validity** added a further +0.074 there and +0.043 on dev, closing
about 17% of the measured headroom. Lexical retrieval alone still has the better
nDCG on the frozen split (0.804), and the product arm is still not the best arm
— what it buys is not missing the decisive memory.

Two findings matter more than the headroom. **The shipping retrieval path is
the weakest non-broken arm** — beaten by plain IDF-weighted token overlap by up
to 32 points, because it is a hashing embedder rather than a trained model; fix
that before building a ranker. And three of the five families with the largest
gaps (indirect evidence, copied evidence, temporal drift) are answerable with
**provenance, source roots and recorded time — all of which the store already
has and retrieval does not use.**

The benchmark was invalid twice before it measured anything: corpus order
leaked the answer, then `k` was as large as the corpus. The deliberately broken
arm caught both, which is the argument for building the thing that can fail
before the thing that can succeed.

Three rules the contract enforces in code, each from a measured mistake:
**irrelevant never means deleted** (Phase A's withdrawal policy cost 12.5
points), **a relevance score never overrides authorisation or retraction**, and
**a missing signal is never scored zero**.

## Central question

> Can we estimate the causal value of agent memories accurately and cheaply enough that retaining, retrieving and sharing memories by that value beats strong heuristic baselines?

If not, everything downstream (federation, ecology, the learned controller) has no foundation — but the governance layer still stands on its own, which is why it was built first. See the kill criteria in [ROADMAP.md](../ROADMAP.md).
