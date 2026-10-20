# Product benchmark: quality, latency, throughput, growth, false blocks

`python -m experiments.product_bench` (seed 7, sizes 1k / 5k / 20k), code at
`637f26a` plus the benchmark itself, Windows 11, Python 3.13.5, SQLite on local
disk, one process. Raw: [product-bench.json](product-bench.json). CI re-runs
it on Linux for every commit on main, into that commit's release evidence
bundle (`RELEASE_REPORT.md`). Not pre-registered; no threshold.

| memories | recall@1 | recall@5 | MRR | remember p50 / p95 ms | retrieve p50 / p95 ms | writes/s | reads/s | disk B/mem | heap B/mem | false blocks |
|---|---|---|---|---|---|---|---|---|---|---|
| 1,000 | 0.132 | 0.964 | 0.421 | 11.1 / 13.7 | 4.4 / 6.1 | 87.4 | 214.7 | 4100 | 18201 | 0/200 |
| 5,000 | 0.147 | 0.970 | 0.434 | 12.8 / 20.7 | 11.3 / 14.1 | 72.4 | 86.6 | 1928 | 17624 | 0/200 |
| 20,000 | 0.163 | 0.950 | 0.433 | 14.0 / 47.2 | 39.0 / 43.3 | 49.1 | 24.8 | 1417 | 17597 | 0/200 |

## What it shows

- **The fact is almost always in the top five, rarely first.** Each planted
  value's asset tag is also named by about three handover, incident and
  spares notes, and the query asks for the quantity in other words than the
  note ("how hot" for "runs at … C"). Lexical ranking finds the tag and cannot
  tell which of the four notes answers, so recall@1 sits near chance among
  them (0.25 would be chance among four; why it falls below chance was not
  investigated).
  An agent given k=5 has the answer; one given k=1 mostly does not. An earlier
  draft of the corpus put the tag in only one note and scored 1.000 on every
  measure, which measured nothing (AGENTS.md 8c).
- **Retrieval latency grows linearly with the store**: 4.4 → 11.3 → 39.0 ms
  p50 from 1k to 20k. Consistent with scoring that scans the candidates. At 20k it is still
  well inside an agent turn; extrapolated linearly, 100k memories would be
  about 200 ms p50, untested. A sub-linear candidate index is open work.
- **Writes stay flat at p50** (11–14 ms);
  the p95 widens at 20k (47 ms); not yet profiled.
- **Growth:** about 1.4 KB on disk per memory once fixed overhead is
  amortised, and about 17.6 KB of Python heap per memory, flat with size: a
  20k store holds about 350 MB in process. Heap, not disk, is the limit for a
  single process.
- **False blocks: 0 of 200 at every size**, on benign writes chosen to look
  like trouble: procedures that say "ignore", "override", "disregard",
  "act as" or "password reset", re-measurements and values at a band's edge.
  With `auto_activate=True`; the default store holds every write for review,
  where a block has no meaning.

## Limits of the measurement

Synthetic corpus from templates; one process (multi-process load is
`p12-load.md`); local disk; the false-block set is 200 texts from eight
templates, so 0/200 bounds the rate below about 1.5% (95%), not at zero.
