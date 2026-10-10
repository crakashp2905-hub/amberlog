# Invariant-to-test matrix

The fourteen invariants from the product engineering roadmap §3, each mapped to
the code that would have to hold it and the test that proves it does.

- **Audited:** 2026-10-10, commit `597bdcb`, 483 tests. **Updated after Phase 1** (532) and **Phase 2** (559) and **Phase 3** (584) and **Phase 4** (605) and **Phase 6** (633 tests).
- An invariant with no test is **not** an invariant. Rows marked ✗ are
  liabilities, not features, and each names what would have to exist.

| | Invariant | State | Implementation | Test |
|---|---|---|---|---|
| **1** | History is never silently rewritten; corrections are attributable events | ✅ | `eventlog.py` `events_no_update` / `events_no_delete` triggers; every change is an appended event | `test_eventlog.py` (update and delete both raise `IntegrityError`); `test_backup.py::test_the_copy_is_append_only_too` (survives a backup) |
| **2** | Every persistent memory retains origin and version provenance | ✅ | `Provenance.parents` carries `(id, version)` and `projections.parent_versions` now keeps it; `offer` records the imported `version` and the origin's opaque `store_id` | `TestStoreIdentity::test_an_import_records_the_origin_identity_and_version` |
| **3** | A committed retraction cannot disappear because a process crashes before dispatch | ✅ | `outbox.py` shares the event log's SQLite connection, so `request_retraction` commits the `RetractionRequested` event and the outbox rows in one transaction | `test_retraction_protocol.py::TestDurability` - stop before any dispatch, reopen the file, the intent is still `queued` |
| **4** | Duplicate delivery is idempotent | ✅ | Inbox keyed on `(origin_store_id, retraction_id)`; a replay returns the *first* outcome and does not re-apply | `TestIdempotency` - one event delivered 100 times yields one `RetractionApplied`; a replay after a local release does not re-quarantine; a genuinely distinct second retraction *is* applied |
| **5** | `received`, `persisted`, `enforced`, `verified` are distinct acknowledgement states | ✅ | `protocol.PropagationState` (8 states), `ALLOWED_TRANSITIONS` as data, `Acknowledgement.overstates_persistence` | `TestAcknowledgements`, `TestStateMachine` - `enforced` cannot regress, nothing leaves `rejected`, an offline recipient is `unknown` not `verified` |
| **6** | A known-invalid version is never returned as usable memory through supported paths | ✅ | **One enforcement layer**: `enforcement.Enforcer.check` resolves lifecycle then decides by `RiskLevel`. `fabric.use()` is the enforced read and returns no memory when the decision refuses; `fabric.get()` is documented and tested as inspection-only. `ExposureToken` binds memory id, version, agent, store and the log's integrity revision, so `verify_before_action` closes the time-of-check/time-of-use gap. Denials are audited via `AccessDenied` **without the content**. | `test_enforcement.py` (25 tests) — a retraction after retrieval blocks the action; a revision invalidates the token; a token is not a bearer credential; a vector hit still matches but cannot be exposed; the audit record excludes the content; `Verdict.UNKNOWN` never reads as permission |
| **7** | Delayed older corrections cannot blindly invalidate newer independently validated versions | ✅ | Per-origin `origin_sequence` plus a recipient cursor that advances with `MAX` so it never rewinds; a retraction below the cursor is recorded `superseded` and not applied | `TestOrdering` - a stale retraction leaves a revalidated version `ACTIVE`, and the refusal is logged as `RetractionRejected` |
| **8** | Invalidating one premise does not automatically destroy independently justified knowledge | ✅ | `justification.JustificationGraph.recompute` replaces the unconditional contest loop. `JustificationKind` distinguishes a conjunction (`REQUIRED`, the safe default) from genuine alternatives (`ALTERNATIVE`) from a copy (`COPIED`, never corroboration). `independent_support` thins survivors against each other **and against the lost premises**. Verdicts cascade nearest-first, each applied before the next is computed, and every recomputation is logged as `SupportRecomputed` even when the conclusion survived. | `test_justification.py` (21 tests) — losing one of two independent premises leaves the conclusion `ACTIVE`; losing both contests it; a copy of a retracted premise does not keep it alive; an unsupported conclusion is contested, never deleted; a revised premise asks for revalidation rather than declaring support absent |
| **9** | Offline, pending, unknown, contested and failed states are explicit | ⚠️ | `LifecycleState.CONTESTED` and `QUARANTINED` are explicit and enforced | `test_retraction.py`, `test_withdrawal_basis.py`. **Gap:** `offline`, `pending`, `unknown`, `failed` do not exist, because propagation does not exist |
| **10** | Projections and indexes can be rebuilt from authoritative events | ✅ | `Projection.apply` fold; `fabric.rebuild()`; index rebuilt on replay | `test_fabric.py`, `test_withdrawal_basis.py::test_it_survives_a_rebuild`, `test_backup.py::test_the_copy_replays_to_the_same_state` |
| **11** | Consequential operations fail closed when identity or authorization is unknown | ✅ | `transport.PeerRegistry` is the authorisation boundary: an unknown peer is neither reachable nor authorised. The federation server authenticates by per-peer HMAC *before* parsing, and refuses with 401; `receive_retraction(sender_authorised=False)` records a `RetractionRejected` event and applies nothing. The observability surface stays read-only. | `test_federation_transport.py::TestHttpTransport` — unsigned and wrong-key retractions are both refused and leave the import `ACTIVE`; reconciliation from an unknown peer is 401; `TestObservabilityStaysReadOnly` asserts the write path was not bolted onto the dashboard |
| **12** | Append-only audit history does not justify retaining sensitive content indefinitely | ✅ | `governance/erasure.py`: content sealed per memory, keys in their own table outside the log, `fabric.erase_content` destroys one key. Unsealing happens at the projection — the single place a `Memory` is built from an event — so all thirty `.content` readers are unchanged. `RetentionPolicy` with rare-event protection still governs lifecycle. | `test_erasure.py` (27 tests) — the log never holds plaintext; erasure survives replay, restart and backup; the memory stops being searchable; provenance, lineage, the retraction basis and the audit trail all survive; the erasure event carries no content; an older backup still holds it, pinned deliberately |
| **13** | Research claims are reproducible and include baselines, seeds, uncertainty, and negative results | ✅ | Four pre-registrations with dated amendments; bootstrap CIs; ≥5 seeds for A/A′/B; raw runs committed; `stats.check_ceiling` enforces principle 8b | `test_experiment_harnesses.py` (36 tests incl. `test_every_phase_runs_the_check`), `test_depotworld.py`, `test_banditworld.py`, `test_h3_harness.py`, `test_retention_arms.py` |
| **14** | Infrastructure follows measured need | ✅ | P9 declined distribution on measurement (4.39 ms at 2,000 memories); P8 declined on a zero denominator; Phase C gated on PB1 and run as exploratory when the gate failed | [P9 decision](../research/decisions/2026-10-07-p9-declined.md), [H5 decision](../research/decisions/2026-10-07-h5-premise-false.md), `research/prereg/phase-c-memory-ecology.md` |

