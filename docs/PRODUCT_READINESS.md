# Product readiness assessment — 30 October 2026

This maps all items in the owner-provided product-readiness checklist. It is an
evidence index, not a blanket release approval. IMPLEMENTED means code/tests or
documentation exist; it does not claim every requested deployment or external
acceptance condition passed. PARTIAL names narrower evidence than requested.
EXTERNAL needs account access, independent people, real participants or hosts.
EXCLUDED is an explicit product choice. Publication remains NO-GO.

The source-layout/official-client/typed-consumer work is being qualified in this
change. Existing historical results remain historical; no new model, customer,
legal, independent-review or physical-network result is invented.

Product hypothesis: platform teams operating multi-agent workflows with
protected external actions and evidence that can be corrected between recall
and execution. This is a proposed buyer/use case, not validated demand.

## 1. Core architecture and correctness (P0)

| ID | Acceptance item | State | Evidence / remaining work |
|---|---|---|---|
| R01.01 | Define stable public SDK contracts and supported behaviors | PARTIAL | `tests/test_data_access_paths.py`, `docs/SDK_CONTRACTS_0.14.md`. Existing signature snapshot and read-surface classification; installed-wheel typing gate added. Wider behavioral versioning remains bounded by alpha/module tiers. |
| R01.02 | Verify event sourcing, replay and hash-chain integrity | PARTIAL | `tests/test_properties.py`, `tests/test_integrity_chain.py`. Replay and chain properties exist; a fixture corpus covering every released schema version is still required. |
| R01.03 | Guarantee atomic memory lifecycle transitions | IMPLEMENTED | `tests/test_transactions.py`, `tests/test_concurrency.py`, `tests/test_multiprocess_crash.py`. Existing focused evidence; run outputs and limits remain separate from a universal correctness guarantee. |
| R01.04 | Validate provenance and derivation graphs | IMPLEMENTED | `tests/test_properties_state_machines.py`. Existing focused evidence; run outputs and limits remain separate from a universal correctness guarantee. |
| R01.05 | Ensure corrections invalidate dependent evidence correctly | IMPLEMENTED | `tests/test_gov_conformance.py`, `tests/test_retraction.py`. Existing focused evidence; run outputs and limits remain separate from a universal correctness guarantee. |
| R01.06 | Prevent re-ingestion of withdrawn facts as fresh independent evidence | PARTIAL | `tests/test_duplicates.py`, `tests/test_transitive_retraction.py`. Copy recognition is tested; arbitrary paraphrase equivalence is not guaranteed. |
| R01.07 | Enforce evidence freshness before protected actions | IMPLEMENTED | `tests/test_certificates.py`, `tests/test_action_fence.py`, `tests/test_visibility_at_action.py`. Existing focused evidence; run outputs and limits remain separate from a universal correctness guarantee. |
| R01.08 | Document external side-effect transaction limitations | IMPLEMENTED | `docs/FAILURE_POLICIES.md`, `tests/test_action_crash.py`. Existing focused evidence; run outputs and limits remain separate from a universal correctness guarantee. |
| R01.09 | Define fail-open versus fail-closed policies by operation | PARTIAL | `docs/FAILURE_POLICIES.md`, `tests/test_access_matrix.py`. Operation matrix added; full cross-interface failure conformance still needs expansion. |
## 2. Security and privacy (P0)

