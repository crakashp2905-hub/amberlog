# S1 result — correcting exact versions across stores: **ABANDONED**

Registration: [prereg/s1-federated-correction.md](../prereg/s1-federated-correction.md)
(`d78176e`). Harness: `experiments/s1_correction_sim.py`, committed before the
run (`8521eeb`). Run: `python -m experiments.s1_correction_sim --seeds 20` in
a worktree pinned at `8521eeb`, 57 s, deterministic (no model). Raw output:
[s1-correction-sim.json](s1-correction-sim.json).

**Verdict: ABANDONED** under the registration's own rule. `delete_and_reshare`,
a registered baseline, reaches 0.9545 on the primary metric against a ceiling
of 0.9568. The headroom is 0.0023, below `memeval`'s 0.05 floor, so the metric
cannot separate any mechanism from that baseline. This is the AGENTS.md 8c
failure: the metric was not run against the registered baselines before the
threshold was written. It was cheap to do, since the simulator is
deterministic and takes a minute, and it was not done.

## Results (20 seeds, 5 stores, 12 facts, 20 steps; 20,520 checks per arm)

| arm | correct state | stale | missing | final convergence | unnecessary invalidation | dependent re-checked | status truth |
|---|---|---|---|---|---|---|---|
| `retraction_only` | 0.492 | 0.508 | 0 | 0 / 20 | 0.000 | 1.000 | (no retractions) |
| `naive_overwrite` | 0.933 | 0.067 | 0 | 3 / 20 | — | — | — |
| `delete_and_reshare` | **0.9545** | 0.046 | 0 | 20 / 20 | 0.000 | 1.000 | 1.000 |
| `versioned` (S1) | **0.9545** | 0.046 | 0 | 20 / 20 | 0.000 | 1.000 | 1.000 |
| `oracle` | 0.9568 | 0.043 | 0 | 20 / 20 | — | — | — |

The registration's checks:

- No arm beats the oracle (8b): **holds**.
- `versioned` closes ≥ 40% of the headroom: **ABANDONED**, because the headroom is 0.0023.
- `versioned` converges in every seed: **holds**, 20/20.
- `versioned`'s unnecessary invalidation is no higher than `retraction_only`'s: **holds**, 0 and 0.

The ≈4% stale share that remains for every arm, the oracle included, is a
store sitting behind a partition. No arm can reach it, and the oracle is not
allowed to either (8b).

## Predictions

1. *S1 passes.* **Not tested**: abandoned.
2. *`naive_overwrite` fails to converge under reordering.* **Confirmed**: 3 of 20
   seeds. An older value delivered last wins.
3. *`delete_and_reshare` has the highest unnecessary invalidation.*
   **Falsified**: 0, the same as every arm. A conclusion with an independent
   second premise survives the withdrawal of the first, whichever way the
   first is withdrawn. The quarantine rules re-check on justification, not on
   identity, so the reshared memory having a new id costs nothing here.
4. *`retraction_only` has the highest stale exposure and never converges on a
   corrected fact.* **Confirmed**: stale 0.508, 0/20.

## What was learned

- **On serving state, version-scoped correction and delete-and-reshare are
  indistinguishable.** Both withdraw the old copies through the same retraction
  protocol and offer the new value, and both re-check dependents through the
  same rules. The product keeps `supersede_copies` for a reason this experiment
  does not measure, and which is a design property rather than a claim: the
  origin's memory keeps its id, its version history, its value evidence and its
  audit trail, where delete-and-reshare starts a new memory with none of them.
  Whether that changes outcomes would need its own registration, with a metric
  that delete-and-reshare cannot max.
- **Building the harness found a product bug (F12, medium, fixed).** A memory
  shared around a cycle came home as an import of itself. A re-share names only
  the intermediary, and the intermediary never forwards a retraction back to
  the store that sent it, so after a correction the origin served its own
  superseded versions. Before the fix, `final_convergence` was 0/20 for every
  arm, because every seed contains a cycle. Imports now record their provenance
  chain, and an offer into a store on the chain is refused (`test_echo_import.py`).
- **Two harness errors were caught by the 8b checks before the registered run.**
  - An offline origin was allowed to send retractions but not offers, so
    recipients served nothing. Partitions are now symmetric.
  - The oracle marked an offline origin stale for its own correction. That was
    a handicap no arm had, and it let `versioned` show less stale exposure than
    the ceiling.
- **Status truth is 1.000.** Every delivery the sender recorded as `enforced`
  matched the recipient's state, including forwarded hops. The protocol's
  `verified` state, where the origin confirms enforcement for itself, is still
  never set. Without a receipt the recipient cannot prove anything, so it moves
  to S5.

## What this does not establish

One process, an in-process transport, scripted faults, and a simulator
written by the project that built the mechanism (registration §9). Nothing
here is evidence about a deployment.
