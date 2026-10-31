# Memory Fabric development and research roadmap

This is the acceptance ledger for the roadmap received on 2026-10-31. It uses
the product's restored name. A check means repository evidence exists; it does
not turn an internal test into independent or external evidence.

States: **COMPLETE** (repository evidence), **PARTIAL** (implementation exists,
more registered evidence is required), **GATED** (owner approval, credentials,
budget, or licensed data), and **EXTERNAL** (independent people or physical
infrastructure).

## P0 — release and correctness

| Item | State | Evidence / next gate |
|---|---|---|
| Exact-SHA tests and machine-readable evidence | COMPLETE | `tools/release_bundle.py`, CI `release-evidence`, `docs/MEMORY_FABRIC_RELEASE_CHECKLIST.md` |
| Generated validation and claim evidence | COMPLETE | `tools/results_manifest.py`, `research/results/manifest.json`, `tools/status_at_head.py` |
| Independent AI security red team | EXTERNAL | Internal corpus and remediation exist; independence requires a separately controlled evaluator |
| External human security review | EXTERNAL | Reviewer packet: `docs/SECURITY_TEST_PLAN.md`, `docs/SECURITY_REVIEW.md`, `SECURITY.md` |
| Authorization/retraction race safety | COMPLETE | `tests/test_action_fence.py`, `tests/test_visibility_at_action.py`, `tests/test_properties_authz.py` |
| Crash/retry-safe action execution | COMPLETE | `tests/test_action_crash.py`, `tests/test_action_receipt.py`, `src/memory_fabric/actions.py` |
| Schema/protocol upgrade qualification | COMPLETE | `tests/test_version_skew.py`, `tests/test_key_migration.py`, `experiments/rollback_drill.py` |
| PyPI Trusted Publishing | GATED | Workflow and fresh-machine gates exist; publishing requires repository-owner approval and PyPI configuration |

## Retrieval and decision quality

| Item | State | Evidence / next gate |
|---|---|---|
| Decision-aware retrieval benchmark | COMPLETE | D1, Phase A, and `research/results/d1-downstream.md` measure downstream action success |
| Separate evidence sufficiency | COMPLETE | `src/memory_fabric/answerability.py`, `tests/test_answerability.py`, P2/P2b |
| Abstention calibration | COMPLETE | A1/A1-h registrations and risk/false-abstention results |
| Query-type routing | PARTIAL | lexical/vector/hybrid and chain arms exist; a single held-out router comparison remains research work |
| Summary dependency preservation | COMPLETE | `src/memory_fabric/lossless_compaction.py`, correction invalidation tests |
| Contradiction-aware rendering | COMPLETE | `tests/test_conflicts.py`, G4b results, context package reason codes |
| Claim-level independent corroboration | COMPLETE | `src/memory_fabric/independence.py`, `tests/test_independence.py` |
| Opt-in budgeted model checks | COMPLETE | model wrapper/cost manifests; deterministic core makes no model calls |

## Distributed engineering

| Item | State | Evidence / next gate |
|---|---|---|
| Real three-host testbed | EXTERNAL | CI uses distinct OS hosts and real networking; three owner-controlled physical hosts remain required |
| Partitions, crashes, clock skew | COMPLETE | `experiments/faultsim.py`, multihost CI, crash tests |
| Durable correction delivery | COMPLETE | outbox/inbox, dead-letter and retry tests |
| Evidence freshness contracts | COMPLETE | signed leases and action rules in `src/memory_fabric/freshness.py` |
| Concurrent tenant isolation | COMPLETE | tenancy, access-matrix, and stateful authorization tests |
| End-to-end authorization latency | PARTIAL | component/load distributions exist; a physical federated p50/p95/p99 run depends on the three-host testbed |
| Backup/restore/disaster recovery | COMPLETE | backup custody and restore drills; RPO/RTO documented |
| Long-duration soak/upgrade | PARTIAL | deterministic long-horizon and upgrade tests exist; representative wall-clock soak is deployment-specific |

## Research infrastructure

| Item | State | Evidence / next gate |
|---|---|---|
| Unified manifests/results | COMPLETE | `research/results/manifest.json`, `tools/results_manifest.py`, benchmark schemas |
| Synthetic vs real-agent scorecards | COMPLETE | `research/SCORECARD.md` and the acceptance ledger separate them |
| Blinded/multi-family evaluation | PARTIAL | held-out and multi-family runs exist; expanded frontier matrix is budget-gated |
| Adversarial generator | COMPLETE | PoisonWorld, mutation tests, held-out injection corpus |
| Ordinary-memory comparison suite | COMPLETE | Phase A and D1 matched baseline arms |
| Reproducibility container | COMPLETE | Docker image, pinned workflows, fresh-machine tests |
| Claims-to-evidence registry | COMPLETE | `docs/ENGINEERING_RESEARCH_CHECKLIST.md`, results manifest, status-at-head report |
| Independent reproduction | EXTERNAL | Reproduction materials exist; a separate team must perform and sign the run |

## Decision models and System 1

| Item | State | Evidence / next gate |
|---|---|---|
| Typed probabilities and abstention API | COMPLETE | `src/memory_fabric/decision_models.py`, `tests/test_decision_models.py` |
| Laya/Jev/encoder/deterministic comparison | GATED | callable adapters and deterministic contract arm exist; model packages, checkpoints, dataset, and compute approval are required |
| Provenance-conditioned features | PARTIAL | evidence IDs and constraints are typed; trained ablation is not yet run |
| Calibration/order/shift measurement | PARTIAL | Brier scoring exists; registered multi-model data is required |
| Risk-sensitive System 1 → System 2 | COMPLETE | entropy, confidence, abstention, and consequential-effect escalation policy |
| Latency/cost/success/unsafe comparison | PARTIAL | deterministic five-seed contract benchmark exists; model arms are gated |
| No probabilistic authorization bypass | COMPLETE | decision API cannot execute; `ActionGate` remains the only effect boundary |

## UTCP and governed Code Mode

| Item | State | Evidence / next gate |
|---|---|---|
| Pin current UTCP and Code Mode | COMPLETE | `docs/DECISION_MODELS_AND_UTCP.md`, official UTCP 1.0.x sources checked 2026-10-31 |
| Optional discovery/native adapters | COMPLETE | strict UTCP manual parser in `src/memory_fabric/tool_protocol.py` |
| Equivalent MCP/UTCP/Code Mode workflows | PARTIAL | shared descriptor/runtime contracts exist; external transport latency comparison remains |
| Capability-scoped sandbox | COMPLETE | literal-call plan rejects imports, loops, dynamic arguments, file/network/arbitrary execution |
| Per-effect execution authorization | COMPLETE | every generated call creates an exact `ActionRequest` and invokes `ActionGate.execute` |
| Dynamic calls/loops/retries/generated args | PARTIAL | safe calls, retries, and argument rejection tested; unrestricted loops are deliberately prohibited |
| Audit receipts/replay protection | COMPLETE | action receipts and per-call idempotency keys |
| Injection/exfiltration/confused deputy red team | PARTIAL | existing held-out suites cover MCP and tool output; new Code Mode parser abuse tests cover local sandbox boundary |

## Ninety-day plan

The decision record, sufficiency, baselines, corrections, provenance-preserving
consolidation, System 1 baseline, MCP integration, receipts, and fair ordinary
memory comparisons are represented by the evidence above. The following cannot
be closed internally: hosted-model and licensed-dataset evaluations, the
physical three-host run, independent security/reproduction, and an external
pilot. They remain visible in `docs/KNOWN_GAPS.md` and must not be relabelled by
a code-only change.