## Tally

| | count | invariants | was at Phase 0 |
|---|---|---|---|
| ✅ implemented and tested | **13** | 1, 2, 3, 4, 5, 6, 7, 8, 10, 11, 12, 13, 14 | 4 |
| ⚠️ partial, gap named | **1** | 9 | 7 |
| ✗ missing, no test possible yet | **0** | — | 3 |

Phase 1 closed all three missing invariants and both root causes the Phase 0
audit identified.

**Version blindness is fixed.** `projections.parent_versions` keeps the version
Provenance always recorded, `offer` records the imported version, and
`_imports_of` matches on origin store *and* exact version — so a retraction of
v1 can no longer withdraw an import of v3.

**Store identity is fixed.** An opaque `st_`-prefixed id, minted once and
recorded as a `StoreIdentified` event so it survives a restore from backup. The
protocol parser rejects path-like strings as identities, with a test enumerating
`/data/store.db`, a Windows path, `:memory:` and a bare filename.

**What the five remaining partials need:**

- **9** — `offline`, `pending`, `failed` and `unknown` now exist as propagation states and are visible through `outbox.pending()` and `DispatchReport`; what remains is surfacing them in the operator tools. Phase 7.

## Rules for this file

1. A new guarantee in a doc, README or changelog requires a row here and a named test, in the same commit.
2. A row may not be marked ✅ without a test that fails when the invariant is broken — not merely one that exercises the happy path.
3. ⚠️ must name the gap in the same cell. "Partial" without a gap is an unaudited claim.
4. ✗ must name what would have to exist. An invariant with no route to a test is a specification, and the audit says so.
