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

- `amberlog.__init__`
- `amberlog._fabric.__init__`
- `amberlog._fabric.access`
- `amberlog._fabric.common`
- `amberlog._fabric.core`
- `amberlog._fabric.federation`
- `amberlog._fabric.lifecycle`
- `amberlog._fabric.retrieval`
- `amberlog._fabric.sealing`
- `amberlog._fabric.sharing`
- `amberlog._fabric.writes`
- `amberlog.adapters.__init__`
- `amberlog.adapters.context`
- `amberlog.adapters.mcp`
- `amberlog.adapters.tracing`
- `amberlog.adapters.transcripts`
- `amberlog.certificates`
- `amberlog.cli`
- `amberlog.dbtypes`
- `amberlog.demo`
- `amberlog.dispatcher`
- `amberlog.duplicates`
- `amberlog.enforcement`
- `amberlog.estimators`
- `amberlog.eventlog`
- `amberlog.events`
- `amberlog.explain`
- `amberlog.exposure`
- `amberlog.fabric`
- `amberlog.federation`
- `amberlog.governance.__init__`
- `amberlog.governance.cipher`
- `amberlog.governance.erasure`
- `amberlog.governance.firewall`
- `amberlog.governance.injection`
- `amberlog.governance.retention`
- `amberlog.governance.sensitive`
- `amberlog.identity`
- `amberlog.ids`
- `amberlog.integrity`
- `amberlog.justification`
- `amberlog.lineage`
- `amberlog.model`
- `amberlog.observability.__init__`
- `amberlog.observability.auth`
- `amberlog.observability.report`
- `amberlog.outbox`
- `amberlog.pgcompat`
- `amberlog.projections`
- `amberlog.protocol`
- `amberlog.relevance`
- `amberlog.sdk`
- `amberlog.service`
- `amberlog.session`
- `amberlog.transport`
- `amberlog.txn`
- `amberlog.vectors`

## Beta (51)

- `amberlog.action_receipt`
- `amberlog.actions`
- `amberlog.adapters.claude`
- `amberlog.adapters.claude_chat`
- `amberlog.adapters.ollama`
- `amberlog.agent_api`
- `amberlog.answerability`
- `amberlog.auditor`
- `amberlog.authority`
- `amberlog.branching`
- `amberlog.chains`
- `amberlog.conflicts`
- `amberlog.connect`
- `amberlog.consensus`
- `amberlog.context_receipt`
- `amberlog.correction`
- `amberlog.dependence`
- `amberlog.extraction`
- `amberlog.freshness`
- `amberlog.governance.directive`
- `amberlog.hindsight`
- `amberlog.incident`
- `amberlog.influence`
- `amberlog.integrations.__init__`
- `amberlog.integrations.langchain`
- `amberlog.integrations.tools`
- `amberlog.lifecycle`
- `amberlog.limits`
- `amberlog.manager`
- `amberlog.migrate`
- `amberlog.models`
- `amberlog.observability.control`
- `amberlog.observability.logs`
- `amberlog.observability.metrics`
- `amberlog.observability.server`
- `amberlog.pilot`
- `amberlog.posture`
- `amberlog.presets`
- `amberlog.reach`
- `amberlog.reasons`
- `amberlog.relations`
- `amberlog.rerank`
- `amberlog.response`
- `amberlog.retrieval_profiles`
- `amberlog.retrievers`
- `amberlog.review`
- `amberlog.status`
- `amberlog.tenancy`
- `amberlog.tour`
- `amberlog.typedclaims`
- `amberlog.validation`

## Experimental (22)

- `amberlog.adapters.systemone`
- `amberlog.claimcheck`
- `amberlog.compaction`
- `amberlog.context_map`
- `amberlog.decay`
- `amberlog.docsource`
- `amberlog.document_formats`
- `amberlog.evidence_completeness`
- `amberlog.governance.model_screen`
- `amberlog.history_query`
- `amberlog.import_preview`
- `amberlog.independence`
- `amberlog.knowledge_compiler`
- `amberlog.lossless_compaction`
- `amberlog.mental_models`
- `amberlog.navigation`
- `amberlog.objective`
- `amberlog.objective_v2`
- `amberlog.receipts`
- `amberlog.rulebook`
- `amberlog.trust`
- `amberlog.typed_query`

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
