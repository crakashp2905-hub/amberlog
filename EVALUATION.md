# EVALUATION.md

## 1. Primary environment: RuleWorld (synthetic)

**Why synthetic:** it is the only way to know every memory's *true* value, which is needed to validate a credit estimator. Real benchmarks come after.

### World
- A set of hidden **rules** `symptom → correct action`, each with a set of contexts where it holds.
- **Contexts** (for example, environments A/B/C) have a controllable **overlap o** ∈ [0, 1], the fraction of rules that hold in every context.
- **Drift:** at episode T, a chosen fraction of rules flip their correct action.
- **Rare rules:** some symptoms occur with probability ≪ 1% but carry a high outcome weight.

### Tasks and outcomes
- An episode presents 1..k symptoms; the agent chooses actions; the outcome is the fraction correct (optionally weighted), **computed by the environment**.

### Memories
- The agent writes claims ("in context A, symptom s → action a") and procedures (ordered action sequences).
- Harmful memories are injected at a configurable rate.
- **True value** of memory m in context c: the exact change in expected outcome from exposing it, computed by enumerating the rule table under the agent's known policy.

### Agents
- **Scripted:** follows an exposed claim with probability q, otherwise uses a prior. Fast.
- **LLM:** the same observation and action interface through a prompt. Used for confirmation runs.

### Key parameters (each experiment sweeps a subset)
number of rules, contexts, overlap o, drift time T and fraction, harmful rate, rare-rule rate, memory budget, exploration ε, number of agents, topology.

## 2. Metrics

| Group | Metric | Definition |
|---|---|---|
| Estimation | ρ_value | Spearman correlation between estimated and true V(m, c) |
| | calibration | coverage of 90% intervals for true V |
| | exploration overhead | success loss caused by randomized exposure versus the greedy policy |
| Task | success | mean outcome over the last N episodes |
| | regret | cumulative (oracle success − achieved success) |
| | recovery time | episodes after drift or injection until success is back within 2 pp of pre-shock |
| Memory | harmful exposure rate | exposures of memories with true V < 0, divided by all exposures |
| | rare-rule retention | fraction of high-impact rare memories still active at the end |
| | memory waste | fraction of stored memories with true V ≈ 0 |
| Federation | transfer gain | Δ success of a recipient versus no sharing |
| | negative transfer rate | shared memories with V(m, c_recipient) < 0 |
| | bytes shared | communication volume |
| Collective | correct-belief probability | P(the population converges on the true rule) |
| | time to consensus | episodes until ≥ 90% of agents agree |
| Cost | LLM calls, tokens, dollars | per episode and per unit of success gained |
| | wall-clock time | per experiment |

## 3. Baselines (minimum set)

1. No memory
2. Relevance-only retrieval
3. Relevance + recency + importance (Generative Agents scoring)
4. Reflection / insight memory (ExpeL-style)
5. **Naive usage-success credit**: the key baseline
6. *(Later, if an adapter is feasible)* Mem0 or A-MEM style off-the-shelf memory
7. **Oracle**: ranking by true V (the upper bound; RuleWorld only)

## 4. Ablation matrix (used instead of "H6")

Starting from the full system at a given milestone, remove one component at a time:
- propensity correction
- amortization
- paired replay
- TMS retraction
- rare-event protection
- the firewall
- selective sharing (→ full sharing)
- hypothesis sets (→ overwrite)
- context splitting

## 5. Statistics

- ≥ 5 seeds; paired comparisons on identical task streams (common random numbers).
- 95% confidence intervals from a bootstrap over seeds × tasks. Report effect sizes, not only p-values.
- Pre-register thresholds and the primary metric for each hypothesis in `research/prereg/` before running.
- Every results table stores the config, seed list, commit hash and cost.

## 6. Real-benchmark validation (after P5)

Choose one benchmark with verifiable outcomes and repeated related tasks (candidates: ALFWorld, WebShop, τ-bench, a SWE-style set; open decision). Report baselines 1–5 and the best system. On a real benchmark, ground-truth value is unavailable, so ρ_value can't be measured; report task metrics and paired-replay spot checks instead.