| ID | Acceptance item | State | Evidence / remaining work |
|---|---|---|---|
| R02.01 | Threat-model every entry point: SDK, MCP, HTTP, dashboard and federation | PARTIAL | `SECURITY.md`, `docs/SECURITY_REVIEW.md`. Existing repository evidence is narrower than the full acceptance condition; qualification and remaining scope must stay explicit. |
| R02.02 | Enforce tenant-scoped authorization on every read and write | PARTIAL | `tests/test_properties_authz.py`, `tests/test_access_matrix.py`. Existing repository evidence is narrower than the full acceptance condition; qualification and remaining scope must stay explicit. |
| R02.03 | Implement service identities, least privilege and credential rotation | PARTIAL | `tests/test_identity.py`, `tests/test_key_rotation_drill.py`. Existing repository evidence is narrower than the full acceptance condition; qualification and remaining scope must stay explicit. |
| R02.04 | Harden prompt-injection and memory-poisoning boundaries | PARTIAL | `docs/SECURITY_TEST_PLAN.md`, `tests/test_sensitive_patterns.py`. Existing repository evidence is narrower than the full acceptance condition; qualification and remaining scope must stay explicit. |
| R02.05 | Verify cryptographic sealing, integrity and key management | PARTIAL | `tests/test_cipher.py`, `tests/test_crypto_profile.py`, `tests/test_key_rotation_drill.py`. Existing repository evidence is narrower than the full acceptance condition; qualification and remaining scope must stay explicit. |
| R02.06 | Protect secrets in logs, exports, telemetry and exceptions | PARTIAL | `tests/test_access_log_chain.py`, `tools/scan_secrets.py`. Existing repository evidence is narrower than the full acceptance condition; qualification and remaining scope must stay explicit. |
| R02.07 | Define deletion, retention and backup-erasure guarantees | PARTIAL | `docs/OPERATIONS.md`, `tests/test_backup_custody.py`. Existing repository evidence is narrower than the full acceptance condition; qualification and remaining scope must stay explicit. |
| R02.08 | Protect API endpoints against replay, flooding and resource exhaustion | PARTIAL | `tests/test_rate_limit.py`, `tests/test_federation_transport.py`. Existing repository evidence is narrower than the full acceptance condition; qualification and remaining scope must stay explicit. |
| R02.09 | Run independent security assessment and remediate findings | EXTERNAL | `docs/LOCAL_AGENT_AUDIT.md`. Requires an independent signed assessment; internal tests cannot substitute. |
| R02.10 | Create vulnerability disclosure and incident response procedures | PARTIAL | `SECURITY.md`, `docs/OPERATIONS.md`. Existing repository evidence is narrower than the full acceptance condition; qualification and remaining scope must stay explicit. |
## 3. Federation and distributed reliability (P0)

| ID | Acceptance item | State | Evidence / remaining work |
|---|---|---|---|
| R03.01 | Durable retraction delivery with retries and deduplication | PARTIAL | `tests/test_multiprocess_crash.py`, `tests/test_retraction_protocol.py`. Existing repository evidence is narrower than the full acceptance condition; qualification and remaining scope must stay explicit. |
| R03.02 | Specify behavior during partitions and offline peers | PARTIAL | `docs/PROTOCOL.md`, `tests/test_freshness.py`. Existing repository evidence is narrower than the full acceptance condition; qualification and remaining scope must stay explicit. |
| R03.03 | Verify cyclic and multi-hop federation convergence | PARTIAL | `tests/test_federation_world.py`, `tests/test_properties_state_machines.py`. Existing repository evidence is narrower than the full acceptance condition; qualification and remaining scope must stay explicit. |
| R03.04 | Test protocol version negotiation and mixed-version peers | PARTIAL | `docs/PROTOCOL.md`, `tests/test_protocol_schemas.py`. Rollback qualification is not mixed-version peer negotiation evidence. |
| R03.05 | Prevent unauthorized or cross-tenant federation | PARTIAL | `tests/test_privacy_federation.py`, `tests/test_federation_transport.py`. Existing repository evidence is narrower than the full acceptance condition; qualification and remaining scope must stay explicit. |
| R03.06 | Measure recovery after prolonged outages | PARTIAL | `benchmarks/federation_world.py`. Scheduled in-process reconnect evidence exists; prolonged realistic outage/load qualification remains open. |
| R03.07 | Detect and surface dead-letter or permanently failed deliveries | PARTIAL | `docs/OPERATIONS.md`, `tests/test_retraction_protocol.py`. Existing repository evidence is narrower than the full acceptance condition; qualification and remaining scope must stay explicit. |
| R03.08 | Test independent physical hosts and realistic networks | EXTERNAL | `docs/LOCAL_AGENT_AUDIT.md`. Requires another physical host and recorded real-network conditions. |
## 4. Performance and scalability (P1)

