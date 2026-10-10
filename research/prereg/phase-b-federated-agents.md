# Pre-registration — Phase B: what should cross a federation boundary?

- **Written:** 2026-10-08, before the harness. Phase A's result is not yet known and does not gate this: the questions are independent, and Phase B is where the one mechanism no adjacent paper has — provenance and retraction that survive a store boundary — is actually put at risk.
- **Origin:** the same external review as Phase A, Phase B of its proposal.
- **Precedent:** H3 measured the federation crossover curve in simulation and was **inconclusive by its own rules** — the registered margin of +0.030 exceeded the +0.027 that perfect knowledge could achieve. That failure is the reason every threshold below is a share of an oracle's headroom, and the reason the oracle arm is built first this time.

Thresholds in §6 are fixed now and are not revised after seeing results.

---

## 1. Hypotheses

**PB1 (negative transfer is real and selective sharing beats both extremes).** With four agents whose contexts partially overlap, sharing everything and sharing nothing are both worse than sharing by estimated transferability. H3 found this curve in simulation; PB1 asks whether it survives real models writing real memories.

**PB2 (provenance survives the boundary usefully).** When a memory is retracted at its origin after being federated, propagating the retraction to importers recovers more of the lost accuracy than leaving them to discover the error themselves. This is the mechanism PRIOR_ART.md identifies as the project's strongest remaining novelty claim, and it has never been measured against the alternative of doing nothing.

**PB3 (reputation is worth its cost).** Weighting imports by the sender's track record beats treating every sender alike. Registered as the weakest of the three: it needs enough history per sender to estimate anything, and four agents over a few dozen episodes may not supply it. A null here is a statement about the data, not about reputation.

The null that has to be taken seriously for all three: **the recipient's own firewall, with no cross-agent information at all, is enough.** Phase A's `shared_memory_decay` lesson applies — the cheap local rule is the baseline, not a strawman.

## 2. The world

DepotWorld (`experiments/depotworld.py`), extended to four agents with **partially overlapping territories**:

| agent | sites |
|---|---|
| `north` | cold_store, urban |
| `south` | coastal, urban |
| `east` | cold_store, coastal |
| `west` | urban only |

Overlap is the independent variable that H3 swept and could not resolve. `west` is deliberately narrow: it is the agent most exposed to a confident import from a territory it cannot check, which is the case a federation gets wrong.

Each agent learns only its own sites, so each holds lessons that are true for it and false for a neighbour — the same hazard as Phase A, now with a real boundary and a real sender. Poisoning stays at 25%, so some lessons are wrong everywhere and arrive carrying a sender's endorsement.

## 3. Arms

Sharing policy, crossed where stated with retraction propagation:

| id | What crosses |
|---|---|
| `isolated` | nothing. The floor, and the arm that shows whether federation helps at all |
| `share_all` | every validated memory to every agent |
| `share_overlap` | only to agents whose territory includes the memory's site |
| `share_valued` | only memories with contrastive value evidence, to any agent |
| `share_valued_overlap` | both conditions |
| `oracle_share` | exactly the memories that are correct for **every** site the recipient works (corrected by amendment; see below) |

**Retraction propagation**, crossed with `share_all` and `share_overlap`:

| id | On retraction at origin |
|---|---|
| `no_propagate` | importers keep the memory and must find out for themselves |
| `propagate` | the retraction follows the memory and importers mark it contested |

**`oracle_share` fixes the ceiling.** Learned before the run that the ceiling must exist first: H3's threshold was unpassable and nobody noticed until afterwards.

## 4. Metrics

- **`success`** — per agent, per episode, verified by the environment.
- **`negative_transfer`** — episodes an agent got wrong where an *imported* memory asserted the chosen action. The harm attributable to federation specifically, separable from an agent's own bad memories.
- **`contamination_imported`** — share of imported memories active in an agent's store that are wrong for that agent's sites.
- **`recovery`** — after a retraction at origin: episodes to the importer's next correct answer on that fault.
- **`propagation_lag`** — episodes between retraction at origin and the importer ceasing to act on it.
- **`imports`** — count, as the cost of sharing; and tokens, as the cost of carrying them in context.
- **`per_agent_spread`** — the gap between the best and worst agent's success. A policy that lifts the mean by making `west` worse is not a federation policy worth having, and a mean-only report would hide it.

