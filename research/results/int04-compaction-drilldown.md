# INT-04 — compaction with reversible drill-down (descriptive)

Produced by `python -m benchmarks.compaction` at commit `8fde780d6ab6`; seeds 1, 2, 3, 4, 5; 8 task
logs of 30 steps each, every step carrying one critical detail (a limit with its unit, a
prohibition, or a date). No model; no improvement claim is registered, so this is a description.
Raw numbers: [int04-compaction-drilldown.json](int04-compaction-drilldown.json).

Share of questions whose critical detail is in the context, by budget (words):

| budget | raw (search top-5) | summary only | summary + drill-down | oracle |
|---|---|---|---|---|
| 40 | 1.000 | 0.329 | 1.000 | 1.000 |
| 80 | 1.000 | 0.485 | 1.000 | 1.000 |
| 160 | 1.000 | 0.661 | 1.000 | 1.000 |

A summary averages 345.1 words against 342.1 for the raw log it replaces.

| invariant | violations | checks |
|---|---|---|
| a withdrawn source is never returned by drilling down | 0 | 120 |
| an erased source never returns text | 0 | |
| a summary built on a withdrawn source is no longer exposable | 0 | |

Invariants: **all held**. Zero violations in these checks bounds the rate,
it does not prove impossibility; the deterministic tests in `tests/test_gov_conformance.py` are the
standing check.

## Reading

- **The default summariser compresses nothing.** It is extractive and refuses to drop a value
  (`CompactionRefused`), so on a log where every line carries a value the summary is as long as
  the log. Under a budget it is truncated, and the detail a question needs is often cut off.
  Compaction's guarantees hold; its token saving, on this kind of log, is zero.
- **Drill-down recovers what truncation loses**: the summary's inputs are its lineage, and a
  retrieval limited to them finds the line. It matches search over the raw log here because every
  line has a unique unit id, which makes search easy; that is a property of this world, not
  evidence that search is enough in general.
- **The invariants held** in every check: drilling down never returned a withdrawn source, an
  erased source never returned text, and a summary built on a withdrawn source stopped being
  exposable.

Implication for §7A.6: a Tencent-style compression arm needs a summariser that actually
compresses (a model, or a structured step record) before token savings can be measured; this
harness is ready for one (`summarise=` in `compact_session`).
