# Pre-registration — PA′: if not blame, then what?

- **Written:** 2026-10-10, before the arms were built. Phase A is closed and killed.
- **Why:** [Phase A](../results/phase-a-real-agent-benchmark.md) established that withdrawing the memory which *asserted the action the agent wrongly took* makes an agent much worse — it cut the rate at which a correct memory reached the prompt from 60% of episodes to 18%. It did not establish what to do instead, and the product still offers a one-command `quarantine` to operators who will reach for exactly that rule.
- **Second job:** this run carries the **corrected oracle** (amendment 3 of Phase A's registration), which settles the ceiling Phase A could not quote. PA″ is folded in here rather than run separately, because a re-run with the old arms and the new oracle would cost the same compute and answer less.

Thresholds in §5 are fixed now and are not revised after seeing results.

---

## 1. Hypotheses

**PA′1 (there is a withdrawal policy worth having).** Some policy for withdrawing
memories beats withdrawing nothing at all.

**PA′2 (attribution is the fix).** Leave-one-out attribution — would this episode
have succeeded *without* this memory? — recovers most of the damage that naive
blame caused.

**What this registration expects.** PA′1 is **predicted to fail.** Phase A found
that in this world more memory is almost always better: every arm converted a
correct memory into a correct answer ~95% of the time, the corpus contains far
more useful lessons than harmful ones, and any withdrawal policy is a bet against
that ratio. Writing the prediction down now is the point — if PA′1 fails, the
conclusion is that *the product should not withdraw memories on outcome evidence
at this hazard rate at all*, which is a stronger and more useful claim than
"naive blame specifically is bad".

PA′2 can hold while PA′1 fails: leave-one-out may recover most of blame's damage
and still not reach the no-withdrawal baseline. That is the most likely single
outcome and is reported as such, not rounded into a win.

## 2. World

DepotWorld, unchanged from Phase A (`experiments/depotworld.py`), same seeds,
same 18-lesson corpus per seed written by the model, same 24 evaluation episodes,
same progressive release. Reusing it exactly is deliberate: PA′'s numbers have to
be comparable to Phase A's arm for arm, and a changed world would make the
comparison an argument instead of a measurement.

## 3. Arms

| id | On a verified failure, withdraw… | Extra model calls |
|---|---|---|
| `no_memory` | — (floor) | 0 |
| `shared_memory` | nothing. **The baseline to beat** — it won Phase A | 0 |
| `fabric_blame` | the memory that asserted the action the agent took. **The killed policy**, carried over so the recovery can be measured against it | 0 |
| `fabric_loo` | only a memory whose removal would have produced the correct answer | up to k per failure |
| `fabric_contrastive` | only a memory whose contrastive value estimate shows harm with its interval below zero | 0 |
| `oracle` | — (ceiling; perfect filtering at k=3, per Phase A amendment 3) | 0 |

`fabric_blame` is Phase A's `fabric` arm under a name that says what it does. The
rename is for the write-up only; the policy is identical, so its score here is
also a replication check on Phase A.

**`fabric_loo` is the expensive one, and its cost is a result, not an
inconvenience.** On each failed episode it re-asks the model once per memory that
was in context, with that memory removed, and withdraws only those whose absence
would have produced the correct answer. This is the screening step MeClear uses
([PRIOR_ART.md](../PRIOR_ART.md)), and PRIOR_ART already notes that MeClear
benchmarks *against* leave-one-out rather than against a cheap baseline. Phase A
supplied the cheap baseline and found it harmful. So this run asks the question
neither has: does real attribution beat no attribution at all, and what does it
cost.

**`fabric_contrastive` is the fabric's own answer**, using the machinery the
project actually ships: withdraw only when the value estimate is contrastive and
its credible interval lies below zero. It needs overlap to exist, so it runs
under the same epsilon-greedy exposure policy `fabric_causal` used in Phase A —
which Phase A found carries a cost of its own. That confound is stated here
rather than discovered later: a loss by this arm cannot be cleanly attributed
between the withdrawal rule and the exploration it requires, and separating them
needs a further arm this run does not have.

## 4. Metrics

Same as Phase A, so the two are comparable:

- `success`, environment-verified.
- `right_memory_rate` — share of episodes in which at least one correct memory reached the prompt. Phase A showed this is nearly the whole story, so it is promoted to a primary metric here rather than left in the analysis.
- `harmful_memory_rate`, `contamination`.
- `withdrawals` — how many memories each policy withdrew, and **how many of them were correct memories.** This is the diagnostic that matters: a policy can look fine on success while quietly destroying good material, and Phase A only found that by looking.
- `tokens` and `model_calls`, including the counterfactual calls `fabric_loo` makes. Cost is a first-class metric (AGENTS.md).
- `degradation` — success in the final third minus the first third.

## 5. Ceiling and thresholds

Ceiling is `oracle` (corrected). Baseline is `shared_memory` — not the weakest
arm but the arm that *won Phase A*, so nothing here can be won against a
strawman.

**PA′1 supported** if the best withdrawal arm captures **≥ 30%** of the headroom
between `shared_memory` and `oracle` on success, with the bootstrap interval on
the paired difference against `shared_memory` clear of zero.

**PA′1 killed** if no withdrawal arm beats `shared_memory` on success. The
conclusion then is a product conclusion: do not withdraw memories on outcome
evidence at this hazard rate, and say so in the tool that makes it easy.

**PA′2 supported** if `fabric_loo` closes **≥ 50%** of the gap between
`fabric_blame` and `shared_memory`, interval clear of zero, **and** withdraws
fewer correct memories than `fabric_blame` does. Both conditions: closing the gap
while destroying the same amount of good material would mean the recovery came
from somewhere else.

**PA′2 killed** if `fabric_loo` does not beat `fabric_blame`.

**The cost of attribution is reported, not thresholded.** `fabric_loo`'s extra
model calls are its defining property, and a number is more useful than a
pass/fail: the result states calls and tokens per episode against
`shared_memory`, so a reader can judge whether any accuracy it buys is worth it.

**Replication check, stated in advance.** `fabric_blame` should land near Phase
A's `fabric` (0.283 [0.208, 0.367]). If it does not, something changed between
the runs and both results are suspect until the difference is explained — that
check is registered now so it cannot be waved away later.

## 6. Design

- **Model:** `qwen2.5:3b`, `nomic-embed-text`. Same as Phase A.
- **Seeds:** 5 (0–4). **Episodes:** 24. 6 arms → 720 verified decisions plus the counterfactual calls.
- **Statistics:** paired by (seed, episode). Bootstrap CIs, 10,000 resamples.
- **Verification:** the environment, including for the counterfactual re-asks.

## 7. Stated limitations (written now)

1. **One model, 3B.** Phase A's finding that every arm uses a correct memory ~95% of the time may be specific to a model this size; a model that reasons past a wrong memory would shrink every effect.
2. **`fabric_contrastive` carries a confound** between its withdrawal rule and the epsilon-greedy exploration its estimate requires, as §3 states.
3. **Leave-one-out here is evaluated against the verified answer**, which a deployment cannot always do — many tasks have no cheap verifier, and where there is none this arm is not implementable at all. Its result is an upper bound on what attribution can buy, not a deployable recipe.
4. **24 episodes.** Phase A noted this is exactly the horizon at which exploration cannot repay itself. The same caveat applies to `fabric_contrastive`.
5. **The hazard rate is a parameter** (25% poisoning, one exception site in three), chosen to make effects measurable. Every conclusion is "at this hazard rate", and a world with far more harmful memories might make withdrawal pay.

## 8. What gets reported

The arm × metric table with intervals; the corrected ceiling and the headroom it
reveals; both hypotheses judged separately; the withdrawal counts split into
correct and incorrect memories; the cost of attribution in calls and tokens; the
`fabric_blame` replication check against Phase A; and the verdict against §5
including "killed", which §1 states is the expected outcome for PA′1.
