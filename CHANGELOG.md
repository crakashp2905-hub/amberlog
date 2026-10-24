# Changelog

Format follows [Keep a Changelog](https://keepachangelog.com/). Versions track the
**memory schema**, not the Python API — see [VERSIONING.md](VERSIONING.md) for why.

## [Unreleased]

### Added
- **Evidence certificates** (`certificates.py`, schema 0.9.0): a versioned record of the evidence a decision rests on (ids, versions, recorded premises, source roots, policy, log position). `verify_certificate` re-checks all of it against the store and fails closed, with stable reason codes. A certificate is not proof and not a capability.
- **Action gate** (`actions.py`): the tool grant is checked before any evidence, so valid memory never grants a tool. Protected tools need a certificate that still verifies; rules can require independent sources and a human approval bound to the certificate digest. Every decision appends an `ActionGated` event (ids and versions, no content). See `examples/action_gate.py`.
- **Mental models** (`mental_models.py`): evidence-backed summaries that go stale when their evidence changes, with a coalesced and idempotent refresh queue. A stale model cannot pass a protected action.
- **Incident reconstruction** (`incident.py`): from a gated action back to source observations, as of the action, redacted, with a read-only counterfactual per source. Measured against live withdrawal in [P9](research/results/p9-incidents.md).
- **Observation-only auditor** (`auditor.py`): triggers and deep checks for high-impact actions, withdrawals, contradictions, write bursts and failed deliveries. It writes nothing and no check consults it. Policies compared in [P10](research/results/p10-audit.md).
- **Independence signals**: near-copies are reported on every certificate verification. An opt-in `independent_support_strict` check counts them as one source.
- **`reconstruct(deadline_ms=...)`**: an optional wall-clock budget for chain search.
- **`conceal_cross_tenant`**: opt-in, makes a cross-tenant refusal identical to a missing id.
- **Benchmarks**: [P5](research/results/p5-poisonworld.md) (ten-agent poisoning, pre-registered), [P12](research/results/p12-load.md) (latency at 1/10/50/100 agents).
- **Threat-mapped security regression suite** (`tests/test_security_regression.py`), **threat model** (`docs/SAFETY_AND_SECURITY.md`), **test plan** (`docs/SECURITY_TEST_PLAN.md`) and **implementation status** (`docs/IMPLEMENTATION_STATUS.md`).
- **MCP server** — `memory-fabric --db store.db mcp --agent <id>` serves one store to one agent over stdio, so any MCP-capable client can use it. Standard library only. Built on `AgentClient`, so it exposes `recall`, `fetch`, `verify` and `remember` and nothing else: no unenforced read, no scope argument, and deliberately no `record_outcome`, because the model on the pipe is the agent being scored. Exposure tokens stay server-side; the model names memories by id and cannot forge one. Checked against the official MCP Python SDK client as well as its own tests.
- **Release workflow** (`.github/workflows/release.yml`) on `v*` tags: version agreement check, full tests and fault matrix, GitHub release with wheel and sdist, container image to GHCR. PyPI publishing is wired but **off** until the repository variable `PYPI_PUBLISH` is set, because the name `memory-fabric` is taken on PyPI by an unrelated project.

- **Live Claude over MCP** (`experiments/live_claude_mcp.py`): Sonnet 5.5 and Opus 5.5, 20 trials; every run recalled and verified, and a retraction issued from another process mid-session was refused 10/10 with no model recommending the withdrawn fix. [Result](research/results/live-claude-mcp.md)
- **`mcp --trusted-local`** for a single user's local assistant: the agent's clean writes become active without review, marked `activation: trusted-local` in provenance; the sensitive-data and injection screens still apply.
- **Prompt-injection screen at ingest** (`governance/injection.py`): instruction overrides, chat-template role tokens and prompt-exfiltration requests are quarantined, on write and again at share time; persona overrides warn. Positive and near-miss negative per pattern.
- **Obfuscation-aware secret screening**: variant scans undo invisible and full-width characters, look-alike letters, spaced key groups, URL encoding and base64/hex wrappers, plus a `password_in_prose` pattern. Red team: **0/13 → 12/13** caught; 0 near-miss false positives.
- **`migrate-keys`**: moves an existing store's content keys out of the database, verified by a full replay before anything is cleared. `--keys` defaults to `$MEMORY_FABRIC_KEYS`.
- **Container keys on their own volume by default** (`/keys`), with an entrypoint that keeps older in-database-key stores running and tells the operator how to migrate.
- **Dashboard operators**: `serve --operators-file` gives each operator their own token, and an access log records who looked at what, including refused requests, outside the event log.
- **Authenticated agent API** (`agent-api`, `agent-api-issue`): recall, fetch, verify and remember over HTTP for agents in other processes or machines, verified per request from signed, expiring credentials. Refuses plain HTTP off loopback, browser requests and oversized bodies.
- **`erase` and `erasure-scope`** commands, and an erasure-request runbook in `docs/OPERATIONS.md`.
- **Optional PostgreSQL backend** (`memory-fabric[postgres]`, `--db postgresql://...`) for writers on several machines. Same modules and SQL through a compatibility layer; append-only triggers in the database; writers serialised on a table lock so `seq` stays gapless and the chain ordered. Storage-touching tests run against it in CI.
- **Release supply chain**: SPDX SBOMs for distributions and image; Sigstore build-provenance and SBOM attestations where GitHub allows them (public repository or Enterprise).
- **macOS** added to the CI test matrix.

### Fixed
- **The agent API reset connections at 100 concurrent agents.** The socket backlog was the library default of 5; it is now 128 (found by `experiments/p12b_api_load.py`).
- **Credentials expired 1000x early.** `now` is epoch milliseconds and the lifetime is seconds, but they were added unconverted. The default hour-long credential lasted 3.6 s, and `agent-api-issue --ttl 1800` lasted 1.8 s. Every unit test called back at once, so nothing failed until a live model, a few seconds into its turn, was refused (`experiments/live_claude_http.py`). Credentials issued before the fix simply expire.
- **The action gate verified against a stale view in another process** (found by `experiments/e2e_validation.py`), and two fail-closed leaks: raw exception text over the agent API and MCP, and concealed cross-tenant `derive` confirming an id exists.
- **Re-ingestion through encoding noise.** Zero-width characters, soft hyphens, ligatures and non-ASCII hyphens no longer let a withdrawn document return as active, independent evidence.

### Changed
- **Agent API rate limits.** Per-agent token bucket (default 20/s, burst 40; `--rate-limit`, `--burst`), failed authentications limited per remote address, `429` with `Retry-After`. The per-agent exposure-token cache is bounded (oldest evicted).
- **Chain search prefers the chain whose weakest link is strongest** (P1d, pre-registered on a fresh holdout: three-hop sufficiency 0.417 → 0.917).
- **A broken `cryptography` install no longer crashes every write.** A native panic on import (a `BaseException`) escaped the availability check. The store now falls back to encrypt-then-MAC, warns once, and `doctor` names the reason: a warning, or a failure when AES-GCM content exists that cannot be read there.
- **`derive` never writes a conclusion less restricted than its premises.** A summary of `restricted` content used to be written `internal`, so it could be shared.
- **The ingest screen reads `context` and `structured`, and `revise` is screened.** Before, a secret or an injection placed in metadata was stored active and inherited by every memory `derive` drew from it, and a revision could add either to an active memory. Both are quarantined now. Ordinary metadata is unaffected; a test pins that.
- **The Claude adapter defaults to `claude-opus-5-5`**, the current Opus, instead of `claude-opus-5`. The request shape was checked against the current API reference and needed nothing else: adaptive thinking, explicit effort (the new model defaults to `medium`), strict tools, no forced `tool_choice`, and the `fallbacks: "default"` form with its matching beta. Still not run live — no key here (P3 gate).

### Fixed
- **CI was red on `main` for seven pushes.** The real-embedder benchmark arms raised when no Ollama embedder was reachable, which is always true in CI; they are now skipped and reported as skipped, as their docstring promised. Asking for one by name still raises.
- **A copy of withdrawn evidence read as justified.** Copy recognition (0.8.0) contested it; `JustificationGraph.recompute` called it a root observation with nothing to lose. `faultsim`'s `cycle_terminates` caught the disagreement. `recompute` now checks the copy component first.
- **`memory_fabric.__version__` said 0.7.0** while the wheel said 0.8.0. A test now keeps them in step.
- **A running fabric did not see other processes' writes.** An operator's CLI quarantine did not reach an already-running MCP server, app or dashboard until restart; verify kept reporting the withdrawn memory usable. Measured live before the fix: refused 0/3. Every serving, enforcing and writing entry point now catches up on the log (`refresh()`), at ~5.5 µs when nothing changed.
- **`backup` crashed on every store with external keys** — the custody SECURITY.md recommends — because its verification replay used the in-database key provider.
- **SECURITY.md contradicted itself** on whether content encryption is authenticated and whether credentials can be revoked; docs/AUDIT.md still listed action-time re-checking as missing.
- **A float's digits could pass as a credit card** in the secret screen (Luhn on the fractional part).

## [0.8.0] — 2026-10-12 — copy recognition
A re-ingested document is recognised as a copy and gets no independent source root; withdrawing a document withdraws its copies. One event type, additive. [SPEC.md §0.8.0](SPEC.md)

## [0.7.0] — 2026-10-11 — bitemporal validity
`valid_from` / `valid_to` on `Memory`, `applies_at()`, and `retrieve(as_of=…)` filtering before the index is queried. Additive. [SPEC.md §0.7.0](SPEC.md)

## [0.6.0] — 2026-10-11 — authenticated content encryption
`enc:v1` was unauthenticated and malleable. `enc:v2` (encrypt-then-MAC, zero-dependency) and `enc:v3` (AES-256-GCM when `cryptography` is installed) replace it for writes, with associated data binding store, memory and version; key custody can leave the database. Older code must not open a newer store. [SPEC.md §0.6.0](SPEC.md)

## [0.5.0] — 2026-10-11 — tenant identity
`tenant_id` on `Memory`, enforced at the handle rather than per call. Additive. [SPEC.md §0.5.0](SPEC.md)

## [0.4.0] — 2026-10-11 — the share record, and a per-hop retraction target
`MemoryShared` records what a recipient store called its copy, so a retraction can follow a memory past the first hop. Additive events plus one storage migration. [SPEC.md §0.4.0](SPEC.md)

## [0.3.0] — 2026-10-10 — withdrawal basis, store identity, retraction protocol
A withdrawal records its `basis`; each store gets an opaque `store_id`; origin records carry the exact version imported; retraction-protocol, access-denied, support-recomputed and content-erased events; per-memory sealed content. Additive. [SPEC.md §0.3.0](SPEC.md)

## [0.2.0] — 2026-10-07

### Added
- **Packaging.** Installable wheel, a `memory-fabric` console script, and the dashboard bundled as package data. CI checks the wheel actually contains it, because a missing static file only fails in front of a user.
- **Duplicate suppression.** `remember` returns the existing memory and emits `MemoryDuplicateSuppressed` when an agent rewrites content it already wrote *in the same episode*, compared after normalising whitespace and case. Scoped to one episode deliberately: the same claim on two occasions is two observations, and that genuinely is more evidence.
- **Token accounting on every model call.** AGENTS.md requires that LLM calls go through one wrapper logging model, prompt hash and token counts, and the Ollama client was logging none of it. It now keeps a ledger. The prompt is hashed rather than stored, because a prompt contains memory content and may contain exactly what the governance layer exists to keep out of secondary surfaces. Cost stays in tokens: multiplying by a made-up price would be a number without a run behind it.
- **Ollama adapter** — local models and real embeddings (`OllamaEmbedder`), with no new dependency since Ollama speaks HTTP over `urllib`. This replaces the hashed bag-of-words placeholder wherever a model is available.
- **Federation** across store boundaries: the recipient's firewall decides, imports arrive unvalidated, and provenance crosses with them.
- **`AgentSession`** — writes scoped to one agent and one episode, so an adapter cannot attribute work to another agent.
- **What the withdrawal bases have actually been measured to be worth.** `co_occurrence` and `unstated` are flagged as weak on the strength of two runs. `contrastive_harm` is documented as resting on thin evidence rather than silently treated as equal to a sensitive-data finding: PA' is its only measurement, where it fired three times in 120 episodes and all three withdrawals were irrelevant to the episode that triggered them. Three events cannot establish a rate, so it stays out of `WEAK_BASES`; what it currently supports is "rare", not "accurate".
- **Schema version reporting.** `overview` names the installed schema version and every version that wrote into the log, and warns when the log is newer than the build reading it. A projection silently skips events it does not recognise, which is the right behaviour and a terrible failure mode to hit without being told. Versions compare numerically, because `0.10.0` sorts below `0.2.0` as a string.
- **Container image.** A wheel on `python:3.13-slim`, non-root, with the store on a volume because the event log is the source of truth. CI builds it and checks the server answers on the published port and refuses unauthenticated requests.
- **`propagate_retraction`** — a retraction reaches the stores a memory travelled to. PRIOR_ART.md identifies this as the claim that survives the novelty downgrade: none of the four adjacent papers carries provenance across a federation boundary, so none can do it. It existed as hand-written experiment code, which meant the product did not actually have it. It quarantines rather than deletes, because an importer may have built on the memory and its descendants need to become *contested* rather than vanish; it leaves alone an import the recipient had already withdrawn, because the recipient having independently found the problem is the evidence that matters when deciding whether to trust that sender again; and it matches on provenance method as well as origin, because a memory derived locally from an import inherits the parent's origin record and looked like a second copy of it — a bug that quarantined the recipient's own conclusion directly instead of contesting it. The origin can say its observation was wrong; only the recipient can say what follows for the reasoning built on top.
- **`memory-fabric backup`** — a consistent snapshot of the event log while the store is live, which then **replays the copy** and fails if its event count does not match the source. The log is the source of truth, so a project that says so should not outsource the one operation that protects it to the `sqlite3` CLI; and `cp` is wrong here, because WAL mode means a mid-write copy is a database plus an uncommitted write-ahead log whose restore depends on timing. The replay check matters because a truncated backup opens perfectly well.
- **[DEPLOYMENT.md](DEPLOYMENT.md)** — backup and restore, serving behind something, measured capacity, upgrades, what to watch, and a plain list of what this is not ready for: one writer, one token with no identity, no encryption at rest, and value-ranked exposure not recommended on current evidence.
- **Secret scanner** (`tools/scan_secrets.py`) pointing the project's own detector at its own repository, wired into CI.
- [VERSIONING.md](VERSIONING.md) — the guarantee is on the event log, not the Python API, because a renamed argument costs a minute and an unreplayable log costs the data.
- CI across Python 3.11–3.13 on Linux and Windows, run with **no dependencies installed**, because the zero-dependency claim is only true if it is checked.

### Fixed
- **`backup` reported success having copied nothing.** `--db :memory:` opens a fresh, empty store, so the command copied its zero events, compared zero against zero, and printed a verified-looking result — the worst possible failure for the one operation that protects the event log. It now refuses, with a non-zero exit and no file left behind. Found by the live memory-OS validation on the first run after that section was added to it.
- **Ranking by value was ranking by creation time.** `rank_by="value"` ordered candidates by `(-value_mean, memory_id)`, and `value_mean` is `0.0` for a memory nothing is known about — so in a store with little value evidence every candidate tied at zero and the sort fell through to the id, which is a ULID and therefore time-ordered. Relevance was discarded entirely, a newly written or imported memory could not be exposed, and value evidence can only be earned by exposure. Only the epsilon exploration broke the deadlock, weakly: a four-agent federation retrieved none of 36 imports across eight consecutive episodes. An unevaluated candidate is now ordered by the only signal that exists for it, which is relevance; measured value still outranks relevance wherever there is any. This also means [Phase A](research/results/phase-a-real-agent-benchmark.md)'s `fabric_causal` number is part exploration cost and part this defect, and is corrected in §6a there. The ranking had tests and they all passed, because every one of them gave its candidates distinct values — nothing tested the case that dominates a real cold store.
- **`explain()` leaked secrets.** Redaction lived in the observability layer, but an explanation is a display surface too: printing one to a terminal showed the exact credential the firewall had quarantined the memory for containing. Found by a live model run, not by the 384 tests that existed at the time. Scrub helpers now live beside the detector in `governance/sensitive.py` and both surfaces share them.
- **`auto_activate` promoted imports**, defeating the guarantee that value earned in one store does not cross to another.
- **Mutating HTTP methods desynchronised the connection.** An unhandled POST left its body unread, so the next request on a keep-alive connection parsed mid-body. They are now refused with `405` and an `Allow` header after draining.
- **Quadratic listings.** The IPS estimator rescanned every exposure record per memory; now indexed once per `fit`. 12× faster at 400 memories, and it scales.
- **Retention treated epoch 0 as "no timestamp"**, silently making every memory immortal.
- **Retrieval had no relevance floor**, so a query with nothing to match returned the least-bad rows in the store.
- **The API emitted invalid JSON.** `Infinity` for an unknown value estimate — which Python reads back happily and `JSON.parse` rejects outright, so every non-Python client broke while the test suite stayed green.
- **Signed hashing could cancel to zero**, crashing the embedder on `log(0)`.
- **The CLI crashed on Windows** consoles that cannot encode box-drawing characters, and silently created an empty store when `--db` was mistyped.

### Changed
- Schema `0.1.0` → `0.2.0`. Additive; old logs replay unchanged.
- **`quarantine` now warns against the policy Phase A killed.** Driving a quarantine from "this memory was in context when an episode failed" cut the rate at which a correct memory reached the prompt from 60% of episodes to 18%: six actions span six fault codes, so the memory that asserted what the agent wrongly said was usually a *correct* memory about a different situation. Agreement with a mistake is not evidence of having caused it. The docstring and the CLI help now say so, because the lifecycle makes withdrawal easy and nothing warned that it destroys more correct memory than wrong.

## [0.1.0] — 2026-09-27

Initial prototype: append-only event log as the source of truth, rebuildable projections, provenance and lineage, TMS-style retraction, governance (sensitive-data detection, firewall, retention), exposure logging with propensities, value estimation, and read-only observability behind token auth.
