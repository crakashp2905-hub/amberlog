# Pre-registration — H2: does credit-driven forgetting beat the heuristics?

- **Written:** 2026-10-01, **before** the v2 world or any retention policy was built.
- **Milestone:** P5 (ROADMAP.md)
- **Depends on:** H1 supported ([result](../results/h1-causal-credit.md)) — the `amortized` estimator recovers true value at ρ≈0.76.

H1 showed the estimator is *accurate*. H2 asks whether that accuracy is *worth anything*: does ranking by estimated credit keep a better set of memories than the heuristics a sensible engineer would reach for?

Thresholds below are fixed now and are not to be revised after seeing results.

---

## 1. Hypothesis

> At an equal memory budget, under drift and with injected harmful memories, pruning a store by estimated causal credit produces higher task success than pruning it by retrieval frequency, by recency-plus-importance, or by naive usage-success.

## 2. World changes from P4 (decided now, for stated reasons)

The P4 world could not test this: every symptom had a correct claim, so wrong claims were ranked below one and never followed (median true value −0.013). Harm has to bite for a forgetting experiment to mean anything. Four changes, all fixed before any run:

1. **Partial coverage.** Correct claims cover only 50% of symptoms. On the rest, a wrong claim can reach the top of the ranking and be followed.
2. **Drift.** At episode `drift_at`, 40% of rules flip their correct action. Memories written against the old rules become actively wrong without changing.
3. **Rare, high-impact symptoms.** 10% of symptoms occur with 1/20th the usual probability. Their memories accumulate almost no evidence, which is the §2.5 failure mode — a credit-driven policy has every reason to delete them.
4. **Stated importance.** Every memory carries an importance score, as a Generative-Agents-style rater would assign: higher for claims than for distractors, but **uncorrelated with whether a claim is right**, because that is not knowable without outcomes. This keeps the recency+importance baseline fair rather than a straw man.

## 3. Procedure

Each arm runs the same world, same seed, same episodes, and differs **only in which memories it keeps**:

1. **Warm-up** — 2000 episodes, full store, ε-greedy exposure (ε=0.20, the H1 operating point).
2. **Prune** — reduce the store from ~120 memories to a budget of **40**, by the arm's ranking rule.
3. **Evaluate** — 2000 further episodes on the pruned store, exposure ranked by relevance for every arm, **re-pruning to budget every 500 episodes** by the arm's own ranking.

Exposure ranking is held at relevance for all arms deliberately. The product question is *what should we forget*, and holding retrieval fixed isolates that rather than confounding it with a second change.

A pruned memory is deprecated and never returns: it is no longer retrievable, so it gathers no new evidence and cannot earn its way back. Early mistakes are therefore permanent, which is the real property of a retention policy and is deliberately not softened.

> ### Amendment, 2026-10-01 — before any H2 run
>
> §3 originally specified a **single** prune. That makes the drift-recovery metric in §5 vacuous: with a static store, no arm can respond to drift at all, so every arm would score the same "no recovery" and the metric would measure nothing.
>
> This is a logical defect in the design, visible without data, and no H2 run had been executed when it was found. The fix is the periodic re-prune now written into step 3, which is what makes recovery a real comparison: a credit-driven arm can notice that a memory has started to hurt and drop it, while recency- or frequency-ranked arms have no signal that anything changed.
>
> Nothing else changed — not the arms, the budget, the metrics, or the §6 thresholds. Limitation 4 in §9 is updated accordingly.

## 4. Arms

| id | Retention ranking | Role |
|---|---|---|
| `random` | uniform | floor |
| `frequency` | most exposed | what relevance-only retrieval effectively keeps |
| `recency_importance` | Generative-Agents style: recency decay + stated importance | **baseline to beat** |
| `naive` | smoothed success rate when exposed | **baseline to beat** |
| `amortized` | estimated causal credit (H1's primary) | the method under test |
| `oracle` | true value | upper bound, not a competitor |

## 5. Metrics

- **Primary:** mean task success over the evaluation phase.
- **Drift recovery:** episodes after `drift_at` until success returns to within 2pp of its pre-drift level.
- **Rare-event retention:** fraction of correct claims about rare symptoms still present after pruning.
- **Harm retention:** fraction of harmful memories (true value < −0.05) still present after pruning.

## 6. Decision rules

Judged on the mean across 10 seeds, with 95% bootstrap intervals.

- **H2 supported** if `amortized` beats **each** of `frequency`, `recency_importance` and `naive` by **≥ 5 percentage points** of mean success, with the bootstrap interval on each paired difference excluding zero.
- **H2 killed** if `amortized` fails to beat the best of those three (point estimate ≤ 0, or interval including zero).
- **Inconclusive** otherwise — beats them, but by less than 5pp, or with an interval touching zero.

## 7. Guardrail, reported whatever the primary says

Credit-driven forgetting has an obvious way to be right on average and wrong where it matters: a memory that pays off once a year accumulates no evidence, so the policy with the best mean has every incentive to delete it (CRITICAL_REVIEW §2.5).

**If `amortized` retains rare-event memories at a lower rate than `recency_importance`, that is reported prominently even if the primary passes**, and it blocks the recommendation to run credit-driven retention without the rare-event protection already in `RetentionPolicy`.

This is pre-registered as a finding to look for, not a threshold to pass, because the right response to it is a design change rather than a verdict.

## 8. Design

- **Seeds:** 10, `0..9`.
- **Episodes:** 2000 warm-up + 2000 evaluation; `drift_at` = 1000 episodes into the evaluation phase.
- **World:** 40 symptoms (4 rare), 8 actions, coverage 0.5, drift fraction 0.4; population 20 correct claims, 30 wrong claims, 40 distractors, plus 10% injected harmful; budget 40.
- **Estimator:** `amortized` over `dr`, as recommended by the H1 decision record.

## 9. Stated limitations (written now)

1. RuleWorld effects remain ~10× larger than production (H1 limitation 1). A win here shows the ordering is right, not that the margin transfers.
2. Scripted agent; no LLM confirmation run.
3. Single context — transferability and federation are H3.
4. **The store never grows.** Pruning happens every 500 episodes, but the agent writes no new memories, so an arm can only remove what has gone wrong — it cannot replace it. A real deployment learns the new rule after drift; this measures only the forgetting half of the lifecycle.
5. The budget (40 of ~120) is a single point. Whether the ordering holds at a tighter or looser budget is not tested.

## 10. What gets reported

The arm table with paired differences and intervals, drift recovery, rare-event and harm retention, the guardrail finding, and the verdict against §6 — including "killed" or "inconclusive".