## 5. Sanity conditions, checked before the registered run

1. `oracle_share` success **≥ 0.80**, and **> `isolated` + 0.15** — federation has something to offer.
2. `share_all` `negative_transfer` **> 0** — sharing everything actually hurts. If it does not, there is no problem to solve and PB1 is vacuous.
3. At least **2 retractions per seed** reach an importer, or PB2 has no events to measure and the run is extended rather than reported.

Failing any of these changes the world, recorded as a dated amendment here, before any registered run.

> ### Amendment, 2026-10-10 — during harness construction, before any registered run
>
> Four changes, none of them to a threshold in §6.
>
> 1. **12 episodes per agent, not 24.** The registered design is 8 cells × 4
>    agents × 24 episodes × 5 seeds = 3,840 verified decisions, which at the
>    measured ~4s per call is over four hours of a single local model. At 12 it
>    is 1,920 decisions and **240 per cell** — still twice the 120 per arm that
>    [Phase A](../results/phase-a-real-agent-benchmark.md) ran on, and the
>    statistics pair by (seed, agent, episode) either way. The cut is to the
>    horizon, not to the pairing, and it is a cut made for compute rather than
>    for a result, which is why it is recorded before the run.
>
> 2. **Every arm runs the same exposure policy** — epsilon-greedy at 0.2,
>    ranking on value. `share_valued` needs contrastive value evidence to exist
>    at all, and a deterministic policy never generates the overlap an unbiased
>    estimate requires, so under `top_k` that arm would promote nothing and
>    silently become `isolated` — the same trap Phase A's amendment 4 recorded
>    for its own `fabric` arm. Holding exposure constant pays the exploration
>    cost in every arm rather than only where it is needed, which Phase A
>    measured at a few points of accuracy, but it keeps the arms differing in
>    exactly one thing. The cost is uniform, so it cannot bias the comparison
>    between arms; it does lower every number including the ceiling, and the
>    thresholds are shares of that ceiling's headroom, so that is accounted for.
>
> 3. **Retraction is a scheduled environment event.** At the halfway episode
>    every poisoned lesson is withdrawn at its origin, as a manufacturer's
>    bulletin would do it. §8.5 already said retraction is triggered by the
>    environment rather than discovered by an agent; this names the mechanism.
>    It matters more than it looks: deriving the retraction from "this memory
>    was in context when something failed" would import the policy
>    [Phase A killed](../results/phase-a-real-agent-benchmark.md) into the
>    middle of PB2 and make its result unreadable.
>
> 4. **`propagation_lag` is measured per episode, not as one number.** The
>    metric is the share of post-retraction episodes in which a memory withdrawn
>    at its origin was still active at an importer *and still in its context*.
>    A single mean lag cannot represent an arm that never stops acting on a
>    retracted memory — there is no lag to average, the behaviour simply
>    continues — and that is the case PB2 exists to detect.
>
> **Disclosure.** A 4-round, 4-cell smoke run preceded this amendment and is what
> produced change 2. It showed every arm at 25-31% success with zero negative
> transfer and zero imports reaching any prompt, despite 126 accepted imports.
> That was not a property of the sharing policies: it was a
> [product bug](../../CHANGELOG.md) in which ranking on value fell through to
> the memory id, and therefore to creation time, so imports — always newer than
> natives — could never be exposed. The bug is fixed and the fix is tested. No
> number from that smoke run carries over, and none of it bears on §6.

