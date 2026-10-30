# Pre-registration — P2b: sufficiency at a fixed budget

**Registered 2026-10-12**, replacing
[p2-context-sufficiency.md](p2-context-sufficiency.md), which was abandoned
because its primary metric was trivially maximised by one of its own registered
baselines. The [result](../results/p2-context-sufficiency.md) stands as the
record of that failure; this document is the repair.

The `sufficiency_aware` selector's measured defect is not fixed either, and this
registration does not pretend otherwise: §6 names what has to change in it
before the comparison is worth running.

## 1. What went wrong, in one line

Sufficiency can always be bought with context. `full_context` holds every
satisfier by definition, scored exactly the oracle's 0.800, and made
`B = max(baselines)` equal to the ceiling — so the threshold was unreachable
before any method existed.

## 2. The repair, and the check the first registration skipped

**Primary metric: `sufficient` at a fixed budget of 400 prompt tokens.**

400 is `task.token_budget`, written into relevance_v2 by its generator before
any of this was measured. It is the one budget this project can use without
having chosen it to produce a result.

Measured first, as principle 8a requires for a ceiling and as this registration
now requires for the metric itself
([sweep](../../experiments/p2_budget_sweep.py), dev, 33 cases):

| budget (tokens) | top-k sufficiency | oracle | headroom | mean memories |
|---|---|---|---|---|
| 25 | 0.500 | 0.567 | +0.067 | 1.9 |
| 50 | 0.533 | 0.800 | +0.267 | 4.2 |
| 100 | 0.533 | 0.800 | +0.267 | 9.1 |
| 200 | 0.600 | 0.800 | +0.200 | 18.6 |
| **400** | **0.600** | **0.800** | **+0.200** | **38.5** |
| 800 | 0.600 | 0.800 | +0.200 | 77.4 |
| 1600 | 0.600 | 0.800 | +0.200 | 156.4 |
| 3200 | 0.600 | 0.800 | +0.200 | 317.7 |
| 6400 | 0.800 | 0.800 | **+0.000** | 504.2 |

Three things this establishes, and all three had to be established before a
threshold could be written down:

1. **The metric is not degenerate at 400.** Headroom is +0.200, and top-k does not reach the ceiling.
2. **The choice of budget is not load-bearing.** Headroom is +0.200 across a **plateau from 200 to 3200 tokens**, a 16× range. A result at 400 is not an artifact of 400.
3. **The degenerate regime is visible and excluded.** At 6400 tokens top-k holds all 504 memories and ties the ceiling at 0.800 — which is precisely the regime the first registration accidentally measured in.

The sweep also says something the old metric hid: at 400 tokens top-k spends its
whole budget on **38.5 memories and reaches 0.600**, while the oracle reaches
0.800 on about 16 tokens. Thirty-eight memories chosen by rank miss what three
or four chosen correctly contain. That is the strongest argument this project
has that selection matters, and it comes from the diagnostic rather than from
any arm.

## 3. The obligation this adds

> **A primary metric must be shown not to be trivially maximised by any
> registered baseline, measured before the threshold is written.**

Proposed as AGENTS.md principle **8c**. 8a made the ceiling mandatory and 8b
made the oracle's handicap checkable, and neither would have caught this: the
ceiling was correctly measured at 0.800 and the oracle was correctly
unhandicapped. The defect was that a baseline *reached* the ceiling for a reason
having nothing to do with the question, and no existing principle required
anyone to look.

## 4. Arms

| arm | what it is |
|---|---|
`top_k@400` | the product as it ships — `retrieval="lexical"`, mechanisms on — filled by rank to the budget. The baseline to beat.
`full_context` | **reported and non-compliant.** It costs ~6,340 tokens, 16× the budget, so it cannot enter `B`. Reported every run so the degenerate regime stays visible rather than being quietly dropped once it stopped being convenient.
`random@400` | eligible memories in a seeded random order, filled to the budget. The floor: it says what the budget alone is worth, independent of ranking. 5 seeds.
`sufficiency_aware@400` | the method under test, budget-capped and permitted to abstain. Its current form is measured not to work; see §6.
`oracle_evidence@400` | the labelled satisfiers, same gates, **same budget**. An oracle with a larger budget than the arms it bounds is the 8b handicap in the direction that makes a ceiling unreachable.

## 5. Threshold

Computed on the evaluation split at run time, never from the dev numbers above:

