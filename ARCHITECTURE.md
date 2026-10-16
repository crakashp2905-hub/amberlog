# ARCHITECTURE.md

## 1. Guiding constraints

- **Single process first.** All agents, the store and the estimators run in one Python process for P1–P5. Network boundaries are introduced only at a named gate (ROADMAP.md).
- **The event log is the source of truth**; everything else is a projection that can be rebuilt.
- **Cognitive plane and compute plane stay separate.** Nothing in `core/` or `intelligence/` knows about distribution.
- **Components are swappable behind protocols**: store, vector index, estimator, exposure policy, conflict detector, firewall policy, agent.

## 2. Components

```text
              ┌──────────────── Agents (scripted | LLM) ────────────────┐
              │   start_episode / retrieve / remember / record_outcome   │
              └───────────────────────────┬─────────────────────────────┘
                                          │ SDK
┌─────────────────────────────────────────▼─────────────────────────────────────┐
│ MemoryFabric (facade)                                                          │
│                                                                                │
│  core/            intelligence/              governance/         federation/   │
│  ├ MemoryStore    ├ ExposurePolicy           ├ Firewall          ├ Scopes (v0) │
│  ├ EventLog       │   (logs propensities)    ├ SensitiveData     ├ Directory   │
│  ├ VectorIndex    ├ ValueEstimators          ├ Audit (= events)  │  (P6)       │
│  ├ Lineage graph  │   naive|ips|dr|replay|   └ Retention                       │
│  └ Projections    │   amortized                                                │
│                   ├ ConflictDetector                                           │
│                   ├ Consolidator (episodic→semantic/procedural)                │
│                   └ Specializer (context splitting)                            │
└─────────────────────────────────────────┬─────────────────────────────────────┘
                                          │
                               experiments/ + benchmarks/
                    RuleWorld env · runners · baselines · reports
```

## 3. Data flow for one decision

1. The agent calls `retrieve(query, context)`.
2. The vector index returns candidates (relevance only).
3. The **ranking policy** reorders them using value estimates (or relevance, for baselines).
4. The **exposure policy** chooses what to expose, with probabilities → `ExposureDecided` events.
5. The agent acts; the environment verifies the outcome → `OutcomeRecorded`.
6. Estimators consume new events → updated `ValueEstimate` projections.
7. Periodic jobs: consolidation, conflict detection, lifecycle transitions, retention.

## 4. Storage (v0)

| Concern | As built (P1) | Upgrade path |
|---|---|---|
| Event log | SQLite, append-only table, update/delete blocked by trigger. **Optional PostgreSQL** (`pgcompat.py`, 2026-10-16) for writers on several machines: same modules and SQL, triggers in the database, writers serialised on a table lock | Kafka/Redpanda only if write throughput, not just writer count, is ever measured as the limit |
| Projections | in-memory, rebuilt from the log on open | Postgres materialized views |
| Vectors | in-process, pure-Python flat index | numpy/FAISS, then pgvector / Qdrant |
| Lineage graph | in-memory adjacency from provenance edges | a graph DB only if queries demand it |

Settled: SQLite with stdlib only, so a run is a single reproducible file and the package installs with no dependencies (ROADMAP.md, decision 2). Projections are held in memory rather than in tables because rebuilding from the log is fast at P1 scale and keeps exactly one persistence path to get right.

## 5. Agents

- **Scripted agent** (built, `experiments/ruleworld.py`): follows the top-ranked matching claim with probability `q`, else guesses. Its success probability is a closed form, which is what makes exact ground truth possible. ~15k episodes/minute.
- **LLM agent** (built, `memory_fabric/adapters/claude.py`): for confirming that effects survive realistic noise. Not yet run against the live API.

## 6. Repository layout

As built at P1. One flat package, with `governance/` as the only subpackage, because it is the layer most likely to be extended or replaced per deployment:

```text
memory_fabric/
├── ids.py           ULID generation
├── model.py         Memory, ValueEstimate, MemoryStats, enums
├── events.py        event types and constructors (SPEC section 4)
├── eventlog.py      append-only SQLite log: the source of truth
├── projections.py   fold events into queryable state
├── lineage.py       derivation graph, retraction set, evidence independence
├── vectors.py       Embedder protocol, hashing default, flat index
├── exposure.py      exposure policies and propensity logging
├── estimators.py    naive baseline + propensity-corrected IPS
├── explain.py       "why does the system remember this?"
├── fabric.py        the MemoryFabric facade
├── session.py       AgentSession: capability-scoped writes
├── federation.py    offering a memory across a store boundary
├── cli.py           command line interface
├── demo.py          seeder for a deliberately messy store
├── __main__.py      python -m memory_fabric
├── adapters/
│   ├── context.py   memories -> prompt text, with injection defences
│   ├── claude.py    Claude API adapter (optional `anthropic` dependency)
│   ├── ollama.py    local models + real embeddings (stdlib only)
│   └── transcripts.py  existing conversation logs -> episodic memories
├── governance/
│   ├── sensitive.py sensitive-data detection
│   ├── firewall.py  scope-promotion rules
│   └── retention.py retention with rare-event protection
└── observability/
    ├── report.py    the shared read model: pure data, no side effects
    ├── auth.py      token, Host validation, Origin checks
    ├── server.py    read-only HTTP API + static serving
    └── static/
        └── dashboard.html

examples/            runnable demos
experiments/         RuleWorld, the H1 harness, statistics (not installed)
research/            review, hypotheses, pre-registrations, results, decisions
tests/
```

**The embedder is now real, where a model is available.** `OllamaEmbedder` implements the same `Embedder` protocol as the hashing placeholder and plugs in through `MemoryFabric(embedder=...)`. The placeholder matches whole tokens, so `symptom_3` never reaches `symptom 3`; every retrieval-quality number measured before P1–P7 was measured against a deliberately weak stand-in, and the live runs are the first to use real semantics. It caches aggressively — an embed call costs ~1.2s, and the fabric re-embeds on every `add` and every `search`.

**The core has no dependencies; adapters may.** `adapters/claude.py` imports `anthropic` lazily, inside the function that needs a client, so installing this package never drags in an SDK the caller does not use and the rest of the suite runs without it.

**One read model, two surfaces.** The CLI and the dashboard both go through `observability/report.py` and neither queries the fabric directly. Two surfaces that each assembled their own view would drift, and the P2 gate is that a reader can get a straight answer — which requires the same answer whichever surface they reach for. `report.py` returns plain dataclasses and performs no writes; formatting lives in `cli.py` and in the dashboard's JavaScript.

**Why this is flatter than first planned.** The earlier tree (`core/`, `intelligence/`, `federation/`, `controller/`, `sdk/`, `benchmarks/`) was roughly one package per future milestone. At P1 most would hold a single module or nothing at all, and directories named for work that does not exist make a codebase look more finished than it is. A module becomes a package when it has more than one implementation to hold: `governance/` earned that, `federation/` and `controller/` will earn it at P6 and P8.

The swappability the layered version was for comes from the protocols — `Embedder`, `ExposurePolicy`, `ValueEstimator`, firewall `Rule` — not from directory boundaries.

Deferred to the product track (ROADMAP.md P2): `api/` (HTTP server), `dashboard/`, `docker/`.

## 7. Failure handling (v0)

Single process, so the concerns are **crash consistency** (event appends are atomic per batch; projections are rebuilt from the log on open) and **reproducibility** (seeded runs, injected clock, config + commit hash stored with every result). Distributed failure modes (partitions, stale metadata, Byzantine agents) are listed in SECURITY.md and handled at P9.
