# Safety and security model

This document has two jobs. It states the threats the
[AI-safety and cybersecurity plan](AI_SAFETY_CYBER_RESEARCH_IMPLEMENTATION_PLAN.md)
names, and for each one it gives the control, the test that exercises the
control, and what is still not covered. The detailed per-surface controls live in
[SECURITY.md](../SECURITY.md) and are linked rather than copied here, so that
the two documents cannot drift apart.

**Rule for this file:** a guarantee is listed only if a test in this repository
exercises it. Anything else is listed as a limitation or an accepted gap. Nothing
here is a formal security proof, and nothing here has been externally audited.

---

## 1. What is protected

| Asset | Why it matters |
|---|---|
| Memory content | It may be confidential, and it becomes an input to future decisions |
| Lifecycle and retraction state | If an attacker can flip it, withdrawn knowledge can be acted on again |
| Provenance, lineage and justification edges | They decide what a retraction reaches and what counts as independent support |
| The event log and its hash chain | Every other structure is rebuilt from the log |
| Content keys | Whoever holds a key can read that memory's content; destroying a key erases the content |
| Credentials and peer keys | They decide who can act, and on whose behalf |
| Access decisions, exposure tokens and evidence certificates | They decide whether an action may go ahead |
| Audit records | They are how an operator reconstructs what happened |

## 2. Who might attack, and what they can already do

| Actor | Assumed capability | Out of scope |
|---|---|---|
| **Honest-but-mistaken agent** | Writes false or stale claims through the normal API | — |
| **Compromised agent** | Holds one valid credential; writes poisoned or injected content; retries, replays and floods | Holding another agent's key |
| **Other tenant** | Holds a valid credential for its own tenant | Reaching the host process |
| **Network attacker** | Can read, replay, drop and reorder federation traffic | Breaking HMAC-SHA256 or AES-GCM |
| **Compromised peer store** | Holds its own peer key and sends signed but false retractions | Holding another peer's key |
| **Database writer** | Can write the SQLite file or the Postgres tables directly | — (see the limit in §5) |
| **Host code** | Holds `MemoryFabric` itself and is trusted by design | — |

## 3. Trust boundaries

1. **Agent → service.** Crossed through the MCP server (`adapters/mcp.py`), the
   agent HTTP API (`agent_api.py`) or a `MemoryService` session (`service.py`).
   Each one verifies identity and tenant on the server side.
2. **Retrieved content → model.** Memory text is delimited and labelled as
   evidence. Retrieved text is treated as data, not as instruction.
3. **Store → store.** Federation messages are signed per peer. The recipient's
   firewall decides what is accepted, and imports arrive as `candidate`.
4. **Memory evidence → action.** A memory that passes the check does not
   authorize a tool. The action gate (`certificates.py`, Task 4) requires a
   separate tool grant.
5. **Process → storage.** On Postgres, triggers make the log append-only. On
   SQLite, file permissions and the hash chain are the controls.
6. **Store → external checkpoint.** This is the only defence against a writer
   who rewrites the whole history.

## 4. Threat register

Status values:
- **controlled**: there is a control and a test for it.
- **partial**: there is a control, with a named gap.
- **accepted gap**: there is no control. This is stated, not hidden.

