# Changelog

Format follows [Keep a Changelog](https://keepachangelog.com/). Versions track the
**memory schema**, not the Python API — see [VERSIONING.md](VERSIONING.md) for why.

## [Unreleased]

### Added: federation across machines; two protocol bugs fixed

- **Sharing over the network.** `offer_remote` and `/federation/offer`:
  a signed offer, with the sender's firewall and chain checks there and the
  recipient's firewall and import here. A networked import is always a
  **candidate**, recorded as `peer:<sending store>`, and idempotent. `offer`
  is now `prepare_offer` + `accept_offer`, shared by both paths.
- **CLI:** `memory-fabric federate` serves the federation endpoints and runs
  the manager; `memory-fabric offer <id> --to <store>` shares; a global
  `--share-policy {value,reviewed}` (default `value`, unchanged) lets a
  validated memory leave a store that has no outcome evidence yet.
- **Fixed: forwarded retractions were refused over HTTP.** A recipient
  verified a forwarded retraction with the key it shares with the *origin*,
  not the forwarder, so every second hop failed with 401. The in-process
  transport checks no signatures and hid it. Found by
  `experiments/multihost.py`; regression test `tests/test_multihop_http.py`.
- **Fixed: a server process applied retractions against a stale view.**
  `receive_retraction` and 26 other public entry points did not catch up on
  other processes' writes first, so a share recorded by another process was
  invisible and the retraction was not forwarded. They now do.
- **Multi-host harness** (`experiments/multihost.py`) and CI jobs
  `multihost` (separate server processes, 50 ms a hop, three OSes) and
  `multihost-compose` (separate containers): correction reached the third
  store in 1.3–1.9 s; with it down, it converged ~1 s after restart.
- **Model injection screen** (`governance/model_screen.py`, opt-in): on
  the third-party test split, 20/60 → 46/60 (qwen2.5:3b) or 54/60
  (gemma3:4b) caught, with 6/56 or 3/56 benign texts flagged for review.
- **Frontier models:** `adapters.claude_chat.ClaudeChat` gives every
  model-based evaluation the same interface on Claude, recording model,
  prompt hash and tokens; `.github/workflows/frontier-eval.yml` runs the
  attack checks on Claude once an `ANTHROPIC_API_KEY` secret is set.

### Added: claim checks against the store's own knowledge; key rotation overlap

- **`validation.py`**: a claim is checked against what the store knows. A
  value that was corrected away and is stated again, a value far outside
  every comparable one (robust z > 3.5 *and* beyond 2x the largest or half
  the smallest), or a contradiction of a fact established by an author with
  a track record makes it **suspicious**; a first claim from an unknown
  author is **provisional**; independent agreement **corroborates**.
  Measured on held-out seeds: all three detectable families caught (1.000),
  0 of 450 honest writes flagged, plausible claims from new sources held
  provisional. Indexed per memory version, about 0.1 ms per write.
- **Defaults:** a suspicious write is held as a candidate
  (`hold_suspicious=True`), the action gate refuses suspicious evidence
  (`ToolRule.refuse_suspicious=True`, code `evidence_suspicious`), and
  recall marks it `implausible`. New command: `memory-fabric suspicious`.
- **Federation key rotation with an overlap window**: `Peer.accepted` and
  `previous_keys` in the peers file. The recipient verifies with the key the
  signature names, if current or still accepted; a retired key is refused.
  Drilled over HTTP in four phases (`tests/test_key_rotation_drill.py`);
  RUNBOOKS §3 rewritten.

### Product documentation and consumability

- **README rewritten for users**: what it is and why, what you get with the
  evidence for each, a quick start whose code runs, connecting an agent,
  scale, operations, limits and a documentation map.
- **New docs:** `docs/CONCEPTS.md`, `docs/COOKBOOK.md` (ten recipes),
  `docs/FAQ.md`, `docs/README.md` (every document, by task),
  `examples/README.md`, `docs/RELEASE_NOTES_0.12.0.md`, and **generated**
  `docs/API.md` and `docs/CLI.md` (`tools/gen_reference.py`).
- **TROUBLESHOOTING** explains every action-gate, certificate and limit
  reason code (44), plus permission, hop-limit, compaction and restore errors.
- **Docs that cannot rot:** tests run every Python block in the README,
  quickstart, concepts and cookbook; every offline example; check every
  relative link (698) and that every doc is indexed; check the generated
  references are current, every CLI option has help (68 were missing), and
  every reason code is documented.
- `memory-fabric --version`. Package metadata: keywords, classifiers and
  documentation, changelog, issue and security URLs.
- **Security reporting** is by private email to the maintainer: GitHub's
  private reporting is not available on a private repository.
- **`tools/check.py`** runs what CI's quick jobs run; `tools/gen_stability.py`
  moved into the repository.
- **CI fixed**: main was red from the authority commit onward (mypy in
  `objective_v2.py`; generated documents committed stale).

### Added: governed session compaction (experimental)

- **`compaction.compact_session(fabric, episode, agent)`** writes one
  summary of a session as a `derive(consolidated)` of everything it wrote
  or cited: lineage, retraction and authority follow it. Disputes are kept
  with every value and source; a summary that drops a recorded value or
  resolves a dispute is refused; the summary passes the ingest screen.
  `summary_for(episode)` returns the current one. The manager's new
  `compaction` task re-compacts a session whose summary lost an input.
- **Retention never retires a premise of an exposable memory**, so a
  summary cannot outlive its sources.
- C1 (held-out): stale value shown 0 vs 1.00 for an ungoverned summary,
  coverage 0.956 vs 0.944 for session-filtered notes, no recall gain.

### Added: reach limits, tenant routing, hostile-source withholding by default

- **A copy no longer travels further than its retraction can follow.**
  `experiments/fed_scale.py` found that in a 20-store chain a correction at
  the origin stopped at `MAX_HOPS` (16) and left the last two copies live.
  `offer` now refuses an import beyond the hop limit. Chains to 17 stores,
  stars to 100 and meshes to 100 (with cycles) all converge
  (`tests/test_federation_reach.py`).
- **Retrieval withholds sources caught injecting, by default** (owner's
  decision; T2b supported). `withhold_hostile_sources=False` opts out.
  `hindsight` moves to beta.
- **`tenancy.TenantRouter`**: one store file and key directory per tenant.
- **Directive detector `OVERRIDE` family** (English and German): on the
  third-party deepset/prompt-injections test split, 0/60 → 20/60 caught,
  0/56 benign flagged.
- **`influence.paraphrases`**: unlinked restatements of a claim, reported
  as `possible_paraphrases` in `impact()`.
- **Scheduled model-in-the-loop attacks** (`model-attacks.yml`, weekly).

### Added: permissions, operations and release tooling

- **Seven permissions** (`identity.PERMISSIONS`): read, write, delete,
  correct, export, administer, execute. Roles are bundles: agent = read,
  write, execute; operator = everything but **execute** (separation of
  duties); auditor = read, export. `perm:<name>` grants one directly. Every
  `Session` operation checks its permission; the action gate refuses a
  session without `execute`. New `Session.export_audit()` (content-free).
- **Backup with custody**: `backup --with-keys --include PATH` copies keys and
  config beside the snapshot and writes a manifest of hashes, the event count
  and the chain head. **`restore`** refuses a backup that does not match its
  manifest, never overwrites, and checks the replayed chain head.
- **Structured logs**: `--log-format json` / `MEMORY_FABRIC_LOG_FORMAT=json`;
  the manager logs each cycle and each task failure with ids and codes.
- **Quickstart and reference agent**: `docs/QUICKSTART.md`,
  `examples/quickstart.py` and `examples/reference_agent.py`, each run by a
  test.
- **Release tooling**: `tools/release_bundle.py` (SHA, CycloneDX SBOM,
  secret scan, adversarial gate, test counts, wheel hash) and
  `tools/fresh_machine.py` (install in a fresh venv, use, uninstall, check
  nothing is left), each a CI job.
- **Open-loop load** (`experiments/p12_openloop.py`): latency from the
  scheduled arrival, so queueing counts.
- Docs: `docs/INTEGRATIONS.md`, a supported-version policy (VERSIONING.md),
  threats T9–T12 (SECURITY.md), RUNBOOKS §8 (restore), and
  `docs/HARDENING_STATUS.md` mapping every item of the owner's three lists.
- T2b, the cross-store hostile-source notice: **supported** on held-out
  seeds (0.732 → 0.949 safe success).

### Added: MemoryObjectiveV2, store limits, recovery states, the adversarial gate

- **`objective_v2.py`** (experimental): goal, required facts, preferred
  evidence, excluded context, safety constraints, scope, `as_of`, freshness,
  uncertainty policy and decision impact. Eligibility (security ∧ lifecycle ∧
  hard rules) is separate from ranking (relevance × authority × kind ×
  freshness × independence × soft preferences). An **unreviewed** compiled
  exclusion never removes safety evidence; a compiled V1 objective converts
  to *uncertain* rules, which never filter. Applying an objective has no
  write path. Changes are proposed and adopted through `ObjectiveLog`, by a
  different reviewer, and refused if any registered metric is worse.
- **`limits.py`**: bounded content (1 MiB library, 256 KiB servers),
  per-agent write quotas and per-peer federation budgets, on in servers;
  the agent API answers 429 / 413.
- **Recovery states**: `verify_recovery` reports `quarantined`,
  `pending_reconciliation`, `recovery_unverified` or `revalidated`.
- **`tools/adversarial_gate.py`** and the CI job `adversarial-gate`: fourteen
  attack families, each mapped to the tests holding its invariant; any
  failure, error or empty family fails the gate.
- Metadata-leakage tests (`tests/test_metadata_leakage.py`): with
  `conceal_cross_tenant`, no tenant channel distinguishes a world holding
  another tenant's matching memory from one without it.

### Added: origin-bound authority, exact-action grants, the influence graph

- **`authority.py`**: every memory's trust (`untrusted` < `unverified` <
  `elevated`) and kind (`instruction` / `observation` / `derived_claim`) are
  bound to its origin. They are inherited through summaries, derivations,
  recognised copies and federation, where the origin's verdict travels as a
  floor. Sources are kept apart from summarisers. `MemoryFabric.elevate`
  lifts soft reasons only, per version, by an approver who is not the author.
  Outcomes never confer authority. The roadmap's test (inject → summarise →
  tool copy → share) is `tests/test_authority.py`.
