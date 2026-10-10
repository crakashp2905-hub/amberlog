# Phase C — can a population learn what should propagate?

**Reported as exploratory. PC is neither supported nor killed**, because its gate
did not pass: [PB1 was killed](phase-b-federated-agents.md), so a threshold
applied to a surface already measured to be flat is not a test. The numbers
below describe; they do not judge.

What they describe is worth more than a verdict would have been. **The outcome
channel the whole design depends on made the population measurably worse** —
−0.042 [−0.081, −0.005], interval clear of zero — and the arm that found the
true sharing structure *best* performed *worst*.

- **Pre-registration:** [phase-c-memory-ecology.md](../prereg/phase-c-memory-ecology.md), with a dated amendment moving the gate from "do not build" to "do not call it a registered test", and recording 3 seeds × 16 rounds with the reason.
- **Run:** `python -m experiments.phase_c --seeds 3 --rounds 16 --best-fixed share_overlap`, 2026-10-11. 2,556 model calls, 1,093,202 tokens, 29,671s wall (8h 14m).
- **Raw:** [phase-c-run.txt](phase-c-run.txt) · [phase-c-decisions.json](phase-c-decisions.json)
- 8 agents, overlapping territories, 16 rounds each, 3 seeds → **384 decisions per arm**.

The chaining script resolved both `best_fixed` (from Phase B's winning selective
policy) and the exploratory flag (from PB1's verdict) by reading Phase B's own
output, so neither was chosen after seeing these numbers.

---

## 1. The table

| arm | success | worst agent | spread | imports (wrong) | value~spread | graph match |
|---|---|---|---|---|---|---|
| `isolated` | 0.544 [0.495, 0.594] | 38% | 33% | 0 | undefined | — |
| `share_all` | 0.724 [0.680, 0.768] | 56% | 31% | 1764 (1060) | undefined | — |
| `best_fixed` | 0.727 [0.682, 0.771] | 58% | 35% | 936 (232) | −0.005 (n=142) | — |
| `learned` | 0.703 [0.659, 0.750] | 56% | **27%** | 1764 (1060) | undefined | **0.753** |
| **`learned_no_feedback`** | **0.745 [0.703, 0.786]** | **60%** | **25%** | 1764 (1060) | undefined | 0.679 |
| `oracle_share` | 0.797 [0.755, 0.839] | 58% | 33% | 704 (0) | +0.048 (n=150) | — |

**The ceiling held.** `oracle_share` at 0.797 is above every arm, and the
automatic principle 8b check confirmed it: *"no arm beat oracle_share"*. That is
the first time in this project a ceiling has survived its own run — H3's
threshold exceeded its ceiling, Phase A's oracle had a smaller retrieval budget
than the arms it bounded, and Phase B's poisoned its own recipients. Headroom
here is a real +7.0 points.

## 2. What the numbers say, without judging

**Federation helps, again.** Any arm that shares beats isolation by 16–20 points,
intervals clear. Consistent with Phase B.

**The learner did not beat the fixed policy.** `learned` 0.703 against
`best_fixed` 0.727 — paired diff −0.023 [−0.060, +0.013], interval spanning
zero — and its worst agent fell, 58.3% → 56.2%. Had the gate passed and this
been a registered test, PC would have been killed on both counts. §1 of the
registration predicted exactly this and said why: *"a learned policy that
merely matches `share_overlap` has established that the ecology metaphor buys
nothing a static rule did not already buy."*

**The outcome channel is worse than inert — it is harmful.** This is the finding.

`learned_no_feedback` is fed only the sender's *own* outcomes.
`learned` is additionally fed the recipient's verified outcomes, which is the
expensive part of the design: a real federation needs an outcome channel, not
just a memory channel. The comparison:

> `learned` − `learned_no_feedback` = **−0.042 [−0.081, −0.005]**

Interval clear of zero, and negative. The registration anticipated a tie and
named it the H2 shape of finding — *"if the two tie, the channel is inert and
the expensive part of the design earned nothing."* It did not anticipate the
channel making things worse, and on 3 seeds and 384 decisions per arm it did.

## 3. The most interesting thing here

**The arm that found the true structure best performed worst.**

`learned` matched the real territory-overlap graph at **0.753**;
`learned_no_feedback`, fed strictly less information, matched it at **0.679**.
So the outcome channel *did* work as a learning signal — it taught the
population more about who overlaps with whom — and the population did worse for
knowing.

Structural fidelity and outcome came apart, and the reason is the finding that
has dominated every live phase: **success is governed by whether a correct memory
reaches the prompt, not by who sent it.** A learner that sharpens its sharing
graph is optimising a variable that is nearly irrelevant to the outcome, and
paying for the optimisation in coverage. Both learners ended up sharing
everything anyway — 1,764 imports each, identical to `share_all` — so what the
better graph bought was not less sharing. It was a differently-ordered exposure
that happened to be worse.

This is the third phase in a row where the same mechanism explains the result
([Phase A](phase-a-real-agent-benchmark.md), [PA′](phase-a-prime-attribution.md),
and now PC). At some point that stops being a coincidence about one world.

## 4. The ecology claim: undefined, not weak

The registration thresholded the ecology claim **separately** from PC, on whether
propagation correlates with measured value, because a population can improve by
learning sharing rules while propagation stays uncorrelated with value — and
that would mean the selective-pressure story is wrong even though the learning
story works.

The answer is that the correlation is **undefined for every learning arm**:

> undefined (spread is constant: everything reached every store)

Both learners converged on sharing with everyone, so every memory reached all
eight stores and there is no variance in spread for value to correlate *with*.
That is an opposite finding to "no relationship found", and `describe_rho`
exists to keep the two apart — a bare `NaN` would have read as a weak
correlation.

Where it is computable, it is ~zero: `best_fixed` **−0.005** (n=142) and
`oracle_share` **+0.048** (n=150), against a threshold of 0.3.

**So propagation does not track measured value. This is drift, not selection.**
The memory-ecology metaphor from the founding document — memories selected for,
inherited, going extinct — is not what these populations do. They share
everything and the spread of a memory is unrelated to whether it helps.

## 5. What this does not show

1. **No verdict is being reported.** The gate held and PC is exploratory. A reader wanting "is the learner better?" should read this as "not on this evidence, and the question was not properly asked".
2. **The learner is a bandit over recipients** (§6.5 of the registration). It cannot represent "share this *kind* of memory with that agent", which is what the founding document actually describes. These numbers rule out the cheap policy class, not a richer one.
3. **3 seeds, not 5** — amended before the run, trading seeds for rounds because a bandit over seven recipients cannot learn in a handful of rounds. The cost is less protection against an unlucky world draw, and seed variance here is large: `best_fixed` ran 80%, 75%, 63% across the three.
4. **The outcome channel is assumed available.** Many real federations cannot report verified outcomes between stores. That this one *hurt* makes the point moot here, but a positive result would have been bounded more tightly than it looked.
5. **One model, 8 agents, stationary world.** An ecology's interesting behaviour is mostly in non-stationary environments, which this does not measure.
6. **Every arm ran under the exposure defect** recorded [here](../decisions/2026-10-10-value-ranking-ignores-uncertainty.md) — ranking on value read the mean and ignored the interval. Held constant across arms by amendment, so it cannot bias one against another; it was fixed after this run finished.

## 6. The honest summary

> A population of eight agents, each adjusting who it shares with from observed
> outcomes, did not beat the fixed sharing policy it was asked to beat — and the
> outcome channel the design requires made it measurably worse, not merely
> inert. The arm fed that channel learned the true overlap structure *better*
> (0.753 against 0.679) and performed *worse*, because what governs the outcome
> is whether a correct memory reaches the prompt rather than who sent it.
>
> Propagation was uncorrelated with measured value wherever it could be
> computed, and undefined everywhere else because both learners converged on
> sharing with everyone. Whatever these populations do, it is not selection.
>
> No verdict is reported. The gate was written before any federation number
> existed and it held.
