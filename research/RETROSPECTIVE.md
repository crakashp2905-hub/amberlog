# Retrospective — what nine milestones actually established

Written 2026-10-07, after P1–P9 closed. The companion to [CRITICAL_REVIEW.md](CRITICAL_REVIEW.md), which was written before any code existed. This is what the evidence says now.

---

## Scorecard

| | claim | outcome |
|---|---|---|
| H1 | Causal value of memories can be estimated accurately and cheaply | ✅ **supported** — ρ=0.76 vs naive 0.47, 8% overhead |
| H2 | That accuracy improves what to forget | ❌ **killed** — loses to a smoothed success rate |
| H3 | Selective federation beats sharing none or all | ⚠️ **inconclusive** — threshold exceeded the ceiling |
| H4a | Sparser networks are more often correct, but slower | ⚠️ **inconclusive** — effect is real, test point was wrong |
| H4b | Preserving contested hypotheses helps | ✅ **supported**, decisively |
| H5 | A small controller can replace LLM memory calls | ⛔ **unaskable** — there are no such calls |
| P9 | Distribution is needed | ❌ **declined** — nothing approaches the limit |

Two supported, one killed, two inconclusive, one unaskable, one declined. **The original document proposed roughly thirty mechanisms; two of them have survived contact with measurement.**

## The four things actually worth keeping

**1. Value is not relevance — and it is estimable.** H1 is the project's load-bearing result. A memory with *exactly zero* true effect, retrieved mostly on easy tasks, scores 0.84 under naive usage-success and ≈0.00 under a propensity-corrected estimator. The confound is real, it is severe, and it is fixable. Everything else in the design assumed this; H1 is the only reason that assumption survived.

**2. Keep contested beliefs alive and re-test them.** H4b is the strongest single intervention measured anywhere in this project: P(correct) 0.905 → 1.000, recovery 24% → 100%, at *half* the regret and *faster* consensus. Strictly better on every axis. It is also the cheapest thing here — a fifth of a round spent re-testing buys escape from an error that otherwise never corrects.

**3. Provenance, retraction and governance.** Never tested as a hypothesis because they are not performance claims. A poisoned memory can be traced to its source and retracted with every descendant marked contested; secrets never reach a screen; an import cannot be pushed past rules the recipient controls. These shipped and work.

**4. The shape of the federation curve.** Sharing everything costs 2.6 points when contexts do not overlap; sharing nothing costs 2.7 when they fully do. Knowing your agents' overlap is worth more than any cleverness measured on top of it.

## What the measurements killed

**Credit-driven retention.** H2's oracle showed the ceiling was 0.485 against random's 0.352, and a smoothed success rate already captured 93% of it. Harm is *directly visible* in raw outcomes — a bad memory that gets followed produces failures — so debiasing buys little at the one threshold a budget decision asks about. Rank correlation was the wrong proxy.

**The learned System-1 controller.** Zero LLM calls in the memory path, 0.26 ms/episode. The expensive operations the controller would have replaced — consolidation, contradiction detection, skill synthesis — were never built, so there was nothing to distill. CRITICAL_REVIEW §6 predicted this exactly.

**The entire distributed layer.** 25× more memories costs 1.7× latency. Both cheap scaling levers (a real embedder with an ANN index, Postgres) remain untouched because nothing has needed them.

## The methodological finding, which may matter more than the results

**Three of four hypotheses were mis-operationalised, and in every case a diagnostic arm caught it rather than the write-up narrating past it.**

| | the error | what caught it |
|---|---|---|
| H2 | Budget set outside the regime where the mechanism binds | Oracle arm (93% already captured) |
| H3 | Threshold of +0.030 against a ceiling of +0.027 — unpassable by any method | Oracle arm, added post-hoc |
| H4a | Assumed monotonicity; the effect is an inverted U, and I tested the extreme | The full topology sweep |

The hypotheses were approximately right. The *measurement points* were chosen badly, and consistently so: each time I picked a parameter by intuition without first establishing what the achievable range was.

This produced the one durable process change, now AGENTS.md principle 8a: **every comparison carries an oracle arm, and thresholds are expressed as a share of headroom, not as absolute margins.** A threshold set without a ceiling is not a threshold. H3 is the clean demonstration — a bar no method could clear, written in good faith, caught only because an oracle was added afterwards.

A second pattern worth naming: **the largest single effect in the whole project was a bug in a measurement, not a method.** In H1 the scoring harness treated "no evidence of its own" as "declined to answer", discarding exactly the predictions amortization exists to produce. Before the fix the primary method scored 0.133; after, 0.604. Any result where the primary method appears to do nothing deserves that suspicion first.

## What a successor should do differently

1. **Build the measurement before the mechanism.** Every milestone that produced a real finding did so because an oracle or a control was present. Every milestone that produced a muddle did so because one was missing.
2. **Three controls are worth more than three mechanisms.** `random_probe` (volume-matched) and the oracle arms changed the interpretation of two results each. The mechanisms mostly confirmed what the controls had already bounded.
3. **Do not build what the measurement does not demand.** Two milestones ended in a measured decline. Both were correct decisions and neither would have been reached by following the original roadmap, which treated them as inevitable.
4. **The untested half is the interesting half.** ~~Nothing here was run against a live LLM agent.~~ **Done — see [live-ollama-validation.md](results/live-ollama-validation.md).** Running it against local models immediately found that RuleWorld's central parameter was wrong (compliance 1.00, not the assumed 0.80), that a wrong memory misleads every model 100% of the time, and a security bug in `explain()` that 384 unit tests had missed. The remaining untested half is the *marginal* case: tasks where a memory helps rather than decides, which is where the small effect sizes — and the whole case for causal credit — actually live.

## The honest one-line summary

> A memory's worth can be estimated from its effect on outcomes rather than its similarity to a query, and that estimate is accurate — but across four attempts it improved exactly one downstream decision, and the cheapest heuristic matched it on the others. The most valuable mechanism turned out to be the simplest one the original document proposed: **keep disagreements alive and go test them.**
