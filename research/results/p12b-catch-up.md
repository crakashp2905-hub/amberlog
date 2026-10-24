# P12b — what the multi-agent collapse was, the fix, and the limits that remain

**The collapse was one function.** P12 measured throughput falling from 214 to
4 operations a second as agent processes were added to one store and said the
cause was "observed, not isolated". Profiled, 95% of a contending agent's time
was a full rebuild of the projection from the whole log, run on nearly every
call. Replacing it with an incremental fold of the new events raised
throughput at 100 agents **23× on SQLite and 32× on Postgres** on the same
machine, and left one agent unchanged. Every operation in every run succeeded.

An operational measurement, not a pre-registered hypothesis: it sets no
threshold. Machine for every number here: Windows 11, 8 CPUs, Python 3.12.13,
SQLite (stdlib) and a local PostgreSQL 16. P12's original numbers came from a
4-CPU Linux machine and are not compared with these.

## 1. The cause, measured

`python -m experiments.p12_profile --agents 10` runs P12's workload in nine
processes and, in a tenth, the same workload under `cProfile`
([profile-before](p12b-raw/profile-before.json), [profile-after](p12b-raw/profile-after.json)):

| | before | after |
|---|---|---|
| profiled agent's operation time, 20 operations | 7,012 ms | **540 ms** |
| of which `MemoryFabric._replay` | 6,855 ms (95%) | — |
| full replays | 30 | 1 (opening the store) |
| events re-read by replays | 38,529 | 202 |
| memories re-indexed | 7,017 | — |

`refresh()`, which every entry point calls so that a running process sees
other processes' writes, rebuilt the projection from the entire log whenever
anyone else had written. Under contention that is almost every call, and the
log grows with every retrieve, because exposures are logged (AGENTS.md
principle 4). Each operation's cost therefore grew with the size of the log
**and** with the number of writers. With a real embedder it also re-embedded
every memory in the store.

## 2. The fix, and why it is the same state

`_catch_up` folds only the events after the last one this process has seen. A
rebuild *is* the in-order fold of the log (`Projection.rebuild` is
`apply_all(log.read())`), so folding the suffix onto the state that holds the
prefix reaches the state a rebuild would. That is checked, not argued:
`tests/test_catch_up.py` interleaves every kind of write across two handles on
one store, then compares the live projection field by field with a freshly
opened one, and their search indexes too. 12 interleavings run in the suite; 500
were run once, all equal.

Building that test found three defects, each fixed in the same change:

- **Erasure left plaintext behind** (security). After crypto-erasure, the
  erasing process kept every *earlier* version's plaintext in
  `state.history`, served by `history()` and the dashboard's version list,
  and the erased text's term set in the copy index. A replay never showed
  either, because the key is gone, so only the long-running process leaked.
  Both are scrubbed now (`tests/test_erasure_residue.py`).
- A memory unindexed by `forget` and later validated back was unretrievable
  in that process until a restart.
- `revise` indexed its own version after folding a later revision by another
  process, putting superseded text in the index.

## 3. Before and after, same machine

`python -m experiments.p12_load`. *Before* is a clean worktree at `8ffba19`;
*after* is `2d5a2fd`, measured in a worktree pinned to it
([p12-load.json](p12-load.json)). The *before* run is
[raw](p12b-raw/sweep-before.json), with what code produced it in
[p12b-raw/README.md](p12b-raw/README.md).

| backend | agents | ops/s | p50 ms | p95 ms | p99 ms |
|---|---|---|---|---|---|
| SQLite | 1 | 159 → **158** | 5.7 → **5.4** | 9.7 → **9.1** | 13 → **12** |
| SQLite | 10 | 24 → **119** | 321 → **5.8** | 840 → **84** | 962 → 1,235 |
| SQLite | 50 | 7.4 → **103** | 5,296 → **7.1** | 14,463 → **462** | 18,155 → **7,183** |
| SQLite | 100 | 4.4 → **103** | 17,211 → **9.9** | 50,841 → **3,046** | 62,451 → **12,094** |
| Postgres | 1 | 178 → 127 | 5.5 → 6.5 | 7.8 → 18 | 11 → 24 |
| Postgres | 10 | 8.8 → **133** | 853 → **58** | 2,238 → **128** | 2,457 → **222** |
| Postgres | 50 | 3.5 → **85** | 9,134 → **478** | 32,679 → **942** | 45,556 → **1,294** |
| Postgres | 100 | 1.7 → **56** | 39,883 → **1,444** | 129,139 → **3,030** | 165,291 → **3,256** |

