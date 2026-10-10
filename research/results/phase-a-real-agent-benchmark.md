# Phase A — governed memory against a vector store, with a real agent

**Verdict: PA is KILLED.** Governed memory lost to an ungoverned vector store by
34 points, and the governance mechanism that caused the loss is the one this
project would have recommended.

- **Pre-registration:** [phase-a-real-agent-benchmark.md](../prereg/phase-a-real-agent-benchmark.md), written before the world, with three dated amendments, all made before or during the run and all disclosing what prompted them.
- **Run:** `python -m experiments.phase_a --seeds 5 --episodes 24`, commit `c769758`, 2026-10-08. 1,050 model calls, 280,062 tokens, 5,111s wall, `qwen2.5:3b` + `nomic-embed-text` through Ollama.
- **Raw:** [phase-a-run.txt](phase-a-run.txt) · [phase-a-mechanism.txt](phase-a-mechanism.txt) · [phase-a-decisions.json](phase-a-decisions.json) (960 per-episode records) · [pilot](phase-a-pilot.txt)

---

## 1. The table

5 seeds × 24 episodes, paired by (seed, episode). Bootstrap 95% CIs.

| arm | success | harmful | contam | tokens | mem ms | 1st third | 3rd third |
|---|---|---|---|---|---|---|---|
| `no_memory` | 0.075 [0.033, 0.125] | 0.000 | 0% | 173 | 0.0 | 5% | 12% |
| `local_rag` | 0.558 [0.467, 0.650] | 0.375 | 2% | 237 | 0.8 | 40% | 78% |
| `shared_memory` | 0.558 [0.467, 0.650] | 0.383 | 8% | 241 | 1.6 | 40% | 75% |
| **`shared_memory_framed`** | **0.583 [0.500, 0.675]** | 0.400 | 8% | 356 | 1.5 | 38% | 80% |
| `shared_memory_decay` | 0.133 [0.075, 0.200] | 0.358 | 7% | 198 | 0.3 | 25% | 10% |
| `fabric` | 0.283 [0.208, 0.367] | 0.550 | 10% | 415 | 1.1 | 38% | 18% |
| `fabric_causal` | 0.242 [0.167, 0.317] | 0.550 | 10% | 414 | 1.7 | 25% | 22% |
| `oracle` | 0.633 [0.550, 0.717] | 0.000 | 0% | 192 | 0.0 | 42% | 80% |

## 2. Against the pre-registration

`best_ungoverned = shared_memory_framed` at 0.583.

| § | Criterion | Result |
|---|---|---|
| 6.1 | `fabric_causal` captures ≥ 50% of success headroom | **FAIL.** Paired diff **−0.342 [−0.442, −0.242]** |
| 6.2 | `fabric_causal` cuts harm by ≥ 50% of harm headroom | **FAIL.** Harm *rose*: **+0.150 [+0.050, +0.258]** |
| 6.3 | `memory_induced_improvement` > 0, interval clear of zero | **PASS.** **+0.167 [+0.083, +0.250]** |
| — | Cost gate: ≤ 1.5× tokens, ≤ 50 ms added latency | Within: 1.16×, +0.2 ms |

§6 states: *"PA killed if `fabric_causal` does not beat `best_ungoverned` on
success at all."* It does not beat it; it loses by 34 points with the interval
nowhere near zero.

**The kill does not depend on the broken oracle.** The third amendment records
that the first oracle was mis-specified, and that criteria 6.1 and 6.2 express
shares of the headroom it revealed. Those *shares* are not trustworthy on this
run. The kill condition is a direct arm-to-arm comparison that never mentions
the oracle, and the margin is far outside what any ceiling correction could
reach: the best conceivable ceiling is 1.000, giving 0.417 of headroom, and
`fabric_causal` sits 0.342 *below* the baseline. There is no ceiling at which
this passes. The re-run with the corrected oracle is still worth doing — the true
ceiling matters for the follow-up design — but it will not change this verdict.