- **`ActionGate`** refuses evidence below `ToolRule.min_authority` (default
  `unverified`) and any `instruction` used as evidence. **Grants**
  (`issue_grant`, `revoke_grant`) are short-lived (≤ 300 s), bound to the
  exact tool, agent, tenant, target, parameters and evidence versions, and
  consumed once: an expired, revoked, replayed or changed request is refused.
  Approvals can be bound to the same digest.
- **`influence.py`**: typed edges (`derived_from`, `summarized_from`,
  `copied_from`, `imported_from`, `exposed_to`, `relied_on`, `authorized`,
  `invalidated_by`), and `impact()`, which keeps potentially contaminated,
  actually retrieved and confirmed use apart.

### Changed: two poisoning defences on by default (owner's decision, 2026-10-19)

- **The directive screen runs at ingest and at share time**
  (`governance/directive.py`). It flags paraphrased injection by what the
  text does: addressing the answerer, or voiding other records. On a held-out
  set it caught 10/12 paraphrased injections and flagged 0/16 benign hard
  negatives; the pattern screen caught 0/12. A flagged memory is quarantined
  for review (`review <id> --approve --override-screen` releases a false
  alarm). Turn it off with `Firewall(directive_screen=False)`.
- **Contradictions are shown, not ranked away.** Memories that give different
  values for one claim, by different authors, are marked as contradicting
  each other in the agent context (`build_context`) and carry a `disputed`
  warning through the SDK, MCP and LangChain recall (G4b: acting on an
  undetected poison 63% → 55%).
