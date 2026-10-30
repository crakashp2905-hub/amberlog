# P4 — the operational envelope, and the one thing that did not scale

**Everything passes, and the sweep found a defect the correctness tests could
not see: copy recognition cost 32.4 ms a write at 10,000 memories against 0.19
ms with it off — a 168× write cost, growing linearly.** That is now 1.27 ms,
and the fix is in the product rather than in a caveat.

- **Harness:** `experiments/p4_envelope.py`. Real processes, not threads
- **Run:** 2026-10-12. Windows 11, single machine, SQLite in WAL mode
- Each row carries its own pass condition; the sweep exits non-zero if any fails

---

## 1. Concurrent writers

| writers | appends | landed | failures | crashed | sequence gaps | wall | ms a write |
|---|---|---|---|---|---|---|---|
| 10 | 100 | 100 | 0 | 0 | none | 0.68 s | 6.82 |
| 25 | 250 | 250 | 0 | 0 | none | 2.00 s | 8.01 |
| 50 | 500 | 500 | 0 | 0 | none | 4.16 s | 8.31 |

**Per-write cost rises 22% while the writer count rises 5×.** Writers serialise
on the log and the queue is fair: nothing was lost, nothing failed, and the
sequence has no gaps at any scale. Total wall time tracks total appends almost
exactly, which is the expected shape for a single-writer-at-a-time log and is
worth stating because it is the only thing in this sweep that behaved as
naively predicted.

The existing concurrency tests use **three or four** processes and
`docs/VALIDATION.md` records their weakness: they pass with the busy-timeout
pragma removed, because writers do not reliably overlap on a fast disk. At 50
writers over 4.16 s the overlap is real, so this sweep is the evidence those
tests could not supply.

## 2. Retrieval latency against store size

| memories | ms a retrieval | ms a write |
|---|---|---|
| 100 | 1.31 | 0.26 |
| 1,000 | 2.72 | 0.24 |
| 10,000 | **19.42** | 0.20 |

**Retrieval is roughly flat to 1,000 memories and linear beyond it.** 100 → 1,000
costs 2.1× for ten times the data, because fixed overhead dominates; 1,000 →
10,000 costs 7.1×, which is linear in all but name. The regime changes around a
thousand memories and the honest statement of the envelope is: **budget about
2 ms a retrieval up to a thousand memories and about 2 ms per additional
thousand after that.**

Writes are flat at ~0.2 ms throughout, which is the append-only log doing what
it is for.

This also puts a third measurement beside P9. The lexical path costs 19 ms at
10,000 memories; the 768-dimension dense path cost **544 ms at 5,183**
(`memory-fabric/vectors.py`). Distribution was declined on a **4.39 ms**
figure, and none of the three numbers since has been close to it.

## 3. The defect this sweep found

Copy recognition compared incoming content against every memory held:

| memories | ms a write, check off | ms a write, check on | overhead |
|---|---|---|---|
| 100 | 0.19 | 0.47 | 2.5× |
| 1,000 | 0.19 | **3.33** | 18× |
| 10,000 | 0.19 | **32.37** | **168×** |

Linear in store size, which makes a store of any size unusable and makes the
default-on choice indefensible. The correctness tests could not see it: they
hold a handful of memories and the rule was right.

**Fixed with a bounded index, not a caveat.** The subset test needs both
directions covered, which is why one inverted index is not enough:

- **Incoming is the shorter side** (`I ⊆ C`): every term of `I` is in `C`, so every candidate appears in `postings[t]` for every `t ∈ I`. The *smallest* of those posting lists is a valid superset, and usually a tiny one — the rarest term in a sentence naming a document is the document's name.
- **Incoming is the longer side** (`C ⊆ I`): a candidate need not contain any particular term of `I`, so the first index cannot reach it. But every term of `C` is in `I`, so indexing each memory under a few of **its own** rarest terms makes it reachable from any of them. This is the re-ingestion case — the copy arrives second, with a filing note — so it is the one that matters.

Both are exact supersets and `is_copy` still decides, so a bug in the index can
only cost time. "Can only cost time" is an argument rather than a measurement,
so `find_copy` — the exhaustive scan — is kept and
`tests/test_duplicates.py::TestTheIndexAgreesWithTheExhaustiveScan` checks the
two paths agree, in both directions, on copies and on near-misses.