> ### Amendment, 2026-10-10 (second) — mid-run, after the ceiling arm was beaten again
>
> **`oracle_share` was mis-implemented and the first registered run was
> abandoned two seeds in.** It shared any memory correct at *its own* site. A
> recipient works several sites, so a lesson correct for `cold_store` reached
> `north` and then misled it on every urban episode. §3 says "exactly the
> memories that are correct for the recipient's **sites**", plural — so this was
> a bug against the registration, not a design choice.
>
> It was beatable by construction, and it was beaten: 85% and 79% against
> `share_overlap_propagate`'s 90% and 81% on the two seeds that ran. What gave it
> away was a contradiction rather than the ordering — at seed 1 it reported
> **zero wrong imports and 10% negative transfer**, which cannot both be true.
>
> **This is the third mis-specified ceiling in this project** (H3's threshold
> exceeded its own, Phase A's oracle had a smaller retrieval budget than the arms
> it bounded, and now this). Principle 8a was written after the first. The
> pattern across all three is the same: the oracle was given a *handicap the
> competing arms did not have*, and in each case it looked unimpeachable until an
> arm beat it.
>
> **Corrected:** the oracle shares exactly what cannot mislead the recipient —
> correct at **every** site that recipient works. Overlap is deliberately not
> required, because a memory that cannot mislead is worth sending whether or not
> its own site is one of theirs, and requiring it would lower the ceiling for no
> reason.
>
> **`imports_wrong` was wrong in the same way** and is corrected with it. It used
> "the lesson's own site is not one of the recipient's" as a proxy for wrongness,
> which is a different question: a lesson from elsewhere can be perfectly correct
> here, and one from a shared site can be wrong at the recipient's other site. It
> now means what §4 says `contamination_imported` means — the import would give
> the wrong answer somewhere in this recipient's territory.
>
> **The run restarts from seed 0.** No threshold in §6 changes. Nothing from the
> abandoned run is reported as a result; the per-seed figures quoted above appear
> only here, as the evidence for the amendment.

## 6. Ceiling and thresholds

Headroom is always `oracle_share − best_simple`, where `best_simple = max(isolated, share_all)` on the metric in question — the two things a team actually does, chosen after the run so the comparison cannot be won against a weak baseline.

**PB1 supported** if the best selective policy (`share_overlap`, `share_valued` or `share_valued_overlap`) captures **≥ 40%** of the success headroom with the bootstrap interval on the paired difference against `best_simple` clear of zero, **and** does not reduce the worst agent's success relative to `best_simple`. The second condition is not decoration: a mean gain bought from `west` is the failure mode this design exists to expose.

**PB2 supported** if `propagate` captures **≥ 50%** of the recovery headroom between `no_propagate` and `oracle_share`, interval clear of zero, **and** shortens `propagation_lag`. Measured under both `share_all` and `share_overlap`, and supported only if it holds under both — a mechanism that works only when everything is shared is not the one being claimed.

**PB3 supported** if reputation weighting beats uniform weighting on success by **≥ 25%** of the headroom, interval clear of zero. **PB3 inconclusive by design** if fewer than 10 imports per sender accumulate, which is declared here rather than discovered later.

**Any of the three killed** if its arm does not beat the baseline at all.

## 7. Design

- **Model:** `qwen2.5:3b`, as Phase A, so the two are comparable.
- **Agents:** 4. **Seeds:** 5. **Episodes:** 12 per agent (amended; see below), interleaved round-robin so sharing happens between episodes rather than in a batch at the end.
- **Sharing:** through `memory_fabric.federation.offer`, with each agent's own firewall deciding. Imports arrive unvalidated and provenance crosses with them. No arm is permitted to bypass the recipient's firewall — if a policy needs that, the policy is wrong and gets recorded as such.
- **Statistics:** paired by (seed, agent, episode). Bootstrap CIs, 10,000 resamples.
- **Verification:** the environment. No self-reported outcomes.

## 8. Stated limitations (written now)

1. **Four agents is not a population.** Phase C is the population question; PB3 in particular may simply lack the data, which §6 declares in advance rather than discovering as a surprise.
2. **Territories are fixed and honest.** No agent lies about its sites, and none changes territory mid-run. Both are realistic failure modes and neither is tested.
3. **No adversary.** A sender whose memories are wrong is misinformed, not malicious, and does not adapt to the firewall.
4. **One model for every agent.** The live multi-agent run used three different models and found real disagreement that way; using one model here isolates the federation policy at the cost of making the agents more alike than real ones would be.
5. **Retraction is triggered by the environment**, not discovered by an agent. How an origin agent comes to doubt its own memory is a separate question and is not in scope.
6. **Reputation is a success rate per sender**, the simplest thing that could work. If PB3 fails, it fails for that estimator and says nothing about better ones.

## 9. What gets reported

The full sharing-policy × propagation grid for every metric, with intervals; headroom shares per criterion; the per-agent spread alongside every mean; the three hypotheses judged separately; and the verdict against §6, including "killed" or "inconclusive" where that is what the numbers say.
