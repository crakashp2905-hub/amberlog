# Memory Fabric federation protocol — v1 (specification)

**Status: specification only. No implementation exists as of commit `597bdcb`.**
Everything the code does today is the in-process behaviour described in
[AUDIT.md](AUDIT.md) §3. This document defines what Phase 1 and Phase 2 must
build, so that the gap is written down rather than inferred.

`protocol_version` is `1`. The wire format is JSON. Transport is authenticated
HTTP; peer-to-peer and brokers are deferred (roadmap §9).

---

## 1. Identities

Every identity is a stable opaque string, assigned once and never reused. The
current code uses a **local filesystem path** as the store identity
(`federation.py:134`), which this specification replaces: two stores at the same
relative path are indistinguishable, and moving a database silently breaks every
provenance match.

| Identity | Form | Assigned by | Notes |
|---|---|---|---|
| `store_id` | `st_` + 26-char ULID | the store, once, at creation | Written into the event log as a `StoreIdentified` event so it is recoverable by replay. Never derived from a path, hostname or port. |
| `tenant_id` | `tn_` + 26-char ULID | the operator | Absent today. Every memory, event and acknowledgement carries one. |
| `agent_id` | `ag_` + 26-char ULID | the operator | Today a free-form string. Must be bound to a credential to be authorisable. |
| `memory_id` | 26-char ULID | the store | **Local to a store.** Never globally unique. A cross-store reference is always the pair `(origin_store_id, origin_memory_id)`. |
| `memory_version` | monotonically increasing `int` from 1 | the store | Already exists on `Memory`. |
| `retraction_id` | `rt_` + 26-char ULID | the origin store | Stable across retries. The deduplication key, with `origin_store_id`. |
| `event_id` | 26-char ULID | the emitter | Already exists. |

**Why `memory_id` alone is not an identity.** `descendants_of` already matches
on store *and* id for this reason, and a test pins it
(`test_an_unrelated_store_sharing_an_id_is_not_touched`). The protocol makes it
structural rather than a convention.

## 2. Ordering: per-origin sequences, not a global clock

Each store maintains `origin_sequence`, a monotonically increasing integer
incremented once per integrity-affecting event it emits. It is carried on every
message and is **meaningful only relative to its own origin**. A recipient keeps
a cursor per origin store.

There is deliberately no global sequence and no wall-clock ordering:

- A single scalar across origins is not a causal clock (roadmap §2).
- `issued_at` is advisory metadata for operators. It never decides precedence, because clocks disagree and an attacker can set one.

Precedence rule, from invariant 7:

> A retraction of `(store, memory, version)` applies only to that version. It
> **never** invalidates a version greater than its target. An arriving retraction
> whose `origin_sequence` is below the recipient's cursor for that origin is
> **recorded and not applied**, with state `superseded`.

That is what "delayed older corrections cannot blindly invalidate newer
independently validated versions" requires, and it is why the retraction event
must name a version at all — which today it does not.

## 3. The retraction event

```json
{
  "protocol_version": 1,
  "event_id": "01M4...",
  "retraction_id": "rt_01M4...",
  "origin_store_id": "st_01M4...",
  "tenant_id": "tn_01M4...",
  "origin_memory_id": "01M4...",
  "origin_memory_version": 3,
  "origin_sequence": 4821,
  "reason_code": "contradicted",
  "evidence_digest": "sha256:9f2b...",
  "evidence_reference": "audit://st_01M4.../event/01M4...",
  "requested_by": "ag_01M4...",
  "issued_at": "2026-10-10T12:00:00Z",
  "signature": { "alg": "hmac-sha256", "key_id": "k1", "value": "base64..." }
}
```

- `reason_code` is drawn from `WithdrawalBasis`, which already exists and already
  distinguishes a sensitive-data finding from co-occurrence with a failure. The
  recipient may weigh a weak basis differently; it is not required to.
- **`evidence_digest`, not evidence.** The content is not shipped. A memory's
  text can contain exactly what the governance layer exists to keep out of
  secondary surfaces, so the message carries a hash plus a dereferenceable
  reference the recipient may or may not be authorised to follow.
- `signature` proves origin and integrity. It does **not** prove the claim is
  true (roadmap §6.3), and nothing in the recipient's logic may treat it as
  evidence about the memory's correctness.

## 4. Two state machines, deliberately separate

