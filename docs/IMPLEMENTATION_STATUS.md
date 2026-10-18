# Implementation status

The living map from the [AI-safety and cybersecurity plan](AI_SAFETY_CYBER_RESEARCH_IMPLEMENTATION_PLAN.md)
to what this repository actually does. Every row names code and a test, or
says plainly that there is none. "Implemented" means *implemented and tested
here*; it is never a claim about security in general.

Status vocabulary: **implemented** · **partial** (exists, with a named gap) ·
**missing** · **blocked** (needs something this environment does not have).

---

## 1. Baseline (Task 0)

Recorded on commit `d05ab2d` (main, 2026-10-16), Linux 6.18, Python 3.13.16,
psycopg 3.2.3, cryptography 50.0.1. No product code was changed to produce it.

| Command | Result |
|---|---|
| `python3 -m unittest discover -s tests -t .` | **1152 tests, OK, 36 skipped**, 201.8 s |
| storage-touching modules with `MF_TEST_POSTGRES_URL` set (Postgres 16, local) | **938 tests, OK** (0 skipped), 364.0 s |
| `python3 -m experiments.faultsim` | **17/17 scenarios pass** |
| `python3 tools/scan_secrets.py` | 94 known synthetic fixtures, **0 unexpected**, exit 0 |
| `python3 -m compileall -q memory_fabric experiments tests examples tools` | exit 0 |
| `ruff check memory_fabric` (defaults; not configured by the repo, informational) | 215 findings, 186 auto-fixable: unused imports ×19, import order ×14, unused locals ×3, **F811 duplicate `access_denied` in `events.py`**, **S110 bare `except: pass` in `cipher.py`** |
| `mypy memory_fabric --ignore-missing-imports` (not configured, informational) | 27 errors in 11 files, mostly `pgcompat` connections typed as `sqlite3.Connection`; two are real (see §4) |

The 36 skips are the Postgres-only file (skipped without a server), optional
model adapters without a running Ollama, and live-model harnesses without an
API key. The benchmark modules excluded from the Postgres run are pure
experiment harnesses, excluded because they take hours there and exercise no
storage path that the included modules do not.

**Environment limits.** No Docker daemon, no Ollama server, no
`ANTHROPIC_API_KEY`. Anything depending on them is **blocked** here, not
assumed to work.

---

## 2. Architecture as it stands

One append-only event log is the source of truth; everything else is a
projection rebuilt from it (AGENTS.md principle 3).

```
 agents ──► MCP server (stdio) ─┐
 agents ──► agent HTTP API ─────┼─► MemoryService / TenantView (verified principal)
 host code ─────────────────────┘          │
                                           ▼
                                   MemoryFabric (library; trusts its caller)
             ┌──────────────┬──────────────┼──────────────┬──────────────┐
         screens       Enforcer +      truth maint.    federation      retrieval
   (sensitive, inj.)  ExposureToken  (justification,  (outbox/inbox,  (lexical, vectors,
                                      lineage, copies) HMAC transport) chains, relations)
                                           │
                       EventLog + IntegrityChain (SQLite or Postgres) + cipher
```

| Layer | Modules |
|---|---|
| Event log, hash chain, checkpoints | `eventlog.py`, `integrity.py`, `pgcompat.py`, `cli.py checkpoint/verify` |
| Projections | `projections.py`, `model.py` |
| Enforcement and action-time check | `enforcement.py`, `fabric.use`, `fabric.verify_before_action` |
| Identity and tenancy | `identity.py`, `service.py`, `fabric.TenantView`, `agent_api.py`, `adapters/mcp.py` |
| Truth maintenance | `lineage.py`, `justification.py`, `duplicates.py`, `relations.py` |
| Federation | `protocol.py`, `outbox.py`, `dispatcher.py`, `transport.py`, `federation.py` |
| Screens and crypto | `governance/sensitive.py`, `governance/injection.py`, `governance/cipher.py` |
| Retrieval | `relevance.py`, `vectors.py`, `rerank.py`, `chains.py`, `exposure.py` |
| Explanation | `explain.py`, `fabric.audit_trail`, `fabric.lineage` |

---

## 3. Capabilities against the plan

### Security controls inventoried by Task 0

