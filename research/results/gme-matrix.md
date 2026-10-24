# GME matrix: governance, compression and branching (blueprint §11.1)

Pre-registration: [research/prereg/gme-matrix.md](../prereg/gme-matrix.md).
Harness: `experiments/gme_matrix.py`. Synthetic world, rule-based reader,
budget 60 estimated tokens, k 20. Raw: `gme-matrix.json` (registered,
seeds 1–5), `gme-matrix-posthoc.json` (repaired code, same seeds),
`gme-matrix-confirm.json` (repaired code, seeds 6–10, Addendum A).
`any_arm_beats_oracle` was empty on every run.

## Registered run (seeds 1–5): **H1, H2 and H3 not supported**

Means over five seeds (phase 1 = branch open, phase 2 = after the merge).

| arm | acc. ph.1 | acc. ph.2 | stale leak | branch leak ph.1 | tokens |
|---|---|---|---|---|---|
| A no memory | 0.000 | 0.000 | 0.000 | 0.000 | 0.0 |
| B conventional retrieval | 0.556 | 0.556 | 0.333 | 0.278 | 56.5 |
| C governance, no compression | 0.889 | 0.711 | 0.056 | 0.000 | 55.8 |
| D compression, no governance | 0.556 | 0.556 | 0.333 | 0.278 | 55.6 |
| E Governed Context Map | 0.578 | 0.550 | 0.300 | 0.000 | 55.8 |
| F naive merge | — | 0.450 | 0.272 | — | 56.0 |
| G full system | 0.578 | 0.417 | 0.300 | 0.000 | 56.1 |
| oracle | 1.000 | 1.000 | 0.000 | 0.000 | 13.6 |

- **H1 not supported.** C captured 0.75 of the headroom over B on every seed
  (threshold 0.50) and never showed a branch value, but its stale leak was
  above 0.02 on four of five seeds (0.056, 0.056, 0.111, 0.000, 0.056).
- **H2 not supported.** E used 0.99–1.01× C's tokens (threshold ≤ 0.80) and
  captured 0.00–0.13 of the headroom against C's 0.75.
- **H3 not supported.** G captured −0.11 to 0.00 of the headroom over F. Its
  invariants held on every seed: **no withdrawn memory resurrected, no lost
  update**.

## What the failures were

Diagnosed by breaking each arm's answers down by asset role:

- **F1 — planner (product defect).** Compact mode ranked every summary ahead
  of every record, so summaries of *other* assets that fit the budget pushed
  out the record that answered the question. Fixed: candidates are taken in
  relevance order and the mode only chooses among options covering the same
  candidate.
- **F2 — summary builder (product defect).** Bundles were ordered by creation
  time, so an older note restating a value came before the correction that
  replaced it. Fixed: most recent first (`extractive-v2`).
- **F3 — rendering (product defect).** The receipt renderer dropped the
  `[DISPUTED]` flag that `adapters.context` has always added, so no arm could
  report a real disagreement.
- **F4 — budget (found by the first repair).** The flag was then added after
  planning, overrunning the budget (62–64 tokens of 60). Fixed: the planner
  flags disagreements and pays for the flag. That post-hoc run was discarded.

Regression tests for each: `tests/test_context_map.py`
(`FoundByTheMatrix`, `BudgetIncludesFlags`).

## Repaired code, same seeds (post hoc, not confirmatory)

C 1.000 / 0.822, E 1.000 / 0.822, F 0.900, G 1.000 / 1.000 (phase 1 / 2).
These were run on the seeds the repairs were made from and confirm nothing.

## Confirmatory replication (Addendum A, seeds 6–10)

| arm | acc. ph.1 | acc. ph.2 | stale leak | branch leak ph.1 | tokens |
|---|---|---|---|---|---|
| B | 0.556 | 0.556 | 0.333 | 0.278 | 56.4 |
| C | 1.000 | 0.839 | 0.094 | 0.006 | 56.3 |
| D | 0.661 | 0.661 | 0.333 | 0.278 | 55.4 |
| E | 1.000 | 0.839 | 0.300 | 0.006 | 56.0 |
| F | — | 0.883 | 0.272 | — | 56.1 |
| G | 1.000 | 1.000 | 0.300 | 0.006 | 56.2 |
| oracle | 1.000 | 1.000 | 0.000 | 0.000 | 13.7 |

- **H1: accuracy criterion met (share 1.00 on every seed); leak criterion
  failed, as predicted** (0.083–0.111). The registered branch-leak criterion
  also failed on seed 6 (0.028), and that failure is **in the metric, not the
  store**: no branch candidate was exposed; a spares note ("store room 14")
  matched a proposal value of 14. The metric matches a number anywhere after
  the tag in a sentence; a future version should match the stated quantity.
- **H2 failed, as predicted:** E used 0.99× C's tokens. Under a binding budget
  every arm fills it, so tokens per task cannot show compression; the
  registered metric could not have supported H2 as written. E matched C's
  accuracy exactly.
- **H3 supported:** G captured 1.00 of the headroom over F on every seed,
  with no resurrection and no lost update.

## What this does and does not show

- Governance removes branch contamination and withdrawn values from context;
  it **does not** reach stale *restatements* — notes that repeat a value
  later corrected elsewhere. Nothing links them to the fact they repeat, so
  the correction does not propagate. This is a real gap: copy recognition or
  claim validation would have to tie a restatement to its fact.
- Summaries carry those restatements too (E's stale leak ≈ 0.30): the reader
  answers correctly only because the correction now comes first (F2).
- A governed merge beat a naive one on every confirmatory seed, and the
  invariants (no resurrection, no lost update) held on all ten seeds.
- Synthetic world, rule reader. No claim about language-model task success.
