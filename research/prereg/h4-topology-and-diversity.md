# Pre-registration — H4: network topology, premature consensus, and minority hypotheses

- **Written:** 2026-10-05, **before** the bandit world, the topologies, or any arm was built.
- **Milestone:** P7 (ROADMAP.md)
- **Why this one matters:** CRITICAL_REVIEW §1 identified this as the strongest genuinely open question in the whole document. The Zollman effect — that *sparser* communication networks reach the correct belief *more often* though more slowly — is a established result in social epistemology that has not been tested on agent memory federation.

Thresholds below are fixed now and are not revised after seeing results.

---

## 1. Hypotheses

**H4a (Zollman).** A sparser sharing topology converges on the correct belief more often than a fully-connected one, and takes longer to do it.

**H4b (minority preservation).** Keeping a contested belief alive and periodically re-testing it — rather than collapsing to the majority — raises the probability of ending up correct, and shortens recovery when a population has converged wrongly.

H4b is the mechanism the whole project is built on ("contradictions stay representable", AGENTS.md principle 6). It has never been tested.

## 2. Why this needs a different world

RuleWorld cannot produce this effect. Following a correct claim there succeeds ~84% of the time against ~5% for a wrong one; with a gap that wide, evidence is never ambiguous and no population ever talks itself into the wrong answer.

The Zollman effect requires **close payoffs**, so that small samples genuinely mislead. So H4 uses a **bandit world**: two actions, success probabilities `p_good = 0.55` and `p_bad = 0.50`. An agent plays greedily — it pulls whichever action its own evidence currently favours — and shares its results with its neighbours.

**The absorbing trap is the mechanism.** A population that collectively comes to believe the worse action is better stops pulling the better one entirely. No new evidence arrives, the belief never corrects, and the error is permanent. Dense networks synchronise beliefs, so they fall into that trap together. Sparse networks keep some agents ignorant of the early bad news, so somebody keeps testing.

**Diverse starting beliefs.** The better action is uncertain and the worse one is well-characterised — the classic safe-versus-risky setup. Each agent begins with 20 observations of the worse action (so its rate is effectively known) and 4 observations of the better one drawn at a uniformly-sampled rate, so initial beliefs about it spread across the whole range and roughly half the population starts willing to test it.

> ### Amendment, 2026-10-07 — before the registered run
>
> This section originally planted **the same 3 failures on the better action in every agent**, intending a reliable misleading signal. That makes H4a unmeasurable by construction, which a quick run confirmed: `P(correct)` was 0.000 for every topology without minority preservation.
>
> The reason is that the absorbing trap becomes *absolute* rather than probabilistic. If every agent starts believing the worse action is better, nobody ever pulls the better one, no evidence about it is ever generated, and no topology can escape — there is nothing for sparsity to preserve. Zollman's effect needs *some* agents still experimenting, which requires diverse starting beliefs.
>
> **Disclosure:** the quick run that revealed this also showed a preliminary H4b figure (minority preservation reaching 1.000 under `complete`). That number is from the broken design and does not carry over; H4b is re-run from scratch under the corrected start. No threshold in §5 was changed, and the amendment was made before the registered run.

## 3. Arms

**Topologies** (10 agents throughout):

| id | Structure | Degree |
|---|---|---|
| `complete` | everyone shares with everyone | 9 |
| `small_world` | ring of degree 4, 10% of edges rewired | 4 |
| `ring` | each agent shares with 2 neighbours | 2 |
| `cycle_sparse` | each agent shares with 1 neighbour | 1 |
| `isolated` | nobody shares | 0 |

`isolated` is a reference, not a competitor: it is maximally diverse and maximally slow, and it shows what the topology axis is bounded by at the sparse end.

**Minority preservation** — crossed with topology, off and on:

| id | Behaviour |
|---|---|
| `collapse` | an agent pulls only the action it currently believes better |
| `preserve` | when an agent's two hypotheses are *contested* — their credible intervals overlap — it spends a small fixed share of its pulls re-testing the minority one |

`preserve` is not uniform exploration. It targets the specific belief that is in dispute, which is what a hypothesis set is for.

## 4. Metrics

- **Primary:** `P(correct)` — the fraction of replications where **every** agent ends believing the better action.
- **Rounds to consensus:** first round after which all agents agree and do not change again.
- **Recovery:** among replications where the population was wrong at round 20, the fraction correct by the end, and how long it took.
- **Cost of being right:** total pulls of the worse action (regret).

## 5. Ceiling and thresholds

Per AGENTS.md principle 8a, thresholds are expressed as a **share of available headroom**, not as absolute margins. Here the ceiling is structural: `P(correct) = 1.0`. Headroom for any arm is `1 − P(correct | complete, collapse)`, the worst case.

**H4a supported** if, against `complete`:
1. the sparsest *connected* topology (`cycle_sparse`) captures **≥ 40%** of the headroom, with the bootstrap interval on the difference clear of zero; **and**
2. `P(correct)` is **monotonically non-decreasing** as degree falls across `complete → small_world → ring → cycle_sparse`; **and**
3. **rounds to consensus is strictly longer** for `cycle_sparse` than for `complete`. *If sparse is both more accurate and faster, this is not the Zollman effect and the claim is not supported however good the accuracy looks.*

**H4a killed** if `cycle_sparse` does not beat `complete` at all.

**H4b supported** if `preserve` captures **≥ 20%** of the headroom remaining under `complete` (where premature consensus is worst), interval clear of zero, **and** shortens recovery.

**H4b killed** if `preserve` does not improve `P(correct)` under `complete`.

Either may be supported without the other.

## 6. Design

- **Agents:** 10. **Replications:** 200 per cell, seeds `0..199`.
- **Rounds:** 150. **Pulls per agent per round:** 10.
- **Payoffs:** `p_good = 0.55`, `p_bad = 0.50`. **Planted start:** 3 failures on good, per agent.
- **Belief:** Beta posterior per action per agent, updated from own pulls and neighbours' shared results. An agent believes whichever action has the higher posterior mean.
- **Contested** (for `preserve`): the 90% credible intervals of the two actions overlap.
- **Preserve budget:** 20% of that round's pulls go to the minority action while contested.

## 7. Stated limitations (written now)

1. **This is a bandit, not an agent.** It tests belief dynamics over a sharing network, not an LLM agent's memory. The mechanism is the project's claim about disagreement; the substrate is deliberately simple so the effect is attributable.
2. **Payoffs are stationary.** Drift is H2's axis.
3. **Every agent shares honestly and completely.** Selective federation (H3) and malicious agents are not modelled.
4. **Fixed topologies.** Real federations change shape; trust-weighted and adaptive topologies are untested.
5. The `preserve` budget (20%) is one point, not swept.

## 8. What gets reported

The full topology × preservation grid for `P(correct)`, rounds to consensus, recovery and regret; headroom shares; all three H4a conditions individually; and the verdict against §5 — including "killed" or "inconclusive".
