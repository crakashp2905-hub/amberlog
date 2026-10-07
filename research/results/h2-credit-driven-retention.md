# Result — H2: credit-driven forgetting does not beat a smoothed success rate

- **Pre-registration:** [../prereg/h2-credit-driven-retention.md](../prereg/h2-credit-driven-retention.md), with a dated amendment made before any run.
- **Run:** 2026-10-01, 10 seeds, 2000 warm-up + 2000 evaluation episodes per arm. Raw output: [h2-run.txt](h2-run.txt).
- **Reproduce:** `python -m experiments.h2`

## Verdict: **KILLED**

The registered rule (§6) kills H2 if `amortized` fails to beat the best of the three baselines. It did not beat `naive`:

| comparison | difference | registered bar |
|---|---|---|
| amortized − frequency | **+0.126** [+0.100, +0.152] | ✅ |
| amortized − recency_importance | **+0.090** [+0.076, +0.105] | ✅ |
| amortized − naive | **−0.012** [−0.025, +0.002] | ❌ |

Estimated causal credit beats both heuristics comfortably and **loses to a smoothed success rate**, with the interval straddling zero.

## Arms

| arm | success | pre-drift | post-drift | rare kept | harm kept |
|---|---|---|---|---|---|
| random | 0.352 [0.340, 0.366] | 0.372 | 0.331 | 50.0% | 37.6% |
| frequency | 0.338 [0.311, 0.368] | 0.375 | 0.302 | **9.3%** | 52.0% |
| recency_importance | 0.375 [0.350, 0.401] | 0.422 | 0.327 | 87.0% | **87.0%** |
| **naive** | **0.476** [0.455, 0.497] | 0.551 | 0.401 | 61.1% | **7.9%** |
| amortized | 0.464 [0.450, 0.481] | 0.532 | 0.397 | 87.0% | 11.6% |
| *oracle* | *0.485* [0.469, 0.502] | *0.557* | *0.413* | *100%* | *0.0%* |

## Why H1's win did not transfer

H1 measured **rank correlation over the whole memory population**, where amortized scored ρ=0.76 against naive's 0.47. That advantage bought almost nothing here, for a reason worth stating plainly:

**1. There was barely anything left to win.** The oracle — perfect knowledge of true value — reaches only 0.485 against random's 0.352. The entire achievable gain is 0.133, and:

| arm | share of the oracle's gain captured |
|---|---|
| naive | **93.2%** |
| amortized | 84.2% |
| recency_importance | 17.3% |
| frequency | −10.5% |

**2. Retention only needs the bottom of the ranking to be right, and harm is directly visible in the outcome.** A harmful memory that gets followed produces failures, so its raw success rate is low — no debiasing required. Naive retains just 7.9% of harmful memories against amortized's 11.6%. The selection bias that wrecked naive's *ordering* in H1 inflates the scores of harmless memories, which barely matters when the decision is "drop the worst 80".

**3. Rank correlation was the wrong proxy for this decision.** This is the finding. ρ measures the whole ordering; a budget decision cares about one threshold. An estimator can be substantially better by ρ and no better at the only question being asked.

Two secondary observations:

- **`frequency` is actively worse than random** (−10.5% of the oracle gain) and destroys rare knowledge, keeping 9.3% of rare-but-correct memories. Keeping whatever gets retrieved most is worse than keeping nothing in particular.
- **`recency_importance` retains 87% of harmful memories** — the highest of any arm. With no outcome signal it cannot tell harm from help, so it preserves confidently-stated wrong answers.

## Guardrail (prereg §7): not triggered

Amortized retained **87.0%** of rare-but-correct memories, equal to `recency_importance` and well above `naive`'s 61.1%. The §2.5 concern — that credit-driven forgetting deletes the memories that pay off once a year — **did not materialise**, and amortized was in fact the best non-oracle arm on this axis.

This is the one place amortized clearly beat naive (87.0% vs 61.1%), and it did not show up in mean success because rare events are by construction rare.

## Defects found and what was done

**A bug was found and fixed mid-run, and that run discarded.** `prune` ranked *all* memories, including already-deprecated ones. Their scores are stale — nothing has exposed them since — so they kept looking good and occupied slots in the top `budget`, letting the live store fall below budget by a different amount in each arm. "Equal memory budget", which the whole comparison rests on, was not holding. Fixed, pinned by `tests/test_retention_arms.py`, and the experiment re-run from scratch.

