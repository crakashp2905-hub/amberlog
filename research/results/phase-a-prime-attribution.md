# PA′ — if not blame, then what?

**PA′1 is KILLED. PA′2 is SUPPORTED.** Real attribution recovers most of the
damage naive blame does, and still loses to withdrawing nothing at all. The
product conclusion is the one the registration named in advance: **do not
withdraw memories on outcome evidence at this hazard rate.**

- **Pre-registration:** [phase-a-prime-attribution.md](../prereg/phase-a-prime-attribution.md), written before the arms, with PA′1's failure predicted in §1 and the reason given.
- **Run:** `python -m experiments.phase_a_prime --seeds 5 --episodes 24`, commit `7d71095`, 2026-10-10. 996 model calls, 306,390 tokens, 3,406s wall, `qwen2.5:3b` + `nomic-embed-text`.
- **Raw:** [phase-a-prime-run.txt](phase-a-prime-run.txt) · [phase-a-prime-mechanism.txt](phase-a-prime-mechanism.txt) · [phase-a-prime-decisions.json](phase-a-prime-decisions.json)
- **Also settles** the corrected ceiling that [Phase A](phase-a-real-agent-benchmark.md) could not quote (its amendment 3). PA″ is folded in here.

---

## 1. The table

5 seeds × 24 episodes, paired by (seed, episode). Bootstrap 95% CIs.

| arm | success | correct memory arrived | withdrew | of those correct | tokens | calls/ep |
|---|---|---|---|---|---|---|
| `no_memory` | 0.092 [0.042, 0.142] | 0.000 | 0 | 0 | 173 | 1.00 |
| **`shared_memory`** | **0.608 [0.525, 0.692]** | 0.600 | 0 | 0 | 246 | 1.00 |
| `fabric_blame` | 0.183 [0.117, 0.258] | 0.150 | 87 | 74 | 398 | 1.00 |
| `fabric_loo` | 0.483 [0.400, 0.567] | 0.508 | 23 | 18 | 842 | **2.55** |
| `fabric_contrastive` | 0.350 [0.267, 0.433] | 0.333 | 3 | 3 | 537 | 1.00 |
| `oracle` | 0.658 [0.575, 0.742] | 0.600 | 0 | 0 | 246 | 1.00 |

## 2. Against the pre-registration

| § | Criterion | Result |
|---|---|---|
| 5 | **PA′1** — best withdrawal arm captures ≥ 30% of headroom over `shared_memory` | **KILLED.** `fabric_loo`, the best of the three, is **−0.125 [−0.200, −0.050]** below the baseline. Headroom share −250%. |
| 5 | **PA′2** — `fabric_loo` closes ≥ 50% of the gap to `shared_memory`, interval clear of zero, **and** withdraws fewer correct memories than `fabric_blame` | **SUPPORTED** on all three. Closed **71%** of a 42.5-point gap (+30.0), paired diff **+0.300 [+0.200, +0.400]**, and withdrew 18 correct against blame's 74. |
| 5 | Cost of attribution — reported, not thresholded | **2.55 model calls per episode** against 1.00, and 842 tokens against 246 (**3.4×**). 186 counterfactual calls in all. |
| 5 | Replication check on `fabric_blame` against Phase A's `fabric` | 0.183 [0.117, 0.258] against 0.283 [0.208, 0.367]. Intervals overlap, so the check passes, but see §6. |

**The ceiling, finally.** The corrected oracle — perfect filtering of
wrong-for-here memories at the same k every other arm gets — scores **0.658**
against the pooled baseline's **0.608**. Headroom for selection is **+5.0
points**. That number is the most consequential one in this result and §4 is
about it.

## 3. What the withdrawal rules actually removed

Every withdrawal joined to the episode that triggered it, split four ways:

| arm | withdrew | poisoned | genuinely misled here | **irrelevant** | true here | justified |
|---|---|---|---|---|---|---|
| `fabric_blame` | 87 | 13 | 17 | **57** | 0 | **34%** |
| `fabric_loo` | 23 | 5 | 5 | 13 | 0 | **43%** |
| `fabric_contrastive` | 3 | 0 | 0 | 3 | 0 | 0% |

**Two thirds of naive blame's withdrawals were memories about a completely
different fault.** This is Phase A's §6a claim, now measured instead of
inferred: six actions span six fault codes, so the memory that asserted what the
agent wrongly said was usually a correct lesson about a different situation that
happened to name the same action. It was never applicable, it was never wrong,
and it was withdrawn.

`true here` is zero everywhere, which is the expected shape rather than a
surprise: a memory correct for *this* episode would not have asserted the wrong
action the agent gave. The damage is not that these rules blamed a memory that
was right for the episode in front of them. It is that they removed, globally,
memories whose only fault was naming an action that came up in a situation they
did not apply to — and those memories were needed later, at their own site.

**Leave-one-out's 13 "irrelevant" withdrawals are a finding about leave-one-out.**
A counterfactual asks "would this episode have succeeded without this memory?",
and sometimes the answer is yes for a memory that is not wrong but merely
*distracting* — removing it shortens the context and the model lands on the
right answer. So leave-one-out conflates "this memory is wrong" with "this
memory was in the way". That is a real limitation of the method, not of this
implementation, and it is why its precision is 43% rather than near 100%.

## 4. Why no withdrawal policy can win here

Three measurements together explain the whole result.