| # | Threat (plan §4) | Control | Evidence (tests) | Status |
|---|---|---|---|---|
| S1 | **Memory poisoning** | New writes start as `candidate`. Provenance is required. The sensitive and injection screens run at ingest. A quarantine propagates through lineage. Action-time re-check. | `test_enforcement.py::test_a_candidate_is_never_usable…`, `test_transitive_retraction.py`, `test_security_regression.py::TestPoisoning` | **partial**: screening is pattern-based, and a well-formed false claim from an authorised writer is caught only by review or retraction |
| S2 | **Prompt injection in retrieved text** | A write-time pattern screen. Retrieved memories are delimited and labelled as data. A memory never grants a tool. | `test_injection_patterns.py`, `test_adapters.py`, `test_security_regression.py::TestInjection`, `test_certificates.py::TestToolPermission` | **partial**: a pattern screen can be bypassed by construction, and whether the model complies is not under this system's control |
| S3 | **Cross-tenant leakage** | The tenant filter runs on every read path. The enforcer refuses a cross-tenant read before it reveals lifecycle or version. The refusal does not name the owning tenant. | `test_service.py::test_an_agent_cannot_reach_another_tenant`, `test_agent_api.py::test_another_tenant_cannot_see_it`, `test_data_access_paths.py`, `test_security_regression.py::TestTenantIsolation` | **partial**: tenancy is logical, all tenants share one physical store, and host code can bypass the filter |
| S4 | **Unauthorized write** | HMAC credentials are verified on every call. Roles are signed into the credential. `remember` takes no scope or agent argument. | `test_service.py::test_an_agent_cannot_forge_a_role…`, `test_auth.py`, `test_agent_api.py::test_every_auth_failure_looks_the_same`, `test_security_regression.py::TestUnauthorizedWrite` | **controlled** at the service, API and MCP boundaries |
| S5 | **Replay or duplicate events** | Dedupe keys. A cursor owned by the recipient. Idempotent apply. A version check on every retraction. | `test_retraction_protocol.py::test_one_event_delivered_a_hundred_times_has_one_effect`, `…below_the_cursor_is_superseded…`, `…for_another_version_is_not_applied`, faultsim | **controlled** for retractions. Credentials are bearer tokens and replay until they expire (see §5). |
| S6 | **Log tampering** | A hash chain. External checkpoints. Append-only triggers on Postgres. | `test_integrity_chain.py` (edit, delete, reorder, truncate, recompute), `test_postgres.py::TestAppendOnly` | **partial**: detecting a full rewrite needs a checkpoint stored somewhere else (§5) |
| S7 | **Retraction failure** | A transactional outbox. Durable retries with backoff. `persisted` and `enforced` acknowledgements kept distinct. A visible `failed` state. | `test_retraction_protocol.py::test_the_intent_survives_a_crash…`, `…transient_failures_back_off_then_fail_visibly`, `test_multiprocess_crash.py`, faultsim | **controlled** in the tested conditions |
| S8 | **Poisoned derived summary** | A derived memory records its parents. Withdrawing a premise contests whatever depended on it. A certificate fails if any premise is no longer usable. | `test_justification.py`, `test_security_regression.py::TestDerivedLeakage`, `test_certificates.py::TestDerivedEvidence` | **partial**: there is no separate summary or mental-model object yet (plan R9) |
| S9 | **Resource exhaustion** | Body limits on the HTTP surfaces. Hop limit on federation. Node and step budgets on chain search. A size limit on certificates. | `test_agent_api.py::test_oversized_bodies_are_refused`, `test_transitive_retraction.py::test_the_hop_limit…`, `test_chains.py`, `test_certificates.py::TestMalformed` | **partial**: no rate limiting and no write-flood quota |
| S10 | **Audit tampering** | Audit events go into the same chained log. The dashboard access log is separate and append-only. | `test_integrity_chain.py`, `test_operator_access.py` | **partial**: same limit as S6. The dashboard access log is a plain file. |
| S11 | **Key compromise** | Per-memory content keys. External key providers. Per-credential revocation. Agent key rotation. Peer keys kept separately. | `test_cipher.py`, `test_key_migration.py`, `test_service.py::test_a_revoked_credential_stops_working_immediately` | **partial**: there is no HSM, peer keys do not rotate automatically, and the default key custody is the weakest option (SECURITY.md) |
| S12 | **Overblocking** | Justification is recomputed rather than blanket-invalidated. Independent support survives a single-source retraction. Benchmarks measure how often valid evidence is withheld. | `test_justification.py::test_losing_one_of_two_independent_premises…`, `test_certificates.py::TestSelectiveReassessment`, `research/results/p3b-agent-teams.md`, Task 5 results | **controlled** in the tested scenarios, and measured (§6) |
| S13 | **Authorization drift** (a permission changes after retrieval) | Credentials are re-verified per call. The certificate verifier re-reads revocation status when the action happens. | `test_service.py::test_a_revoked_credential_stops_working_immediately`, `test_certificates.py::TestRevokedPermission` | **controlled** for revocation and expiry |
| S15 | **Derived-content leakage across classes** | `derive` inherits the strictest security class of its premises, and a caller cannot lower it | `test_privacy_federation.py::TestDerivedContent` | **controlled**. Found by these tests: a summary of `restricted` content was written `internal` |
| S16 | **Existence disclosure** | Cross-tenant refusals name only `wrong_tenant`, never the version or lifecycle. With `conceal_cross_tenant=True` they are identical to a missing id | `test_privacy_federation.py::TestDisclosureOfExistence` | **partial**: by default the refusal confirms the id exists elsewhere (documented policy). Concealment is opt-in |
| S17 | **Concurrent requests on one store connection** (a threaded server serving several agents or peers) | One re-entrant lock owned by the fabric. Its entry points take it; the agent API holds it for revocation and the operation, the dashboard and federation server per store call, the service for credential reads and writes. Signature, expiry and rate limit run outside it, so a forged or over-rate request never queues | `test_concurrent_requests.py::ConcurrentAgentRequests`, `test_rate_limit.py::TestApiLimits` | **controlled**. Found 2026-10-18 by `experiments/p12_http.py`: 39 of 200 requests failed with `InterfaceError`, because authentication read revocations outside the lock; an interfered read can answer "not revoked" |
| S18 | **Erased content surviving in a running process** | Erasure scrubs every version in the projection's history and removes the memory's copy-index entry, in the erasing process and in any that folds the erasure in | `test_erasure_residue.py::ErasureLeavesNoResidue`, `test_catch_up.py::CatchUpEqualsReplay` | **controlled**. Found 2026-10-18: earlier versions' plaintext stayed in `history()` and the dashboard, and the term set in the copy index, until a restart |
| S19 | **Scope not enforced on reads** (another agent in the tenant reading a private or restricted memory) | Private means the writing agent, checked in the one retrieval chokepoint and in the enforcer before any lifecycle fact; restricted memories cannot be written or shared wider than private; `derive` is no wider than its narrowest premise | `test_scope_visibility.py::PrivateMeansTheWriter`, `test_scope_visibility.py::RestrictedStaysPrivate`, `test_scope_visibility.py::DerivedIsNoWiderThanItsPremises` | **controlled**. Found 2026-10-18 (F10): retrieval checked only lifecycle and tenant |
| S14 | **TOCTOU between verification and action** | Verification happens immediately before the action and is pinned to the log head. A certificate records the watermark it was checked against. | `test_enforcement.py::test_a_retraction_after_retrieval_blocks_the_action`, `test_certificates.py` | **accepted residual race**: a retraction committed after `verify` returns and before the tool runs is not seen. This is documented, not solved. |