| ID | Acceptance item | State | Evidence / remaining work |
|---|---|---|---|
| R04.01 | Establish reproducible latency and throughput baselines | PARTIAL | `experiments/product_bench.py`. Existing repository evidence is narrower than the full acceptance condition; qualification and remaining scope must stay explicit. |
| R04.02 | Benchmark SQLite and PostgreSQL separately | PARTIAL | `tests/test_concurrency.py`, `.github/workflows/ci.yml`. Existing repository evidence is narrower than the full acceptance condition; qualification and remaining scope must stay explicit. |
| R04.03 | Measure retrieval quality under growing corpus sizes | PARTIAL | `research/results/BENCHMARK_SCOREBOARD.md`. Existing repository evidence is narrower than the full acceptance condition; qualification and remaining scope must stay explicit. |
| R04.04 | Profile memory, CPU, disk and network usage | PARTIAL | `docs/LIMITATIONS.md`. A deployment-specific CPU/RSS/disk/network envelope is not established. |
| R04.05 | Quantify governance overhead versus ordinary memory | PARTIAL | `research/results/local-three-agent.json`. Scripted recheck baseline reaches oracle; no superiority headroom. Content bytes are not total disk storage. |
| R04.06 | Test high-volume correction propagation | PARTIAL | `benchmarks/federation_world.py`. Existing repository evidence is narrower than the full acceptance condition; qualification and remaining scope must stay explicit. |
| R04.07 | Define capacity planning and scaling guidance | PARTIAL | `STABILITY.md`. Existing repository evidence is narrower than the full acceptance condition; qualification and remaining scope must stay explicit. |
| R04.08 | Set SLOs and alert thresholds based on measured performance | PARTIAL | `docs/OPERATIONS.md`. Do not invent production SLOs from small local runs. |
## 5. SDK, integrations and developer experience (P0)

| ID | Acceptance item | State | Evidence / remaining work |
|---|---|---|---|
| R05.01 | Publish installable amberlog wheel and source distribution | PARTIAL | `docs/AMBERLOG_MIGRATION_REPORT.md`, `tools/fresh_machine.py`. Wheel/sdist can be built and installed locally; index publication is not complete. |
| R05.02 | Verify PyPI package name and release ownership | EXTERNAL | `docs/PYPI_PUBLISHING.md`. No visible exact-name index project was found; account-side ownership and name rights are not verified. |
| R05.03 | Implement secure GitHub OIDC Trusted Publishing | PARTIAL | `.github/workflows/publish-pypi.yml`, `docs/PYPI_PUBLISHING.md`. GitHub environments/reviewers/tag policies verified on 30 October; index-side publishers unverified and approval flags false. |
| R05.04 | Provide first-class Python SDK with type hints | IMPLEMENTED | `tools/check_typed_consumer.py`, `docs/SDK_CONTRACTS_0.14.md`. Positive/negative typed consumer and clean import-origin checks added; qualification results recorded separately. |
| R05.05 | Test MCP interoperability using an official client | IMPLEMENTED | `tests/test_mcp_official.py`. Official SDK 1.26.0 negotiates and checks isolation/late withdrawal locally. This is not a model-backed workflow. |
| R05.06 | Validate LangGraph and OpenAI Agents SDK integration | PARTIAL | `docs/LOCAL_AGENT_AUDIT.md`. Existing optional adapters do not establish real LangGraph and OpenAI Agents SDK workflows. |
| R05.07 | Provide consistent CLI, HTTP and SDK semantics | PARTIAL | `tests/test_lifecycle_through_mcp.py`, `tests/test_agent_api.py`. Existing repository evidence is narrower than the full acceptance condition; qualification and remaining scope must stay explicit. |
| R05.08 | Ship an interactive 60-second demonstration | PARTIAL | `src/amberlog/tour.py`, `tests/test_first_run.py`. Interactive demo exists; external new-user onboarding observation is still required. |
| R05.09 | Legacy import aliases during migration | EXCLUDED | `docs/MIGRATING_TO_AMBERLOG.md`. Intentionally excluded: retain the complete rename and data compatibility; avoid shadowing an unrelated distribution. |
| R05.10 | Publish migration, troubleshooting and upgrade guides | IMPLEMENTED | `docs/MIGRATING_TO_AMBERLOG.md`, `docs/TROUBLESHOOTING.md`, `experiments/rollback_drill.py`. Existing focused evidence; run outputs and limits remain separate from a universal correctness guarantee. |
## 6. Control Center and operator experience (P1)