## 3. What actually determined the outcome

One number explains nearly all of it. Conditioning each episode on whether a
correct memory reached the prompt:

| arm | success given a correct memory was shown | n | given none was | n |
|---|---|---|---|---|
| `local_rag` | 93% | 67 | 9% | 53 |
| `shared_memory` | 92% | 72 | 2% | 48 |
| `shared_memory_framed` | 96% | 72 | 2% | 48 |
| `shared_memory_decay` | 100% | 5 | 10% | 115 |
| `fabric` | 95% | 21 | 14% | 99 |
| `fabric_causal` | 93% | 15 | 14% | 105 |
| `oracle` | 95% | 79 | 2% | 41 |

**Every arm converts a correct memory into a correct answer about 95% of the
time, and fails about 95% of the time without one.** The model is not the
variable. Nothing in the arms changes how well the memory is *used*; they differ
only in how often one arrives. `shared_memory` delivered a correct memory in 72 of
120 episodes (60%), `fabric` in 21 (18%), `fabric_causal` in 15 (12%), and
`shared_memory_decay` in 5 (4%).

The live validation in P-phase had already measured the first half of this — a
correct memory took accuracy from 6.7% to 100%, a wrong one misled every model.
Phase A's contribution is the second half: under governance that withdraws
memories, the correct memory stops arriving.

## 4. The mechanism: withdrawal removes the wrong memories

The analyser's prediction, registered before the verdict was known: if
over-pruning is the mechanism, correct memories reaching the prompt should fall
for the withdrawing arms and hold or rise for the arms that withdraw nothing,
over the identical episode sequence and the identical released corpus.

**Correct memories reaching the prompt**, by third of the run:

| arm | 1st | 2nd | 3rd | change | withdraws? |
|---|---|---|---|---|---|
| `local_rag` | 0.30 | 0.55 | 0.82 | **+0.52** | |
| `shared_memory` | 0.42 | 0.65 | 0.88 | **+0.45** | |
| `shared_memory_framed` | 0.42 | 0.65 | 0.88 | **+0.45** | |
| `oracle` | 0.45 | 0.70 | 0.82 | **+0.37** | |
| `shared_memory_decay` | 0.12 | 0.03 | 0.00 | **−0.12** | yes |
| `fabric` | 0.28 | 0.17 | 0.10 | **−0.18** | yes |
| `fabric_causal` | 0.12 | 0.15 | 0.12 | ±0.00 | yes |

Clean separation, no overlap between the groups. The corpus is released
progressively, so every arm has *more* correct material available as the run
proceeds. The non-withdrawing arms ride that upward; the withdrawing arms go
down against it.

**And the wrong memories stayed.** Withdrawal is supposed to remove those:

| arm | 1st | 2nd | 3rd | change |
|---|---|---|---|---|
| `shared_memory` | 0.33 | 0.17 | 0.17 | −0.15 |
| `shared_memory_decay` | 0.10 | 0.05 | 0.12 | **+0.02** |
| `fabric` | 0.23 | 0.23 | 0.25 | **+0.02** |
| `fabric_causal` | 0.30 | 0.10 | 0.25 | −0.05 |

The withdrawing arms removed correct memories and left wrong ones in place. They
worked precisely against themselves. Total memories reaching the prompt collapsed
— `shared_memory_decay` 1.80 → 0.55, `fabric` 2.98 → 1.45 — against a flat 3.00
for the pooled arms.

### Why the blame rule picks the wrong memory

`shared_memory_decay` withdraws everything that was in context at a failure,
which over-prunes by construction and is the registered baseline's own fault.
The `fabric` arms are the interesting case, because their rule is narrower and
looks principled: withdraw the memory that *asserted the action the agent took*,
when that action was wrong.

Six actions are shared across six fault codes. So the memory that asserted what
the agent wrongly said is very often a **correct memory about a different
fault** — correct where it was written, correct where it will be needed, and
quarantined for agreeing with a mistake it had nothing to do with. The blame rule
matches on surface agreement with the agent's output, and surface agreement is
not attribution.