**The recovery column in the raw output is not interpretable and is omitted above.** `_recovery` returns NaN for seeds that never recover, and the reported mean is taken over the remaining seeds — a different subset for each arm. An arm where one seed recovered quickly and nine never did reports a better number than one where all ten recovered slowly. The metric needs a recovery *rate* alongside the time; it is fixed for H3 rather than reported misleadingly here.

## Limitations

The five from the pre-registration stand. Two are now material rather than theoretical:

1. **Budget was a single point** (40 of ~120). A generous budget leaves room to keep the valuable *and* the merely harmless, so a better ranking has little to prove. An exploratory sweep follows below.
2. **The store never grows.** Arms could only remove what had gone wrong, never replace it. Credit-driven *writing* is untested and is where the mechanism might earn its keep.
3. RuleWorld effects remain ~10× production scale.
4. Scripted agent; no LLM confirmation.
5. Harm is directly observable here. In a domain where a bad memory causes a *delayed* or *diffuse* failure, naive's advantage should shrink — that is the condition under which H2 deserves re-registering.

## Appendix — exploratory budget sweep (post-hoc, **not** pre-registered)

Raw output: [h2-budget-sweep.txt](h2-budget-sweep.txt) · `python -m experiments.h2 --budget-sweep --seeds 5`

Limitation 1 above says the registered budget was a single point. This sweeps it. **It cannot overturn the verdict** — the registered test ran at budget 40 and failed — and choosing a budget after seeing which one wins is precisely the move pre-registration exists to prevent. It is reported to decide whether a *differently registered* test is worth running.

| budget | naive | amortized | oracle | amortized − naive |
|---|---|---|---|---|
| 10 | 0.352 | **0.384** | 0.380 | **+0.032** [+0.021, +0.045] |
| 20 | 0.406 | **0.465** | 0.481 | **+0.060** [+0.039, +0.084] |
| 40 | 0.456 | 0.462 | 0.473 | +0.006 [−0.010, +0.022] |
| 80 | 0.432 | 0.428 | 0.449 | −0.004 [−0.010, +0.001] |

The ordering reverses as the budget tightens. At budget 20 amortized beats naive by **+0.060** — above the registered 5pp bar — with the interval clear of zero, and lands within 0.016 of the oracle while naive trails by 0.075.

### This explains both H1 and H2 together

**What a retention decision asks depends on how tight the budget is.**

- **Loose budget (40–80 of ~120):** there is room to keep every valuable memory *and* a pile of harmless ones. The only question that matters is "drop the actively harmful", and harm is directly visible in raw outcomes. Naive answers it well, and ranking quality is nearly irrelevant.
- **Tight budget (10–20):** harmless memories now compete for slots with valuable ones. The question becomes "which of these non-harmful memories is actually worth keeping" — exactly the distinction the selection-bias confound destroys, and exactly what the propensity correction fixes. Naive cannot tell a distractor on an easy task from a correct claim; both show high success rates.

So H1 and H2 are not in tension. The estimator's advantage is real and lives in the *middle and top* of the ranking. A loose budget only exercises the bottom.

### What this does not license

The P5 decision stands: **ship naive**. This is 5 seeds, post-hoc, with the budget chosen after seeing the outcome. The honest next step is to pre-register **H2b** — credit-driven retention at a tight budget — with fresh seeds and a threshold fixed in advance, and to treat the +0.060 above as the effect it is powered to detect, not as a result.

## Consequence

Per ROADMAP P5, **credit-driven retention is not justified** on this evidence.

- **Ship naive usage-success as the default retention ranking.** It is simpler, needs no propensity logging, and performs at 93% of the achievable ceiling.
- **Keep the amortized estimator** — H1 stands, and it is the better choice wherever the full ordering matters rather than one threshold. It is also materially better at preserving rare knowledge.
- **Do not present retention by causal credit as a product feature** without evidence from a setting where harm is not directly observable in the outcome.
- **P6 (federation) is not blocked by this.** H3 is about which memories to *share*, which is a different decision with a different error cost — sending a harmful memory to another agent is worse than keeping it locally, and the full ordering matters more there.