| Concern | Status | Code | Tests |
|---|---|---|---|
| Authenticated encryption at rest | **implemented** — AES-GCM with `cryptography`, else encrypt-then-MAC (HMAC-SHA256 keystream); AAD binds store, memory and version; legacy v1 read-only | `governance/cipher.py` | `test_cipher.py`, `test_key_migration.py` |
| Key custody | **implemented** — keys outside the event log via Sqlite/Directory/Callback providers; crypto-erasure | `governance/cipher.py`, `fabric.erase_content` | `test_erasure.py`, `test_cipher.py` |
| Cipher suite selection | **partial at baseline** — silent fallback, and a broken `cryptography` crashed every write. Now fixed: visible fallback | `governance/cipher.py` | `test_cipher.py::BrokenCryptography` |
| Agent identity | **implemented** — HMAC credentials, expiry, revocation persisted in SQLite; re-verified per call | `identity.py`, `service.py` | `test_identity.py`, `test_auth.py`, `test_service.py` |
| Principal registrations | **partial** — registrations live in memory; revocations persist | `identity.py` | `test_identity.py` |
| Tenancy | **partial (logical only)** — tenant filter on every read path and on the enforcer; one physical store | `fabric.TenantView`, `enforcement.Enforcer.check` | `test_data_access_paths.py`, `test_service.py`, `test_enforcement.py` |
| Server-side authorization | **implemented** at `MemoryService`, agent API and MCP; **not** at `MemoryFabric`, which is the host library and trusts its caller by design | `service.py`, `agent_api.py`, `adapters/mcp.py` | `test_agent_api.py`, `test_mcp.py`, `test_service.py` |
| Replay / duplicate retraction | **implemented** — dedupe keys, recipient-owned `origin_sequence` cursor, idempotent apply | `outbox.py`, `dispatcher.py`, `protocol.py` | `test_retraction_protocol.py`, `test_federation_transport.py`, faultsim |
| Peer authentication | **implemented** — each retraction HMAC-signed by the origin's peer key and verified before processing; replay handled by the dedupe key above; **no TLS** in-process (terminate in front) | `transport.py` | `test_federation_transport.py` |
| Log tamper evidence | **implemented, with the documented limit** — hash chain detects edits, deletion and reorder; a full rewrite by a writer is detected only against an external checkpoint the operator keeps | `integrity.py`, `cli.py checkpoint` | `test_integrity_chain.py` |
| Append-only at the database | **implemented** on Postgres (trigger); **not** on SQLite (file permissions are the control) | `pgcompat.py` | `test_postgres.py` |
| Secrets in content | **implemented** — ingest screen with variant decoding; quarantine on hit | `governance/sensitive.py` | `test_sensitive_patterns.py`, `test_sensitive_redteam.py` |
| Prompt injection in content | **partial** — write-time pattern screen; retrieved memories delimited as data; a pattern screen is bypassable by construction | `governance/injection.py`, `adapters/` | `test_injection_patterns.py`, `test_adapters.py` |

### Research directions and backlog

| Plan item | Status at baseline | Evidence |
|---|---|---|
| R1 proof-carrying memory / Task 3 | **partial** — `ExposureToken` binds one memory, version, revision, agent, store, tenant and policy id; no multi-evidence certificate, no dependency check, no versioned schema | `enforcement.py`; `test_enforcement.py` |
| Task 4 action-time verification | **partial** — `verify_before_action` re-checks one token; nothing re-checks a *set* of evidence or a derived conclusion's premises, and tool permission is not modelled | `fabric.verify_before_action`, `sdk.py`, `adapters/mcp.py` |
| Task 5 ten-agent benchmark | **partial** — P3b runs 10–100 deterministic agents with five arms incl. oracle for *correction propagation*; poisoning, injection, permission change and copied evidence are not scenarios | `experiments/teamworld.py`, `research/results/p3b-agent-teams.md` |
| Task 6 / R3 independent support | **implemented** for exact copies — source roots, `COPIED` justification, conservative copy recognition (containment and Jaccard thresholds); similar-but-independent reports are kept | `justification.py`, `duplicates.py`; `test_justification.py`, `test_duplicates.py`, `research/results/p2b-copy-recognition.md` |
| Task 7 / R7 bounded multi-hop | **implemented** — bounded chain search with step and node budgets, reports `budget_exhausted` | `chains.py`; `test_chains.py`, `research/results/p1-evidence-chain-reconstruction.md` |
| Task 8 / R9 mental models | **missing at baseline**; now implemented (§6) | — |
| Task 9 / R2 incident reconstruction | **partial** — `explain()` and `audit_trail()` give write → derivation → exposure; no link from an exposure to a plan or tool action, no counterfactual harness | `explain.py`; `test_fabric.py` |
| Task 10 / R6 active auditing | **missing** — `health()` and `doctor` are on-demand checks; no triggers, no audit policy comparison | — |
| Task 11 / R5 privacy-aware federation | **partial** — firewall, scope, `security_class`; tenant refusal leaks no detail; leakage through *derived* memories untested | `governance/`, `enforcement.py`; `test_governance.py` |
| Task 12 operational hardening | **partial** — faultsim (17 scenarios), multiprocess crash, concurrency, backup/restore, key migration; **no** p50/p95/p99 at 10/50/100 agents | `experiments/faultsim.py`; `test_multiprocess_crash.py`, `test_concurrency.py`, `test_backup.py` |
| Contradiction handling | **partial** — `challenge`/`resolve` mark a memory contested and keep both; no automatic contradiction *detector* | `fabric.challenge` |
| State machine | **implemented** — lifecycle states and allowed propagation transitions | `model.py`, `protocol.py`; `test_properties_state_machines.py` |

---

Rows in this section describe the baseline. §6 records what each task changed.

