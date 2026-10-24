# Pre-registration — S1: correcting exact versions across independently operated stores

**Registered 2026-10-18, before the mechanism's harness exists.** Research
direction S1 in [WORKPLAN.md](../../docs/WORKPLAN.md). Prior work, checked in
[literature-2026-10-18.md](../literature-2026-10-18.md): distributed truth
maintenance (Bridgeland & Huhns, 1990) and dependency-guided repair inside one
store (Yu et al., 2026) exist; correcting exact versions across stores that
are partitioned, re-share, and receive concurrent corrections was not found.

## 1. Why now

G4's harness showed that **a correction does not travel**: revising a memory at
its origin changes nothing in the stores that hold a copy, and offering the
new version again leaves the old copy active beside it. Only retractions
travel. And designing this found F11 (a delayed retraction dropped as
superseded), fixed before this registration.

## 2. The mechanism under test: version-scoped correction

When the origin revises a memory it has shared, for every store that holds a
copy of an older version it owes a retraction **of that version only**
(`reason_code: contradicted`, `evidence_reference: superseded by vN`) through
the same outbox, transport and dispatcher as any retraction, without
withdrawing its own current version; and offers the current version. A
recipient withdraws exactly the copy of that version, so the new import is the
only active one. No wire change: the protocol already carries the version.

## 3. Question

Under partitions, duplicate and reordered delivery, re-sharing (including a
cycle) and concurrent corrections, does version-scoped correction make every
store converge on the origin's latest version -- serving it, and no
superseded version -- without withdrawing conclusions that independent
evidence still supports?

## 4. Design: CorrectionSim (deterministic, no model)

Five stores with real `MemoryFabric` instances and the real dispatcher over an
in-process transport. Per seed (20 seeds): 12 facts written at random origins
and shared to 2–4 other stores, some re-shared onward (one cycle per seed);
1–3 corrections per fact at random times, two of them concurrent (the second
issued before the first is delivered); scripted partitions (a store offline
for an interval); every delivery has a 0.2 chance of being duplicated and the
queue is shuffled before each dispatch pass. At each recipient, some facts have
a derived conclusion: from that fact alone, or from it **and** an independent
second fact (which should survive a correction of the first).

A check after every event batch records, for every (store, fact) pair the store
should hold: is it serving the origin's latest version, a superseded one, or
nothing? Stores that are offline are checked too.

## 5. Arms

| arm | on correction | 
|---|---|
| `retraction_only` | revise at the origin and offer again (the product before S1) |
| `naive_overwrite` | send the new content to every holder, applied on arrival, last arrival wins, no versions |
| `delete_and_reshare` | retract the memory everywhere, then share the new version as a new memory |
| `versioned` | §2 |
| `oracle` | every reachable store holds exactly the latest version at once; an offline store at the moment it reconnects |

## 6. Metrics

- **Primary: correct-state rate** -- over all checks, the share of (store,
  fact) pairs serving exactly the origin's latest version.
- Stale exposure: share serving a superseded version.
- Missing: share serving nothing although the store should hold the fact.
- Unnecessary invalidation: share of conclusions with an independent second
  premise that are withdrawn after a correction of the first.
- Final convergence: after every partition heals and the queue drains, does
  every store hold exactly the latest version (per seed, binary)?
- Status truth: the origin's recorded acknowledgement state for each
  recipient agrees with that recipient's actual state.

## 7. Hypothesis and thresholds

**S1.** `versioned` closes **at least 40%** of the headroom between the best
baseline and the oracle on the correct-state rate, pooled over seeds and
checks; **and** final convergence holds for `versioned` in all 20 seeds;
**and** its unnecessary invalidation is no higher than `retraction_only`'s.
`memeval.Registration` applies ABANDONED / INVALID / UNDERPOWERED; 20 seeds.

## 8. Predictions

1. S1 passes.
2. `naive_overwrite` fails under reordering: an older correction arriving last
   wins, so it does not converge in some seeds.
3. `delete_and_reshare` converges but has the highest unnecessary invalidation:
   withdrawing the memory contests conclusions that had independent support,
   and the reshared memory is a new id they do not cite.
4. `retraction_only` has the highest stale exposure and never converges on a
   corrected fact.

## 9. What a pass would not establish

One process, an in-process transport, scripted faults, a simulator written by
the project that built the mechanism. It establishes the protocol's
behaviour under these faults, not a deployment's.