0 errors in every row. Two rows got worse:

- **Postgres at one agent, 178 → 127 ops/s: noise.** Re-run five times on
  its own at the same commit, one Postgres agent did 174, 175, 174, 89 and
  177 ops/s. The 127 was one slow run. A single run of the one-agent rows
  swings by 2× on this machine: one SQLite agent did 285–373 ops/s alone,
  against 158 inside the sweep.
- **SQLite's p99 at 10 agents, 962 → 1,235 ms: not resolved.** The same code
  gave 1,363 and 1,235 ms in two runs, so the tail at 10 agents moves by
  hundreds of milliseconds between runs, and one run each side cannot say
  whether it moved here. The p95 fell tenfold.

## 4. The deployment the docs recommended, measured for the first time

P12 recommended many agents behind one `agent-api` process instead of a store
handle each, without measuring it. `python -m experiments.p12_http`, at
`2d5a2fd` ([p12-http.json](p12-http.json)): one server process, N agent
processes over HTTP, P12's operation mix (`verify` standing in for the gated
action, which HTTP does not expose).

| agents | ops/s | p50 ms | p95 ms | p99 ms | errors |
|---|---|---|---|---|---|
| 1 | 28 | 23 | 39 | 341 | 0 |
| 10 | 135 | 60 | 135 | 205 | 0 |
| 50 | 129 | 294 | 652 | 1,379 | 0 |
| 100 | 129 | 611 | 1,290 | 2,069 | 0 |

**Its first run found a security defect**: 39 of 200 requests at 10 agents
failed with `sqlite3.InterfaceError`, because authentication read the
revocation table on the store's one connection outside the API's lock,
concurrently with another request. A read corrupted that way is a revocation
check that can answer "not revoked". The federation server had no lock at all.
Both now hold the fabric's own lock (`tests/test_concurrent_requests.py`), and
the table above is the fixed code ([before the fix](p12b-raw/http-before-lock-fix.json)).

Throughput plateaus at about 130 operations a second, because one process
serialises every request on one lock. What the shape buys is the tail: at 100
agents the p99 is 2.1 s against 12.1 s for a SQLite handle per process. One
request costs about 23 ms over loopback HTTP on this machine, against 5 ms
in-process.

## 5. Tried and not adopted

SQLite's busy handler waits for the write lock by sleeping up to 100 ms
between attempts, which looked like the source of its tail. An arm that
retried `BEGIN` every 0.5–5 ms with jitter
([raw](p12b-raw/sweep-poll-arm.json)) cut the p99 at 10 agents
(1,363 → 798 ms) but made the p95 worse (69 → 150 ms) and changed nothing at
100 agents. Not a clear win in one run, so it was removed, not shipped behind
a flag. The tail that remains is one serialised writer shared by up to 100
processes on 8 cores, which no waiting strategy changes.

## 6. Supported capacity, from these runs

Every agent in these runs issues operations back to back, with no model call
between them, so these are worst-case closed-loop limits. Real agents spend
most of their time waiting on a model. Open-loop load, with think time, was
**not** measured, and nothing below is extrapolated to it.

| Shape | Supported, with p95 ≤ 150 ms | Beyond it |
|---|---|---|
| A store handle per agent process, SQLite | **10 processes** (p95 84 ms; p99 1.2 s) | p95 0.5 s at 50, 3 s at 100 |
| A store handle per agent process, Postgres | **10 processes** (p95 128 ms; p99 222 ms) | p95 0.9 s at 50, 3 s at 100 |
| Agents behind one `agent-api` process, SQLite | **10 agents** (p95 135 ms; p99 205 ms) | throughput flat at ~130 ops/s; p95 1.3 s at 100 |

**Aggregate ceiling: about 100–135 operations a second per store** on this
machine, whatever the shape, because every write takes one lock that keeps the
log in a single order and the hash chain linear.

**What would move the ceiling** is not more processes. Candidates, none
measured: logging exposures in batches rather than per retrieve (most
operations are retrieves, and each is a write), and a store per tenant
instead of one per deployment.