This is the same confusion the project names in its first principle, arriving
from an unexpected direction. Principle 1 says value is not relevance. Phase A
adds: **agreement is not causation.** A memory that says what you said is not
thereby the reason you said it.

`fabric_causal` was supposed to be the answer to exactly this — propensity-
corrected credit instead of naive blame — and it was the *worst* of the governed
arms at 0.242. Its epsilon-greedy policy withholds a fifth of exposures to create
the overlap the estimator needs, and 24 episodes never repay that cost. H1
measured the estimator recovering true value at ρ=0.604; H2 found that accuracy
did not transfer to the retention decision; Phase A finds it does not transfer to
the live exposure decision either, and that the exploration it requires is
itself a harm at this horizon.

## 5. The ablation earned its place

`shared_memory_framed` — pooled, zero governance, rendered in the fabric's
provenance-and-caveats framing — was the best non-oracle arm at 0.583, and it was
added by amendment four hours before the run because the pilot exposed the
confound. Without it the comparison would have been governance-with-framing
against vector-store-with-plain-text, and a 0.583-vs-0.558 framing effect would
have been scored as a governance effect.

It is a small effect and its interval overlaps the plain arms heavily
([0.500, 0.675] against [0.467, 0.650]), so the honest statement is: **the
framing is worth at least as much as the governance, and the governance is worth
less than nothing.** It also costs 48% more tokens (356 vs 241) for that
difference, which makes it a poor trade on its own terms.

## 6. What survived

**Memory works, and the effect is large.** `no_memory` scores 0.075;
every non-withdrawing memory arm scores 0.558–0.583. Criterion 6.3 passes with
+0.167 for `fabric_causal` and would pass far more comfortably for the pooled
arms. The premise that agent memory matters is not in doubt here.

**Governance does no harm it is not asked to do.** Retrieval latency is
0.8–1.7 ms across every arm, and the fabric's full governed path costs +0.2 ms
against the baseline — well inside the registered 50 ms gate. Nothing here says
the machinery is slow. It says the *policy* was wrong.

**Contamination control works and did not help.** The fabric arms let through
10% wrong-for-here memories against the pooled arms' 8% — no better, despite
contested marking. And contamination is low everywhere (2–10%) while harm is high
(36–55%), which means most harmful memories were *about other faults*: the agent
took an action a memory suggested for a different situation. Filtering by "wrong
for this context" does not catch that, because the memory is not wrong — it is
irrelevant, and irrelevant plausible text is enough.

**Exception sites were not the problem.** The registration worried that an arm
might win only where no memory is actively wrong. The base-vs-exception gaps are
small for every arm (`local_rag` −1.7%, `shared_memory_framed` ±0.0%, `oracle`
−6.7%). The hazard the world was built around turned out to matter less than the
plain availability of a correct memory.

## 6a. Correction, 2026-10-10 — a product bug inflated `fabric_causal`'s loss

Found two days later while building Phase B, and it changes the reading of one
arm.

`rank_by="value"` ordered candidates by `(-value_mean, memory_id)`, and
`value_mean` is `0.0` for a memory nothing is known about. So in a store with
little value evidence every candidate tied at zero and the sort fell through to
the memory id — which is a ULID, and ULIDs are time-ordered. **"Rank by value"
was silently "rank by creation time", with relevance discarded entirely.** A
newly written memory could not be exposed, and value evidence can only be earned
by exposure; only the epsilon exploration broke the deadlock, weakly. It was
found because a four-agent federation retrieved *none* of 36 imported memories
across eight consecutive episodes.

`fabric_causal` is the only arm that used that policy. Its 0.242 and its
12% correct-memory rate are therefore part exploration cost, as §4 says, and part
this defect — and the two cannot be separated from this run's data. **That arm's
number should not be quoted as a measurement of causal value selection.**

What does *not* change:

