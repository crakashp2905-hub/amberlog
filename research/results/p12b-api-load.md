# P12b — many agents through one agent-api process

Produced by `python -m experiments.p12b_api_load` at commit `4359625`; raw numbers
in [p12b-api-load.json](p12b-api-load.json). Machine: Linux x86_64, 4 CPUs, Python 3.13.16. One `agent-api`
server process on a SQLite store seeded with 200 memories, rate limiting
off. N agents with their own credentials are client threads, 20 requests
each (30% remember, 50% recall, 20% fetch then verify). An operational measurement,
not pre-registered.

Latencies in ms as the client sees them, p50 / p95 / p99. Throughput is successful
operations per second of wall time (a fetch+verify counts once).

| agents | ok / ops | ops/s | all ops | remember | recall | fetch+verify | errors |
|---|---|---|---|---|---|---|---|
| 1 | 20/20 | 187 | 5.5 / 6.7 / 7.1 | 6.3 / 7.1 / 7.1 | 5.2 / 6.5 / 6.5 | 3.8 / 6.0 / 6.0 | none |
| 10 | 200/200 | 195 | 46.5 / 82.4 / 107.2 | 39.6 / 65.9 / 67.1 | 38.5 / 65.4 / 66.9 | 67.6 / 107.2 / 119.1 | none |
| 50 | 1000/1000 | 169 | 249.0 / 504.5 / 559.3 | 239.3 / 309.6 / 316.7 | 239.6 / 308.2 / 317.1 | 464.0 / 559.3 / 609.3 | none |
| 100 | 2000/2000 | 159 | 534.8 / 1079.7 / 1159.0 | 514.7 / 599.6 / 622.7 | 516.8 / 610.2 / 630.9 | 1033.6 / 1161.0 / 1182.0 | none |

Compare [P12](p12-load.md), where each agent was its own process opening the
store: 214 → 31 → 9 → 4 ops/s at 1, 10, 50 and 100 agents on SQLite.

**What this shows.** Serving agents from one process keeps throughput flat,
about 150–180 ops/s from 1 to 100 agents. With one process per agent it fell
to 4 ops/s. Latency grows linearly with the number of agents waiting on the
one store lock: p50 is about 5 ms per agent ahead in the queue, which is the
expected cost of a serialised store. It does not collapse. At 100 concurrent
agents, p99 is about a second.

**Two defects this run found, both fixed before the numbers above.** First,
authentication had been moved outside the store lock for the rate limiter. It
reads revocations from SQLite, so concurrent requests shared the connection
and 14% failed. Second, the socket backlog was the library default of 5, and
the kernel reset connections when 100 agents connected at once.

**Supported scale, from P12 and P12b on this machine (4 CPUs, SQLite):** one
`agent-api` process per store, up to 100 concurrent agents, about 160
operations a second in total, with p99 latency of about 1 s at that
concurrency. Beyond that is unmeasured. Many processes opening one store
directly is not supported for more than a few writers.
