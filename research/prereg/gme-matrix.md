# Pre-registration: GME matrix (blueprint §11.1)

**Registered before any method arm (C–G) was run.** Harness:
`experiments/gme_matrix.py`. Pilot: seed 0, arms A, B and the oracle only
(AGENTS.md 8d: baselines first, on the metric and budget the thresholds are
written in). Evaluation: seeds 1–5, every arm. The pilot seed is not
evaluated.

## World and reader

36 assets per seed; each has one current fact and three notes naming its
tag (one restating the value). Roles: corrected (revised after the branch
base), withdrawn (quarantined and replaced by another source), disputed (a
second source, unresolved), plain. A branch opened before main moved
proposes re-measurements for a third of the non-disputed assets. The reader
is fixed for every arm: first context item naming the tag with a value, or
"disputed" if a dispute line names it.

**Budget: 60 estimated tokens per question; k = 20 candidates.** Same for
every arm, the oracle included (AGENTS.md 8b).

## Metrics

- **accuracy** (primary): reader answer equals the truth. Phase 1 (branch
  open) truth is main's current value. Phase 2 truth for F, G and the oracle
  is main after a correct merge (proposals on untouched assets applied);
  for arms with no merge (A–E) it is main unmerged.
- **stale_leak_rate**: a superseded or withdrawn value for the asked asset
  appears in the context.
- **branch_leak_rate** (phase 1): an unmerged branch value appears in the
  context.
- **tokens_per_task**: estimated tokens delivered.
- **version control** (G only): withdrawn memories active again after the
  merge (`resurrected`), corrected facts overwritten by a stale proposal
  (`lost_updates`).

## Pilot (seed 0), measured at budget 60, k 20

| arm | accuracy | stale leak | branch leak (ph. 1) | tokens |
|---|---|---|---|---|
| A no memory | 0.000 | 0.000 | 0.000 | 0.0 |
| B conventional retrieval | 0.556 | 0.333 | 0.278 | 56.8 |
| oracle | 1.000 | 0.000 | 0.000 | 13.9 |

Headroom over B: **0.444**. B does not max the primary metric (8c). No arm
beat the oracle.

## Hypotheses and thresholds

Thresholds are shares of headroom, computed **per seed** from that seed's B
(or F) and oracle, then averaged over seeds 1–5 (8a).

- **H1 (governance).** Phase 1: C captures **≥ 50%** of the headroom over B,
  `(acc_C − acc_B) / (acc_oracle − acc_B) ≥ 0.50`; and C's stale leak
  **≤ 0.02** and branch leak **= 0** on every seed.
- **H2 (compression).** Phase 1: E's tokens **≤ 0.80 ×** C's, and E's
  headroom share is **no more than 0.05 below** C's (non-inferiority).
- **H3 (merge).** Phase 2: G captures **≥ 50%** of the headroom over F,
  `(acc_G − acc_F) / (acc_oracle − acc_F) ≥ 0.50`; and `resurrected = 0`
  and `lost_updates = 0` on every seed.
- **D (compression without governance)** is descriptive: no threshold. The
  expectation, not a hypothesis, is that its stale leak is at least B's.

Every run reports `any_arm_beats_oracle`; a non-empty list invalidates the
run (8b).

## What would not count

A pass on synthetic data is a pass on synthetic data. The reader is a rule,
not a model; the world is templates. Nothing here supports a claim about
task success with a language model, which needs a model arm and an
independent evaluator (docs/INDEPENDENT_EVALUATION.md).

## Addendum A — confirmatory replication of the repaired system

**Registered after the post-hoc run on seeds 1–5 and before seeds 6–10 were
run.** The registered run (seeds 1–5) found three product defects (F1–F3)
and the first repair a fourth (F4, a budget overrun); see
`research/results/gme-matrix.md`. The repaired code was then run post hoc on
the same seeds, which cannot confirm anything: the repairs were made by
looking at those seeds.

This addendum runs the repaired system, unchanged, on **seeds 6–10**, with
the hypotheses and thresholds above **unchanged**: H1 (share ≥ 0.50, stale
leak ≤ 0.02 and branch leak = 0 on every seed), H2 (tokens ≤ 0.80 × C,
share within 0.05 of C), H3 (share over F ≥ 0.50, no resurrection, no lost
update). Two predictions are written down now so they cannot be
rationalised later: **H1's leak criterion will fail** (restatement notes
are not linked to the fact they restate, so a correction does not reach
them), and **H2's token criterion will fail** (under a binding budget every
arm fills it). Output: `research/results/gme-matrix-confirm.json`.