## 5. Limitations (not guarantees)

- **Hash-chain limit.** Anyone who can write both the log and the chain can
  rewrite both consistently. Only a checkpoint kept outside their reach detects
  that (`test_integrity_chain.py::test_a_recomputed_chain_is_caught_by_a_checkpoint`).
- **Logical tenancy.** The tenant boundary is an authorisation check inside one
  store. It is not physical isolation, and host code holding `MemoryFabric` can
  cross it (`test_service.py::test_the_fabric_is_reachable_by_anyone_who_insists`).
- **Bearer credentials.** A stolen credential works until it expires or is
  revoked. Transport confidentiality is the deployment's responsibility: the
  agent API refuses plain HTTP off loopback unless TLS is declared.
- **Pattern screens** catch known shapes only. A false claim that is otherwise
  ordinary is not detectable by inspecting it.
- **A certificate is not proof that a claim is true.** It records that declared
  checks passed against a specific log state and policy.
- **Rate limiting is per agent and per address on the agent API only** (20 requests a second, burst 40, by default). The MCP server is one agent on stdio and has none; the federation server has none and relies on the peer registry.
- **No formal verification and no third-party audit.**
- **Write contention.** All writes take one lock to keep the log ordered, and a retrieve is a write. About 100–135 operations a second per store on the measured machine, whatever the deployment shape ([P12b](../research/results/p12b-catch-up.md)). A write flood from one credential slows every agent sharing the store, bounded on the agent API by its rate limit (S9).

## 6. Failure behaviour

| Situation | Behaviour | Evidence |
|---|---|---|
| Lifecycle state is not modelled | `UNKNOWN`, which is refused | `test_enforcement.py::test_unknown_integrity_is_not_treated_as_usable` |
| Certificate version is unknown, or required fields are missing or malformed | Refused for protected actions, with a reason code | `test_certificates.py::TestMalformed` |
| Authoritative state cannot be read (the store raises) | Refused with `state_unavailable` | `test_certificates.py::TestFailClosed` |
| A peer is offline | Acknowledgement is `unknown`, not verified. The delivery retries and then shows as `failed`. | `test_retraction_protocol.py::test_an_offline_recipient_is_unknown_not_verified` |
| A credential is revoked or expired | Refused on the next call | `test_service.py` |
| Overblocking | Measured, never assumed to be zero | Task 5 results, `research/results/p3b-agent-teams.md` |

### Fail-closed audit (2026-10-16)

Every `except` on an authorisation, integrity or screening path was read
(`enforcement`, `certificates`, `actions`, `service`, `identity`,
`agent_api`, `adapters/mcp`, `transport`, `governance/*`, `fabric`,
`outbox`, `dispatcher`, the dashboard server). Pinned in
`test_fail_closed.py`.

| Path | Behaviour on an exception | Verdict |
|---|---|---|
| Enforcer check, `use`, `verify_before_action` | propagates, so no decision is returned and nothing is usable | closed |
| Ingest screen | propagates, so the write is refused and nothing is stored | closed |
| Unmodelled lifecycle | `UNKNOWN`, refused | closed |
| Certificate verifier, action gate | `state_unavailable` or `credential_invalid`; a failed audit write refuses | closed |
| Credential parsing, signature | `IdentityError`, the same 401 for every failure kind | closed |
| Federation receive | rejected before parsing when unauthenticated; parse errors are not echoed | closed |
| `fabric` transaction and open | re-raise after rollback or close | closed |
| **Agent API and MCP generic handler** | refused, **but returned the exception's text to the caller** | **fixed**: faults return a fixed sentence and are logged server-side (`sdk.public_error`) |
| **Concealed cross-tenant `derive`** | refused, **but the message confirmed the id exists** | **fixed**: identical to a missing id |