## 4. Known gaps at baseline

1. `events.access_denied` is defined twice with identical bodies (dead code).
2. `cipher.default_suite` swallows any exception building AES-GCM and uses EtM
   instead. Both are authenticated, so it is not a confidentiality hole, but an
   operator cannot tell which suite is in use from the failure. **Fixed after
   the baseline:** a broken install (seen for real as a pyo3 `PanicException`,
   a `BaseException` that crashed every write) now falls back to EtM, warns
   once, and `doctor` names the reason (`tests/test_cipher.py::BrokenCryptography`).
3. `integrity.py` compares an optional bound with `>` (mypy); `chains.py`
   returns a `set` where `frozenset` is declared.
4. Tenancy is logical. One store holds all tenants; there is no hard isolation.
5. Without an external checkpoint, a writer with full database access can
   rewrite the whole chain undetected. This is documented, not solved.
6. No contradiction detector, no mental models, no audit triggers, no latency
   percentiles at agent scale.
7. Lint and type checking are not configured or run in CI.

---

## 5. Proposed sequence

As the plan orders it, inspecting before building and reusing what exists:

1. **Task 1** — `docs/SAFETY_AND_SECURITY.md`: one threat register linking
   SECURITY.md's controls to tests, with accepted gaps stated.
2. **Task 2** — threat-mapped regression tests, `docs/SECURITY_TEST_PLAN.md`.
3. **Tasks 3–4** — a versioned evidence certificate built *on* `ExposureToken`
   and the justification graph; a deterministic verifier with reason codes;
   action-time verification that also requires a separate tool grant.
4. **Task 5** — extend the ten-agent harness with poisoning, injection, copies,
   corroboration and permission changes; selective vs blanket invalidation.
5. **Tasks 6–7** — re-measure the existing copy recognition and chain search
   against the plan's acceptance rather than rebuild them.
6. **Tasks 8–12** — mental models, incident reconstruction, observation-only
   auditing, derived-content leakage, latency percentiles.
7. **Task 13** — full re-run and a README limited to what the runs show.

---

## 6. Progress log

| Task | Status | Where |
|---|---|---|
| 0 Baseline | done | this file |
| 1 Threat model | done | [SAFETY_AND_SECURITY.md](SAFETY_AND_SECURITY.md) |
| 2 Security regressions | done. **Found and fixed:** metadata not screened; `revise` unscreened | `tests/test_security_regression.py`, [SECURITY_TEST_PLAN.md](SECURITY_TEST_PLAN.md) |
| 3 Certificates | done | `certificates.py`, `tests/test_certificates.py` |
| 4 Action-time verification | done | `actions.py`, `examples/action_gate.py` |
| 5 Ten-agent benchmark | done. H5b–d supported, **H5a not supported** as registered | [p5-poisonworld.md](../research/results/p5-poisonworld.md) |
| 6 Independent support | done. Copies collapse; near-copies reported, opt-in strict check; defaults unchanged | `tests/test_independence.py` |
| 7 Bounded multi-hop | done. Time budget added; withdrawn and cross-tenant nodes tested; P1 stays NOT SUPPORTED, so `retrieve` remains the default | `chains.py`, `tests/test_chains.py` |
| 8 Mental models | done | `mental_models.py`, `tests/test_mental_models.py` |
| 9 Incident reconstruction | done. First evaluator had 20% false attribution, fixed | `incident.py`, [p9-incidents.md](../research/results/p9-incidents.md) |
| 10 Active auditing | done, observation only | `auditor.py`, [p10-audit.md](../research/results/p10-audit.md) |
| 11 Privacy-aware federation | done. **Found and fixed:** a summary of restricted content was downgraded to internal | `tests/test_privacy_federation.py` |
| 12 Operational hardening | measured. **Write contention collapses throughput** | [p12-load.md](../research/results/p12-load.md) |
| 13 Release evaluation | done | [RELEASE_EVALUATION.md](RELEASE_EVALUATION.md) |

### 2026-10-18: release track and research directions (docs/WORKPLAN.md)

- **0.11.0 release candidate** cut and accepted (`rc/0.11.0`):
  - SQLite 1,636 OK; Postgres 224 OK;
  - faultsim 17/17; lint and types clean;
  - the wheel installs and `doctor` reports sound;
  - not tagged, because of CI billing.
- **Research results** (each linked from [SCORECARD](../research/SCORECARD.md)):

  | direction | outcome |
  |---|---|
  | G4 | not supported on qwen (35% of headroom); underpowered on gemma |
  | S1 | abandoned |
  | S2 | not supported (28%) |
  | S4 | supported, on the bar |
  | S5 | soundness supported; the leakage bar was mis-set |
  | S6 | supported |
  | M1 | supported on qwen (58%); compiled filters harmful |
  | M2 | running |

- **Security findings fixed:** F12 (echo imports), F13 (acknowledgement
  leakage), an unbounded Postgres connect. Branch protection is enforced from
  the client, with verified backups (docs/BRANCHES.md).