**Coverage is the only channel.** Decomposing each arm's success into
P(a correct memory arrived) × P(right | it did) + P(none) × P(right | none):

| arm | success | coverage | P(right given one) | P(right given none) | share of success from memory |
|---|---|---|---|---|---|
| `oracle` | 66% | 60% | 94% | 23% | 86% |
| `shared_memory` | 61% | 60% | 93% | 12% | 92% |
| `fabric_loo` | 48% | 51% | 93% | 2% | 98% |
| `fabric_contrastive` | 35% | 33% | 98% | 4% | 93% |
| `fabric_blame` | 18% | 15% | 72% | 9% | 59% |

P(right | a correct memory arrived) is **93–98%** for every arm that keeps its
store. The model is not the variable and the *presentation* is not the variable.
Rank correlation between coverage and success across the arms is **+0.975**: they
are ordered by coverage and by essentially nothing else.

**So a withdrawal policy can only act through coverage, and withdrawal only
lowers it.** The degradation figures are unambiguous — correct memories reaching
the prompt, first third against last:

| arm | 1st | 2nd | 3rd | change |
|---|---|---|---|---|
| `shared_memory` / `oracle` | 42% | 57% | 80% | **+37.5%** |
| `fabric_loo` | 40% | 40% | 72% | +32.5% |
| `fabric_contrastive` | 40% | 38% | 22% | **−17.5%** |
| `fabric_blame` | 25% | 15% | 5% | **−20.0%** |

The corpus is released progressively, so every arm has more correct material
available as the run proceeds. The arms that withdraw nothing ride that upward.
`fabric_loo` very nearly keeps up, which is why it recovers most of blame's
damage. The other two go down against a rising tide.

**And there was almost nothing to win.** Selection headroom is +5.0 points,
because a pooled top-3 over this corpus rarely surfaces a wrong-for-here memory
in the first place. The binding constraint is not which memories are shown but
whether a correct one **exists in the corpus yet** — a coverage problem, which
belongs to memory *construction* rather than governance. MemBuilder
([PRIOR_ART.md](../PRIOR_ART.md)) is the work that attacks it, and nothing in
this project does.

## 5. What this means for the product

**Unchanged and now doubly evidenced:** do not withdraw memories because they
were in context when something failed. Phase A measured the damage; PA′ measured
it again at 5 seeds with the withdrawals itemised, and shows that the best
available repair still loses.

**New:** do not withdraw on outcome evidence *at all* at this hazard rate. The
registration said in §1 that this was the likely finding and why — the corpus
holds far more useful lessons than harmful ones, so any withdrawal policy is a
bet against that ratio. It is a stronger claim than "naive blame is bad", and it
is the claim the data supports.

The `WithdrawalBasis` machinery added after Phase A is the right response and
does not need changing: `co_occurrence` and `unstated` are flagged, and the two
rules measured here would both be recorded as weak. What PA′ adds is that
`contrastive_harm` — which the product treats as a *strong* basis — withdrew
three memories across 120 episodes and all three were irrelevant to the episode
that triggered them. On this evidence it is not a strong basis either, only a
rare one, and the honest change is to say so rather than to leave it implying
more than it has earned.

## 6. What this does not show

1. **`fabric_contrastive` did not get a fair test.** Its arm ran under the exposure defect recorded in [this decision](../decisions/2026-10-10-value-ranking-ignores-uncertainty.md): ranking on value reads the mean and ignores `n_eff` and the interval, so a single observation with an interval spanning zero outranks an unevaluated memory nineteen times more relevant. The registration stated the confound in advance (§3) and the decision record characterised the mechanism before this run's numbers were seen. Its registered question — does withdrawing on contrastive harm beat withdrawing nothing — **has not actually been asked yet**, and must be re-asked under a ranking that respects its own intervals.
2. **The replication is lower than Phase A's.** `fabric_blame` at 0.183 [0.117, 0.258] against Phase A's `fabric` at 0.283 [0.208, 0.367]: the same policy, overlapping intervals, so the registered check passes. But the point estimate is 10 points lower, and the explanation is corpus variation — the model writes the corpus afresh each run at temperature 0, and Ollama is not bit-deterministic. That is a limit on how precisely any of these numbers should be read, and it applies to all of them.
3. **Leave-one-out needs a verifier per episode**, which many tasks do not have. §7.3 of the registration called its result an upper bound rather than a recipe, and that stands: it cost 2.55 model calls per episode to buy a result that still lost.
4. **One model, 3B.** P(right | correct memory) at 93–98% may be specific to a model this size. A larger model that reasons past a wrong memory would compress every effect here.
5. **The hazard rate is a parameter.** 25% poisoning and one exception site in three. A world with far more harmful memories than useful ones would change the bet a withdrawal policy is making, and nothing here measures where that crossover sits.
6. **24 episodes.** Short enough that an exploration-based estimator cannot repay its cost, as Phase A also noted.

## 7. The honest summary

> Naive blame destroys an agent's memory, and two thirds of what it destroys was
> never even relevant to the failure it was blamed for. Real counterfactual
> attribution fixes most of that — it withdraws a quarter as much and recovers 71%
> of the lost accuracy — at 2.55 model calls per episode, and it still loses to
> withdrawing nothing. The reason is that success in this world is determined
> almost entirely by whether a correct memory reaches the prompt, every withdrawal
> policy can only lower that, and perfect selection over the corpus was worth just
> five points anyway. The remaining gap is coverage, which is a different problem
> than the one this project is built to solve.
