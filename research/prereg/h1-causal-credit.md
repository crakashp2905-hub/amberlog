# Pre-registration — H1: estimating the causal value of agent memories

- **Written:** 2026-09-28, **before** any estimator was run against RuleWorld.
- **Milestone:** P4 (ROADMAP.md)
- **Status at time of writing:** RuleWorld not yet built; DR, paired-replay and amortized estimators not yet written.

Thresholds below are copied from ROADMAP.md / CRITICAL_REVIEW.md §13, which were fixed before any data existed. They are not to be revised after seeing results. If the result lands between the success and kill lines, that is an inconclusive result and is reported as one.

---

## 1. Hypothesis

> A propensity-corrected, amortized estimator of memory value recovers the true value of agent memories accurately enough, and cheaply enough, to be worth the machinery — beating the naive usage-success baseline that a competent engineer would write in an afternoon.

## 2. Environment

RuleWorld (EVALUATION.md §1), single agent, stationary (no drift), one context. Drift and multi-context are H2/H3 concerns and are out of scope here.

- Hidden rules: `symptom → correct action`. Each symptom has `n_plausible` actions the agent would guess among, which varies per symptom and is what makes some tasks easier than others.
- Memories are pre-seeded, not learned during the run, so the memory population is fixed and ground truth is stable:
  - **correct claims** — state the right action for a symptom
  - **wrong claims** — state a wrong action (the injected-harm population)
  - **distractors** — mention a symptom but assert no action. **True value exactly 0.**
- The agent follows the top-ranked matching claim with probability `q`, else guesses uniformly among that symptom's plausible actions.
- Outcome is a Bernoulli draw on the resulting probability, verified by the environment.

**The designed confound.** Retrieval ranks by relevance, so a distractor about an *easy* symptom is exposed mainly on episodes that succeed anyway. Its true value is 0, but its observed success rate is high. This is the selection bias of CRITICAL_REVIEW §2.2, built in deliberately so the experiment can fail.

## 3. Ground truth

For memory `m`, the true value is the average treatment effect over the episodes where `m` was in the candidate pool:

```
V*(m) = mean over those episodes of [ P(correct | m exposed at its rank) − P(correct | m withheld) ]
```

Both terms are computed **analytically** from the agent's known policy and the rule table — not simulated — so ground truth carries no Monte Carlo noise. It is reconstructed from the event log (candidate order and exposure flags), which also checks that the log is sufficient to support the claim.

The population is "episodes where `m` was a candidate" because that is the only population an estimator has data from.

## 4. Estimators

| id | Role |
|---|---|
| `naive_usage` | **The baseline to beat.** Smoothed success rate over episodes where the memory was exposed. |
| `ips` | Propensity-corrected difference (already implemented) |
| `dr` | Doubly robust: outcome model on episode context + IPS correction |
| `amortized` | **Primary.** Per-memory DR estimates shrunk toward a feature-based prediction |

Primary comparison is `amortized` vs `naive_usage`.

## 5. Primary metric

**ρ = Spearman rank correlation between the estimate and `V*`**, over the analysis population.

**Analysis population (fixed now):** every memory with at least one exposure decision in an episode that has a verified outcome. Memories an estimator declines to score (returning `UNKNOWN`) are ranked lowest, tied — declining to answer is not free, and excluding them would flatter an estimator that only scores the easy cases. Coverage (the fraction scored) is reported separately.

## 6. Exploration overhead

```
overhead = (mean outcome under relevance-ranked top-k − mean outcome under ε-greedy) / mean outcome under top-k
```

Measured on paired runs: same seed, same world, same memory population.

## 7. Decision rules

Judged at the **smallest ε in the sweep that reaches ρ ≥ 0.6**:

- **H1 supported** if at that ε: `ρ(amortized) ≥ 0.6` **and** `overhead ≤ 10%` **and** `ρ(amortized) − ρ(naive_usage) ≥ 0.15`.
- **H1 killed** if no ε in the sweep reaches `ρ ≥ 0.5` at `overhead ≤ 20%`. Consequence (ROADMAP P4): causal credit stays a heuristic, governance remains the product, and P5 does not start.
- **Inconclusive** otherwise. Reported as inconclusive; no threshold is moved.

All three conditions are judged on the **mean across seeds**, with 95% bootstrap intervals reported alongside.

## 8. Design

- **Seeds:** 10 (exceeds the ≥5 in AGENTS.md), seeds `0..9`, used for world generation, memory seeding, task sampling and exposure randomisation.
- **ε sweep:** {0.05, 0.10, 0.20, 0.30}
- **Episodes:** 2000 per run for the primary result; a power sweep over {250, 500, 1000, 2000, 4000} reports how ρ grows with evidence.
- **World:** 40 symptoms, 8 actions, `n_plausible` drawn from {2,…,6}; memory population 40 correct claims, 20 wrong claims, 40 distractors; retrieval `k=3` from a pool of 12.
- **Fixed:** `q = 0.8`.

## 9. Stated limitations (written now, not after)

1. **RuleWorld effects are larger than real ones.** A correct claim here moves success by roughly `q·(1 − 1/n_plausible)` ≈ 0.4–0.7. CRITICAL_REVIEW §2.1 expects real memories at 0.02–0.05. A ρ that clears 0.6 here says the estimator is *correct*, not that it is cheap enough in a real deployment. The power sweep is the honest part of this result.
2. **The agent is scripted.** LLM-agent confirmation needs an API budget and has not been run.
3. **Stationary and single-context.** Drift, transferability and federation are untested here.
4. **The memory population is fixed.** Real stores grow while being estimated.

## 10. What gets reported

Whatever happens: the ρ/ε/overhead table, the power sweep, coverage, the naive baseline, and the verdict against §7 — including "killed" or "inconclusive".
