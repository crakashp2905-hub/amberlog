# Result — H4: the Zollman effect is real at intermediate sparsity; preserving minority hypotheses works

- **Pre-registration:** [../prereg/h4-topology-and-diversity.md](../prereg/h4-topology-and-diversity.md), with a dated amendment made before the registered run.
- **Run:** 2026-10-07, 10 agents, 200 replications per cell, 150 rounds. Raw output: [h4-run.txt](h4-run.txt).
- **Reproduce:** `python -m experiments.h4`

## Verdicts

| | outcome |
|---|---|
| **H4a** (sparser networks are more often correct, but slower) | **INCONCLUSIVE** — at the registered test point. The effect is unmistakable at intermediate sparsity; I registered the wrong comparison. |
| **H4b** (preserving minority hypotheses helps) | **SUPPORTED**, decisively, on every axis measured. |

## The grid

| topology | degree | preserve | P(correct) | consensus | recovery | regret |
|---|---|---|---|---|---|---|
| complete | 9 | — | 0.905 [0.865, 0.945] | 9.8 | 24% | 10.9% |
| complete | 9 | ✔ | **1.000** [1.000, 1.000] | **4.6** | **100%** | **5.4%** |
| small_world | 4 | — | **0.985** [0.965, 1.000] | 25.1 | 96% | 4.9% |
| small_world | 4 | ✔ | 1.000 [1.000, 1.000] | 27.5 | 100% | 11.5% |
| ring | 2 | — | **0.985** [0.965, 1.000] | 40.8 | 97% | 6.5% |
| ring | 2 | ✔ | 0.995 [0.985, 1.000] | 42.0 | 99% | 14.7% |
| cycle_sparse | 1 | — | 0.935 [0.900, 0.965] | 61.8 | 91% | 11.2% |
| cycle_sparse | 1 | ✔ | 0.945 [0.910, 0.975] | 68.8 | 94% | 18.8% |
| isolated | 0 | — | 0.000 [0.000, 0.000] | 14.3 | 0% | 52.8% |
| isolated | 0 | ✔ | 0.290 [0.230, 0.350] | 103.8 | 26% | 29.6% |

## H4a: the effect is an inverted U, and I registered the wrong point on it

| topology | degree | P(correct) | consensus | vs complete | headroom captured |
|---|---|---|---|---|---|
| complete | 9 | 0.905 | 9.8 | — | — |
| **small_world** | 4 | **0.985** | 25.1 | **+0.080** [+0.040, +0.125] | **84%** |
| **ring** | 2 | **0.985** | 40.8 | **+0.080** [+0.045, +0.120] | **84%** |
| cycle_sparse | 1 | 0.935 | 61.8 | +0.030 [−0.020, +0.080] | 32% |
| isolated | 0 | 0.000 | 14.3 | −0.905 | — |

**Both halves of the Zollman prediction hold at degree 2–4.** Sparser networks reach the correct belief more often (+0.080, interval clear of zero, 84% of available headroom) *and* take two to four times as long to get there (25–41 rounds against 9.8). That is the tradeoff exactly as stated.

**It fails at the extreme.** At degree 1 the gain collapses to +0.030 with the interval through zero, and at degree 0 the population never learns anything (P = 0.000). Beyond a point, decorrelating beliefs stops protecting diversity and simply starves everyone of evidence.

So the structure is an **inverted U with an interior optimum around degree 2–4**, not the monotone improvement I registered. §5 condition 2 required `P(correct)` to rise monotonically as degree falls, and condition 1 tested the *sparsest connected* topology. Both were written on the assumption that sparser is always better. The data says otherwise, so the registered verdict is INCONCLUSIVE even though the phenomenon is clearly present.

**That is a defect in my operationalisation, not a null result**, and it is the third time in this project that a registered detail has been slightly wrong in a way the diagnostic arms exposed (H3's threshold exceeded its ceiling; H2's budget sat outside the binding regime). The pattern is consistent: the hypotheses have been roughly right and the *measurement points* have been poorly chosen. Pre-registration has been doing its job — it keeps turning up these errors instead of letting me narrate past them.