- **The verdict.** `fabric` used `top_k:relevance` and was unaffected, and it lost to the pooled baseline by 30 points on its own (0.283 against 0.583). §2's kill condition is an arm-to-arm comparison that `fabric` fails without help.
- **The mechanism.** Over-pruning (§4) was measured on `fabric` as well as `fabric_causal`, and `shared_memory_decay` — no fabric code at all — collapsed hardest of the three.
- **Every other arm**, none of which ranked on value.

The fix orders an unevaluated candidate by the only signal that exists for it,
which is relevance, keeping the id solely to make the sort deterministic.
Measured value still outranks relevance when there is any. `fabric_causal` is
re-measured in [PA′](../prereg/phase-a-prime-attribution.md) under the fixed
policy, as `fabric_contrastive`.

The uncomfortable part is why it survived: the ranking had tests, and they all
passed, because every one of them gave its candidates distinct values. Nothing
tested the case that dominates a real cold store — no evidence at all.

## 7. What this does not show

1. **One model, 3B parameters.** Every arm converts a correct memory at ~95% and fails without one at ~95%, so this world may be measuring retrieval coverage and nothing else for a model of this size. A larger model that reasons past a wrong memory would change the harm figures and might change the ordering.
2. **The oracle on this run was mis-specified** (amendment 3). The kill does not depend on it, but the true ceiling is unknown and the headroom shares in §2 should not be quoted.
3. **The withdrawal policies are mine, not the product's.** `fabric` here means contested marking plus quarantine-on-contradiction, which is a reasonable governed analogue of decay and is what the registration named. The shipped product also has `sweep_retention` and the firewall, neither of which was under test. A different governed policy might not lose.
4. **24 episodes is a short horizon**, and it is exactly the horizon at which an exploration-based estimator cannot repay its cost. H2's budget sweep is the precedent: the ordering reversed once the regime changed.
5. **The corpus is held constant across arms**, so nothing here speaks to whether the fabric helps an agent write better memories.

## 8. What follows

**Immediately — stop recommending withdrawal-on-failure.** This is a product
change, not a research note. The fabric's lifecycle makes quarantine easy and the
attention list invites an operator to use it; nothing in the product warns that
blaming what was in context destroys more correct memory than wrong. The
`explain()` surface should say what a quarantine is based on, and
quarantine-on-contradiction should not be presented as good practice without
evidence it helps.

**Registered follow-ups, in priority order:**

- **PA′ — attribution that is not agreement.** The blame rule failed because it matched surface agreement. Leave-one-out or a contrastive check — would this episode have failed without the memory? — is the obvious alternative and is what MeClear ([PRIOR_ART.md](../PRIOR_ART.md)) does. The killed H2 said a cheap usage-success baseline matches propensity correction for *retention*; Phase A says naive blame is actively harmful for *exposure*. Those are compatible and together they sharpen the question: attribution matters where the decision is which memory to withdraw, and the cheap version of it is worse than doing nothing.
- **PA″ — the re-run with the corrected ceiling.** Needed for the true headroom, not for the verdict.
- **PA‴ — noisy context labels.** `local_rag` has a perfect context partition in this world, flagged in amendment 2 before the run. A loss to it would have meant "exact metadata filtering beats governance". In the event `local_rag` and `shared_memory` tied exactly (0.558), so the partition bought nothing and that worry was unfounded — which is itself worth recording, and makes the noisy-label variant less urgent than it looked.
- **The longer horizon.** 24 episodes is where exploration cannot pay. 200 would say whether `fabric_causal`'s estimator ever earns its withholding.

## 9. The honest summary

> Put on a real task against a real baseline, this project's governance made an
> agent worse — not through cost or latency, both of which were negligible, but
> because withdrawing memories blamed for failures withdrew the correct ones. The
> model used a correct memory 95% of the time whenever it got one; governance cut
> the rate at which it got one from 60% of episodes to 18%, and the
> propensity-corrected version of it to 12%. The prompt framing was
> worth more than all of the machinery, and the machinery was worth less than
> nothing.
