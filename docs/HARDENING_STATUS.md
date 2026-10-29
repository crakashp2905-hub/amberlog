# Hardening status: the three lists, item by item

The owner's three lists of 2026-10-19 (six safety improvements, six
memory-objective upgrades, the Phase 0–7 release checklist), validated
against the repository. Every **done** names the code and the test that
holds it. **Partial** names the gap. **Open** says what it needs.

"Done" never means certified: there has been no independent review
([INDEPENDENT_EVALUATION.md](INDEPENDENT_EVALUATION.md)).

## A. Safety improvements

### A1 (P0). Origin-bound authority: **done**

| requirement | where | test |
|---|---|---|
| Trust boundary bound at first write | `authority.py`: kind from the first version's `context.kind`, or inferred then; escalated by a later instruction version, never relabelled | `test_authority.py::Elevation::test_the_kind_is_bound_at_first_write`, `DelayedActivation` |
| Survives summaries, tool outputs, federation | inherited through lineage, `copy_of` and `context.federation.authority` (the origin's verdict, a floor at the recipient) | `TheBoundarySurvivesEveryTransformation` (inject → summarise → tool copy → share) |
| Source identity separate from the summariser's | `Authority.origins` vs `Authority.transformed_by` | `test_the_summary_keeps_the_source_apart_from_the_summariser` |
| Instruction / observation / derived claim are distinct | `KINDS`; an instruction is never evidence at the gate | `test_an_instruction_is_never_evidence` |
| Policy-controlled elevation before consequential use | `Amberlog.elevate`: a different approver, one version, soft reasons only; `ToolRule.min_authority` (default `unverified`) | `Elevation` |
| Success does not prove the memories were right | nothing in `authority.py` reads outcomes | `OutcomesDoNotConferAuthority` |

### A2 (P0). Influence graph with typed edges: **done (structure)**

`influence.py`: `derived_from`, `summarized_from`, `copied_from`,
`imported_from`, `exposed_to`, `relied_on`, `authorized`, `invalidated_by`,
rebuilt from the log. `impact()` keeps **potentially contaminated**,
**actually retrieved** and **confirmed use** apart (`tests/test_influence.py`).
Gap: a paraphrase with no lineage or copy link joins the graph only through
exposure.

### A3 (P0). Fail-closed action authorisation: **done**

| requirement | where |
|---|---|
| Bound to action, target, parameters, evidence versions, identity, expiry | `actions.binding_digest`, `Grant`, `ActionRequest` |
| Short-lived tool grants | `issue_grant(ttl_s ≤ 300)`, `revoke_grant`; an agent cannot grant itself |
| Stale evidence or revoked permission rejected | evidence re-verified inside the fence (S6); credential re-verified per call; `execute` permission checked |
| Idempotency and reconciliation | `execute(key=)`: `already_executed`, `retry=True` re-verifies; `unfenced_changes` |
| Human approval by policy | `ToolRule.requires_human_approval`; `Approval(binding=)` voids on any change |
| Poison, expired grant, retracted premise, changed target, replay cannot bypass | `test_authority.py::ExactActionGrants`, one test each |

### A4 (P1). Federation recovery: **done**, one item partial

- Origin-bound identity across hops: `context.federation` `{store, agent, chain, root, authority}` (F12).
- Periodic reconciliation including offline peers: the manager's `dispatch` task retries every cycle (`test_verified_recovery.py::test_an_offline_peer_keeps_recovery_unresolved_until_it_confirms`).
- Recovery states `pending_reconciliation`, `quarantined`, `recovery_unverified`, `revalidated`: `response.verify_recovery` (same test file).
- External checkpoint: `--checkpoint-dir` (the manager's `checkpoint` task).
- Correlated or paraphrased evidence: copy recognition and source-root grouping (on); `independence.py` (S2, opt-in, it costs independent evidence). **Partial**: no semantic paraphrase detection without lineage.

### A5 (P1). Tenant isolation and credentials: **done**

- Short-lived scoped credentials, rotation, revocation: done (`identity.py`; RUNBOOKS §1–3).
- Rate limits, write quotas, bounded payloads, federation budgets: done (`limits.py`, agent-API limits; `tests/test_limits.py`).
- Independently protected audit checkpoints: done (`--checkpoint-dir`, signed checkpoints).
- Metadata-leakage tests: done (`tests/test_metadata_leakage.py`, with `conceal_cross_tenant`).
- **Physically isolated stores and keys: done.** `tenancy.TenantRouter` gives each tenant its own store file and key directory; tenant ids cannot name a path (`tests/test_tenancy.py`). Tenancy *inside* one store remains an authorisation boundary only.

### A6 (P1). Continuous adversarial release gate: **done**, one item partial

`tools/adversarial_gate.py` and the CI job `adversarial-gate`: fourteen
families (injection; delayed and progressive poisoning; laundering; false
corroboration; cross-tenant and metadata leakage; stale authorisation and
replay; authority; offline peers and recovery; log tampering; privacy;
resource exhaustion; objective filters dropping safety evidence; privilege separation; backup tamper and restore). Any
failure, error or empty family fails it, and the release checklist requires
it green on the exact commit. **Partial: multiple models.** The CI gate is
model-free. Model-in-the-loop attacks (G4, G4b, T2b, M1b) run as
pre-registered research on two local model families (qwen2.5:3b,
gemma3:4b), not on every push.

## B. Memory-objective upgrades

| # | item | status | evidence |
|---|---|---|---|
| B1 | `MemoryObjectiveV2` with goal, required facts, preferred evidence, excluded context, safety constraints, scope, freshness, uncertainty policy, decision impact; irrelevant ≠ deletable | **done** | `objective_v2.py`; `test_objective_v2.py::IrrelevantIsNotDeletable` (an objective has no write path) |
| B2 | Hard vs soft vs uncertain; eligible = security ∧ lifecycle, then rank; a compiled filter never removes safety evidence unchecked | **done** | `Constraint.strength`; `eligibility()` keeps safety evidence against an unreviewed exclusion, and only `reviewed_by` can exclude it; `from_v1(compiled_by=…)` makes compiled rules *uncertain* (`HardSoftUncertain`) |
| B3 | Evidence-aware satisfaction | **done** | `evidence_score`: authority, kind, freshness and validity, independence (source root), preference, relevance (`EvidenceAware`) |
| B4 | Temporal and revision-aware | **done** | `as_of`, `freshness_ms`, expired validity ranks last; elevation and authority are per version |
| B5 | Adaptive but not self-authorising, proposals and evaluations logged | **done** | `ObjectiveLog.propose` / `adopt`: a different reviewer, no metric worse than baseline; every step an `ObjectiveChanged` event (`GovernedChange`) |
| B6 | Objective-quality experiment, six arms, eight metrics, vague / missing-metadata / changing objectives, malicious memories | **done** | `experiments/m1b_objective_quality.py`, held-out ([result](../research/results/m1b-objective-quality.md)): accuracy not supported (0.585 vs 0.729 prompt-only); unsafe action 0 vs 0.867 and safety-fact omission 0 vs 1.00, both supported |

## C. Phase 0–7 release checklist

| phase | item | status | evidence |
|---|---|---|---|
| 0 | CI on an exact SHA | **done** for 0.11.0; 0.12.0 at its release commit | `docs/RELEASE_EVALUATION.md` |
| 0 | Reproduce the benchmarks | **done** | CI jobs `faults`, `e2e`, `rollback`; research results cite commit and config |
| 0 | Reconcile the docs | **done** this pass | stale rows fixed in SECURITY.md, LIMITATIONS.md, SAFETY_ROADMAP_COVERAGE.md |
| 0 | Proven features vs experiments | **done** | [STABILITY.md](../STABILITY.md), enforced by `tests/test_stability.py` |
| 1 | One install path with clean removal | **done** | [QUICKSTART.md](QUICKSTART.md) §1; `tools/fresh_machine.py` checks the uninstall |
| 1 | 10-minute quickstart (store, retrieve, inspect, correct, verify) | **done** | `examples/quickstart.py`, `tests/test_quickstart.py` |
| 1 | Example reference agent application | **done** | `examples/reference_agent.py`, `tests/test_reference_agent.py` |
| 1 | Supported integrations documented | **done** | [INTEGRATIONS.md](INTEGRATIONS.md) |
| 1 | Diagnosable failures, structured logs | **done** | `doctor`, TROUBLESHOOTING.md; `--log-format json` (`observability/logs.py`) |
| 1 | Clean-environment matrix | **done** | CI `test` (3 OS × 3 Python), `package`, `fresh-machine` (3 OS) |
| 2 | Threat model | **done** | SECURITY.md T1–T12 |
| 2 | Origin-bound authority | **done** | A1 |
| 2 | Separate permissions | **done** | `identity.PERMISSIONS`: read, write, delete, correct, export, administer, execute; the operator has no execute (`tests/test_permissions.py`) |
| 2 | Tenant isolation, including inference | **done** | A5: `TenantRouter`; inference channels tested in `test_metadata_leakage.py` |
| 2 | Credentials and keys | **done** | A5; key rotation runbooks |
| 2 | Resource limits | **done** | `limits.py` |
| 2 | Audit tamper, rollback, deletion, replay tests | **done** | `test_integrity_chain.py`, `test_chains.py`, rollback drill, `test_erasure.py`, grant replay |
| 2 | Privacy leakage | **done** | `test_privacy_federation.py`, `test_receipts.py` (F13), metadata leakage |
| 3 | Lineage, trust vs relevance, contradictions and corrections, poisoning, false corroboration, stale and offline peers, exposed uncertainty | **done** | lineage and authority; conflicts (on by default); correction and receipts; G4b, T2b; S2; verified recovery; value estimates carry intervals and effective n |
| 4 | Exact-action binding, recheck before execution, safe retries, approval gates, failure tests, documented boundary | **done** | A3; S6 fence; `actions.py` module docstring |
| 5 | Keep the prompt-only baseline; compilation safety; hard vs ranking; ambiguity tests; more metrics; held-out tests; inspectable decisions | **done**, held-out run **pending** | B1–B6; `MemoryObjectiveV2.explain()` |
| 6 | Backup and restore including keys, config, audit | **done** | `backup --with-keys --include`, `restore` (manifest-checked), `tests/test_backup_custody.py`, RUNBOOKS §8 |
| 6 | Migrations and rollback | **done** | MIGRATION.md; CI `rollback` (real v0.11.0 code) |
| 6 | Runbook, incident process | **done** | RUNBOOKS.md §1–8; `incident`, `incident --verify` |
| 6 | Observability | **done** | structured logs; `maintain --status`; `doctor`; the dashboard |
| 6 | Performance limits under open-loop load | **done** | `experiments/p12_openloop.py`; limits in DEPLOYMENT.md §3 |
| 6 | Supported-version policy | **done** | [VERSIONING.md](../VERSIONING.md#supported-versions) |
| 7 | Automated security regression gate | **done** | A6 |
| 7 | Independent review | **open** | needs a third party ([INDEPENDENT_EVALUATION.md](INDEPENDENT_EVALUATION.md) is the brief) |
| 7 | Limitations page | **done** | [LIMITATIONS.md](LIMITATIONS.md) |
| 7 | Release evidence bundle: SHA, SBOM, scans, reports | **done** | `tools/release_bundle.py`; CI job `release-evidence` uploads it |
| 7 | A complete recovery scenario | **done** | `tests/test_verified_recovery.py`: poison → summary → belief → action → offline peer → contained, actions listed for review |
| 7 | Fresh-machine acceptance | **done** | `tools/fresh_machine.py`; CI job `fresh-machine` on Linux, macOS and Windows |

## Still open, and why

1. **Independent review.** Needs a third party.
2. ~~Physical tenant isolation~~: **done**: `tenancy.TenantRouter`, one store file and one key directory per tenant (`tests/test_tenancy.py`).
3. ~~Paraphrase links~~: **done, unvalidated**: `influence.paraphrases` and `possible_paraphrases` in `impact()`; 1.000 / 1.000 on its own fixture after one tuning, no held-out set ([result](../research/results/paraphrase-links.md)).
4. ~~Model-in-the-loop attacks~~: **scheduled**: `.github/workflows/model-attacks.yml` runs G4b and T2b weekly against a small Ollama model on the runner and fails on an invariant regression (`tools/model_attack_check.py`). Not on every push: one run takes hours. It has not run on GitHub yet.
5. ~~M1b held-out result~~: **done**: safety supported, accuracy not.
6. ~~A third-party injection dataset~~: **done**: deepset/prompt-injections, 0/60 → 20/60 caught on its test split with 0/56 benign flagged ([result](../research/results/injection-thirdparty.md)).