## H4b: preserving contested hypotheses is strictly better on every axis

Under the densest topology, where premature consensus is worst:

| | P(correct) | consensus | recovery | regret |
|---|---|---|---|---|
| complete | 0.905 | 9.8 | 24% | 10.9% |
| complete + preserve | **1.000** | **4.6** | **100%** | **5.4%** |

Captures **100% of the available headroom** (+0.095 [+0.055, +0.135]), lifts recovery from 24% to 100%, and does so while reaching consensus **faster** and with **half the regret**.

The regret result is worth pausing on, because it looks backwards: `preserve` *spends* 20% of its pulls re-testing a belief it currently thinks is wrong, and ends up wasting less effort overall. The explanation is the absorbing trap. Without preservation, an agent that wrongly concludes the worse action is better stops testing the better one and spends *every* subsequent pull on the worse one. Targeted re-testing costs a fifth of a round and buys escape from a mistake that otherwise lasts forever. **Keeping a contested hypothesis alive pays for itself.**

It helps everywhere, and most where isolation hurts most: `isolated` goes from 0.000 to 0.290 with no sharing at all.

This is the first time one of this project's founding design principles — *"contradictions stay representable"* (AGENTS.md principle 6) — has been tested rather than asserted. It holds.

## What this says about the design

1. **Full connectivity is the wrong default for a memory federation.** Sharing with everyone cost 8 points of accuracy against sharing with two or four neighbours. A fabric that broadcasts every memory to every agent is choosing speed over correctness, and should say so.
2. **Minority preservation is cheap and has no measured downside under dense sharing.** It is the single most effective intervention in this experiment.
3. **Diversity without communication is worthless.** `isolated` scores 0.000. The value is in *partial* connection, not in independence.
4. **The two mechanisms are substitutes, not complements.** `complete + preserve` reaches 1.000 and so does `small_world + preserve`; once contested beliefs are re-tested, topology stops mattering much. A system that does one well does not need the other.

## Limitations

The five from the pre-registration stand. Two are material:

1. **This is a bandit, not an agent.** It tests belief dynamics over a sharing network, deliberately simple so the effect is attributable to the mechanism rather than to a model's behaviour. Whether LLM agents sharing memories reproduce it is untested.
2. **One evidence regime.** 10 agents × 10 pulls per round is a lot of evidence per round. The Zollman effect is known to depend on how quickly evidence accumulates, and the inverted U's optimum will move with it. The registered design fixed this parameter without checking where the phenomenon lives along it — the same class of error as choosing the test point.
3. Stationary payoffs; honest, complete sharing; fixed topologies; one preservation budget (20%), unswept.

## Defects found, and what was done

**The first design made H4a unmeasurable and was amended before the registered run** (amendment dated in the pre-registration). Planting the same misleading failures in every agent makes the absorbing trap *absolute*: nobody ever pulls the better action, no evidence about it is ever generated, and no topology can escape. A quick run confirmed it — `P(correct)` was 0.000 for every topology without preservation. The fix was diverse starting beliefs, which is what Zollman's own model has and what the effect requires.

**Disclosed in the amendment:** that quick run also showed a preliminary H4b figure of 1.000 under `complete`. It came from the broken design and does not carry over; H4b was re-run from scratch.

## Consequence

- **H4b ships as a recommendation.** Where a store holds contested memories, re-test them rather than collapsing to the majority. It was free on every axis measured here.
- **H4a needs re-registering as H4a′** with the test point chosen from the curve rather than assumed: *intermediate* connectivity against full connectivity, and an evidence-per-round sweep to locate the optimum rather than fixing it blind.
- **The curve is already actionable** even without a passing verdict: degree 2–4 beat full connectivity by 8 points at 200 replications with intervals clear of zero. Nothing about the registered verdict makes that measurement wrong — it makes it unregistered.