| ID | Acceptance item | State | Evidence / remaining work |
|---|---|---|---|
| R06.01 | Show memory origin, lineage, status and confidence evidence | PARTIAL | `src/amberlog/observability/report.py`. Existing repository evidence is narrower than the full acceptance condition; qualification and remaining scope must stay explicit. |
| R06.02 | Expose correction propagation and pending delivery status | PARTIAL | `src/amberlog/observability/report.py`, `tests/test_observability.py`. Existing repository evidence is narrower than the full acceptance condition; qualification and remaining scope must stay explicit. |
| R06.03 | Implement contested-memory review and approval workflow | PARTIAL | `tests/test_lifecycle_through_mcp.py`. Read-only dashboard is not a full authorized administrative review UI. |
| R06.04 | Provide policy and tenant administration | PARTIAL | `tests/test_identity.py`. Existing repository evidence is narrower than the full acceptance condition; qualification and remaining scope must stay explicit. |
| R06.05 | Support searchable, exportable audit trails | PARTIAL | `tests/test_access_log_chain.py`, `tests/test_observability.py`. Existing repository evidence is narrower than the full acceptance condition; qualification and remaining scope must stay explicit. |
| R06.06 | Expose system health, failures and resource metrics | PARTIAL | `src/amberlog/observability/report.py`. Existing repository evidence is narrower than the full acceptance condition; qualification and remaining scope must stay explicit. |
| R06.07 | Make failures actionable rather than opaque | PARTIAL | `docs/TROUBLESHOOTING.md`, `tests/test_reasons.py`. Existing repository evidence is narrower than the full acceptance condition; qualification and remaining scope must stay explicit. |
| R06.08 | Test dashboard accessibility and browser security | PARTIAL | `tests/test_auth.py`. HTTP/browser-security tests exist; a complete accessibility audit remains open. |
## 7. Packaging, CI/CD and supply chain (P0)

| ID | Acceptance item | State | Evidence / remaining work |
|---|---|---|---|
| R07.01 | Organize canonical code under src/amberlog | IMPLEMENTED | `pyproject.toml`, `MANIFEST.in`. Implementation moved to src/amberlog; import identity and schema remain unchanged. |
| R07.02 | Keep tests, experiments and datasets out of the production wheel | IMPLEMENTED | `tools/fresh_machine.py`, `.github/workflows/ci.yml`. Existing focused evidence; run outputs and limits remain separate from a universal correctness guarantee. |
| R07.03 | Run unit, integration, security and contract tests in CI | PARTIAL | `.github/workflows/ci.yml`. Main protection verified: 32 required CI contexts including the passing official MCP check, strict updates, administrators included, no force pushes/deletion; independent review remains separate. |
| R07.04 | Test supported Python and operating-system matrix | IMPLEMENTED | `.github/workflows/ci.yml`. Existing focused evidence; run outputs and limits remain separate from a universal correctness guarantee. |
| R07.05 | Run static analysis, type checks and dependency scanning | PARTIAL | `tools/check.py`, `pyproject.toml`. Existing repository evidence is narrower than the full acceptance condition; qualification and remaining scope must stay explicit. |
| R07.06 | Generate SBOM and artifact provenance attestations | PARTIAL | `tools/release_bundle.py`, `.github/workflows/release.yml`. SBOM generation exists; release attestations need an actual approved release. |
| R07.07 | Use reproducible builds and immutable versioned artifacts | PARTIAL | `.github/workflows/publish-pypi.yml`. No bit-identical build reproducibility claim yet; preserve artifact hashes and qualified source. |
| R07.08 | Protect tags, releases and publishing credentials | PARTIAL | `.github/workflows/publish-pypi.yml`. Existing repository evidence is narrower than the full acceptance condition; qualification and remaining scope must stay explicit. |
| R07.09 | Document semantic versioning and compatibility policy | PARTIAL | `VERSIONING.md`, `STABILITY.md`. Existing repository evidence is narrower than the full acceptance condition; qualification and remaining scope must stay explicit. |
| R07.10 | Exercise release rollback and incident response | IMPLEMENTED | `experiments/rollback_drill.py`, `tests/test_checkout_namespace.py`. Existing focused evidence; run outputs and limits remain separate from a universal correctness guarantee. |
## 8. Evaluation and research validation (P0)

