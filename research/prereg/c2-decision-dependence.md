# Pre-registration — C2: which decisions genuinely depended on a corrected memory?

**Registered 2026-10-24**, before `memory_fabric/dependence.py` and
`experiments/c2_dependence.py` existed.

## 1. Question

When a memory is corrected, `influence.impact` lists every action whose
evidence is downstream of it. That list is complete, but it is noisy: an
action backed by an independent second source would have been allowed
anyway, and reviewing it is wasted effort. The counterfactual asks the
product's own gate a different question. Remove the corrected memory and
everything derived from it, re-certify the action with what remains, and
authorise it in a dry run. Would it still be allowed?

## 2. World (known answers, deterministic, seeds 1–5)

One store per seed. 40 independent facts, each with a distinct source root.
Some facts have copies (re-ingestions of the same text, sharing a root) and
derived conclusions (`derive`). 60 allowed actions, each certified with 1–3
evidence memories under `min_independent_sources` of 1 or 2. Then one fact
is corrected (quarantined, basis `contradicted`).

**Ground truth, from construction:** an action *depended* on the corrected
fact if, after removing that fact, its copies and everything derived from it,
the remaining evidence covers fewer distinct roots than the action's
`min_independent_sources`. This is computed from the generator's own labels,
not from the product.

## 3. Arms

| arm | flags for review |
|---|---|
| `graph` | every action `influence.impact` lists as authorized by something in reach |
| `counterfactual` | `dependence.decisions_depending_on`: re-certify without reach, dry-run the gate |
| `oracle` | the ground-truth depended set |

## 4. Metrics and thresholds

- **recall** of depended actions; **precision** of the flagged set.
- **C2a (safety):** counterfactual recall = 1.000 on every seed. Missing a
  genuinely dependent action is the failure that matters.
- **C2b (review load):** counterfactual precision ≥ graph precision +
  0.40 × (1.000 − graph precision), pooled over seeds.
- **8c:** before the evaluation, the harness prints the graph arm's precision
  and the share of affected actions that depended. If the graph arm's
  precision is already ≥ 0.95, C2b is abandoned for lack of headroom.

## 5. What a pass would not establish

- Dependence here means "the recorded evidence would no longer satisfy the
  recorded policy". It does not mean that the agent's reasoning used the
  memory. That needs model replay (exposure attribution), which is not tested
  here.
- Independence is judged by source roots, which inherits S2's limits: an
  independent-looking root that was laundered is counted as independent.

## Amendment 1 — 2026-10-24, after the C2 run, before any seed 6–10 number

C2a failed because of a product defect (`min_independent_sources` was not
enforced unless `independent_support` was listed). It was fixed in the
verifier and covered by a test. The re-run uses fresh seeds 6–10, with the
mechanism and world unchanged, and the same thresholds. The original seeds
1–5 result stands as recorded.
