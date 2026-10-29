# Engineering and research acceptance ledger

This ledger is the completed assessment of the engineering and research
checklist received on 30 October 2026. It is a claims-to-evidence index, not a
marketing checklist. A row is **COMPLETE** only when the acceptance condition
has repository evidence. **PARTIAL** names a remaining repository-controlled
gap. **GATED** needs an owner decision, budget, licensed data, or a deliberately
unpassed research gate. **EXTERNAL** needs independent people or infrastructure
and cannot truthfully be completed by a source-code change.

The detailed test-by-test governance map is in
[INVARIANTS.md](INVARIANTS.md), [VALIDATION.md](VALIDATION.md), and
[MASTERPLAN_TRACKER.md](MASTERPLAN_TRACKER.md). Negative and inconclusive
results remain published in [the research scorecard](../research/SCORECARD.md).

## E1. Formal correctness and data integrity

| Acceptance item | State | Evidence |
|---|---|---|
| Formal lifecycle, authority, causality, and deletion invariants | COMPLETE | [INVARIANTS.md](INVARIANTS.md), [SPEC.md](../SPEC.md), `tests/test_lifecycle.py`, `tests/test_authority.py`, `tests/test_erasure.py` |
| Explicit memory transition state machines | COMPLETE | [PROTOCOL.md](PROTOCOL.md#4-two-state-machines-deliberately-separate), `src/amberlog/model.py`, `src/amberlog/protocol.py`, `tests/test_properties_state_machines.py` |
| Append-only log integrity, replay, tamper, and crash recovery | COMPLETE | `tests/test_eventlog.py`, `tests/test_integrity_chain.py`, `tests/test_verified_recovery.py`, `tests/test_multiprocess_crash.py` |
| Idempotent externally retried operations | COMPLETE | `tests/test_duplicates.py`, `tests/test_retraction_protocol.py`, `tests/test_import_preview.py`, `tests/test_action_crash.py` |
| Concurrent corrections and contradictory updates | COMPLETE | [documented conflict semantics](CONCEPTS.md), `tests/test_concurrency.py`, `tests/test_conflicts.py`, `tests/test_concurrent_requests.py` |
| TOCTOU protection | COMPLETE | transactional evidence boundary in `src/amberlog/enforcement.py`; `tests/test_action_fence.py`, `tests/test_visibility_at_action.py` |
| Exact action-gate guarantee | COMPLETE | [SAFETY_AND_SECURITY.md](SAFETY_AND_SECURITY.md), `tests/test_enforcement.py`, `tests/test_action_receipt.py`, `tests/test_action_crash.py` |
| Schema, event, and cryptographic compatibility | COMPLETE | [VERSIONING.md](../VERSIONING.md), `tests/test_version_skew.py`, `tests/test_vectors.py`, `tests/test_key_migration.py`, `experiments/rollback_drill.py` |
| Property-based and stateful adversarial testing | COMPLETE | deterministic generated properties in `tests/test_properties.py`, `tests/test_properties_authz.py`, and `tests/test_properties_state_machines.py`; no third-party test dependency is required |
| Executable model checking for critical protocols | COMPLETE | `tests/test_properties_state_machines.py` exhausts declared transitions and adversarial walks; `experiments/faultsim.py` model-checks 17 deterministic multi-store schedules and seven invariants per step |

## E2. Retrieval, provenance, and knowledge reasoning

| Acceptance item | State | Evidence |
|---|---|---|
| Evidence-complete retrieval | COMPLETE | [EVIDENCE_COMPLETENESS.md](EVIDENCE_COMPLETENESS.md), `tests/test_evidence_completeness.py`, `tests/test_answerability.py` |
| Contradictory and withdrawn evidence surfaced | COMPLETE | `tests/test_conflicts.py`, `tests/test_withdrawal_basis.py`, `tests/test_abstention_premise.py` |
| Relevance separated from authority | COMPLETE | [RELEVANCE_SPEC.md](RELEVANCE_SPEC.md), `tests/test_relevance_contract.py`, `tests/test_authority.py` |
| Independent supporting sources survive one withdrawal | COMPLETE | `tests/test_independence.py`, `tests/test_min_sources_enforced.py`, `tests/test_transitive_retraction.py` |
| Derivation confidence and source uncertainty | COMPLETE | `src/amberlog/typedclaims.py`, `tests/test_typedclaims.py`, `tests/test_reasons.py`; limitations are reported in `research/results/x2-typed-confidence.md` |
| Safe abstention and escalation states | COMPLETE | `tests/test_answerability.py`, `tests/test_abstention_premise.py`, `research/results/a1-abstention.md` |
| Provenance-preserving summarization/compression | COMPLETE | [LOSSLESS_COMPACTION.md](LOSSLESS_COMPACTION.md), `tests/test_lossless_compaction.py`, `tests/test_compaction.py` |
| Held-out 3–6 hop dependency chains | COMPLETE | `tests/test_chains.py`, `tests/test_evidence_completeness.py`, `research/results/p1-evidence-chain-reconstruction.md` |
| Retrieval cache freshness | COMPLETE | `tests/test_freshness.py`, `tests/test_cross_process_freshness.py`, `tests/test_x6_estimand.py` |
| Deterministic governance boundary | COMPLETE | `tests/test_governance.py`, `tests/test_gov_conformance.py`; probabilistic ranking cannot grant authority or an action credential |

## E3. Federation and distributed systems

| Acceptance item | State | Evidence |
|---|---|---|
| Consistency and failure semantics | COMPLETE | [PROTOCOL.md](PROTOCOL.md), [REFERENCE_DEPLOYMENT.md](REFERENCE_DEPLOYMENT.md), [LIMITATIONS.md](LIMITATIONS.md) |
| Durable outbox/inbox delivery, acknowledgement, and retry | COMPLETE | `src/amberlog/outbox.py`, `src/amberlog/dispatcher.py`, `tests/test_retraction_protocol.py` |
| Duplicate and reordered application | COMPLETE | `tests/test_federation_transport.py`, `tests/test_catch_up.py`, `tests/test_retraction_protocol.py` |
| Correction freshness budget and stale-action policy | COMPLETE | `tests/test_freshness.py`, `tests/test_action_fence.py`, [DEPLOYMENT.md](../DEPLOYMENT.md) |
| Partition, reconnect, and split-brain recovery | COMPLETE | `experiments/faultsim.py`, `experiments/multihost.py`, `tests/test_federation_world.py` |
| Causal-cycle and fan-out bounds | COMPLETE | `tests/test_reach.py`, `tests/test_propagation_v1.py`, `tests/test_limits.py` |
| Mixed-version negotiation | COMPLETE | `tests/test_version_skew.py`, `tests/test_protocol_schemas.py`; unsupported combinations fail closed |
| Cross-tenant federation authorization | COMPLETE | `tests/test_privacy_federation.py`, `tests/test_tenancy.py`, `tests/test_access_matrix.py` |
| Multi-machine distributed testing | EXTERNAL | Multi-process, real-network, latency, restart, and container-host tests run in CI (`multihost` jobs). A second physical machine remains MF-021/MF-046. |
| Convergence diagnostics and recovery | COMPLETE | `tests/test_status.py`, `tests/test_reasons.py`, [TROUBLESHOOTING.md](TROUBLESHOOTING.md), [RUNBOOKS.md](RUNBOOKS.md) |

## E4. Security, privacy, and adversarial hardening

| Acceptance item | State | Evidence |
|---|---|---|
| Complete threat model | COMPLETE | [SECURITY.md](../SECURITY.md), [SECURITY_TEST_PLAN.md](SECURITY_TEST_PLAN.md) |
| SDK, HTTP, MCP, and dashboard authentication/authorization | COMPLETE | `tests/test_access_matrix.py`, `tests/test_auth.py`, `tests/test_mcp.py`, `tests/test_operator_access.py` |
| Storage and application tenant isolation | COMPLETE | `tests/test_tenancy.py`, `tests/test_properties_authz.py`, `tests/test_data_access_paths.py` |
| Prompt-injection and memory-poisoning defence | COMPLETE | `tests/test_injection_patterns.py`, `tests/test_poisonworld.py`, `tests/test_model_screen.py`, `research/results/injection-heldout.md` |
| Forgery and replay protection | COMPLETE | `tests/test_federation_transport.py`, `tests/test_security_regression.py`, `tests/test_retraction_protocol.py` |
| Trust and key rotation | COMPLETE | [CRYPTOGRAPHY.md](CRYPTOGRAPHY.md), [RUNBOOKS.md](RUNBOOKS.md), `tests/test_key_rotation_drill.py` |
| Secret leakage controls | COMPLETE | `tools/scan_secrets.py`, `tests/test_sensitive_patterns.py`, `tests/test_metadata_leakage.py` |
| Bounds, quotas, rate limits, and DoS controls | COMPLETE | `tests/test_limits.py`, `tests/test_rate_limit.py`, `tests/test_ingest_hardening.py` |
| Replica/backup deletion and retention | COMPLETE | `tests/test_erasure.py`, `tests/test_erasure_residue.py`, `tests/test_backup.py`; limits are explicit in [LIMITATIONS.md](LIMITATIONS.md) |
| Independent penetration test and remediation | EXTERNAL | MF-022/MF-050. Internal review is in [SECURITY_REVIEW.md](SECURITY_REVIEW.md); it is not represented as independent. |

## E5. Reliability, performance, and operations

| Acceptance item | State | Evidence |
|---|---|---|
| Reproducible latency/throughput envelopes | COMPLETE | [DEPLOYMENT.md](../DEPLOYMENT.md), `research/results/p12b-api-load.md`, `research/results/p12c-api-load-200-400.md` |
| CPU, memory, I/O, and storage profiling | COMPLETE | `research/results/p12b-catch-up.md` and its retained raw profiles |
| Separate SQLite/PostgreSQL benchmarks | COMPLETE | `research/results/p12b-catch-up.md`, `research/results/pg-failover.md`, CI `postgres` job |
| Structured tracing and metrics | COMPLETE | `tests/test_tracing.py`, `tests/test_metrics.py`, `tests/test_observability.py` |
| Backup, restore, PITR, RPO/RTO | COMPLETE | [OPERATIONS.md](OPERATIONS.md), [RUNBOOKS.md](RUNBOOKS.md), `tests/test_backup.py`, `tests/test_backup_custody.py` |
| Fault injection and chaos harness | COMPLETE | `experiments/faultsim.py`, `tests/test_multiprocess_crash.py`, CI `faults` and `e2e` jobs |
| Resource limits and backpressure | COMPLETE | `tests/test_limits.py`, `tests/test_rate_limit.py`, `research/results/p12b-api-load.md` |
| Long-duration soak/leak/corruption checks | PARTIAL | deterministic long-horizon worlds and load ladders exist; a continuously timed production soak on representative hardware remains deployment-specific |
| Upgrade and rollback | COMPLETE | `experiments/rollback_drill.py`, CI `rollback` job, [OPERATIONS.md](OPERATIONS.md) |
| Capacity-planning guidance | COMPLETE | measured envelope and limits in [DEPLOYMENT.md](../DEPLOYMENT.md) and [SCALE.md](SCALE.md) |

## E6. SDK, packaging, and software quality

| Acceptance item | State | Evidence |
|---|---|---|
| Import-safe installable package | COMPLETE | `pyproject.toml`, CI `package` and `fresh-machine` jobs; the project deliberately keeps the import package at repository root rather than imposing a compatibility-risking directory move |
| PyPI wheel/sdist with Trusted Publishing | GATED | `.github/workflows/publish-pypi.yml`, [PYPI_PUBLISHING.md](PYPI_PUBLISHING.md); publication requires owner approval and index/name readiness |
| Legacy `Amberlog` migration window | COMPLETE | [MIGRATING_TO_AMBERLOG.md](MIGRATING_TO_AMBERLOG.md), `tests/test_amberlog_migration.py`, `tests/test_verify_unfetched.py` |
| Public API and semantic versioning | COMPLETE | [API.md](API.md), [VERSIONING.md](../VERSIONING.md), `tests/test_sdk.py`, `tests/test_cli_versioning.py` |
| Typed SDK and stable errors | COMPLETE | `src/amberlog/py.typed`, typed public interfaces, `tests/test_sdk.py`, CI `mypy` |
| Python/MCP/HTTP conformance | COMPLETE | `tools/conformance_audit.py`, `tests/test_mcp_extended.py`, `tests/test_multihop_http.py`, `research/results/local-conformance-audit.json` |
| Supported OS/Python matrix | COMPLETE | CI tests Python 3.11–3.13 on Linux, macOS, and Windows |
| SBOM, provenance, and vulnerability controls | COMPLETE | `tools/release_bundle.py`, CI `release-evidence`, pinned release actions, secret and adversarial gates |
| Experimental/stable API separation | COMPLETE | [STABILITY.md](../STABILITY.md), `tests/test_stability.py`, explicit experimental namespaces |
| ADRs and contributor standards | COMPLETE | [CONTRIBUTING.md](../CONTRIBUTING.md), `AGENTS.md`, `docs/adr/`, `docs/architecture/` |

## R1. Experimental design and scientific validity

| Acceptance item | State | Evidence |
|---|---|---|
| Falsifiable hypotheses and primary outcomes | COMPLETE | `research/prereg/` and [ACCEPTANCE.md](../research/ACCEPTANCE.md) |
| Fair baselines and governance ablations | COMPLETE | registrations plus `benchmarks/checks.py`; baseline failures are retained |
| Matched models/prompts/tools/budgets/hardware | COMPLETE | run manifests and per-study registrations; unmatched arms are labelled rather than pooled |
| Held-out splits and contamination controls | COMPLETE | benchmark builders and manifests under `research/bench/` |
| Multiple seeds and model families | COMPLETE | five-seed minimum in `AGENTS.md`; cross-family evidence in `research/results/x6-cross-model-portability.md` and G4 results |
| Confidence intervals and effect sizes | COMPLETE | `benchmarks/stats.py` and result reports |
| Negative results | COMPLETE | [SCORECARD.md](../research/SCORECARD.md), [RETROSPECTIVE.md](../research/RETROSPECTIVE.md) |
| Frozen final-test configurations | COMPLETE | preregistrations, immutable raw results, and dev/test separation |
| Preregistered thresholds | COMPLETE | threshold JSON/Markdown files in `research/prereg/`; unreachable thresholds are reported as failures |
| Reproduction package | PARTIAL | scripts, manifests, seeds, and raw results are present; public-dataset licensing and outside reproduction remain MF-048/MF-050 |

## R2. Real-agent utility and downstream outcomes

| Acceptance item | State | Evidence |
|---|---|---|
| End-to-end real LLM agents | COMPLETE | `research/results/live-multi-agent.md`, `live-claude-mcp.md`, `live-ollama-validation.md`, G4 |
| Task success and decision quality | COMPLETE | `research/results/d1-downstream.md`, `phase-a-real-agent-benchmark.md` |
| Unsafe stale/withdrawn-evidence actions | COMPLETE | `research/results/t1-learned-staleness.md`, `s6-action-fence.md` |
| False blocking and abstention | COMPLETE | `research/results/a1-abstention.md`, `s1-screen-false-positives.md` |
| Long-horizon evolving workflows | COMPLETE | `research/results/l1-long-running.md`, `phase-c-memory-ecology.md` |
| Agent-error/hallucination recovery | COMPLETE | G4, correction, poisoning, and source-notice studies |
| Token, compute, latency, and cost | COMPLETE | common model client and `benchmarks/cost.py`; run manifests retain usage |
| Multiple capability families | PARTIAL | multiple local/hosted families have been measured; a frontier-family matrix remains budget gated |
| Retrieval-to-action attribution | COMPLETE | `research/results/phase-a-prime-attribution.md`, `tests/test_influence.py` |
| External workflows/datasets | PARTIAL | SciFact and LongMemEval evaluations exist; independent partner pilots remain external |

## R3. Memory learning, evolution, and consolidation

| Acceptance item | State | Evidence |
|---|---|---|
| Retain/merge/forget utility | COMPLETE | H1/H2/H3 studies and negative H2 result |
| Provenance-preserving compression | COMPLETE | C1/C2/INT-04 and lossless-compaction qualification |
| Uncertainty-aware consolidation | COMPLETE | X2/X2b and typed-claim studies, including negative calibration finding |
| Temporal knowledge decay | COMPLETE | `research/results/decay-view.md`, T1 |
| Correction-aware summarization | COMPLETE | C1/C2, `tests/test_lossless_compaction.py` |
| Episodic/semantic/procedural interaction | GATED | episodic/semantic components are measured; procedural assets are deliberately gated by ADR 0003 and MF-020 |
| Causal dependencies | COMPLETE | `research/prereg/causal-intervention-design.md`, C2 and attribution studies; limitations are explicit |
| Selection under fixed budgets | COMPLETE | H2 budget sweep, P2b, M1/M1b |
| Meta-memory/self-assessment | COMPLETE | answerability, abstention, and typed-confidence studies |
| Cross-domain transfer | COMPLETE | S4 recipient trust, X6 portability, external retrieval evaluations |

## R4. Collective intelligence and federation research

| Acceptance item | State | Evidence |
|---|---|---|
| Shared versus isolated memory | COMPLETE | H3 and phase-B studies |
| Selective versus blanket sharing | COMPLETE | H3, phase-B, G4 |
| Correction spread in heterogeneous networks | COMPLETE | S1, P3/P3b, propagation-v1 |
| Diversity-preserving aggregation | COMPLETE | H4 topology/diversity and GME matrix |
| Adversarial trust weighting | COMPLETE | S2, S4, G4 |
| Disagreement without false certainty | COMPLETE | G4b contradiction surfacing, consensus tests |
| Federation topologies | COMPLETE | H4 and five-store chain/star experiments |
| Provenance-preserving collective summaries | COMPLETE | compaction and federation lineage tests |
| Honest correction/uncertainty incentives | PARTIAL | cooperative/adversarial reporting is measured; economic/mechanism-design incentives need a new registration |
| External multi-agent tasks | PARTIAL | real-agent and external-style tasks exist; independent replication remains MF-028 |

## R5. Security research and trust evaluation

| Acceptance item | State | Evidence |
|---|---|---|
| Adaptive poisoning suite | COMPLETE | PoisonWorld, G4, injection held-out corpus |
| Indirect injection/tool compromise | COMPLETE | T2/T2b, G4, injection pattern tests |
| Source-authenticity spoofing | COMPLETE | S2 laundering, federation signature tests |
| Screening false positives | COMPLETE | S1 screen study |
| Correction/retraction attacks | COMPLETE | S1, S5, replay and reorder fault tests |
| Colluding/compromised peers | COMPLETE | G4 and Byzantine-style registered assumptions |
| Query leakage and membership/tenant isolation | COMPLETE | S5 leakage, metadata leakage, tenancy tests |
| Safety–utility–cost frontier | COMPLETE | G4 and scorecard report safe success, baseline utility, headroom, and costs |
| Versioned reproducible red-team corpus | COMPLETE | `research/bench/injection_heldout/`, PoisonWorld and manifests |
| Independent adversarial evaluation | EXTERNAL | third-party model outputs exist, but an independent attack team/report remains MF-022/MF-050 |

## R6. Novelty, publication, and external validation

| Acceptance item | State | Evidence |
|---|---|---|
| Prior-work and research-gap map | COMPLETE | [PRIOR_ART.md](../research/PRIOR_ART.md), [RELATED_WORK.md](../research/RELATED_WORK.md), literature matrix |
| Engineering/science claims separation | COMPLETE | this ledger, [FINDINGS.md](../research/FINDINGS.md), capability registry, scorecard |
| One primary falsifiable thesis | COMPLETE | central governed-memory thesis and gates in [RESEARCH.md](../RESEARCH.md) |
| Theory/formal analysis and limitations | COMPLETE | [SPEC.md](../SPEC.md), invariants, protocol ADRs, limitations |
| Mechanism ablations | COMPLETE | registered baseline/ablation arms throughout H-, P-, S-, and X-series studies |
| Benchmark protocols and evaluation code | COMPLETE | `benchmarks/`, `memeval/`, `research/prereg/`, raw results |
| External replication and peer feedback | EXTERNAL | MF-028/MF-050; no internal run is labelled independent |
| Technical paper with failure analysis | PARTIAL | methods, results, limitations, and failure analyses are published as repository reports; a submission-ready single paper remains owner work |
| Cross-industry generalization | GATED | cross-domain data exists; industry partner evidence needs licensed datasets/partners |
| Open problems and future experiments | COMPLETE | [RESEARCH_ROADMAP.md](RESEARCH_ROADMAP.md), [KNOWN_GAPS.md](KNOWN_GAPS.md), masterplan tracker |

## Closure summary

Repository-controlled engineering acceptance is complete except for a timed
production soak. The remaining non-complete rows are deliberately visible:
approved publication, physical multi-machine qualification, frontier-model
budget, procedural-memory research, licensed/partner datasets, a consolidated
paper, and independent security/replication/pilot work. Closing those rows
requires the named owner or external action; changing their labels without that
evidence would violate the repository constitution.
