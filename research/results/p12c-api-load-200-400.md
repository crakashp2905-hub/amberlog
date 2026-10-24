# P12b — many agents through one agent-api process

Produced by `python -m experiments.p12b_api_load` at commit `cdf937d`; raw numbers
in [p12b-api-load.json](p12b-api-load.json). Machine: Linux x86_64, 4 CPUs, Python 3.13.16. One `agent-api`
server process on a SQLite store seeded with 200 memories, rate limiting
off. N agents with their own credentials are client threads, 20 requests
each (30% remember, 50% recall, 20% fetch then verify). An operational measurement,
not pre-registered.

Latencies in ms as the client sees them, p50 / p95 / p99. Throughput is successful
operations per second of wall time (a fetch+verify counts once).

| agents | ok / ops | ops/s | all ops | remember | recall | fetch+verify | errors |
|---|---|---|---|---|---|---|---|
| 200 | 4000/4000 | 198 | 984.4 / 1357.7 / 1405.5 | 982.1 / 1364.3 / 1404.7 | 985.4 / 1260.8 / 1405.5 | 0.0 / 0.0 / 0.0 | none |
| 400 | 8000/8000 | 166 | 2432.1 / 3023.0 / 3073.0 | 2427.5 / 3016.7 / 3070.2 | 2433.0 / 3024.3 / 3074.6 | 0.0 / 0.0 / 0.0 | none |

Compare [P12](p12-load.md), where each agent was its own process opening the
store: 214 → 31 → 9 → 4 ops/s at 1, 10, 50 and 100 agents on SQLite.
