# P12 — latency and throughput at 10, 50 and 100 agents

Produced by `python -m experiments.p12_load` at commit `dd6aac5`; raw numbers
in [p12-load.json](p12-load.json). Machine: Linux x86_64, 4 CPUs, Python 3.13.16. One process per agent,
20 operations each, on one shared store holding 200
memories at the start. An operational measurement: no threshold, no
pre-registration.

Latencies in ms, shown as p50 / p95 / p99. Throughput is successful operations
per second of wall time.

| backend | agents | ok / ops | ops/s | all ops | remember | retrieve | gated action | errors |
|---|---|---|---|---|---|---|---|---|
| sqlite | 1 | 20/20 | 214 | 4.1 / 6.5 / 10.2 | 4.1 / 10.2 / 10.2 | 3.6 / 4.5 / 4.5 | 4.5 / 6.5 / 6.5 | none |
| sqlite | 10 | 200/200 | 31 | 262.8 / 570.4 / 682.5 | 243.7 / 342.4 / 367.1 | 251.0 / 385.0 / 397.9 | 499.7 / 682.5 / 697.8 | none |
| sqlite | 50 | 1000/1000 | 9 | 4402.6 / 10433.4 / 13768.9 | 3680.4 / 7923.7 / 9308.2 | 4043.7 / 8580.4 / 9878.4 | 7893.2 / 13768.9 / 16444.0 | none |
| sqlite | 100 | 2000/2000 | 4 | 19005.8 / 47120.1 / 56400.2 | 17249.6 / 29596.5 / 32165.6 | 17423.8 / 29322.8 / 31639.1 | 35687.0 / 56203.2 / 60199.0 | none |
| postgres | 1 | 20/20 | 63 | 15.2 / 26.9 / 27.1 | 7.2 / 9.1 / 9.1 | 24.0 / 27.1 / 27.1 | 12.8 / 21.9 / 21.9 | none |
| postgres | 10 | 200/200 | 5 | 1552.0 / 3235.5 / 4063.2 | 1460.3 / 1930.4 / 2039.1 | 1424.8 / 2114.3 / 2188.3 | 2884.4 / 4063.2 / 4608.6 | none |
| postgres | 50 | 1000/1000 | 2 | 19868.4 / 45410.2 / 52624.3 | 16679.5 / 26730.2 / 27935.0 | 18134.2 / 26808.7 / 27801.4 | 33686.2 / 52624.3 / 54236.9 | none |
| postgres | 100 | 2000/2000 | 1 | 69790.6 / 159719.8 / 248337.3 | 59898.8 / 135375.5 / 154747.7 | 59420.4 / 122714.6 / 151116.7 | 115799.7 / 247674.7 / 276663.0 | none |

**What this shows.** One agent runs an operation in a few milliseconds. Adding
agent processes to one store collapses throughput rather than spreading it,
and tail latency grows from milliseconds to seconds, then minutes on Postgres
at 100 agents. No operation failed; they all queued. **Nothing here supports
running tens of agent processes against one store,** and no scaling claim is
made.

**Why: observed, not isolated.**
- Every write takes the store's single write lock: SQLite's database lock, or
  Postgres's `LOCK TABLE events IN EXCLUSIVE MODE`, which keeps `seq` gapless
  and the hash chain ordered. A retrieve writes too, because it logs exposure
  decisions.
- Every call first folds in the other processes' new events
  (cross-process freshness), so each agent's work grows with everyone's.
- At 100 agents on Postgres, all 100 connections were idle while the agent
  processes were CPU-bound (load average about 100 on 4 cores).
  That points at client-side work and CPU contention, not lock waits, at that
  scale.

How much each factor contributes has not been measured. A profile under
contention is the next step before any design change.

**Supported workload, from these numbers only:** a single process, or a few,
per store. Many agents should share one process (the agent HTTP API serves
many agents from one) rather than each opening the store. That is a
recommendation from the design, not a measurement: the HTTP API was not
load-tested here.