- **Cross-store hostile-source notice** (`SourceNotice`, `/federation/notice`,
  the manager's `sources` task): a source caught by an ingest screen is
  withheld at the stores holding its memories.

### Added: the background memory manager (schema 0.12.0)

- **`memory_fabric/manager.py`: the store maintains itself.**
  - **Tasks:** every interval it delivers owed retractions to peer stores,
    applies the retention policy, scans for the auditor's triggers, finds
    contradicting memories, records an integrity checkpoint (off-host with
    `--checkpoint-dir`) and runs the doctor's checks.
  - **Recovery:** each task is isolated and backs off exponentially when it
    fails.
  - **Coordination:** a lease held in the store means one manager per store,
    across processes, with takeover when the holder stops.
  - **Audit:** every cycle is a `MaintenanceRan` event.
  - **Startup:** it starts automatically with `serve`, `agent-api` and
    `mcp`, and runs alone with `memory-fabric maintain`. `--status` shows
    the last cycle and what needs a person.
  - **No terminal step by default:** retention *deletions* need
    `--retention-delete`, contradictions are queued and never resolved, and
    nothing is validated or released.
- **Retraction delivery now has a configuration path:** `--peers` or
  `MEMORY_FABRIC_PEERS` (a JSON peer list). Before, nothing in the CLI
  delivered retractions to other stores.
- `doctor` reports a manager that has stopped.
- `sweep_retention(actions=)` limits which retention actions are applied.

### Added after the 0.11.0 release candidate (opt-in research modules)

- **Memory objective** (`objective.py`, M1): a session's statement of what is relevant,
  as rules over memory metadata applied by `retrieve(objective=)` at the eligibility
  chokepoint, and as rules for the agent's prompt (`prompt()`). `compile_objective` asks a
  model and validates the result. `sanity()` refuses an objective that admits nothing.
  Measured: helps in the prompt, hurts when the model compiles it
  ([M1](research/results/m1-memory-objective.md)).
- **Reflective rulebook** (`rulebook.py`, M2): an agent's rules as one versioned memory.
  A reflection becomes a candidate, adopted only when held-out accuracy verified by
  someone else beats the incumbent. Rules can only narrow retrieval.
- `derive(auto_activate=)`, as `remember` has.
- **Contradiction surfacing** (`conflicts.py`, G4b, under test): notes that give different values for the same claim, by different authors (imports resolve to the original author), are placed together and flagged, instead of lexical ranking deciding which the agent sees first.
- **In the RC as well:** `trust.py` and `exposure.TransferGatePolicy` (S4),
  `independence.py` (S2), `receipts.py` (S5), `MemoryFabric.supersede_copies` (S1),
  `ActionGate.execute` (S6). See the release note.

### Changed — breaking

- **Scope is enforced on reads.** A `private` memory is visible only to the
  agent that wrote it; `team` and `federated` are visible to every agent in
  the tenant. Until now retrieval checked only lifecycle and tenant, so a
  validated private memory, restricted ones included, was returned to every
  agent in its tenant although the specification defines scope as visibility
  ([security review](docs/SECURITY_REVIEW.md) F10). **Upgrading a store:**
  `memory-fabric --db store.db share --all-private-active --actor <you>`
  restores the previous effective visibility through the firewall, and
  restricted memories are refused and listed.
- **Promotion to `team` no longer needs value evidence.** The value rule now
  guards leaving the store (`federated`) only; with scope enforced on reads, a
  value gate on `team` would keep every new memory from its own teammates.
- `derive(scope=...)`: a conclusion is no wider than its narrowest premise.
- A restricted memory written at a scope wider than `private` is refused.

### Added

- **The action fence (schema 0.11.0, `ActionExecuted`).** `ActionGate.execute`
  verifies and runs a protected tool inside one store write transaction, so a
  retraction can no longer land between "verified" and "done" (threat S14,
  previously accepted as a residual race). It takes a lease (bounded below the
  busy timeout), idempotency keys and explicit, re-verifying retries, and
  `unfenced_changes()` reports what changed under a lease overrun.
- **Exposure-based evidence independence** (`independence.py`, opt-in, S2):
  a report is not a second source when its author had been shown the first.
  Imports carry `root` and `informed_by`, so this holds across stores.

- **Collections** (schema 0.10.0, `CollectionChanged`): named sets of memories in
  a tenant. Attaching an agent (`read`) lets it read the members even when
  private; `write`, `approve` and `retract` let an authenticated agent add to,
  validate and withdraw a collection's members without the operator role. Every
  change is an event naming its actor. `memory-fabric collection ...`.
- A review queue (`review`), safe correction with a preview that is the outcome
  (`correct`), reach on every memory page, and four status labels.
- `share` and `agent-api-revoke` commands; `list --agent`.
- `init`: a production-shaped store in one step, with the MCP configuration printed.
- `lifecycle`: retention rules, stale and sensitive finders, erasure and retraction progress.
- `incident`: guided response -- candidates, assessment, containment, and a record generated from the log.
- `posture` (which controls are on here, and the accepted gaps) and `audit-export`
  (decisions, changes, access, deletion receipts; no content; ends with a chain checkpoint).
- **Integrations**: framework-neutral function tools (`integrations.tools`), a LangChain
  retriever (`integrations.langchain`, extra `langchain`), and `import` from other stores'
  exports as candidates waiting for review.

### Fixed

- **The Claude contract test seeded a private memory for another agent.** Since scope is enforced on reads (F10) that memory is correctly invisible, so `recalled` was empty and CI's `claude-contract` job failed. The test skips without the anthropic SDK, so no local run caught it. The seed is now `team`, and `test_adapters.py` covers the recall-follows-scope path without the SDK. The release workflow now refuses a tag unless CI passed on that exact commit.
- **A Postgres connect is bounded** (10 s unless the URL sets `connect_timeout`). A mistyped URL hung for 131 s on Windows.
- **Acknowledgements no longer describe the recipient to the origin.** `state_revision` counts that origin's retractions instead of exposing the recipient's log head, and `detail` carries no copy or peer counts ([security review](docs/SECURITY_REVIEW.md) F13).
- **Echo imports.** A memory shared around a cycle (A -> B -> A) is no longer imported back into a store that already holds it; imports record their provenance chain (`context.federation.chain`). Before, a correction at A left A serving its own superseded versions ([security review](docs/SECURITY_REVIEW.md) F12).

- Concurrent requests to the agent API and the federation server shared one
  SQLite connection; a revocation read could be corrupted (security review F1).
- Crypto-erasure left earlier versions' plaintext and the copy-index term set
  in a running process (F2, F3).
- Cross-process refresh replayed the whole log on nearly every call: 4.4 ->
  103 ops/s at 100 agents ([P12b](research/results/p12b-catch-up.md)).

### Added (earlier in this cycle)
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
- **Credentials expired 1000x early.** `now` is epoch milliseconds and the lifetime is seconds, but they were added unconverted. The default hour-long credential lasted 3.6 s, and `agent-api-issue --ttl 1800` lasted 1.8 s. Every unit test called back at once, so nothing failed until a live model, a few seconds into its turn, was refused (`experiments/live_claude_http.py`). Credentials issued before the fix simply expire.
- **The action gate verified against a stale view in another process** (found by `experiments/e2e_validation.py`), and two fail-closed leaks: raw exception text over the agent API and MCP, and concealed cross-tenant `derive` confirming an id exists.
- **Re-ingestion through encoding noise.** Zero-width characters, soft hyphens, ligatures and non-ASCII hyphens no longer let a withdrawn document return as active, independent evidence.

### Changed
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
