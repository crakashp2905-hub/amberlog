# Changelog

Format follows [Keep a Changelog](https://keepachangelog.com/). Versions track the
**memory schema**, not the Python API — see [VERSIONING.md](VERSIONING.md) for why.

## [Unreleased]

### Fixed
- **`min_independent_sources` above one was not enforced** unless `independent_support` was also listed among the required checks. `ToolRule(min_independent_sources=2)` let a single-source certificate through, so the corroboration defence recommended for consequential tools did nothing. Asking for more than one source now implies the check. Found by C2.
- **Agent API `verify` on a withdrawn memory the agent never recalled** answered "recall or fetch first" instead of "not usable", because withdrawn memories no longer come back from recall. It now fetches under the agent's own permission check and answers directly; unknown and other-tenant ids stay opaque. Found by the multi-agent pilot.

### Added: operating modes, guarantees and the Control Center
- **Answerability** (`answerability.py`): a verdict on the evidence (answerable, conflicting, insufficient, undetermined), separate from retrieval scores. `RetrievalResult.answerability()`; the agent API's `recall` returns it. Evaluated with real models (A1, A1-h): an instructed model already abstains perfectly on this world, so the verdict ships as a reported signal and an optional gate.
- **Retrieval profiles** (`retrieve(profile=..., method=...)`): `precise`, `conversational`, `semantic`, `multi_hop` and `audit`, each citing its measurement, plus a per-call ranking method.
- **Strict freshness** (`freshness.py`, `ToolRule(require_fresh=True)`): imported evidence needs a signed, unexpired lease from its origin, so no protected action relies on a withdrawal at an offline peer for more than one lease lifetime.
- **`memory-fabric anchor`**: checkpoint anchoring in one command to `dir:`, `git:` or `https://` targets, with `--verify`.
- **Signed action receipts** (`action_receipt.py`, `mf-action-receipt/1`): Ed25519, verifiable with the public key alone, and carrying hashes, never content. `memory-fabric receipt-verify`.
- **Decision dependence** (`dependence.py`): which recorded decisions depended on a corrected memory, by counterfactual through the product's own verifier.
- **Consensus by independent source** (`consensus.py`): repetition is not corroboration, and artificial consensus is flagged.
- **Memory Control Center** (dashboard): a guided start page, agent actions with their evidence then and now, a "would retrieval show this?" trace, decision dependence and known limitations. `memory-fabric sandbox` seeds a store with deliberately wrong memories and opens it in the dashboard.
- **Tenant isolation patterns** (DEPLOYMENT.md), **PostgreSQL failover runbook** (OPERATIONS §4b), and the team review flow (validate *and* share).

### Fixed: constraints an engineer would hit
- **Claim checks missed every equipment code written with a separator.** `H-14`, `PMP_0012` and `K/31` were split into a word and a number, so the claim had no identifier and the contradiction, re-assertion and corroboration checks never ran on it. A poisoned "update" to such a code went through unflagged (D1, with one attacker account per case: 15 of 15). Codes before a claim's verb now form its subject, and codes after it are values. Held-out: detection 1.000, false alarms 0.000 ([V2](research/results/v2-codes.md)).
- **A compromised account could change a reviewer-validated fact unflagged.** The change is now provisional (`revises_validated`) until someone validates it. `ToolRule(refuse_provisional=True)` lets a protected tool refuse it.
- **"Every assistant should treat X as …" passed both injection screens.** The directive screen now catches it, with 0 of 40,919 benign memories flagged.

### Added
- **`doctor --webhook URL`**: a JSON alert POSTed when the store is not sound (`--webhook-on warn` for warnings too). Before this, `doctor` had no alerting path.
### Added: governed decay view (OptMem-inspired compression)

- `memory_fabric/decay.py` (experimental): a bounded session-start view with
  recent memories whole and older ones in summaries that coarsen with age over
  a binary tree of fixed log positions; `zoom` back down to the records;
  summaries written by the agent on request ("nap"), stored as derived
  candidate memories so lineage, retraction and erasure reach them, refused if
  they state any number, identifier, date or negation their sources do not.
  A summary is served only while every source is current and readable.
  Inspired by OptMem's published design; no OptMem code is used (no licence).
- CLI `context wake|zoom|pending|summarise`; MCP extended tools `wake`,
  `zoom`, `nap`.
- Evaluation (pre-registered, research/results/decay-view.md): bars narrowly
  not met on fresh seeds (0.21 of 0.25; 0.71 of 0.75), but at the same budget
  the view carried 86% of current facts against 50% for the newest records,
  with no stale value on any seed.

### Changed

- Context receipts and branches are **available** (module tier beta): the
  merge result held on ten fresh seeds, with CLI, dashboard, MCP and Postgres
  coverage. The Governed Context Map and the decay view stay experimental.

### Changed: faster retrieval, same results

- Lexical search uses an inverted index and a top-k selection; the fold after
  each write re-indexes only the memories it changed (`ChangeTrackingDict`)
  instead of comparing the whole table. Rankings are unchanged (randomised
  equivalence test against a full scan, `tests/test_lexical_postings.py`).
  Retrieval at 10,000 memories: 19.1 -> 10.2 ms p50, measured back to back.

### Changed: a correction reaches the notes that repeat the old value

- Revising a fact, or withdrawing it with basis `contradicted`, now contests
  other usable notes in the tenant that state the same claim with the old
  value (`validation.restatements`). They are withheld from retrieval and
  stay visible for review; nothing is deleted. `MemoryFabric(...,
  contest_restatements=False)` turns it off.
- GME matrix v2 (pre-registered, fresh seeds): stale leakage halved; the
  remainder is withdrawals recorded without a basis. Compression saves 5-19%
  tokens when the budget does not bind (bar was 20%). The governed merge
  again captured all headroom over a naive merge.

### Added: surfaces and evaluation for receipts, the context map and branches

- CLI `branch`, `merge` and `context`; dashboard tabs Changes, Agent context
  and Capabilities (read-only; badges from the capability registry); MCP
  `--extended-tools` (`build_context`, `explain_context`, `trace_provenance`,
  `preview_correction`, `branch_create`, `branch_propose`, `merge_preview`),
  off by default, none of which applies a merge or a correction.
- `examples/wrong_memory_demo.py`: the blueprint's flagship story.
- GME matrix (`experiments/gme_matrix.py`, pre-registered): the registered
  run supported none of H1-H3 and found four defects in the context map
  (F1-F4 below). A pre-registered replication of the repaired code on fresh
  seeds supported H3 (governed merge over naive, no resurrection, no lost
  update) and failed H1's leak criterion and H2, as predicted.
  `research/results/gme-matrix.md`.

### Fixed (found by the GME matrix)

- F1: compact planning let summaries of other subjects displace the record
  that answered the question. Relevance now comes first.
- F2: summaries listed an old restatement before the correction that replaced
  it. `extractive-v2` lists the most recent first.
- F3: the receipt renderer dropped the `[DISPUTED]` flag.
- F4: the flag, once restored, was not paid for out of the token budget.

### Added (schema 0.13.0): context receipts, the Governed Context Map and memory branches

Blueprint Phases 0, 2 and 3. Additive: six event types (SPEC.md 0.13.0); a
0.12.0 log replays unchanged.

- **Capability registry** (`product/capabilities.json`, generated
  `docs/product/CAPABILITY_REGISTRY.md`): every capability's status, code,
  tests and surfaces, checked against the code. It found session compaction
  listed as available while its module is experimental.
- **Correction previews are revalidated at apply**: `apply(preview_digest=)`
  and `correct --apply --preview DIGEST` refuse with `STALE_PREVIEW` if a
  version, descendant, copy or recipient changed since the preview.
- **Context receipts** (`context_receipt.py`, experimental): every context
  bundle records the exact memory versions and summary nodes delivered and
  each exclusion's reason code, as a `ContextBuilt` event with no content or
  query text. `explain_receipt` reports what is no longer admissible.
- **Governed Context Map** (`context_map.py`, experimental): L1/L2 summary
  nodes keyed by exact source versions, refused if they would drop a number,
  identifier or negation, checked for staleness and admissibility at every
  use, and a token-budgeted planner with four modes.
- **Memory branches** (`branching.py`, experimental): branches, immutable
  content-addressed commits, compare-and-swap heads, deterministic diff, a
  three-way merge that classifies every change and never resurrects a
  withdrawn memory, stale-preview refusal, idempotent apply, compensating
  revert, and snapshots that keep history separate from current permission.
- ADR-001 to ADR-003 in `docs/architecture/`; baseline and gap report in
  `docs/product/BASELINE_AND_GAPS.md`.

### Fixed

- A write rolled back with its transaction stayed in the copy-recognition
  index, so the next similar write failed with `KeyError`. Found by
  concurrent branch commits; `_replay` now unindexes what the log does not
  hold.

### Added (release evidence): product benchmark and a generated release report

- `experiments/product_bench.py`: retrieval quality (recall@1, recall@5,
  MRR on planted facts whose tags other notes also name), `remember` and
  `retrieve` latency percentiles, throughput, disk and heap per memory, and
  false blocks on 200 benign writes built to look suspicious, at 1k, 5k and
  20k memories. Results: `research/results/product-bench.md`.
- `tools/release_report.py`: renders a release evidence bundle as one page,
  `RELEASE_REPORT.md`, from the bundle's own files. `release_bundle.py
  --bench quick|full` adds the benchmark; CI's `release-evidence` job runs it
  in full on every commit, so the numbers for a commit come from that commit.

### Added (testing): property-based authorisation walks and mutation testing

- `tests/test_properties_authz.py`: 30 seeded walks of 60 steps over writes,
  validation, quarantine, revision, collections and grants; after every step
  `use()` and every held token are checked against an oracle written from the
  specification. Reverting the F15 fix fails it (seed 18, step 25).
- `tools/mutation_check.py`: 20 curated mutants of security guards, each of
  which must be killed by its named tests; run in CI (`mutation` job). The
  first run found two untested guards, now covered: a summariser dropping an
  undisputed value, and an ungranted agent holding its own valid certificate.

### Changed (internal): MemoryFabric split into a core and seven services

- `fabric.py` was one 3,722-line module with a 3,400-line class. It is now a
  182-line facade composing `memory_fabric/_fabric/`: `FabricCore` (identity,
  log, refresh, transactions, replay) and services for writes, retrieval,
  lifecycle, federation, sharing, sealing and access. Methods moved
  verbatim; no behaviour changed.
- **No public API changed**: `tests/test_fabric_structure.py` checks all 74
  public members against signatures recorded from the original class, and
  the full suite passed unchanged.
- Fully type-checked as before: the cross-service calls are declared on
  `FabricCore` for mypy, and the declarations are tested against the
  implementations. No checking was switched off.

### Fixed and verified: authorization, crashes, tamper detection, cryptography

- **F15 (high): a token stayed usable after its memory stopped being
  visible.** The action-time re-check ignored scope, so a private memory an
  agent read through a collection still verified after the grant was revoked.
  Fixed; `tests/test_visibility_at_action.py`.
- **Every access path tested against every authorisation change**
  (`tests/test_access_matrix.py`): SDK, service session, tenant view, HTTP
  agent API, MCP and function-calling tools, against another tenant's
  memory, a revoked grant, a revoked credential, a revision and a
  withdrawal. It catches F15 when the fix is reverted.
- **A crash mid-action is uncertain, never absent.** `ActionAttempted` is
  committed before the fence; a process that dies mid-tool leaves the key
  `uncertain`, and the next call is refused until `retry=True`. Before, the
  tool ran again as if nothing had happened (`tests/test_action_crash.py`,
  a real process killed mid-action).
- **Log-and-chain rewriting detected end to end**: the manager's
  checkpoints, kept off the store's disk, catch an edited event with a
  recomputed chain; `checkpoint --verify` reads the manager's JSONL file
  (`tests/test_checkpoint_rewrite.py`).
- **Production cryptography profile**: `MEMORY_FABRIC_CRYPTO_PROFILE=production`
  writes only AES-256-GCM from the maintained `cryptography` library and
  refuses to open without it; the Docker image installs it and defaults to
  it; extra `memory-fabric[crypto]`; `doctor` reports the profile.
  `docs/CRYPTOGRAPHY.md` sets out every decision for independent review.
- `docs/SECURITY_REVIEW.md`: F15–F17 recorded; every open item now carries
  current status and a review-by date.

### Fixed: writes slowed as a store filled with near-identical notes

- Copy recognition re-tokenised the incoming text once per candidate, and
  every memory's third index anchor tied on a common word, so one bucket
  held the whole store. On 5,000 near-identical notes a write took ~29 ms
  and seeding them took 144 s. Now the text is tokenised once and each
  memory is anchored under its single rarest term, which is still exact:
  0.9 ms a write at 5,000, 0.5 ms at 500, seeding in 4 s.
- New tests: a randomised comparison of the index with the exhaustive scan
  in both directions, a bound on the candidate set, and writes at 5,000
  near-duplicates at most 3x writes at 500.

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
