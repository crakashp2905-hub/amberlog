# AGENTS.md — Repository Constitution

This file applies to everyone who changes this repository: humans and AI coding agents alike.

## Principles

1. **Value is not relevance.** A memory is worth keeping, showing or sharing because evidence says it improves outcomes, not because it is similar to the query.
2. **Every persistent memory has provenance.** No memory exists without a record of how it came to exist (source episode, creating agent, parent memories).
3. **The event log is the source of truth.** Memory records, credit estimates and profiles are *projections* of an append-only event log and can be rebuilt from it.
4. **Log propensities, always.** Every decision to expose or withhold a memory records the probability with which it was made. Without this, causal credit cannot be estimated later (see SPEC.md §4).
5. **Credit is a distribution, not a number.** Every value estimate carries uncertainty and an effective sample size.
6. **Contradictions stay representable.** Nothing silently overwrites a conflicting memory. Conflicts become competing hypotheses or context-specialized memories.
7. **Unvalidated memories are never federated.** Sharing across agents requires passing the firewall policy.
8. **Every research claim needs an experiment** with a baseline, pre-registered thresholds, and ≥ 5 seeds. A demo is not evidence.
8a. **Establish the ceiling before setting the threshold.** Every comparison against baselines carries an oracle arm — the best achievable with perfect knowledge — and the threshold is expressed as a share of the headroom it reveals, not as an absolute margin. H3 registered a bar of +0.030 when the total available gain was at most +0.027, so no method could have passed; H2 passed its arms comfortably and the oracle showed the naive baseline was already capturing 93% of what existed. A threshold set without a ceiling is not a threshold.
8b. **Give the oracle no handicap, and check that no arm can beat it.** 8a made the ceiling mandatory and did not stop it being built wrong three times. H3 registered a margin larger than its own ceiling. Phase A's oracle showed *one* memory where every other arm showed three, so the ceiling was set by its retrieval budget rather than by the limits of selection. Phase B's oracle shared memories correct at a lesson's own site while its recipients worked several sites, so it poisoned them itself. In each case it looked unimpeachable — Phase A's scored 100% on the pilot — until an arm beat it. So: the oracle gets **the same budget, the same k, the same mechanisms** as the arms it bounds, differing only in knowing the answer; and **"did any arm beat the oracle?" is checked on every run**, because an arm above the ceiling is not a surprising result, it is a proof the ceiling is wrong. Contradictions in the oracle's own metrics are the same signal: Phase B's reported zero wrong imports and 10% negative transfer at once, which cannot both be true.
8c. **Check the metric before the threshold: a primary metric must be shown not to be trivially maximised by a registered baseline.** 8a made the ceiling mandatory and 8b made the oracle's handicap checkable, and neither would have caught P2. Its ceiling was measured correctly at 0.800 and its oracle carried no handicap — and `full_context`, a registered baseline, *reached* 0.800 for a reason with nothing to do with the question, because sufficiency can always be bought with context. The threshold was unreachable before any method existed. So the check is: run each registered baseline against the primary metric first, and if one of them maxes it, the metric is wrong. The repair is usually a constraint the metric was missing — P2b fixes a token budget, measures a **plateau** of headroom across a 16× range so the constraint's value is not load-bearing, and reports the degenerate regime every run rather than dropping it once it stopped being convenient. A metric nobody tried to max is not a metric.

9. **Infrastructure follows measured need.** No distributed, P2P, or learned-controller component is added before its gate in ROADMAP.md is passed.
10. **Schema changes are explicit and versioned.** A schema change comes with a migration and a version bump in SPEC.md.

## Engineering rules

- **Language:** Python ≥ 3.11 *(open decision; see ROADMAP.md)*. Type hints are required on public APIs.
- **Determinism:** every experiment takes a seed. Randomness goes through an injected RNG, never through global `random`.
- **Separation:** `research/` and `experiments/` may import from core packages; core packages never import from `research/` or `experiments/`.
- **Tests:** every module under `core/`, `intelligence/` and `governance/` has unit tests. Estimators additionally have *known-answer tests* against RuleWorld ground truth.
- **No numbers in docs without a run.** Tables of results cite the experiment config and commit that produced them.
- **LLM calls go through one client wrapper** that logs model, prompt hash, token counts and cost. Cost is a first-class metric.
- **Secrets and PII never enter memory content.** The ingestion path runs a sensitive-data check (see SECURITY.md).

## Glossary (use these terms consistently)

| Term | Meaning |
|---|---|
| **Memory** | A versioned, typed record with provenance (SPEC.md §2) |
| **Exposure** | Placing a memory in an agent's context for a decision |
| **Propensity** | The probability with which an exposure decision was made |
| **Outcome** | A verified scalar result of an episode, provided by the environment or an evaluator, never self-reported |
| **Credit / value** | V(m, c) = the expected improvement in outcome from exposing m in context c, net of cost. There is one value concept; "utility" and "usefulness" are not separate quantities. |
| **Value estimate** | A posterior over V(m, c): mean, credible interval, effective n |
| **Transferability** | V(m, c′) for a context c′ other than the one where m was created |
| **Lifecycle state** | Health of a memory: candidate / active / contested / quarantined / deprecated / deleted |
| **Scope** | Visibility of a memory: private / team / federated. Scope is independent of lifecycle state. |
| **Hypothesis set** | A group of mutually contradictory memories kept together, each with a posterior |
