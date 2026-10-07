# Result — H1: estimating the causal value of agent memories

- **Pre-registration:** [../prereg/h1-causal-credit.md](../prereg/h1-causal-credit.md), written before the environment or the estimators existed.
- **Run:** 2026-09-28, 10 seeds, 2000 episodes per cell, scripted agent. Raw output: [h1-run.txt](h1-run.txt).
- **Reproduce:** `python -m experiments.h1`

## Verdict: **SUPPORTED**

Judged by the pre-registered rule (§7), at the smallest ε reaching ρ ≥ 0.6:

| Condition | Required | Observed at ε=0.05 | |
|---|---|---|---|
| ρ(amortized) | ≥ 0.60 | **0.604** | ✅ |
| exploration overhead | ≤ 10% | **1.8%** | ✅ |
| ρ(amortized) − ρ(naive) | ≥ 0.15 | **+0.366** | ✅ |

**The triggering cell is marginal and should not be quoted on its own.** ρ = 0.604 with a 95% bootstrap interval of [0.572, 0.634] — the interval straddles the 0.60 threshold. The registered rule judges the mean, so the verdict stands as written, but the honest reading is the ε=0.20 cell, where every condition is met with the interval clear of its threshold:

| | ρ(amortized) | overhead | margin over naive |
|---|---|---|---|
| ε=0.20 | **0.761** [0.732, 0.790] | 8.0% | +0.292 |

## Primary table

ρ = Spearman against true value; mean over 10 seeds [95% bootstrap CI].

| ε | overhead | naive_usage | ips | dr | **amortized** |
|---|---|---|---|---|---|
| 0.05 | 1.8% | 0.238 | 0.131 | 0.133 | **0.604** |
| 0.10 | 3.7% | 0.297 | 0.384 | 0.387 | **0.679** |
| 0.20 | 8.0% | 0.469 | 0.739 | 0.743 | **0.761** |
| 0.30 | 11.5% | 0.541 | 0.761 | 0.763 | 0.759 |

Coverage — the fraction of the analysis population an estimator scored rather than declining:

| ε | naive | ips / dr | amortized |
|---|---|---|---|
| 0.05 | 100% | 36.2% | 100% |
| 0.10 | 100% | 72.0% | 100% |
| 0.20 | 100% | 96.5% | 100% |
| 0.30 | 100% | 99.9% | 100% |

## What the numbers say

**1. Amortization buys coverage, and coverage is most of the win.** At ε=0.05 the propensity-corrected estimators can only score 36% of memories — the rest have no comparison group, so IPS and DR correctly decline, and declining is penalised by ranking them last. Amortization answers for all of them by borrowing the population's view, and that alone takes ρ from 0.13 to 0.60. This is the sample-size problem of CRITICAL_REVIEW §2.1 showing up exactly where it was predicted, and amortization is the predicted remedy.

**2. Once every memory has its own evidence, amortization stops helping.** At ε=0.30, IPS (0.761) and DR (0.763) match or slightly beat amortized (0.759): shrinkage toward a population prediction is a small drag when the per-memory estimate is already good. Amortization is a low-data technique, and the crossover is visible at ε≈0.20–0.30.

**3. DR barely beat IPS on ranking** — 0.743 vs 0.739 at ε=0.20, well inside the noise. The outcome model does tighten intervals (a unit test confirms DR's intervals are narrower than IPS's on the same data), but *ranking* is driven by coverage and by which memories have overlap at all, not by the variance of the estimates that exist. **DR is not currently earning its complexity for this metric.** It may earn it for the retention decisions in P5, where the interval matters and not just the order.

**4. The naive baseline improves with exploration too** (0.238 → 0.541). Randomising exposure partly decorrelates which memories get retrieved from how hard the task was, so it de-confounds the observational estimator as a side effect. Anyone reading only the ε=0.30 column would conclude the naive baseline is adequate; the gap is widest exactly where exploration is cheapest.

**5. Power sweep (ε=0.20).** Amortized reaches useful ranking far earlier than the propensity-corrected estimators alone:

| episodes | naive | ips | dr | amortized |
|---|---|---|---|---|
| 250 | 0.301 | 0.034 | 0.034 | **0.473** |
| 500 | 0.330 | 0.107 | 0.106 | **0.571** |
| 1000 | 0.403 | 0.437 | 0.438 | **0.676** |
| 2000 | 0.469 | 0.739 | 0.743 | **0.761** |
| 4000 | 0.537 | **0.798** | **0.799** | 0.791 |

At 250 episodes plain IPS is worthless (0.034) while amortized is already at 0.473. By 4000 the ordering has reversed.

## Limitations

The four from the pre-registration, unchanged, plus two found during the run:

1. **RuleWorld effects are much larger than real ones.** A correct claim moves success by ~0.4–0.7 here; CRITICAL_REVIEW §2.1 expects 0.02–0.05 in a real deployment. **This result shows the estimator is correct, not that it is affordable.** The power sweep is the transferable part: it says how ρ grows with evidence, and real deployments sit far to the left of it.
2. **The agent is scripted.** No LLM-agent confirmation run — that needs an API budget and has not happened.
3. **Stationary, single-context.** Drift, transferability and federation are untested.
4. **The memory population is fixed.** Real stores grow while being estimated.
5. **Harmful memories were largely inert.** The registered config gives every symptom a correct claim, so wrong claims were usually ranked below one and never followed — their median true value was −0.013, not the strong negative intended. The injected-harm population was therefore weakly exercised. **H2 needs a config where harm actually bites**, and this is a defect in the registered world, not something to fix retroactively here.
6. **The realized candidate pool was ~2.5, not 12.** The pre-registration caps retrieval at 12, but single-token symptom queries plus the relevance floor mean only memories about that symptom score above zero. With k=3, the greedy policy therefore exposes nearly every candidate, so *all* overlap comes from ε. This makes the ε axis cleaner than intended but narrower than a realistic retrieval setting.

## Disclosure

While validating the harness — before running the experiment — I looked at the naive baseline's ρ on one seed (0.496) and at the per-group medians, to confirm the designed confound was present. That is a look at one of the three decision inputs. **The pre-registered configuration was not changed in response**, including the two defects in it now listed as limitations 5 and 6, which were visible at that point and deliberately left alone.

Two harness bugs were fixed before the final run, both found by known-answer tests rather than by looking at results:
- Ground truth's analytic bound was wrong (`q·(1−guess_rate)` instead of `q`).
- The scoring function treated `n_eff == 0` as "declined to answer", which discarded exactly the predictions amortization exists to produce. Before the fix, amortized scored identically to DR; after, it scored 0.604 where DR scored 0.133. **This is the single largest effect in the experiment and it was a bug in the measurement, not in the method** — worth remembering when reading any result where the primary method appears to do nothing.

## Consequence

Per ROADMAP P4, the kill criterion is not met and P5 (credit-driven lifecycle) is unblocked. Two things should carry forward:

- **Use `amortized` as the default contrastive estimator**, with `dr` as its base. It dominates at every sample size below ~4000 episodes, which is where real deployments live.
- **DR's extra machinery is unproven for ranking.** Keep it for its intervals, and re-examine at P5 where retention decisions depend on the lower bound rather than the order.
