# Phase 0 - Implementation-vs-spec audit

> **Superseded in part by Phase 1 (2026-10-10).**
> The durable retraction protocol now exists: opaque store identity recorded in
> the log, exact-version targeting, a transactional outbox, a recipient inbox
> deduplicating on event identity, per-origin cursors, and eight propagation
> states. Invariants 3, 5 and 7 moved from **missing** to **implemented**, and
> 2 and 4 from partial to implemented. See [INVARIANTS.md](INVARIANTS.md) for
> the current matrix and `tests/test_retraction_protocol.py` for the crash
> matrix.
>
> **Phase 2 (2026-10-10) added the transport.** Authenticated HTTP on its own
> endpoint — deliberately *not* on the observability server, which stays
> read-only by test — plus an outbox dispatcher, reconciliation from the
> recipient's own cursor, and integrity snapshots that name unresolved
> retractions. Invariant 11 moved to implemented for the federation path.
> A retraction now crosses a real socket between two stores, is refused when
> unsigned or signed with the wrong key, and converges after an outage.
>
> **Phase D (2026-10-11) lifted the one-hop restriction.** An accepted offer
> records the recipient *store* (`MemoryShared`), a retraction carries a
> per-hop target alongside an unchanging campaign identity, and a recipient
> commits what it owes downstream inside the transaction that withdraws its own
> copy. Five fault scenarios cover chain, outage, crash-before-forwarding,
> diamond and cycle. "Federation where an importer re-shares onward" moved from
> **unsupported** to supported.
>
> **Tenant and agent identity (2026-10-11).** Memories carry a `tenant_id`;
> `_eligible_ids` and `Enforcer.check` refuse to cross it, so no ranking
> policy, index query or federation import can surface one tenant's knowledge
> to another. `PrincipalRegistry` issues signed, expiring credentials and
> `fabric.as_principal` returns a handle that cannot be asked to read outside
> its tenant. Two rows below move: **tenant identity** from missing to
> implemented-as-authorisation, **agent identity** from partial to implemented
> at the handle. What has *not* changed: a caller holding the `Memory Fabric`
> can still act as anyone, because the check and the bypass would be on the
> same side of that boundary. See `identity.py`.
>
> **Phase 3 (2026-10-10) added one enforcement layer.** Every agent-facing read
> goes through `Enforcer.check`, and an `ExposureToken` binds the decision to
> the memory version and the log's integrity revision, so
> `verify_before_action` re-checks at action time. "Action-time re-check" and
> "one enforcement layer" below moved from missing/partial to **implemented**;
> denials are audited as `AccessDenied` events.
>
> **Phase 4 (2026-10-10) added support recomputation.** Invalidating a premise
> recomputes each descendant's justification rather than contesting all of
> them, with typed edges (required, alternative, copied, contradicts). The two
> truth-maintenance rows below marked partial are **implemented**; copies of a
> withdrawn document are covered since 0.8.0.
>
> **Phase 6 (2026-10-10) added crypto-erasure**, with per-memory content keys
> and an erasure that keeps the audit trail; **authenticated encryption followed
> on 2026-10-11** — AEAD envelopes bound to store, memory and version, and
> external key custody. The retention row
> below is **implemented**; see SECURITY.md for what erasure does not reach.
>
> **Cross-process freshness (2026-10-16).** A running fabric now catches up on
> other processes' writes before serving, enforcing or writing. Before this, a
> retraction issued from another process did not reach a running server until
> restart, which this audit did not check.
>
> **This file is a dated snapshot.** For the current state of every guarantee,
> use [INVARIANTS.md](INVARIANTS.md), which maps each to its test.
>
> **Still true:** peer-to-peer discovery, brokers and consensus remain
> deferred. Multi-tenancy is now an *authorisation* boundary and not a physical
> one — one SQLite file holding several tenants is one blast radius whatever
> the labels say, and `doctor` reports a multi-tenant store as a warning for
> that reason.

- **Audited:** 2026-10-10, commit `597bdcb`, 483 tests passing, secret scan clean.
- **Method:** read the path from local quarantine through `propagate_retraction()` to recipient lifecycle and retrieval enforcement, then checked each advertised guarantee against the code that would have to implement it.
- **Scope:** `federation.py`, `lineage.py`, `events.py`, `eventlog.py`, `projections.py`, `fabric.py`, `exposure.py`, `model.py`, `observability/`, `tests/test_federation.py`.

Labels: **implemented** (code + test), **partial** (works under stated conditions, gap named), **specified only** (documented, no code), **missing**.

