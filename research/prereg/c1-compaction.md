# Pre-registration — C1: governed session compaction

**Registered 2026-10-19, after the dev split (seeds 200–202) and before the
held-out split (300–309).** Model-free and deterministic:
`experiments/c1_compaction.py`. Raw dev output:
[c1-compaction-dev.json](../results/c1-compaction-dev.json).

## The question

A later session asks "what did session X establish?" within a word budget.
Does a governed summary (`compaction.compact_session`) help, and is it
safer than an ungoverned one?

## Dev (handoff coverage / stale value shown after a correction)

| arm | 40 words | **80 words** | 160 | 320 |
|---|---|---|---|---|
| `raw` (no session filter) | 0.00 / 0 | 0.00 / 0 | 0.00 / 0 | 0.00 / 0 |
| `raw_episode` (strong baseline) | 0.67 / 0 | **0.93 / 0** | 1.00 / 0 | 1.00 / 0 |
| `compacted` (governed) | 0.31 / 0 | **0.93 / 0** | 0.98 / 0 | 1.00 / 0 |
| `naive_summary` | 0.67 / **1** | 0.99 / **1** | 1.00 / **1** | 1.00 / **1** |
| `full_context` (degenerate, unbudgeted) | 1.00 / 0 | | | |
| `oracle` | 0.71 / 0 | 1.00 / 0 | 1.00 / 0 | 1.00 / 0 |

**8c fires on coverage.** `raw_episode` is at 0.93 of an oracle 1.00 at
the primary budget, and reaches the ceiling at 160. No coverage-improvement
hypothesis is registered, because there is no headroom to register one
against.

**Fixed during dev, disclosed:**
1. The first world asked single-fact questions that name their equipment;
   raw retrieval reached 1.00 at every budget (8c). Replaced by handoff
   questions.
2. The extractive summariser kept every restatement and chatter line (0.35
   coverage at 80). It now keeps one line per claim.
3. A correction contested the whole summary and hid its other facts.
   `recompact` (run by the manager) writes a fresh summary from the inputs
   still usable.
4. Harness bugs: a regex mangled by shell quoting; counting a value
   anywhere in a large context (now per clause); a full-context arm that
   used retrieval; summaries looked up by fuzzy text match while the
   baseline used an episode filter (both summary arms now use the episode).
5. One diagnosis was wrong and is recorded: I believed a corrected
   session's summary stayed active. It did not. The old summary was
   contested and the re-compacted one held no stale value.

## Hypotheses (held-out, seeds 300–309)

- **C1-S (safety).** At every budget ≥ 80 words, `compacted` shows a
  corrected-away value at a rate ≤ 0.05, and `naive_summary` at ≥ 0.50.
- **C1-N (non-inferiority).** At 80 words, `compacted` coverage ≥
  `raw_episode` coverage − 0.05.

## Predictions

1. Both hold.
2. At 40 words `compacted` is worse than `raw_episode`: a summary larger
   than the budget is skipped, not truncated. Reported as a limitation.
3. No coverage gain over `raw_episode` anywhere. Governed compaction is a
   safety property and a convenience, not a recall improvement, in this
   world.
