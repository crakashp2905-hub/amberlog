# ADR 0002: historical belief reads retain current authorization

Status: accepted design (N14). Initial explicit-ID implementation and seeded
qualification exist; checkpoint acceleration and expanded security qualification
remain pending. See `docs/HISTORICAL_READS.md` for implemented limits.

Use a separate experimental `history.query` surface rather than change stable
`retrieve(as_of=...)`. `valid_at` asks when a fact applies; `known_at` is an
inclusive event-log sequence and asks what had been recorded. `until` includes
claims beginning before an event time, including subsequently superseded ones.
Question event time is supplied evidence context, not an authorization clock.
Current authorization always uses the current store and wall clock.

A historical read must intersect historical tenant/scope eligibility with
current tenant, scope, lifecycle, erasure and hostile-source eligibility before
returning any content or aggregate count. Current withdrawal or erasure wins
over historical readability. Missing current keys cannot be recovered from an
older backup, replay, cache or checkpoint. Replayed encrypted payloads remain
sealed until the existing enforced read boundary authorizes access.

Historical content is labelled archival and must not be accepted as current
action evidence. Protected effects still require `ActionGate.execute` against
current policy, source versions, leases and grants. Query receipts carry source
versions, validity window, transaction sequence, current log head, permitted
lineage pointers, redaction counts scoped to authorized records, replay work,
read counts and elapsed time. Do not reveal counts of formerly private records.

Bound replay by an explicit maximum event count and deadline. A request beyond
the bound is incomplete/refused, never silently answered from a truncated
snapshot. Checkpoints must be verified, versioned, rebuildable projections of
the event log, contain no independent source of truth, and respect current
erasure at every read. A first implementation may refuse checkpoint acceleration
rather than retain erased plaintext.

Acceptance: independent sequence/valid-time oracle, late corrections, same-value
independent sources, imported updates, concurrency, scope revocation, erased
keys, stale checkpoints and adversarial action-certificate reuse. Measure replay
scaling before setting a supported workload envelope. Rollback disables the
experimental surface without rewriting events or affecting stable `as_of`.
