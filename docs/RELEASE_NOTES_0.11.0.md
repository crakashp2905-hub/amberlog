# Memory Fabric 0.11.0 — release candidate notes

**Released as `v0.11.0`** from `rc/0.11.0`, after CI and acceptance passed on
the tagged commit ([RELEASE_EVALUATION.md](RELEASE_EVALUATION.md)). Not on PyPI:
the distribution name is not decided yet.

## Upgrading from 0.9.x

1. **Scope is now enforced on reads** (breaking, 0.10.0). A `private` memory is
   readable only by its writer and by agents granted `read` on a collection
   containing it. Until now every agent in the tenant could read it. To keep
   the old effective visibility for existing memories:
   `memory-fabric --db store.db share --all-private-active --actor <you>`.
   Restricted memories are refused and listed, by design.
2. The schema goes to 0.11.0, which is additive: two new event types and a few
   projection fields. Older logs replay unchanged. No migration step.
3. `Acknowledgement.state_revision` now counts the origin's own retractions.
   It used to be the recipient's log head (F13). The wire format is
   unchanged, and an origin comparing revisions for regression still can.

## What is new

| area | what | evidence |
|---|---|---|
| Governance | Collections with read / write / approve / retract grants. A review queue. Safe correction with preview. Lifecycle centre. Posture page and content-free audit export. Incident response workflow. Status labels. `init` | P1–P10 in WORKPLAN, all tested |
| Integrations | Function tools (OpenAI / Anthropic formats), a LangChain retriever, import from Mem0 / LangChain exports as reviewable candidates | `test_integrations.py`, CI `langchain-contract` |
| Concurrency | Incremental catch-up instead of full replays | 23× (SQLite) / 32× (Postgres) at 100 agents; capacity table in DEPLOYMENT §3 |
| **Action fence** | `ActionGate.execute`: verification and side effect in one write transaction. Lease, idempotency key, re-verifying retry, `unfenced_changes()` | [S6](../research/results/s6-action-fence.md): 0 / 1,229 violations, against 28.4% for authorize-then-act |
| Correction | `supersede_copies`: a revision withdraws exactly the older versions' copies elsewhere | [S1](../research/results/s1-correction-sim.md): converges 20/20 |
| Receipts | `receipts.py`: an opt-in correction receipt that reveals nothing and binds at audit | [S5](../research/results/s5-correction-receipts.md): soundness 150/150 |
| Independence | `independence.py`, opt-in: a report is not a second source if its author was shown the first | [S2](../research/results/s2-launder-sim.md) |
| Trust | `trust.py`, opt-in: recipient-side trust per (origin, context) from its own outcomes | [S4](../research/results/s4-recipient-trust.md) |

## Security fixes in this release

| finding | severity | what was wrong |
|---|---|---|
| F1 | High | concurrent requests shared one SQLite connection |
| F10 | High | scope was not enforced on reads |
| F11 | High | a retraction delayed by an outage could be silently dropped |
| F12 | Medium | a memory shared around a cycle came home as an echo import, and a correction left the origin serving its own old version |
| F13 | Medium | acknowledgements told every origin the recipient's activity, copy count and onward peers |

The full table is [SECURITY_REVIEW.md](SECURITY_REVIEW.md). There are **no
open critical or high findings.**

## What the measurements say, including what failed

| claim | outcome |
|---|---|
| G4: a governed, federated store beats plain shared stores by ≥ 40% of the headroom with real models | **Not supported**: 35% on qwen2.5:3b, though it is the best arm by +0.15. **Underpowered** on gemma3:4b, whose oracle is wrong |
| S1: version-scoped correction beats the alternatives | **Abandoned**: delete-and-reshare already reaches the ceiling |
| S2: exposure-based independence | **Not supported** at 28% of headroom. It is the only arm that catches laundering, at a structural cost |
| S4: recipient trust | **Supported, on the bar** (40.04%) |
| S5: receipts | Soundness supported. The leakage bar, as registered, failed on a statistic whose bar pure noise fails 26% of the time |
| S6: action fence | **Supported**, all three claims |

## Known limitations

- **Paraphrased prompt injection passes the screen.** It scored 0.05 safe
  success in G4. The screen matches patterns.
- **Before a poison is detected, retrieval can rank it above the honest
  note.** That happened in 35 of 40 cases in G4, against 20 of 40 for a plain
  lexical store. The cause has not been isolated.
- **The action fence costs writers.** They wait up to about 2 s under
  continuous action, and throughput drops 12–16%. On Postgres the fence is
  covered by its tests, in-process and cross-process, but not by the RaceSim
  experiment.
- **A crash mid-action records nothing.** The tool must deduplicate by its
  idempotency key.
- **The capacity limits in DEPLOYMENT §3 apply**: p95 ≤ 150 ms up to about
  10 agent processes per store.
- **Frontier models are untested here** (no API access, X-API). There is no
  container smoke test, because there is no Docker daemon (X-DKR).
- **The opt-in research modules are not wired into defaults**:
  `independence`, `trust`, `receipts` and `TransferGatePolicy`. Each has a
  measured result, but none has the evidence to change default behaviour.

## Not in this release

The memory-objective work (M1) and reflective rulebooks (M2) are research
running after this RC. They are on the work branch, not here.