```
B = max(sufficient) over {top_k@400, random@400}
C = sufficient(oracle_evidence@400)
support iff  sufficient(sufficiency_aware@400) >= B + 0.40 * (C - B)
```

**Abandonment clause.** If `C - B <= 0.05`, abandoned rather than
reinterpreted. On dev that would be 0.600 and 0.800, a threshold of 0.680.

**Ceiling check** every run: any arm above `oracle_evidence@400` means the
ceiling is wrong (8b), not that the arm is good.

**Budget compliance check** every run: any arm whose mean prompt tokens exceed
400 is reported as non-compliant and excluded from `B` and from the verdict. A
budget that is not enforced is not a budget, and the first registration's
failure was exactly a non-compliant arm setting the bar.

## 6. The method does not exist yet, and its predecessor's defect is named

`sufficiency_aware` in its measured form scores **0.000 on both multi-hop
families** and is identical to budget-matched top-k on every other family. The
cause is structural: it maximises marginal coverage of uncovered *query* terms,
and a chain's middle hop covers none — "tug-3 was re-fitted with the heavy axle
set" shares no token with a query about bay 7 in winter, so its whole value is
connecting hop 1 to hop 3 and its marginal gain is zero.

**This registration is not satisfied by re-running that selector.** The arm
under test must value a connector, which means treating assembly as
path-finding over the entity graph the memories induce rather than as coverage
maximisation. Until it does, running P2b would re-measure a known defect against
a repaired metric and report it as a finding about sufficiency.

Secondary metrics, reported always and decisive for none:
`requirement_recall`; `abstention_precision` on the nine cases a split where
abstention is the only correct answer, where **every arm measured so far scores
0.000**; `false_abstention`, because the first selector reached 1.000 abstention
precision by abstaining on 79% of answerable cases; `prompt_tokens`;
`latency_ms`; and `must_not_expose_rate`, where any non-zero value fails the run
outright.

## 7. Predictions

1. **`random@400` will score well above zero**, because 38 memories of 495 at random will sometimes contain a single-fact answer. If it approaches `top_k@400`, ranking is worth little at this budget and that is the finding, not a nuisance.
2. **`top_k@400` will not improve much above 200 tokens.** The plateau says so already on dev, and the reason is that rank order exhausts the useful candidates early — more budget buys more near-misses.
3. **Any method that closes this headroom will do it on `multi_hop_3` and `multi_hop_4`**, which are 0.000 for every non-oracle arm, and nowhere else. `direct`, `facet_trap` and `superseded_rev` are already at 1.000.
4. **Abstention will not improve without a mechanism that is not about coverage.** Token presence is not evidence about a conjunction: on an `unanswerable` case every term of the absent tuple appears somewhere, in sentences about something else. I expect a path-finding selector to leave abstention at 0.000, and record that now so a failure there cannot be presented as unexpected.

## 8. What a pass would not establish

Nothing downstream — whether a sufficient context changes what a model answers
is R6's question, and R6's dev finding did not replicate. Nothing external —
SciFact has no requirements, no provenance and no gates. And nothing about the
decomposition: sufficiency is defined by requirement slots I wrote, and a
different reading of "enough evidence" could order the arms differently.

Minimum 5 seeds for `random@400` and for any arm with a stochastic component;
the rest are deterministic and will be reported as such.

## Amendment 1 — 2026-10-16, before any P2b number

§6 required that the arm under test value a connector by path-finding before
the comparison was worth running. That now exists: `Memory Fabric.reconstruct`
(P1), whose link-strength selection P1d supported on a fresh holdout. Nothing
below was chosen after seeing a P2b number; none exists yet.

- **Arm under test: `chain@400`.** It takes the steps of
  `reconstruct(k = 5)` in chain order, applies the same gates as every other
  arm, then fills the rest of the 400-token budget by the shared ranking. It
  never abstains, so prediction 4 is tested as stated (abstention stays at
  0.000). The measured `sufficiency_aware` selector is reported alongside,
  unchanged, so the §6 defect stays visible.
- **Evaluation split: a fresh holdout, `holdout_p2b`.** It is built by the
  frozen generator at indices 400–405 for all 11 families (66 cases) and
  scored once. dev is reported for comparison. test is reported as
  **contaminated**, because P1 inspected it when the chain was designed.
- `random@400` uses seeds 0–4. Every other arm is deterministic.
- Thresholds, abandonment and the ceiling and budget-compliance checks are
  exactly §5, computed on `holdout_p2b`.