---

## 0. The headline correction

> **`propagate_retraction` is an in-process function call, not a protocol.**

It takes a list of live `Memory Fabric` *objects* as its targets:

```python
propagate_retraction(source, memory_id, [store_b, store_c])
```

Both stores must exist in the same Python process, and the caller must already
know every store that holds a copy. There is no transport, no serialisation, no
durability across a crash, no acknowledgement, no retry, and no authentication.

**This changes how [Phase B's PB2 result](../research/results/phase-b-federated-agents.md) must be described.** PB2
measured that acting on origin-retracted memory fell from 17% to 0% under both
sharing policies, and that measurement stands — but it is a result about
**lifecycle and enforcement semantics**, not about distributed delivery. The
separate stores were separate event logs in one process. Nothing in that run
crossed a network, survived a restart, or was acknowledged.

Phase 0's exit gate requires this sentence, so it is written here and propagated
to the claim surfaces: *in-process behaviour is not durable distributed
propagation.*

---

## 1. Guarantee-by-guarantee

### Provenance and versioning

| Guarantee | State | Evidence and gap |
|---|---|---|
| Every persistent memory retains origin provenance | **implemented** | `Provenance(created_by, source_episodes, parents, method)` on every memory; `tests/test_federation.py` asserts it crosses an import. |
| Dependency edges identify the exact parent **version** | **partial** | `Provenance.parents` is `tuple[tuple[str, int], ...]` — id *and* version, so the data is recorded. But `projections.py:153` discards it: `for parent_id, _version in memory.provenance.parents`. The lineage graph is version-blind, so §4.1 of the roadmap is half-done: recorded, not used. |
| Stable store identity | **missing** | `federation.py:134` writes `"store": source.log.path` — a **local filesystem path**. Two stores at the same relative path are indistinguishable; moving a database file silently breaks every provenance match. The roadmap names this explicitly ("stable ID, not a local file path"). |
| Stable agent identity | **implemented at the handle** | `identity.PrincipalRegistry` registers an agent against a tenant, roles and a key; `issue`/`verify` mint and check HMAC-signed credentials with an expiry, signature before expiry, and roles that may only narrow a registration. `fabric.as_principal(credential)` returns a bound handle. The raw fabric remains unauthenticated by construction and `test_identity.py::test_the_raw_fabric_is_still_unauthenticated` pins that rather than implying a perimeter. |
| Tenant identity | **implemented as authorisation** | `Memory.tenant_id`, filtered in `_eligible_ids` *before* the index is queried and refused in `Enforcer.check` *before* the lifecycle is resolved, so a cross-tenant refusal leaks nothing about the memory. `ExposureToken` carries the tenant so the time-of-use check is not weaker than the time-of-check. `derive` refuses a premise from another tenant and inherits its parents' tenant. Not physical isolation: see the header. |
| Immutable versions | **implemented** | `revise()` creates a new version; history retained; `tests/test_fabric.py`. |
| Versioned event schema | **partial** | Every event carries `schema_version`; additive changes replay (test in `test_withdrawal_basis.py`); `overview` reports installed-vs-log versions. But there is **no machine-readable schema registry** and no compatibility policy per event type. |

### Retraction

| Guarantee | State | Evidence and gap |
|---|---|---|
| Local retraction quarantines and contests descendants | **implemented** | `fabric.quarantine(propagate=True)`; descendants become `contested`, not quarantined. Tested. |
| Retraction records why | **implemented** | `WithdrawalBasis` + `withdrawal_basis` projection; surfaced in `attention`, `explain`, `MemoryRow`. |
| Retraction targets an exact **version** | **missing** | `propagate_retraction` matches on `origin.memory_id` and `origin.store` only. A retraction of v1 would withdraw an import of v3. |
| A committed retraction survives a crash before dispatch | **missing** | No outbox. The retraction event is committed to the source log; the dispatch is a synchronous loop in the same call. A crash between them loses the dispatch with no record that it was owed. |
| Duplicate delivery is idempotent | **partial, by accident** | Re-running `propagate_retraction` is harmless because it skips an already-quarantined import. That is state convergence, not deduplication: there is no event identity on the recipient side, so a *different* retraction of the same memory cannot be distinguished from a replay. |
| Acknowledgements distinguish received / persisted / enforced / verified | **missing** | `PropagationResult(store, memory_id, acted, state, reason)` is a synchronous return value describing what the function just did in-process. None of the four states exists. |
| Propagation state is separate from lifecycle state | **missing** | There is no propagation state at all. §1.2's distinction — a memory retracted at source while one recipient is enforced and another offline — is unrepresentable. |
| Old retraction arriving after a newer correction | **missing** | No ordering model. No `origin_sequence`, no causal version. |
| Transitive re-sharing | **not supported, deliberately** | Only native memories are offered; imports are never re-shared (`phase_b.py`). So the origin always knows its recipients. This is the design limit that makes the current model work and the thing that breaks it when lifted. |

### Enforcement

| Guarantee | State | Evidence and gap |
|---|---|---|
| A known-invalid version is never returned through supported paths | **implemented for lifecycle state** | `retrieve()` computes `_eligible_ids()` = `EXPOSABLE_STATES` (`ACTIVE` only) and passes it as `restrict_to` to the index, so a quarantined, deprecated or deleted memory cannot be returned. Verified live (validation §5: "retracted memory no longer retrievable anywhere"). |
| Vector index cannot bypass validity checks | **implemented** | The index is only ever searched with `restrict_to=eligible`. `observability/report.preview_search` reaches the index directly but is read-only and does not return memories to an agent. |
| Enforcement is version-aware | **missing** | Eligibility is per memory id, not per version. |
| One enforcement layer for all supported paths | **partial** | `retrieve()` is the only agent-facing path, and `AgentSession.recall` delegates to it. But `fabric.get()` returns any memory regardless of state, and adapters could call it. No enforcement boundary is declared. |
| Action-time re-check for consequential actions | **missing** | Exposure is logged at retrieval. Nothing re-checks at action time, so a time-of-check/time-of-use gap exists by construction. |
| Exposure records bound to version, policy decision, integrity revision | **partial** | `ExposureRecord` carries memory id, episode, step, propensity, policy id. No version, no integrity revision, no expiry. |
| Denials are audited without leaking content | **partial** | Withheld exposures are logged. Firewall rulings are logged with reasons. Secret *values* are scrubbed from display surfaces (`governance/sensitive.scrub`), but there is no explicit audit record for "retrieval denied because retracted". |

### Truth maintenance

| Guarantee | State | Evidence and gap |
|---|---|---|
| Contradictions stay representable | **implemented** | `HypothesisSet`, `challenge()`, `resolve()`; contested memories retrievable only with `include_contested=True`. H4b and the live multi-agent run measured the effect. |
| Multiple independent justifications | **partial** | `LineageGraph.evidence_is_independent()` exists and correctly refuses to count copies as corroboration. But nothing *recomputes* support when a premise is invalidated: `quarantine` marks every descendant contested unconditionally, with no check for a surviving justification. §4.2's central requirement is unimplemented. |
| Invalidating one premise does not destroy independently justified knowledge | **partial** | Descendants are *contested*, not deleted, which is the right weaker action. But a conclusion with two independent parents, one invalidated, is treated identically to one with a single invalidated parent. |
| Edge types beyond parent/child | **missing** | One relation (`parents`/`children`). The roadmap lists eight (`copied_from`, `derived_from`, `generalized_from`, `specialized_from`, `corroborates`, `contradicts`, `supersedes`, `validated_by`). `ProvenanceMethod` carries some of this intent on the *memory* but not on the *edge*. |
| Safe recovery from a false retraction | **partial** | `release()` returns a quarantined memory to `candidate`, requiring deliberate re-validation, and the audit trail is preserved. Not implemented: replacement with a corrected version, context specialisation, rebuilding dependent conclusions, or recording that a retraction was itself wrong. |

### Durability and operations

| Guarantee | State | Evidence and gap |
|---|---|---|
| History is never silently rewritten | **implemented** | `events_no_update` / `events_no_delete` SQLite triggers; test asserts `IntegrityError`; survives backup (`test_backup.py`). |
| Projections rebuildable from authoritative events | **implemented** | `rebuild()`; tested; backup verification replays the copy. |
| Consequential operations fail closed on unknown identity | **partial** | The HTTP surface fails closed (non-loopback bind requires a token; `Host` validated; cross-origin refused; `hmac.compare_digest`). But it is **read-only** — there is no authenticated write path, so federation has no authentication at all because it has no transport at all. |
| Offline / pending / unknown / contested / failed states explicit | **partial** | `contested` and `quarantined` are explicit lifecycle states. `offline`, `pending`, `unknown` and `failed` do not exist, because propagation does not exist. |
| Append-only audit does not justify indefinite sensitive retention | **partial** | `RetentionPolicy` with rare-event protection exists, and content is separable in principle. No crypto-erasure, no content/audit split, and no documented interaction between deletion and replay. |
| Research claims reproducible with baselines, seeds, uncertainty, negatives | **implemented** | Four pre-registrations with dated amendments, bootstrap intervals, ≥5 seeds for A/A′/B, raw runs committed, killed hypotheses reported as killed, three mis-specified ceilings documented. Principle 8b now enforces the ceiling check mechanically. |

---

## 2. Unsupported deployment modes

Stated so they can be refused rather than discovered.

| Mode | Status | Why |
|---|---|---|
| Multiple concurrent writers to one store | **unsupported** | SQLite single-writer; untested under concurrent writes. |
| Federation between stores in different processes or hosts | **unsupported** | `propagate_retraction` requires live objects in one process. |
| Federation where an importer re-shares onward | **supported** | Phase D. `MemoryShared` records each accepted offer's recipient store; a retraction is retargeted per hop under one campaign identity and forwarded inside the transaction that applies it. Terminates by deduplication over concrete targets, with `MAX_HOPS` as an auditable backstop. Five fault scenarios; disabling forwarding fails all five. |
| Multi-tenant deployment | **supported as authorisation, not as isolation** | Per-tenant authorisation on every read path, tested one test per path. One file is still one blast radius against a caller holding it; prefer one store per tenant where isolation must survive a compromised process. |
| Untrusted recipients or senders | **unsupported** | No authentication on the federation path. |
| Storing data requiring encryption at rest | **unsupported** | Plain SQLite file; quarantined memories still contain their content on disk. |
| Application code holding the raw fabric | **not recommended** | `MemoryService` is the supported surface: it owns the fabric and hands out only credential-derived sessions that re-verify per call. The fabric itself trusts its caller completely and always will. |
| Serving agents over a network | **unsupported for writes** | The HTTP surface is read-only by design and has one shared bearer token with no identity, roles, expiry, or revocation. |
| Relying on value-ranked exposure | **not recommended** | Three live attempts lost to cheap baselines ([Phase A](../research/results/phase-a-real-agent-benchmark.md), [PA′](../research/results/phase-a-prime-attribution.md)), and the ranking has a [known defect](../research/decisions/2026-10-10-value-ranking-ignores-uncertainty.md). |

**Supported today:** one process, one writer, loopback or trusted-network read-only observability, authenticated agents at a handle, per-tenant authorisation within one store, and transitive federation over authenticated HTTP.

---

## 3. Synchronous versus durable

Every federation operation is **synchronous and in-process**. The table records
what each return value actually guarantees, because the roadmap requires that
distinction and the current names overstate it.

| Operation | Returns | Actually guarantees |
|---|---|---|
| `offer(source, mid, target, ...)` | `OfferResult(accepted, decision, reasons, imported_memory_id)` | The recipient's firewall ran **in this process** and, if accepted, the import was written to the recipient's log as a `candidate`. Nothing about delivery, durability of intent, or the recipient's agreement. |
| `propagate_retraction(source, mid, targets)` | `list[PropagationResult]` | Each named target's import was quarantined **in this process**, or was already withdrawn. Says nothing about targets not passed in, nothing about crash survival, and nothing about enforcement at any other time. |
| `fabric.quarantine(...)` | `list[str]` of contested descendants | Local only. Durable, because the event log commits. |
| `retrieve(...)` | `RetrievalResult` | Blocked lifecycle states were excluded at *this moment*. No version binding, no expiry, no action-time guarantee. |

---

## 4. What Phase 0 concludes

Three of the roadmap's fourteen invariants are **fully implemented** (1, 10, 13),
eight are **partial**, and three are **missing entirely** (3, 5, 9 — crash-safe
retraction intent, acknowledgement states, explicit propagation states). The
invariant-to-test matrix in [INVARIANTS.md](INVARIANTS.md) carries the detail.

The honest summary of the gap:

> The project has a well-tested **local** integrity model — provenance, immutable
> versions, append-only history, lifecycle enforcement on the retrieval path,
> contradiction preservation, rebuildable projections — and it has **no
> distributed protocol at all**. What has been called cross-store retraction is
> a correct in-process lifecycle operation that two logs in one program can
> perform on each other.
>
> That makes Phase 1 the right next step and makes its framing non-negotiable:
> retraction has to become a durable protocol with identity, versions, an
> outbox, an inbox, and acknowledgements, before anything about distribution can
> be claimed.
