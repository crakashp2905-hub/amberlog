# Stability, compatibility and capacity

What you can rely on, and in what way. Every product module declares its tier
in code (`__stability__`). `tests/test_stability.py` fails if this document and
the code disagree.

## The three tiers

| tier | promise | may change |
|---|---|---|
| **stable** | Public functions, classes and CLI commands keep their names and meaning within a minor series. Removals are deprecated for one minor version first and noted in the CHANGELOG. **Events written by any released version replay on every later version** ([VERSIONING.md](VERSIONING.md)). | Internals, private names (`_x`), wording of messages |
| **beta** | Used in production paths and tested, but new. Names may change in a minor version, always with a CHANGELOG entry. Events they write are covered by the replay guarantee like any other. | Signatures, defaults, output shapes |
| **experimental** | New mechanisms. **All opt-in**: nothing in the default path calls them unless you turn it on. | Anything, or removal |

Promotion needs evidence that the change in default behaviour helps,
and the owner's decision (AGENTS.md principle 9).

## Stable (57)

- `memory_fabric.__init__`
- `memory_fabric._fabric.__init__`
- `memory_fabric._fabric.access`
- `memory_fabric._fabric.common`
- `memory_fabric._fabric.core`
- `memory_fabric._fabric.federation`
- `memory_fabric._fabric.lifecycle`
- `memory_fabric._fabric.retrieval`
- `memory_fabric._fabric.sealing`
- `memory_fabric._fabric.sharing`
- `memory_fabric._fabric.writes`
- `memory_fabric.adapters.__init__`
- `memory_fabric.adapters.context`
- `memory_fabric.adapters.mcp`
- `memory_fabric.adapters.tracing`
- `memory_fabric.adapters.transcripts`
- `memory_fabric.certificates`
- `memory_fabric.cli`
- `memory_fabric.dbtypes`
- `memory_fabric.demo`
- `memory_fabric.dispatcher`
- `memory_fabric.duplicates`
- `memory_fabric.enforcement`
- `memory_fabric.estimators`
- `memory_fabric.eventlog`
- `memory_fabric.events`
- `memory_fabric.explain`
- `memory_fabric.exposure`
- `memory_fabric.fabric`
- `memory_fabric.federation`
- `memory_fabric.governance.__init__`
- `memory_fabric.governance.cipher`
- `memory_fabric.governance.erasure`
- `memory_fabric.governance.firewall`
- `memory_fabric.governance.injection`
- `memory_fabric.governance.retention`
- `memory_fabric.governance.sensitive`
- `memory_fabric.identity`
- `memory_fabric.ids`
- `memory_fabric.integrity`
- `memory_fabric.justification`
- `memory_fabric.lineage`
- `memory_fabric.model`
- `memory_fabric.observability.__init__`
- `memory_fabric.observability.auth`
- `memory_fabric.observability.report`
- `memory_fabric.outbox`
- `memory_fabric.pgcompat`
- `memory_fabric.projections`
- `memory_fabric.protocol`
- `memory_fabric.relevance`
- `memory_fabric.sdk`
- `memory_fabric.service`
- `memory_fabric.session`
- `memory_fabric.transport`
- `memory_fabric.txn`
- `memory_fabric.vectors`

## Beta (33)

- `memory_fabric.actions`
- `memory_fabric.adapters.claude`
- `memory_fabric.adapters.claude_chat`
- `memory_fabric.adapters.ollama`
- `memory_fabric.agent_api`
- `memory_fabric.auditor`
- `memory_fabric.authority`
- `memory_fabric.chains`
- `memory_fabric.conflicts`
- `memory_fabric.correction`
- `memory_fabric.extraction`
- `memory_fabric.governance.directive`
- `memory_fabric.hindsight`
- `memory_fabric.incident`
- `memory_fabric.influence`
- `memory_fabric.integrations.__init__`
- `memory_fabric.integrations.langchain`
- `memory_fabric.integrations.tools`
- `memory_fabric.lifecycle`
- `memory_fabric.limits`
- `memory_fabric.manager`
- `memory_fabric.migrate`
- `memory_fabric.observability.logs`
- `memory_fabric.observability.server`
- `memory_fabric.posture`
- `memory_fabric.reach`
- `memory_fabric.relations`
- `memory_fabric.rerank`
- `memory_fabric.response`
- `memory_fabric.review`
- `memory_fabric.status`
- `memory_fabric.tenancy`
- `memory_fabric.validation`

## Experimental (13)

- `memory_fabric.adapters.systemone`
- `memory_fabric.branching`
- `memory_fabric.compaction`
- `memory_fabric.context_map`
- `memory_fabric.context_receipt`
- `memory_fabric.governance.model_screen`
- `memory_fabric.independence`
- `memory_fabric.mental_models`
- `memory_fabric.objective`
- `memory_fabric.objective_v2`
- `memory_fabric.receipts`
- `memory_fabric.rulebook`
- `memory_fabric.trust`

## Compatibility, as tested

These are what CI runs on every commit to `main`, and what the 0.11.0
release acceptance ran ([RELEASE_EVALUATION.md](docs/RELEASE_EVALUATION.md)).
Anything else is untested, not unsupported.

| dimension | tested |
|---|---|
| Python | 3.11, 3.12, 3.13 |
| OS | Ubuntu, macOS, Windows (GitHub-hosted runners); Windows 11 locally |
| Storage | SQLite (stdlib, the default); PostgreSQL 16 (`postgresql://` URL, needs `psycopg>=3.1`) |
| Runtime dependencies | none for the core; optional extras for Postgres, the Claude adapter and the LangChain retriever |
| Container | the repository's `Dockerfile` (non-root, uid 10001), built and smoke-tested in CI |
| Store schema | every released schema opens on this version; a newer schema is refused by `doctor` (exit 5) rather than half-read |
| Federation protocol | version 1. Peers on different schema versions interoperate; an unsupported protocol version is refused |
| MCP | protocol versions 2025-06-18 and earlier negotiated versions (`tests/test_mcp.py`) |

## Capacity, as measured

From [DEPLOYMENT.md §3](DEPLOYMENT.md), measured on one machine:

- **About 100–135 operations a second per store**, whatever the shape.
- **p95 under 150 ms** up to about 10 agent processes per store, or 10 agents
  behind one `agent-api` process.
- **Past that, run one `agent-api` process** rather than giving every agent
  its own store handle.
- **The action fence makes writers wait** while a fenced action runs: up to
  about 2 s under continuous action, 12–16% fewer actions a second.

These are measurements, not limits the code enforces. Measure your own
workload before relying on them.
