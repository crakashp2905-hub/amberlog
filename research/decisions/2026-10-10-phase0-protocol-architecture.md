# Decision — Phase 0 architecture: identity, ordering, acknowledgement, failure

- **Date:** 2026-10-10, commit `597bdcb`
- **Status:** accepted as the design for Phase 1. Nothing here is implemented yet.
- **Input:** the [implementation audit](../../docs/AUDIT.md), the [invariant matrix](../../docs/INVARIANTS.md), and the product engineering roadmap §§1–2 and 10.

Four decisions the roadmap requires before any protocol code is written. Each
records what was rejected, because the rejected option is usually the one that
looks cheaper later.

---

## 1. Identity: opaque store ids, assigned once, recoverable by replay

**Decision.** A store mints `store_id = "st_" + ULID` once and records it as a
`StoreIdentified` event in its own log. Cross-store references are always the
pair `(origin_store_id, origin_memory_id)`. Tenants and agents get the same
treatment.

**Rejected: the current behaviour.** `federation.py:134` writes
`"store": source.log.path` — a local filesystem path. It fails in three ordinary
situations: two stores at the same relative path (`./store.db` in two
containers) are indistinguishable; moving or renaming a database breaks every
provenance match silently; and `:memory:` is the identity of *every* in-memory
store, so a test fixture and a production store share one.

**Rejected: hostname, URL, or port.** These describe where a store can be
reached, which changes. Identity must not.

**Rejected: a content hash of the store.** Changes on every write.

**Why recorded as an event.** The identity has to survive a restore from
backup, and the log is the only thing guaranteed to. Deriving it from a config
file means a mis-deployed config silently re-identifies a store, and every
retraction addressed to the old id goes nowhere.

**Consequence.** `descendants_of` already matches on store *and* id, with a test
for an unrelated store minting a colliding memory id
(`test_an_unrelated_store_sharing_an_id_is_not_touched`). This makes the
convention structural. The migration is additive: existing logs have no
`StoreIdentified` event, so a store without one mints one on first open and
records that it did.

## 2. Ordering: per-origin sequences; version is the authority

**Decision.** Each store keeps `origin_sequence`, incremented once per
integrity-affecting event it emits. Recipients keep one cursor per origin.
Precedence between a retraction and a memory version is decided **by version,
never by time**:

> A retraction of `(store, memory, version)` applies to that version only, and
> never to a greater one. A retraction arriving below the recipient's cursor for
> its origin is recorded with state `superseded` and not applied.

**Rejected: a single global sequence.** Not a causal clock across multiple
origins — the roadmap says so and it is right. Two origins incrementing one
counter would require coordination this architecture explicitly avoids.

**Rejected: wall-clock `issued_at` as the decider.** Clocks disagree, and a
sender controls its own. `issued_at` stays in the message as operator-facing
metadata and is barred from precedence logic.

**Rejected: vector clocks.** They would answer a question nobody has asked yet.
Invariant 7 needs only "is this retraction about a version I have superseded?",
which a per-origin cursor plus an exact version answers. Principle 9 applies:
infrastructure follows measured need.

**Consequence, and it is a real cost.** Today's retraction carries no version at
all, so `propagate_retraction` would withdraw an import of v3 on a retraction of
v1. Adding the version is a schema change to the retraction event and a change
to the matching logic in `descendants_of`. The projection must also stop
discarding the parent version at `projections.py:153`, which is the same fix
four partial invariants need.

## 3. Acknowledgement: committed state only, with `unknown` as a first-class answer

**Decision.** Eight states (`received`, `persisted`, `enforced`, `verified`,
`rejected`, `superseded`, `pending_review`, `unknown`), and a recipient may
report:

- `persisted` only after its own transaction commits;
- `enforced` only after its projections and index no longer expose the version;
- `verified` only when the origin has independently confirmed, so a recipient never self-certifies it.

**An unreachable recipient is `unknown`.** Not `verified`, not `failed`, not
absent from the report.

**Rejected: a boolean.** `PropagationResult.acted` is what exists today and it
cannot express the ordinary case the roadmap names — retracted at source, one
recipient enforced, another offline.

**Rejected: collapsing `persisted` and `enforced`.** They are separated by a
projection rebuild, and a crash in between is precisely the window invariant 6
covers. A protocol that cannot distinguish "I have the event" from "I am acting
on it" cannot answer the question the product exists to answer.

**Rejected: acknowledging on receipt.** Returning `enforced` before committing
is the most damaging lie available here: the origin would record the correction
as landed, the operator dashboard would show green, and the recipient would keep
serving withdrawn knowledge.

**Consequence.** Acknowledgements must be persisted at the origin, not held in
memory, or a crash loses the record of what was confirmed.

## 4. Failure handling: transactional outbox, at-least-once, idempotent by event identity

**Decision.** The origin commits the retraction event and the outbox intent in
**one** transaction. A separate dispatcher drains the outbox with bounded
exponential backoff and jitter. The recipient deduplicates on
`(origin_store_id, retraction_id)` and applies the event, inbox record and
lifecycle change in **one** transaction. Permanent failures stay visible.

**Rejected: exactly-once delivery.** Not available over a network. At-least-once
plus idempotent processing is the only honest arrangement, and it is what the
roadmap specifies.

**Rejected: the current synchronous dispatch.** `propagate_retraction` commits
the local quarantine and then loops over live target objects in the same call.
A crash between those loses the dispatch with *no record that it was owed* —
invariant 3, unimplementable without an outbox. This is the single largest gap
in the audit.

**Rejected: relying on state convergence for idempotency.** Re-running
`propagate_retraction` is harmless today because it skips an already-quarantined
import. That is convergence, not deduplication, and it cannot distinguish a
replay from a genuinely new second retraction of the same memory. Event identity
can.

**Rejected: a message broker now.** A broker provides neither idempotency nor
causal ordering nor correctness — the roadmap says this explicitly — and P9
already declined distribution on measurement. SQLite is the transactional
boundary until a measured need appears, then PostgreSQL, then a broker only if
throughput demands it.

**Consequence.** The outbox and inbox must share a transactional boundary with
the event log. In SQLite that is free: same file, same transaction. The moment
they are split across two systems, the dual-write problem appears and must be
solved explicitly rather than hoped past — which is a reason to keep them
together for as long as possible.

---

## What these four decisions cost

They are not free, and the roadmap's framing is the justification: **build one
durable, reliable, end-to-end retraction path before adding anything else.**

| Decision | Change required |
|---|---|
| Opaque store identity | New event type; `federation.py` origin record; `descendants_of` matching; additive migration for existing logs |
| Per-origin ordering + exact versions | Retraction event gains two fields; `projections.py` must stop discarding the parent version; `descendants_of` matches on version |
| Eight acknowledgement states | New propagation state machine, persisted separately from lifecycle; `PropagationResult` replaced |
| Outbox / inbox / at-least-once | Two new tables in the same transactional boundary; a dispatcher; a recipient entry point; the crash matrix from roadmap §1 "Tests" |

None of it requires peer-to-peer networking, a broker, consensus, or a learned
controller, all of which stay deferred. The transport is authenticated HTTP, and
even that is Phase 2 — Phase 1 is durability and idempotency with both sides in
one process, which is a strictly larger set of guarantees than exists today and
is testable without a network.