| ID | Acceptance item | State | Evidence / remaining work |
|---|---|---|---|
| R08.01 | Compare against ordinary shared memory and vector retrieval | PARTIAL | `research/results/local-three-agent.json`. Strong shared metadata recheck matches oracle in the scripted study; external vector/model comparisons remain separate. |
| R08.02 | Run real multi-agent workflows with changing evidence | EXTERNAL | `docs/LOCAL_AGENT_AUDIT.md`. Needs a real held-out workflow and changing evidence, not scripted-role substitution. |
| R08.03 | Measure unsafe actions and false blocking together | IMPLEMENTED | `research/results/local-three-agent.json`. Existing focused evidence; run outputs and limits remain separate from a universal correctness guarantee. |
| R08.04 | Evaluate abstention and incomplete evidence chains | PARTIAL | `src/amberlog/chains.py`, `tests/test_abstention_premise.py`. Existing repository evidence is narrower than the full acceptance condition; qualification and remaining scope must stay explicit. |
| R08.05 | Benchmark LongMemEval and external retrieval datasets | PARTIAL | `benchmarks/registry.json`, `research/results/BENCHMARK_SCOREBOARD.md`. Existing repository evidence is narrower than the full acceptance condition; qualification and remaining scope must stay explicit. |
| R08.06 | Measure prompt-injection and poisoning resistance | PARTIAL | `docs/SECURITY_REVIEW.md`. Existing repository evidence is narrower than the full acceptance condition; qualification and remaining scope must stay explicit. |
| R08.07 | Test adversarial retractions, copies and contradictory sources | IMPLEMENTED | `tests/test_properties.py`, `tests/test_properties_state_machines.py`. Existing focused evidence; run outputs and limits remain separate from a universal correctness guarantee. |
| R08.08 | Repeat experiments across models, seeds and configurations | PARTIAL | `research/SCORECARD.md`. Prior seeded results exist; new hosted-model studies remain on hold with no budget. |
| R08.09 | Publish negative results and limitations | IMPLEMENTED | `research/SCORECARD.md`, `docs/LIMITATIONS.md`. Existing focused evidence; run outputs and limits remain separate from a universal correctness guarantee. |
| R08.10 | Obtain at least one independent reproduction | EXTERNAL | `docs/LOCAL_AGENT_AUDIT.md`. Requires a genuinely independent reproducing party. |
## 9. Enterprise deployment and operations (P1)

| ID | Acceptance item | State | Evidence / remaining work |
|---|---|---|---|
| R09.01 | Publish reference Docker and PostgreSQL deployment | PARTIAL | `Dockerfile`, `deploy/helm/amberlog/Chart.yaml`. Existing repository evidence is narrower than the full acceptance condition; qualification and remaining scope must stay explicit. |
| R09.02 | Provide backup, restore and disaster-recovery procedures | PARTIAL | `docs/OPERATIONS.md`, `tests/test_backup.py`. Existing repository evidence is narrower than the full acceptance condition; qualification and remaining scope must stay explicit. |
| R09.03 | Support secure TLS, reverse proxy and secrets management | PARTIAL | `DEPLOYMENT.md`, `tests/test_auth.py`. Existing repository evidence is narrower than the full acceptance condition; qualification and remaining scope must stay explicit. |
| R09.04 | Add SSO/OIDC and enterprise authorization where required | PARTIAL | `docs/KNOWN_GAPS.md`. Enterprise SSO/OIDC is demand-gated; source-level credentials do not establish it. |
| R09.05 | Provide OpenTelemetry-compatible observability | PARTIAL | `src/amberlog/adapters/tracing.py`. Existing repository evidence is narrower than the full acceptance condition; qualification and remaining scope must stay explicit. |
| R09.06 | Test upgrades and rollback with persistent customer data | EXTERNAL | `experiments/rollback_drill.py`. Synthetic real-version rollback passes; no customer-data staged qualification is claimed. |
| R09.07 | Document data residency and data-flow boundaries | PARTIAL | `docs/product/LEGAL_PRIVACY_REVIEW_BRIEF.md`. Existing repository evidence is narrower than the full acceptance condition; qualification and remaining scope must stay explicit. |
| R09.08 | Define support, escalation and incident ownership | PARTIAL | `docs/OPERATIONS.md`. Existing repository evidence is narrower than the full acceptance condition; qualification and remaining scope must stay explicit. |
| R09.09 | Create customer-facing security documentation | PARTIAL | `docs/SAFETY_AND_SECURITY.md`. Existing repository evidence is narrower than the full acceptance condition; qualification and remaining scope must stay explicit. |
## 10. Product, documentation and commercial readiness (P0)