| memories | before | after | improvement |
|---|---|---|---|
| 1,000 | 3.33 ms | **0.31 ms** | 11× |
| 10,000 | 32.37 ms | **1.27 ms** | **25×** |

At 2,000 memories the index examines **under a quarter** of the store, and in
the 3,000-memory probe that drove the design, 161 candidates of 3,001.

Residual growth is real and reported: 0.31 → 1.27 ms is 4× for ten times the
data, so the cost is sub-linear and not constant. The anchor posting lists
lengthen as common terms accumulate memories. At the next order of magnitude
this would need measuring again rather than extrapolating.

## 4. Authorisation under load

| agents | tenants | memories | exposures checked | cross-tenant leaks | ms a retrieval |
|---|---|---|---|---|---|
| 10 | 4 | 40 | 100 | **0** | 0.42 |
| 50 | 4 | 200 | 500 | **0** | 1.60 |
| 100 | 4 | 400 | 1,000 | **0** | 1.67 |

**Zero leaks across 1,600 checked exposures.** A pass condition rather than a
measurement: any non-zero value fails the run whatever the latency said.

Latency rises 4× from 10 to 50 agents and then **flattens** between 50 and 100
(1.60 → 1.67 ms) — the cost is in the store size, not the agent count, which is
what a per-query tenant filter in `_eligible_ids` should look like.

The limit of this row is the limit `docs/VALIDATION.md` already states:
**tenancy is checked as authorisation, not as isolation.** Every agent here runs
in one process against one file. Nothing demonstrates — or could demonstrate —
isolation against a caller holding the database.

## 5. Recovery after a kill under contention

| writers | killed mid-write | survivors | stored | sequence gaps | writable after |
|---|---|---|---|---|---|
| 50 | 16 | 36 | 360 | **none** | **yes** |

Sixteen of fifty processes killed while writing, and the log reopens with no
gaps and accepts new writes. The existing 17 fault scenarios kill a **quiet**
store; a partially written frame is only reachable while others are writing, so
this is the case they do not reach.

What it does not show: the surviving count (36) is not deterministic, because it
depends on how far each victim got before `kill()`. The invariants — no gaps,
still writable — are what the row asserts, and those are deterministic.

## 6. What this does not establish

1. **One machine, one disk, Windows, SQLite.** Nothing here speaks to a network filesystem, a different OS's locking, or a disk under independent load.
2. **10,000 memories is not large.** Retrieval is linear beyond a thousand, so 100,000 would be ~190 ms and would need a different approach rather than a bigger budget. This sweep says where the knee is, not that there is no knee.
3. **Ten appends a writer.** The concurrent rows measure contention at the start of a run; a long-running store with a large WAL may behave differently, and the WAL was not stressed.
4. **No federation.** Cross-store delivery, retraction forwarding and reconciliation are untested here; ROADMAP's P-gates still govern them.
5. **Authorisation, not isolation**, as §4 says.
6. **The recovery row kills at a fixed moment**, 250 ms in. A kill during a specific critical section is what `tests/test_multiprocess_crash.py` targets deterministically, and that remains the stronger evidence for the retraction path.

## 7. The honest summary

> Every pass condition holds: **500 appends from 50 processes with nothing lost
> and no sequence gaps**, **zero cross-tenant leaks across 1,600 exposures**,
> and a log that reopens clean and writable after 16 of 50 writers are killed
> mid-write.
>
> Two things did not scale as naively expected, in opposite directions.
> Per-write cost under contention rose **22% for 5× the writers**, which is
> better than linear. Retrieval is flat to a thousand memories and **linear
> beyond it** — 19 ms at ten thousand — so the envelope has a knee rather than
> a slope, and 100,000 memories would need a different approach, not a bigger
> budget.
>
> And the sweep earned its place by finding a defect the correctness tests
> could not: **copy recognition cost 32 ms a write at 10,000 memories**, 168×
> the baseline and linear in store size. A feature that is right at a hundred
> memories and unusable at ten thousand is not finished. It is now **1.27 ms**,
> via a bounded index that covers both directions of the subset test and is
> checked against the exhaustive scan it replaced — so the fix is in the
> product rather than in a sentence advising people to switch it off.
