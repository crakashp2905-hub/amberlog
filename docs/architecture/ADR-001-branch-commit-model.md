# ADR-001: Memory branches and commits as an overlay on the event log

**Status:** accepted, implemented in `amberlog/branching.py`.

## Context

Agents and people want to try memory changes — a new interpretation, a batch
of imports, a re-measurement campaign — without changing what every other
agent retrieves, then merge what holds up. The store already has one
authority, the append-only event log, and every guarantee (screens,
sealing, erasure, retraction, tenant isolation, the action fence) is
enforced on the ordinary write and read paths. A second storage engine for
branches would need every one of those re-implemented, and would be the
second database the blueprint's risk table warns about.

## Options considered

1. **Copy the corpus per branch.** Simple reads; storage grows with branches,
   and an erasure must find every copy. Rejected.
2. **A separate graph/version store** (a Git-like object store beside the
   log). Content-addressed and familiar, but every write bypasses the
   screens and sealing unless they are duplicated. Rejected.
3. **An overlay on the log (chosen).** A branch is a named pointer to a
   commit. A branch's changes are ordinary memories written through the
   ordinary write path as **candidates** tagged with the branch, which no
   other branch or main retrieval ever serves (candidates are not
   exposable). Commits and head moves are events in the same log.

## Decision

- `BranchCreated`, `BranchCommitted`, `BranchHeadMoved`, `MergeApplied`,
  `BranchClosed` events (schema 0.13.0, additive).
- **Commit** = content-addressed id: SHA-256 of the canonical JSON of
  `{branch, tenant, parents, base_seq, changes}`. A change is
  `{op: add|revise|withdraw, memory_id, base_version?, candidate_id?, digest}`
  — ids and digests only, never content. Commits are immutable; a parent
  must be the branch's current head.
- **Head update** is compare-and-swap inside the fabric's write transaction
  (`_transaction`, which holds the store's write lock and catches up with
  other processes first): the move is refused unless the head is still the
  one the caller read.
- **Merge** is three-way: base = main at the branch's `base_seq`, source =
  the branch's changes, target = main now. Each change is classified
  (identical, compatible, content conflict, evidence conflict, governance
  conflict, dependency conflict, unknown) and a **policy** turns the class
  into a decision (allow, allow with warning, preserve conflict, require
  review, reject, cannot determine). Tenant and lifecycle checks run before
  the policy and cannot be overridden by it.
- **Preview then apply.** A preview carries a digest of both heads and the
  change set. Apply recomputes the preview from the current state and
  refuses (`STALE_PREVIEW`) unless the digest matches. An idempotency key
  replays the earlier result for the same digest and is refused for a
  different one.
- **Applying** goes through the ordinary operations: an added memory is
  validated, a revision is `revise`, a withdrawal is `quarantine`. So the
  screens, retraction propagation and audit run exactly as for any write.
- **Revert** is compensating: a merge's additions are deprecated and its
  revisions are revised back. Withdrawals are not undone automatically.
- **History is not permission.** `snapshot(commit)` answers "what was
  recorded" and, separately, each memory's current admissibility. Nothing
  in a snapshot is ever served by retrieval.

## Security and privacy

Branch candidates are sealed, screened and erasable like any memory. A
branch is bound to one tenant; a merge across tenants is refused before any
policy runs. Commit envelopes carry ids and digests only, so erasing a
memory's content leaves no recoverable text in branch history.

## Migration and compatibility

Additive event types; an older reader ignores them (SPEC.md §8). No change
to existing memories. Schema 0.12.0 → 0.13.0.

## Test strategy

`tests/test_branching.py`: isolation, immutability, CAS under concurrent
writers (threads and processes), stale preview, idempotency, every merge
class, no resurrection of a withdrawn memory, cross-tenant refusal,
revert, snapshot versus admissibility.

## Rollback

Stop using branches; main is unaffected by any unmerged branch. Branch
candidates can be deprecated in bulk by `close`.

## Open questions

- Branch-of-branch (nested bases) is not supported in the first version.
- A merge into a branch other than main is not supported.
