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
| **Embedder** | A trained embedder beats the hashing stub | ⚠️ **corpus-dependent, and the generalisation was wrong.** SciFact: trained **0.701** against hashed **0.315**, the largest single effect measured. LongMemEval's short conversational turns: trained **0.811** against hashed **0.820**, and hashing hybrid (0.851) beats trained hybrid (0.836). A hashed bag of words is weak on a paraphrased abstract and strong on a turn sharing most of its words with the question. "Fix the embedder" was right from SciFact and is not a general conclusion ([result](results/longmemeval.md) §5a) |
| **SciFact** | Retrieval quality on an external corpus with third-party labels | ✅ **run** — the hashing embedder scores **0.315 against lexical's 0.621**, where my own benchmark reported an 8% gap. The parameter-free lexical arm lands just under published BM25; a trained embedder fused with it reaches **0.726, above published BM25**, which is what makes `hybrid` the recommendation there and `lexical` the default |
| **relevance_v2** | A benchmark where selection is a real problem | ✅ **built and falsified** — a no-signal arm scores **0.000** against **0.843** on v1. Headroom **+0.193 nDCG@5** (corrected from +0.232 after the quarantine-timing fix changed eligibility), concentrated in multi-hop chains; `direct` and `facet_trap` solved at 1.000, which makes the family built to be hardest a known defect. The R4/R5 mechanisms' nDCG gain is now **+0.000** — the third correction to land on them ([result](results/relevance-v2-ceiling.md)) |
| **Sufficiency** | Assembling against evidence requirements beats ordering by relevance | ⛔ **ABANDONED on both splits, on a metric flaw of mine.** `full_context` scores exactly the oracle's 0.800, so the headroom was +0.000 before any method existed: **sufficiency can always be bought with context**, and the primary metric had to be sufficiency at a fixed budget. At equal budget there is no reliable gain (tie on dev, +0.100 on test). The selector I built **does not work** — 0.000 on both multi-hop families, because a chain's middle hop has zero marginal query-term coverage. Abstention is still at zero and now has a diagnosis ([result](results/p2-context-sufficiency.md)) |
| **Correction propagation** | The product's dependency-aware behaviour beats simpler rules | ✅ **the product is already correct, and an earlier version of this row said the opposite.** Quarantining contests descendants, contested memories are withheld, and a sibling conclusion sharing the root is kept — so the product and `graph_traversal` score **identically on every metric**, and a traversal rule at exposure time would duplicate work done at write time. The earlier "−150% of headroom" was measured with the fixture quarantining before the children existed, so the propagation never ran. Blanket invalidation is still wrong: 0.500 unnecessary invalidation, sufficiency halved. **The whole remaining gap is one family** — a withdrawn document re-ingested under its own root, 100% of the residual, which needs content identity at ingestion rather than a propagation rule ([result](results/p3-correction-propagation.md)) |
| **Implied facets** | Near-misses are hard when the deciding facet is *implied*, not merely one token away | ✅ **measured, with a matched control.** `lexical` scores **1.000** on a stated control and **0.000** on all three implied families, both splits — the comparison `facet_trap` lacked, which is why its own 1.000 was uninterpretable. A trained embedder recovers part of one family and **refutes the prediction** that it would close the paraphrase family. `implied_by_default` is **0.000 for every arm at k=3** — but **corrected 2026-10-13**: at k=5 the rule ranks 4th and plain `lexical` reaches 1.000 sufficiency on dev, so "similarity cannot find it" is struck. The narrower claim survives: it ranks *below the distractors* ([result](results/facet-v1-implied.md) §11, [what the overreach cost](results/x1-extraction.md) §1) |
| **Evidence-chain reconstruction** | The fabric can rebuild a sufficient, currently valid chain when no single memory matches, and say why each intermediate is necessary | ❌ **NOT SUPPORTED: 33% of headroom against a registered 40%, both splits.** `multi_hop_3` passes alone (0.667) and `multi_hop_4` scores 0.000, and the registration pooled them. The mechanism does work: it recovers a connector at **rank 462 of ~486** carrying no query term, marks it `dependency_required` — a reason code that had no producer since R0 — and justifies it by leave-one-out. nDCG 0.654 → **0.873** dev and 0.549 → **0.743** test with **no family regressing on either split**, at **~1.3×** a lexical query. `multi_hop_4` fails because its missing memory *modifies* the answer without mentioning the question ([result](results/p1-evidence-chain-reconstruction.md)) |
| **Copy recognition** | A withdrawn document re-ingested under its own id must not count as independent support | ✅ **closed, product matches the oracle on both splits** — 0.000 stale citations, 0.000 unnecessary invalidation, 1.000 sufficiency, where this family was 100% of P3's residual. The rule is subset containment, chosen **against my first design by measurement**: Jaccard scores a real copy at 0.722 and the worst of 152,640 near-miss pairs at 0.800, so any Jaccard threshold catching copies catches near-misses first. Three order-dependences fixed inside the change, one pre-existing (`derive` produced active conclusions from already-withdrawn premises) ([result](results/p2b-copy-recognition.md)) |
| **Agent teams** | A team does better with Memory Fabric than with an ordinary shared store | ✅ **SUPPORTED, 86% of headroom against a registered 40%, and 85% at 100 agents.** `local` 0.060 · `shared` 0.780 · `shared_blanket` 0.720 · **`fabric` 0.970** · oracle 1.000. The clearest single difference: a plain shared store lets agents act on withdrawn knowledge in **18%** of tasks and the fabric in **none**. The naive fix is worse than it looks — `shared_blanket` eliminates stale actions and destroys the fact next door, which shows up only as a 0.250 re-measure rate and 2× the duplicate discoveries. **The agent is deterministic**, so this measures whether the right evidence arrives and not whether a model uses it ([result](results/p3b-agent-teams.md)) |
| **Operational envelope** | It holds up under concurrency, scale and failure | ✅ **passes every condition, and found a defect the correctness tests could not.** 500 appends from 50 processes with nothing lost and no gaps; per-write cost +22% for 5× the writers; zero cross-tenant leaks across 1,600 exposures; a log that reopens clean and writable after 16 of 50 writers are killed mid-write. Retrieval is flat to 1,000 memories and **linear beyond** — 19 ms at 10,000. And copy recognition cost **32 ms a write at 10,000 memories**, 168× the baseline, now **1.27 ms** via a bounded index checked against the exhaustive scan ([result](results/p4-envelope.md)) |
| **LongMemEval** | Retrieval quality on an external corpus that tests corrections, time and multi-hop | ✅ **run, and it found two product defects.** 500 questions, turn-level third-party labels, median 491 turns a history. `lexical` **0.753** turn recall · `hybrid` 0.693 · `chain` 0.460 (but **0.898 session recall** from a quarter of the context, at **68 ms** after a 2.9× speedup that left recall unchanged) · `vector` 0.456 · oracle 1.000. Passing a question's own date as `as_of` costs **19 points** on ordering questions, and no internal benchmark could show it because none ever placed evidence after the task's event time. **Knowledge-update is the easiest type (0.935)** and preference the hardest (0.528) ([result](results/longmemeval.md)) |
| **Abstention** | A retrieval-stage signal can tell answerable from unanswerable | ❌ **three signal families eliminated, one rejected on its operating point.** Term absence sits at the 0.067 base rate; chain coverage is 1.000 on every instance (d=0.00); three calibrations all made the score worse. Absolute match quality is right in **4 of 4 question types** and, **corrected 2026-10-13**, pools at **AUC 0.682** — not the 0.319 originally reported, which was the same number upside down (and replicates at 0.711 on the `s` split). It is rejected not for failing to discriminate but because a global threshold's best achievable F1 is **0.206** — abstaining on 23% of answerable questions to catch 53% of unanswerable ones. **Abstention is not a retrieval problem at any operating point worth having** ([result](results/abstention-signals.md) §7, [how it was found](results/x1-extraction.md) §5). Externally confirmed at 0–7%. On LongMemEval's 30 deliberately unanswerable questions every arm reports insufficiency between 0.000 and 0.067, and the only arm above zero pays 0.074 false insufficiency for it. The same number `relevance_v2`, P1 and P2 reported on my own fixtures, now replicated on data I did not write ([result](results/longmemeval.md)) |
| **Feature reranker** | Reranking makes fusion safe | ❌ **NOT SUPPORTED, 7.8% of headroom against 40%** — and the failure is informative. On four benchmarks reranking **converges both arms** to within a point of each other (LongMemEval 0.707/0.717, SciFact 0.559/0.551, relevance_v2 0.752/0.752), which is literally "fusion made safe", at a level *below* the better arm on three of four. The `tiebreak` mode that keeps the retriever's score and adds phrase order and proximity changes **nothing anywhere** — those features are worth exactly zero. A feature reranker cannot beat a length-normalised IDF retriever whose features are a superset of its own; reranking needs a model ([result](results/r2a-feature-reranker.md)) |
| **Cross-model portability** | A memory one model writes is as usable by another model as by its writer | ✅ **PORTABLE: diagonal interaction D = −0.002, 95% CI −0.016 to +0.012**, inside the registered ±0.05 equivalence margin, 120 paired units across `qwen2.5:3b`, `llama3.2:3b`, `gemma3:4b`; realised half-width 0.014, so the verdict was reachable. Who *wrote* a memory matters about 15× more than whether the reader wrote it (writer effects −0.021 to +0.015; llama weakest, as predicted). Conversion given a correct lesson in context is ~0.9 in every cell, diagonal included; the oracle's 4–14 point lead is retrieval (0.70 against 0.62–0.65). No cell above its reader's oracle, so the pilot's three excesses were noise. **Small local models and one-sentence lessons only**: the frontier↔small case is untested, and per-writer writing cost was not recorded ([result](results/x6-cross-model-portability.md)) |
| **Context rendering** | The governed context rendering costs task accuracy at equal retrieval | ✅ **SUPPORTED: 7.0 points, 95% CI +4.7 to +9.4**, 640 paired episodes, realised MDE 0.037 against a registered 0.05. **The security control is not why**: the prompt-injection preamble and delimiters alone cost 0.6, indistinguishable from zero, so the trade the registration warned about does not exist. Labels alone cost 3.4; labels plus the instruction to prefer well-evidenced memories cost 7.0, an interaction of about 3 points — in a cold store every label reads *unevaluated*, so the model is told to discount everything it is shown. Hedging was zero in all 2,560 generations: it got *less accurate*, not more careful. `render_compact()` drops the costly pair; the MCP server returns JSON without labels or that instruction, so it already avoids them (by argument: the JSON form was not an arm); the library's `render()` is unchanged so earlier results keep their meaning ([result](results/x5-context-rendering.md)) |
| **Governed vs pooled, under correction** | The recommended configuration (no outcome-driven withdrawal) beats a pooled vector store when memory gets corrected | ⛔ **ABANDONED at every correction rate on degenerate headroom.** The oracle — perfect filtering, same budget, same corrections — is only **0.650 against a plain vector store's 0.600** at rate 0, and 0.608 against 0.583 at rates 0.5 and 1.0. Headroom 0.050 / 0.025 / 0.025 against an abandonment threshold of 0.05, so no mechanism could have passed and `fabric_governed`'s 0.567-0.583 is not evidence either way. **The finding is the headroom: perfect memory selection is worth at most 5 points in DepotWorld**, which is stronger than PA′'s result — not "withdrawal loses" but "selection has nothing to win here". Per-seed baseline spread is 42 points, so five seeds cannot separate arms 2 points apart. Prediction held that governance costs nothing measurable when idle; `shared_memory_delete` was *identical* to `shared_memory` despite mis-deleting 4 of 14 corrections. **The claim is unfalsifiable in this world rather than false** ([result](results/x4-governed-vs-pooled.md)) |
| **Recalibration** | Refitting the vendor temperature on our own data rescues a typed confidence signal | ❌ **It cannot, and that is provable.** ECE 0.6631 → **0.0083** (better than the vendor's own reported refit) and the registered primary moves by **nothing**: AUC and best-F1 are invariant under any strictly monotone transform, identical to four decimals across every arm. Worse, the fit buys its calibration by **predicting the base rate** — mean p 0.94 on a 94%-answerable population, indistinguishable from a constant predictor, which ECE and Brier cannot see. A temperature alone cannot shift a distribution and is measured doing exactly that: mean 0.277 → 0.497 with fixed-threshold accuracy unmoved at 0.116. Lesson: **get the discrimination first**; calibration transforms a signal and a transformed weak signal is a well-presented weak signal ([result](results/x2b-recalibration.md)) |
| **Typed confidence** | A decision model returning calibrated probabilities supplies the abstention signal retrieval cannot | ❌ **NOT SUPPORTED: F1 0.1739 against a registered 0.5514, and it loses to a one-line lexical score** (AUC 0.6286 against 0.7113). Nearer the degenerate always-abstain arm (0.1132) than any real baseline. **The failure is calibration, not ignorance**: it calls 470 of 500 instances unanswerable, never exceeds P(answerable)=0.786 in 500 calls, and the class medians differ by 0.03 — above chance but far too compressed to threshold. ECE 0.6622, Brier 0.5037 against its own card's 0.481, accuracy 0.116 at p=0.5 where answering everything scores 0.94. All four registered predictions confirmed, including the one about confidence being higher on errors. Kev-0.8B zero-shot at its shipped temperature; 4B needs 8 GB against 3.1 GB free and is **not** covered by this result, as the registration said in advance ([result](results/x2-typed-confidence.md)) |
| **Scoped adjustments** | A record that adjusts a quantity at named sites is admitted the way a default is | ✅ **SUPPORTED on dev: 0.000 → 1.000, 3 of 3, against a registered 0.400**, critical recall 0.750 → 1.000, and the model's own extraction matches the fixture's exactly. Test abandoned in advance at a ceiling of 0.000. **It also explains X1's null result**: that 0.000 was a missing consumer, not the model — `_admit_defaults` admitted records with *exceptions* only, so a correctly extracted scoped adjustment was unreachable, and X1's own arm now scores 1.000. Found three defects in shipped code, including one that made the whole admission path **inert in any store with a candidate pool** — its unit test passed on a store holding one memory ([result](results/x3-scoped-adjustments.md)) |
| **Extraction at ingest** | A model can supply the declarations that a typed relation needs | ❌ **NOT SUPPORTED: 0.000 against a registered 0.400, 0% of headroom, and zero relations proposed out of three.** The model is not the reason — `gemma2` scores 19/19 on extraction quality and extracts **both** sides of the relation correctly (`modifies='axle-set figure'`, `predicate='tyre pressure'`). `infer_relations` joins them by string containment and no containment exists; the link is semantic. **Zero of seven models** form the edge. The matcher's unit test supplied both strings, matching on one of four combinations of {hand-written, measured} × {target, predicate} — the one where I chose both halves, so the circularity the registration thought it had escaped moved from the extractor to the step after it. Cost: 8,962 s for three cases to produce nothing ([result](results/x1-extraction.md)) |
| **Declared relations** | A typed non-derivation relation closes the modifier case | 🔶 **ceiling of 1.000 on dev, 0.000 on test.** With fixture-supplied `QUALIFIES` declarations, `chain` goes from 0.832 to **1.000 nDCG and 0.000 to 1.000 sufficiency** on `multi_hop_4` — the first arm ever sufficient there. On the frozen split it changes nothing, because the chain picks the wrong axle rule and a qualifier can only attach to a memory the chain found: the defect [P1 §4](results/p1-evidence-chain-reconstruction.md) disclosed now also blocks the mechanism that would close the family. **A ceiling, not a method** — nothing discovers these, deliberately, because a pattern fitted to my own generated phrasing would pass by construction ([result](results/relations-ceiling.md)) |
| **P9 cost** | Distribution was declined at 4.39 ms a retrieval | ✅ **re-measured at the right dimension, and the figure was 89× off.** P9 used the 256-dim hashing embedder. A trained-embedder retrieval costs **393 ms** — one model call to embed the query, so independent of corpus size — against lexical's 19 ms at 10,000 memories. Three measured points now, and P9's conclusion does not transfer to the embedder SciFact recommends ([result](results/longmemeval.md) §5a) |
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

## 2b. The safety track (plan Tasks 5–12, 2026-10-16)

All internal, hand-built benchmarks with a deterministic agent.

| | claim | outcome |
|---|---|---|
| **P5 H5a** | Fabric closes ≥ 50% of the invalid-evidence-action headroom over the best baseline | ❌ **not supported** as registered: the best M1 baseline (`local`) barely acts. Against acting baselines it closes 65% (exploratory) ([result](results/p5-poisonworld.md)) |
| **P5 H5b** | No task-success loss against shared memory (margin 0.02) | ✅ **supported**: 0.837 vs 0.625 |
| **P5 H5c** | Selective reassessment blocks less valid evidence than blanket mode, at equal safety | ✅ **supported**: 0.064 vs 0.133 |
| **P5 H5d** | No unauthorized action through the gate | ✅ **supported**: 0.000, after a disclosed harness ordering fix |
| **P9** | A read-only replay predicts which sources an action depended on | 📏 **measured**: precision 0.996, recall 1.000 against live withdrawal, after a 20% false-attribution bug was found ([result](results/p9-incidents.md)) |
| **P10** | Triggered auditing finds planted problems that periodic sampling misses | 📏 **measured**: 100% vs 32% ([result](results/p10-audit.md)) |
| **P12** | Many agent processes can share one store | ❌ **does not hold**: 214 → 4 ops/s from 1 to 100 SQLite agents ([result](results/p12-load.md)) |

## 2c. Real model, fixed budget, and chain links (plan Phase 3, 2026-10-16)

Every row below was pre-registered and scored once on cases no design
decision had seen.

| | claim | outcome |
|---|---|---|
| **D1a** | With a governed store in front of a real model, task success closes ≥ 40% of the headroom over an ungoverned store | ✅ **supported**: `sonnet`, 5 seeds. `naive` 0.492, **`fabric` 0.867**, oracle 1.000 (74% of headroom). The gain is the 9 of 24 cases where governance had already withdrawn the wrong value, so its **size is set by the registered case mix** ([result](results/d1-downstream.md)) |
| **D1b** | ...with harm reduced by ≥ 40% of its headroom, at no success loss | ✅ **supported**: harmful answers 0.508 → **0.133**. All of the remainder is **undetected poison (15/15 harmed in both arms)** plus one paraphrased injection |
| **D1c** | Governance does not block valid evidence | ✅ **supported**: valid blocked 0.000 (`haiku`, secondary: 0.020) |
| **D1 injections** | *(measured, not registered)* Do current models obey injected notes? | 📏 **almost never, even unscreened**: `sonnet` 1/20, `haiku` 0/20, when the instruction warns that evidence may be wrong. P5's obedient-agent injection figures are an upper bound, not a rate |
| **V2** | Claim checks catch contradicting updates to equipment codes written with separators | ✅ **supported** on a held-out world: detection 1.000, false alarms 0.000. The registered two-code risk (1.000) was fixed and confirmed on fresh seeds (0.000) ([result](results/v2-codes.md), [amendment](results/v2-codes-amend1.md)) |
| **D1-r** | D1 re-run on the current product, with an ungoverned baseline and one attacker per hazard | ✅ **`fabric` reaches the oracle**: 1.000 success, 0.000 harmful on fresh seeds 6–10, where D1's residual was undetected poison. Same templates as the world where the defect was found, so this confirms the fix end to end. It is not independent evidence ([result](results/d1r-downstream.md)) |
| **A1 / A1-h** | A separate answerability verdict improves abstention over instructing the model | ⛔ **ABANDONED, no headroom**: instructed `sonnet` 1.000 and `haiku` 0.993 equal the oracle on near-miss unanswerable questions. Without the instruction both models answer every unanswerable question wrongly; the structural verdict gives zero wrong answers but false abstention on paraphrases; a `haiku` judge refuses 72% of answerable questions ([result](results/a1-abstention.md), [haiku](results/a1h-abstention.md)) |
| **C2 / C2-r** | A counterfactual finds exactly the decisions that depended on a corrected memory | ❌ **C2a not supported** at first: it missed dependent decisions, traced to a **product defect** (`min_independent_sources` not enforced), fixed. ✅ **C2-r** on fresh seeds: recall 1.000, review precision 1.000 against the graph's 0.356 ([result](results/c2-dependence.md), [re-run](results/c2r-dependence.md)) |
| **C3** | A model the user chooses can hold free-text contradictions the built-in rules miss, without holding honest writes | ✅ **SUPPORTED**, opt-in: haiku and sonnet each held **1.00** of contradictions (built-in rules 0.00) with false holds **0.067 / 0.058**, all five seeds; ~$0.0004 a checked write on haiku. Templated world, labels mine ([result](results/c3-free-text.md)) |
| **L1 / L1′** | Over a long task with corrections, Memory Fabric removes at least half the harmful actions a vector store takes, without a degenerate loss of completion | ⛔ **L1 ABANDONED (8c)**: with canonical-phrased queries both vector-store baselines already scored 0 harmful actions, equal to the oracle. ✅ **L1′** (amendment, fresh seeds 6–10, job-phrased queries): **0.0 harmful actions per 1,000** against 80.5 for the best baseline, recovery 0 steps against 130, completion 0.894 against 0.873; without lineage 0.0 and 0.946. Simulation, not models ([L1](results/l1-long-running.md), [L1′](results/l1p-long-running.md)) |
| **P2b** | At a fixed 400-token budget, a path-finding assembler closes ≥ 40% of the sufficiency headroom | ✅ **supported narrowly**: 0.600 → **0.700** against an oracle of 0.800, threshold 0.680. The whole gain is **one family** (`multi_hop_3`), and `multi_hop_4` stays at 0. `random@400` scores 0.047, which refutes the registration's own prediction ([result](results/p2b-budget.md)) |
| **P1b** | Discriminating links for covering candidates | ❌ **not supported**: the switch changed nothing reachable ([result](results/p1b-links.md)) |
| **P1c/P1d** | Prefer the chain whose weakest link is strongest | ❌ **P1c not supported** when pooled over both chain families (0.250 → 0.458, threshold 0.550). ✅ **P1d supported** when registered afterwards for three hops only, on a fresh holdout: 0.417 → 0.917. P1d was registered after P1c's result, so it is the weaker kind of evidence. Now on by default ([P1c](results/p1c-strength.md), [P1d](results/p1d-strength-mh3.md)) |

## 2d. Release-track research (docs/WORKPLAN.md, 2026-10-18)

| | claim | outcome |
|---|---|---|
| **G4 / S3** | A governed, federated store closes ≥ 40% of the safe-success headroom over plain shared stores, with real models, across poisoning, injection, correction and an offline site | ❌ **NOT SUPPORTED on qwen2.5:3b: 35%** (fabric 0.721 against `shared_delete_all` 0.571, oracle 0.996; +0.150, CI +0.115 to +0.183; MDE 0.051); 36% re-run after F11–F13. ⚠️ **gemma3:4b UNDERPOWERED**, and its oracle is beaten on three kinds, so its ceiling is wrong (8b). **Failures**: paraphrased injection 0.05; before detection, fabric ranked the poison first in 35/40 questions (0.10 against a plain store's 0.30); the offline site serves poison until reconciliation ([result](results/g4-labnet.md)) |
| **G4b** | Surfacing contradictions stops an undetected poison being used first (≥ 40% of headroom, held-out seeds) | ❌ **NOT SUPPORTED at 40%**, but **both arms beat the shipped store significantly**: flag +0.081 (CI +0.038 to +0.131), incumbent +0.119 (CI +0.056 to +0.181); acting on an undetected poison 63% → 51–55%. Clean and corrected facts unaffected. Incumbent still beats flag when the attack is written first, so the gain is the presentation, not the write order. Recommended as the default presentation (flag mode), pending the owner's decision ([result](results/g4b-contradiction-surfacing.md)) |
| **S1** | Version-scoped correction closes ≥ 40% of the correct-state headroom over the best baseline, converges in every seed, and invalidates no more than retraction alone | ⛔ **ABANDONED on degenerate headroom**: `delete_and_reshare` already reaches 0.9545 against a ceiling of 0.9568 (headroom 0.0023). The 8c check was not run before registering. `versioned` matches it exactly, converges 20/20 and invalidates nothing unnecessarily; `naive_overwrite` converges 3/20, `retraction_only` 0/20. Building the harness found **F12** (echo imports around a cycle left an origin serving its own superseded versions), now fixed ([result](results/s1-correction-sim.md)) |
| **S2** | Exposure-based independence closes ≥ 40% of the corroboration-decision headroom over the best baseline (laundered copies are not second sources) | ❌ **NOT SUPPORTED: 28% of headroom**, +0.102 (CI +0.045 to +0.160) over a tuned near-duplicate store, 420 clusters, realised MDE 0.086. **The only arm that catches laundering**: perfect on both laundering families (in one store and across stores), where every baseline scores at most 0.23. False corroboration falls 0.83 → 0.28. **The price is structural**: an exposed author who observed for themselves scores 0, so blocked independent evidence rises 0.02 → 0.25. Off-store collusion is invisible to every arm. All four predictions held; not wired in ([result](results/s2-launder-sim.md)) |
| **S6** | A fenced action never takes effect after its evidence's withdrawal committed; overruns are all reported; no writer gives up | ✅ **SUPPORTED, all three**: 0 violations in 1,229 fenced effects (5 seeds, real processes, withdrawals aimed at the window), where `authorize` + act violated in **28.4%** and a second check before acting in 10.4%. All 30 overrun violations were reported by `unfenced_changes()`. Zero writer failures. **The cost is on writers**: they waited up to 1.9 s (2.4 s under overruns), and throughput fell 12–16%, more than predicted, because SQLite's busy handler is not fair. S14 is now controlled for tools run through `execute` ([result](results/s6-action-fence.md)) |
| **S5** | A correction receipt reveals nothing about the recipient (≤ 0.05 advantage) and binds at audit | 🔶 **S5b SUPPORTED, S5a NOT SUPPORTED as registered.** Soundness was 150/150 on every check (honest passes; forged, never-applied and borrowed receipts fail; re-activation reported). On leakage the receipt scored 0.113 on copies held, through a SHA-256 byte, against a 0.05 bar. **That bar fails a receipt of pure random bytes 25.6% of the time**: it was set inside the statistic's own noise, the floor-side version of 8a. Replication gave 0.053, through a different field. **Found a real leak in today's protocol (F13, fixed)**: acknowledgements gave the origin the recipient's activity (R² 0.994), copy count and onward peers ([result](results/s5-correction-receipts.md)) |
| **S4** | A recipient learns whom to trust, where, from its own verified outcomes (≥ 40% of headroom; less harmful reliance than import-using baselines) | ✅ **SUPPORTED, on the bar**: 40.04% (0.636 against a bar of 0.6359; +0.130, CI +0.117 to +0.144, which straddles the bar; MDE 0.020). Harmful reliance 0.23, against 0.49–0.52. The grain is the finding: per (sender, context) it works, while the store's per-memory contrastive estimator stays at the default at about 10 visits per cell. The world was generated at that grain. Not wired in ([result](results/s4-recipient-trust.md)) |
| **M1** | Stating the session's objective first makes agents use the relevant memory (≥ 40% of headroom over plain retrieval) | ✅ **SUPPORTED on both models**: qwen2.5:3b 58% registered (stale compile cache, disclosed) and **70% corrected**; **gemma3:4b 74%** (0.327 → 0.707). Use of an irrelevant memory falls from about 49% to 16–19%. Compiled filters help less (+0.18 / +0.29 over plain) and lose to the prompt alone, because model compilation drops the plant-wide alternative; hand-written rules reach the ceiling. The largest gain on real models in this repository ([result](results/m1-memory-objective.md)) |
| **M2** | Reflective rulebooks: gated self-revision from verified outcomes closes ≥ 40% of the headroom, without more regressions | ❌ **M2a NOT SUPPORTED: 26%** (0.664 against Reflexion's 0.545, ceiling 1.000). ✅ **M2b SUPPORTED**: 1 test regression, against 3 for ungated rewriting and 8 for Reflexion. Ungated self-rewriting ends *below* no rulebook (0.445 against 0.500); the gate adopted 6/20 proposals and plateaus after round 2. Experimental, opt-in ([result](results/m2-reflective-rulebooks.md)) |
| **T1** | Trust that learns how fast to forget, per context, decides better than fixed forgetting or Zep-style invalidation | ❌ **NOT SUPPORTED: 1.5% of headroom** (+0.004, CI −0.005 to +0.012, MDE 0.012). Detection perfect: no forgetting for the stable context, a 20-episode half-life for the drifting one, on 10/10 seeds. Adapting removes the fixed-rate trade (it keeps the stable context and takes most of the drifting gain) but adds nothing beyond it; the 0.24 gap to the oracle is exploration, not staleness ([result](results/t1-learned-staleness.md)) |
| **T2** | Once a source is caught being wrong, re-reading its other notes improves later decisions | ❌ **NOT SUPPORTED, all three arms** (held-out, 460 units): flag −0.007 (ignored by the model), withhold −0.111 (the attacker's undetected notes 0.05 → 0.50, but the honest technician's valid notes 0.92 → 0.12), hostile-only −0.002. The hostile signal (the injection screen) never leaves its origin store: a federation gap, not a temporal one ([result](results/t2-hindsight.md)) |
| **V1** | Checking a claim against the store's own knowledge catches plain false claims (no injection wording) at a low false-alarm rate | ✅ **SUPPORTED** (held-out, 10 seeds, model-free): corrected values restated, far-out-of-range values and contradictions of established facts all caught (1.000); 0 of 450 honest writes flagged; plausible claims from new sources held provisional. Undetectable by design: plausible claims about never-seen things ([result](results/v1-claim-validation.md)) |
| **M1b** | Objective V2 with evidence-aware ranking and safety constraints beats the best objective baseline | ❌ **accuracy NOT SUPPORTED** (0.585 vs 0.729 prompt-only); ✅ **safety SUPPORTED**: unsafe action 0 vs 0.867, safety-fact omission 0 vs 1.00 for compiled filters ([result](results/m1b-objective-quality.md)) |
| **C1** | Governed session compaction gives a later session a handoff that stays correct after a correction, at no recall cost | ✅ **SUPPORTED** on safety and non-inferiority (held-out, 10 seeds, model-free): stale value shown 0 vs 1.00 for an ungoverned summary; coverage 0.956 vs 0.944 at 80 words. **No recall gain** (8c: session-filtered notes are near the ceiling); worse at 40 words ([result](results/c1-compaction.md)) |
| **T2b** | A signed cross-store notice that a source was caught injecting lets the stores holding its memories withhold them | ✅ **SUPPORTED** (held-out seeds 15–19, 690 units): safe success 0.732 → **0.949**, 81% of the headroom against a 40% bar; collateral 0.803 → 0.914; the attacker's undetected notes withheld 0.19 → 1.00. Depends on the attacker tripping a screen once under one identity, stated in advance ([result](results/t2b-source-notice.md)) |

## 3. Integrity engineering (roadmap phases 0–7)

Not hypotheses. Deterministic guarantees, so the unit is "tested or not", and a
reproducible counterexample is a bug rather than a statistic.

| | at Phase 0 | now |
|---|---|---|
| Invariants implemented **and tested** | 4 | **14** |
| Invariants partial | 7 | 0 |
| Invariants with no route to a test | 3 | 0 |

Unit, integration and property tests (current count in [VALIDATION.md](../docs/VALIDATION.md#current-baseline)), 17 deterministic multi-store fault
scenarios, fourteen testing layers. Full matrix in
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
