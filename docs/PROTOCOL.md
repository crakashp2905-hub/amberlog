# Memory Fabric federation protocol — v1 (specification)

**Status: implemented as of Phase 2 (2026-10-10).** §§1–7 are built and tested:
`protocol.py` (identities, events, acknowledgements, the state machine),
`outbox.py` (transactional outbox and recipient inbox), `transport.py`
(authenticated HTTP on its own endpoint), `dispatcher.py` (delivery and
reconciliation). The crash matrix is `tests/test_retraction_protocol.py`; the
fault scenarios are `tests/test_federation_transport.py`.

§8 ("what this specification does not cover") still holds in full — transitive
re-sharing, content distribution, consensus and multi-tenancy are all out of
scope, and a signature still proves origin rather than truth.

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
| `tenant_id` | `tn_` + 26-char ULID | the operator | Every memory carries one (0.5.0), defaulting to `tn_default`. **Local to a store**: nothing here makes `tn_acme` at two stores the same customer, so `offer` takes the recipient's tenant explicitly rather than copying the sender's. |
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
  "state_revision": 12,
  "origin_sequence_seen": 4821,
  "at": "2026-10-10T12:00:03Z",
  "detail": "withdrawn",
  "signature": { "alg": "hmac-sha256", "key_id": "k7", "value": "base64..." }
}
```

A lost acknowledgement is safe: the origin retries, the recipient deduplicates
and returns the same state. `state_revision` lets the origin detect a recipient
that has been restored from a backup and regressed.

**`state_revision` counts this origin's retractions only, and `detail` carries
no counts.** Until 2026-10-18 the field was the recipient's log head, and
`detail` said how many copies were withdrawn and how many peers it forwarded
to. So every origin learned the recipient's activity between two retractions
and part of its sharing graph (security review F13, measured in
[S5](../research/results/s5-correction-receipts.md)). A per-origin count still
falls when the recipient regresses, which is the field's job. Both counts stay
in the recipient's own log. The wire format is unchanged. For a receipt that
proves enforcement to an auditor without revealing anything, see
`memory-fabric/receipts.py`.

## 7. Reconciliation after an outage

On reconnect the recipient sends its cursor per origin; the origin replays every
integrity event above it. Reconciliation is idempotent by §5.4, so replaying too
much is safe and replaying too little is the only failure — which is why the
cursor is the recipient's, not the origin's guess about it.

**Snapshots must carry integrity state.** A snapshot includes `schema_version`,
`protocol_version`, per-origin cursors, a checksum, and the set of unresolved
retractions. A restore that silently drops pending retractions would reintroduce
withdrawn knowledge, and nothing downstream could detect it.

## 7a. Forwarding past the first hop

A recipient may re-share what it imported. When it does, the origin cannot
address the stores two hops out — it has never heard of them — so each hop
forwards on its own behalf.

**The campaign and the target are different things.** `retraction_id` together
with `origin_store_id` identifies the *campaign* and never changes along a
chain. The *target* — `target_store_id`, `target_memory_id`,
`target_memory_version` — says which copy this hop is about, and is rewritten
at every hop, because a store two hops out imported from the store one hop out
and holds no record of the origin at all. All three fields are optional and
default to the origin fields, so a hop-0 retraction is byte-identical to
version 0.3.0 on the wire.

**What a store must record.** An accepted offer emits `MemoryShared`
(`memory_id`, `version`, `recipient_store_id`, `imported_memory_id`). This is
not derivable after the fact: the recipient's copy is a new memory in the
recipient's log with its own id. Only an *accepted* offer records one; a
refusal that wrote a share record would create a permanent delivery obligation
to a store holding nothing.

**What a store must do on apply.** In the *same transaction* that withdraws its
own copy, a recipient enqueues the retraction onward to every store it
re-shared that copy to, retargeted and with `hop` incremented. Committing the
onward intent separately would leave live copies downstream that nothing in the
federation was tracking — and nothing would notice, because the upstream
acknowledgement already said `enforced`, truthfully, about the one copy it was
asked about.

**Forwarding is asynchronous, and acknowledgements say so.** A recipient
returns `enforced` once *its own* copy is no longer exposed. It does not wait
for the hops beyond it; a synchronous cascade would put an unbounded number of
network calls inside one recipient's transaction. So `enforced` from one hop is
not a statement about the whole subtree, and an operator asking "has this
converged?" is asking about the system at rest, which is what
`OperatorClient.propagation()` and `/api/propagation` report.

**Termination.** Three mechanisms, in order of which one actually does the work:

1. **Deduplication over concrete targets.** A target is a `(store, memory, version)` triple and a federation holds finitely many, so a cycle re-arrives with a triple already recorded and stops.
2. **Not forwarding back to the sender.** A pure optimisation — deduplication would absorb it — worth one saved round trip per hop.
3. **`MAX_HOPS` (16).** A backstop, not the defence. Reaching it means something is wrong with the topology or the dedup key, so a store at the limit withdraws its own copy, refuses to forward, and records `RetractionRejected` with `hop_limit` rather than dropping the retraction quietly.

## 7b. On "one transaction"

Where this document says a retraction's local effect and its delivery intent
commit together, that is now true and was not always. `sqlite3`'s connection
context manager commits unconditionally and does not nest, so an inner
`with conn:` inside an outer one ended the outer transaction — and every append
had one. The claim was in this document, in INVARIANTS.md and in the Phase 1
commit message before it was in the code.

`txn.transaction` provides the nesting: `BEGIN IMMEDIATE` at the outermost
level, named savepoints below it, with the depth keyed per **connection**
because the log, the outbox and the content vault share one in order to share
one boundary. Schema setup stays outside it, because `executescript` issues its
own COMMIT.

An implementation of this protocol in another language should check the same
thing about its own database driver before believing its own documentation.

## 8. What this specification does not cover

- **Transitive re-sharing.** v1 assumes an importer does not re-share onward. Lifting that assumption means the origin no longer knows its recipients, and retraction must flood the provenance graph hop by hop. That is the measured trigger for peer-to-peer work and is deliberately out of scope until the single-hop case is durable.
- **Content distribution.** Only integrity events cross. `offer` remains in-process until Phase 2.
- **Consensus.** There is no agreement protocol. Each recipient decides independently and records its own state, which is the existing "the recipient decides" guarantee.
- **Trust in the claim.** Authentication establishes who sent a retraction, never whether the retracted memory was actually false.
