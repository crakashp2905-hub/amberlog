# How many agents, how far connected, and what carries between sessions

Every number here is measured, with its source. An extrapolation says so.

## Agents on one store

One store takes about **100–135 operations a second**, whatever the shape,
because every write takes one lock that keeps the log ordered, and a
retrieval is a write (exposures are logged) ([P12b](../research/results/p12b-catch-up.md)).

| shape (agents issuing operations back to back) | supported with p95 ≤ 150 ms |
|---|---|
| a store handle per agent process, SQLite | 10 processes |
| a store handle per agent process, Postgres | 10 processes |
| agents behind one `agent-api` process | 10 agents; flat at ~130 ops/s beyond |

Back-to-back is the worst case. Measured **open-loop**, with arrivals that
do not wait on completions, one store sustains **130 operations a second**
(p99 91 ms) and saturates at 160 (p99 2.0 s) (DEPLOYMENT.md §3). The agent
count follows from how often each agent touches memory, which this does not
measure: at one operation per agent every 5 seconds, 130 ops/s is about 650
agents; at one a second, about 130.

**Beyond one store's write rate, add stores, not agents per store.** Each
team or tenant gets its own store (`tenancy.TenantRouter` for tenants), and
stores federate.

## How far stores can be interconnected

Federation is store to store: each store offers memories to peers, peers
re-share, and a correction at the origin follows every copy. Measured with
`experiments/fed_scale.py` (in-process transport, a correction at the
origin, every store's dispatcher drained until quiet):

| topology | stores | received a copy | copies still live after the correction | dispatcher rounds |
|---|---|---|---|---|
| chain | 2 – 17 | all | **0** | 2 |
| chain | 20 | 17 | **0** | 2 |
| star | 100 | 100 | **0** | 2 |
| mesh, each store re-sharing to 3, with cycles | 100 | 93 | **0** | 4 |

- **Depth is limited to 16 hops** (`protocol.MAX_HOPS`), on purpose. A
  forwarded retraction stops there, so before 0.12.0 a 20-store chain left
  its last two copies live after a correction. `offer` now refuses an import
  that would sit beyond the limit, so **a copy never travels further than its
  retraction can follow**.
- **Breadth is not limited.** A star of 100 and a mesh of 100 both converge.
- **Cycles terminate**: a store already on a memory's provenance chain is not
  offered it again.
- Measured in one process. Over HTTP, each hop adds a network round trip,
  and an offline peer stays `pending_reconciliation` until it returns
  (`verify_recovery`). Multi-machine numbers have not been measured.

## Carrying a session's context into future sessions

Yes. That is what the store is for. A session's context persists in three
forms, and later sessions get it through governed retrieval:

1. **What the agent learned**: `remember(..., source_episodes=[episode])`
   writes a memory tied to the session that produced it. Any later session
   that the memory's scope allows can retrieve it (`private`: that agent and
   its collection readers; `team`; `federated`).
2. **The session itself**: `start_episode(agent, task, context={...})`
   records the session's context (site, team, task). `adapters.ingest_transcript`
   stores a whole past conversation as an episode plus an episodic memory,
   with an optional verified outcome.
3. **A compact handoff**: `compaction.compact_session(episode)` writes one
   governed summary of what the session established, as a derivation of
   its memories, with disputes kept and every value checked. A correction to
   any input contests it, and the manager re-compacts from what still
   stands. C1: stale values shown 0 against 1.00 for an ungoverned summary,
   at the same coverage ([c1](../research/results/c1-compaction.md)).
4. **Its purpose**: a `MemoryObjectiveV2` states what the session needs, and
   proposals to change it are logged and adopted only by another reviewer
   (`ObjectiveLog`), so the next session can start from the adopted one.

What a future session gets is governed, not raw. It sees only memories its
scope allows. It does not see anything withdrawn, contested or from a source
caught injecting. Each memory comes with its provenance, its authority and
any disputes. A session's context is evidence for later sessions, not an
instruction to them: a memory that reads as an instruction is classed as one
and never authorises an action (`authority.py`).
