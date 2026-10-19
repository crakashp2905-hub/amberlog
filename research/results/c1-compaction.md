# C1 result — governed session compaction: **safety SUPPORTED, non-inferiority SUPPORTED, no recall gain**

Registration: [prereg/c1-compaction.md](../prereg/c1-compaction.md), written
after the dev split and before these seeds. Held-out seeds 300–309,
model-free and deterministic. Raw: [c1-compaction-test.json](c1-compaction-test.json).

Question: a later session asks "what did session X establish?" within a
word budget. Handoff coverage (the session's current facts in context) and
stale exposure (a corrected-away value shown):

| arm | 40 words | **80 words** | 160 | 320 |
|---|---|---|---|---|
| `raw` (no session filter) | 0.00 / 0 | 0.00 / 0 | 0.00 / 0 | 0.00 / 0 |
| `raw_episode` (strong baseline) | 0.66 / 0 | **0.94 / 0** | 1.00 / 0 | 1.00 / 0 |
| `compacted` (governed) | 0.36 / 0 | **0.96 / 0** | 0.98 / 0 | 1.00 / 0 |
| `naive_summary` (ungoverned) | 0.68 / **1.00** | 0.99 / **1.00** | 1.00 / **1.00** | 1.00 / **1.00** |
| `full_context` (degenerate, unbudgeted) | 1.00 / 0 | | | |
| `oracle` | 0.73 / 0 | 1.00 / 0 | 1.00 / 0 | 1.00 / 0 |

- **C1-S, safety: SUPPORTED.** At every budget ≥ 80 words the governed
  summary showed a corrected-away value at rate **0** (bar ≤ 0.05). The
  naive summary did so at **1.00** (bar ≥ 0.50): a summary with no lineage
  keeps every value it was written with, whatever is corrected later.
- **C1-N, non-inferiority: SUPPORTED.** At 80 words, 0.956 against 0.944
  (bar ≥ 0.894).
- **Predictions held.** No recall gain over session-filtered raw notes at
  any budget; at 40 words the summary does not fit and is skipped (0.36
  against 0.66).

## What this means for the question "is compaction worth having?"

It is safe to have, and it does not make recall worse at ordinary budgets.
It does not improve recall here, because the store can already filter a
session's own notes. Its value is a single, readable handoff record that
stays correct: lineage makes a correction reach it, and `recompact`
rewrites it from the inputs still standing. An ungoverned summary looks
better on recall (0.99) only because it keeps exactly the values that were
corrected. That is the failure the design exists to prevent.

**Limits.** A model-free world, written by the same author as the
mechanism. Facts are numeric claims, which `conflicts.claim` parses
reliably. Summaries of free-text reasoning are not measured, and a
summary larger than the budget is skipped rather than truncated.