A memory may be retracted at its origin while one recipient has enforced it and
another is offline. One boolean cannot express that, which is invariant 5.

**Lifecycle** — a property of a memory in one store. Exists today:
`candidate → active → contested → quarantined → deprecated → deleted`,
with `release` returning a quarantined memory to `candidate` rather than to
`active`, so trust is re-earned deliberately.

**Propagation** — a property of one `(retraction, recipient)` pair. Does not
exist today:

```
requested ─> queued ─> delivered ─> persisted ─> enforced ─> verified
                │           │           │
                ├─> retrying ┘           └─> rejected
                ├─> superseded
                └─> failed        (and unknown, for "we have not heard")
```

| State | Means |
|---|---|
| `requested` | committed in the origin's log, atomically with the outbox intent |
| `queued` | in the outbox, not yet attempted |
| `delivered` | the recipient returned a response to the transport |
| `persisted` | the recipient committed the event to its own log |
| `enforced` | the recipient's projections and index no longer expose the version |
| `verified` | the origin has independently confirmed enforcement |
| `rejected` | the recipient refused: bad schema, unauthorised sender, unknown memory |
| `superseded` | a newer correction for the same memory already applies |
| `retrying` | a transient failure, awaiting backoff |
| `failed` | permanently failed, visible to an operator, never silently dropped |
| `unknown` | no information. **An offline recipient is `unknown`, never `verified`.** |

`persisted` and `enforced` are separate because committing an event and
rebuilding the projections that enforce it are separate acts, and a crash
between them is exactly the case invariant 6 is about.

## 5. Delivery: at-least-once plus idempotent processing

Exactly-once network delivery is not available and is not assumed.

**Origin, in one transaction:** append the retraction event and insert the
outbox row. A separate dispatcher reads the outbox, so a crash after commit
leaves the intent recorded and owed — which is invariant 3, and the reason the
current synchronous loop cannot satisfy it.

**Recipient, in this order:**

1. Authenticate the sender.
2. Validate schema and `protocol_version`.
3. Authorise sender-for-destination-and-operation.
4. Deduplicate on `(origin_store_id, retraction_id)`. A second copy returns the **first** outcome; it does not re-apply.
5. Check version and cursor rules (§2).
6. **In one transaction:** persist the event, update the inbox, and apply the lifecycle change.
7. Rebuild affected projections and index entries.
8. Acknowledge with committed state only.

Step 8 is the rule that keeps acknowledgements honest: a recipient may return
`persisted` only after its own commit, and `enforced` only after its projections
no longer expose the version. Returning `enforced` on receipt would be the
single most damaging lie the protocol could tell.

## 6. Acknowledgement

```json
{
  "protocol_version": 1,
  "retraction_id": "rt_01M4...",
  "recipient_store_id": "st_01M4...",
  "state": "enforced",
  "state_revision": 918,
  "origin_sequence_seen": 4821,
  "at": "2026-10-10T12:00:03Z",
  "detail": "3 descendants contested",
  "signature": { "alg": "hmac-sha256", "key_id": "k7", "value": "base64..." }
}
```

A lost acknowledgement is safe: the origin retries, the recipient deduplicates
and returns the same state. `state_revision` lets the origin detect a recipient
that has been restored from a backup and regressed.

## 7. Reconciliation after an outage

On reconnect the recipient sends its cursor per origin; the origin replays every
integrity event above it. Reconciliation is idempotent by §5.4, so replaying too
much is safe and replaying too little is the only failure — which is why the
cursor is the recipient's, not the origin's guess about it.

**Snapshots must carry integrity state.** A snapshot includes `schema_version`,
`protocol_version`, per-origin cursors, a checksum, and the set of unresolved
retractions. A restore that silently drops pending retractions would reintroduce
withdrawn knowledge, and nothing downstream could detect it.

## 8. What this specification does not cover

- **Transitive re-sharing.** v1 assumes an importer does not re-share onward. Lifting that assumption means the origin no longer knows its recipients, and retraction must flood the provenance graph hop by hop. That is the measured trigger for peer-to-peer work and is deliberately out of scope until the single-hop case is durable.
- **Content distribution.** Only integrity events cross. `offer` remains in-process until Phase 2.
- **Consensus.** There is no agreement protocol. Each recipient decides independently and records its own state, which is the existing "the recipient decides" guarantee.
- **Trust in the claim.** Authentication establishes who sent a retraction, never whether the retracted memory was actually false.