| ID | Acceptance item | State | Evidence / remaining work |
|---|---|---|---|
| R10.01 | Finalize Amberlog name, domain and trademark screening | EXTERNAL | `docs/PYPI_PUBLISHING.md`. Candidate retained by owner; existing brand usage remains documented without trademark clearance. |
| R10.02 | Define ideal customer profile and primary use case | PARTIAL | `docs/product/decisions/2026-10-28-packaging-options.md`. Packaging/buyer options are hypotheses; customer discovery and owner selection remain needed. |
| R10.03 | Rewrite README around a demonstrated failure and solution | PARTIAL | `README.md`, `examples/wrong_memory_demo.py`. Existing repository evidence is narrower than the full acceptance condition; qualification and remaining scope must stay explicit. |
| R10.04 | Publish architecture, quickstart, API and integration docs | PARTIAL | `docs/README.md`, `docs/API.md`. Existing repository evidence is narrower than the full acceptance condition; qualification and remaining scope must stay explicit. |
| R10.05 | Produce a comparison against relevant alternatives | PARTIAL | `research/SCORECARD.md`. Existing repository evidence is narrower than the full acceptance condition; qualification and remaining scope must stay explicit. |
| R10.06 | Create three reference workflows with measurable value | PARTIAL | `examples/reference_agent.py`, `examples/action_gate.py`, `examples/poisoning_and_rollback.py`. Reference demonstrations exist; they are not customer value measurements. |
| R10.07 | Define licensing and commercial usage rights | EXTERNAL | `LICENSE`, `docs/product/LEGAL_PRIVACY_REVIEW_BRIEF.md`. Existing proprietary rights are documented, not independently legally reviewed. |
| R10.08 | Create design-partner pilot agreement and success metrics | PARTIAL | `docs/product/decisions/2026-10-28-packaging-options.md`. Draft planning exists; no signed partner agreement or participant consent is invented. |
| R10.09 | Complete at least two external pilots | EXTERNAL | `docs/LOCAL_AGENT_AUDIT.md`. Two external pilots require real partners and documented outcomes. |
| R10.10 | Define pricing hypotheses and support model | PARTIAL | `docs/product/decisions/2026-10-28-packaging-options.md`. Hypotheses exist, but pricing/support conclusions require customer evidence. |

## Current external setup

GitHub `testpypi`/`pypi` environments require owner review and only allow `v*`
tags. Both approval flags are false. No approved SHA, release tag or package
upload has been created. The browser integration failed before account access;
PyPI/TestPyPI publisher ownership remains unverified. Independent security
assessment, reproduction, physical hosts and real pilots still require outside
evidence. No budget has been authorized for hosted model evaluations.

## Local qualification of this change

On 30 October 2026: `tools/check.py` passed regeneration, lint, mypy over
152 source files, the secret allowlist check, 25 document tests and the
adversarial gate. The official MCP client and namespace/migration group passed
10 tests; focused SDK/state-machine/authorization/transaction checks passed
50 tests; documentation/link/read-surface checks passed 21 tests.

Both wheel and source archive passed `twine check --strict`. The wheel passed
`tools/fresh_machine.py` outside the checkout with source-path overrides cleared,
including installation, CLI/doctor and uninstall isolation. Its PEP 561
consumer accepted declared public return types and rejected an incompatible
assignment. `experiments.rollback_drill --old-ref v0.11.0` passed every step.
The pre-rename encrypted synthetic store retained its identity, plaintext,
exact event bytes and valid hash chain in `tools/verify_prior_store.py`.

The first full local run executed 2,236 tests (46 skipped) and failed two
dashboard tests using the old source path. All nine dashboard tests passed
after correcting that path. Candidate CI also exposed a missing child-process
source path in the federation launcher; after correction its local delayed
retraction/reconnect drill passed. A fresh candidate CI run is required. The
first candidate already passed package, official MCP, Docker, adapter-contract,
rollback, mutation and isolated-install checks. These focused results do not
approve a release or complete every PARTIAL row.
