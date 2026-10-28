# Product and alpha qualification decision packet

Status: prepared for owner review (N51); no commercial, license or SLA decision
is approved by this document. Evidence still needed: independent workflow pilots,
operating-cost measurements, security review and supported-deployment envelope.

## Product boundary

Working positioning: general-purpose trust, memory and continuity infrastructure
for agents. Demonstrations should cover single-agent continuity, shared context,
source revisions, governed actions and incident recovery without choosing an
industry. Describe traceable corrections and current evidence checks precisely;
do not claim universal truth, superior task accuracy or independent certification.

## Owner choices and required evidence

| Decision | Options to evaluate | Evidence needed before selection |
|---|---|---|
| First delivery | Self-hosted developer alpha; supported private deployment; managed service pilot | Independent onboarding failures, demand, operational capacity |
| Developer flow | Python SDK, MCP, HTTP, local Control Center | Time to first governed memory/correction and integration failure traces |
| Shared deployments | Logical tenant controls; store/process/host per tenant | Threat model, trust boundary, performance and customer requirements |
| Identity | Existing scoped identities/tokens; deployment-specific external identity integration | Rotation/revocation tests, customer identity requirements; no assumed SSO capability |
| Support | Best-effort alpha; paid deployment assistance; later contracted support | Incident workload and owner capacity, never unmeasured availability guarantees |
| Telemetry | Local diagnostics; explicitly opted-in pilot metrics; agreed hosted observability | Data inventory, consent, secret redaction, retention and deletion review |
| Residency | Owner-operated local storage; private-region hosted storage | Actual deployment and provider contracts; model/embedding egress inventory |
| Erasure | Current content-key destruction plus retained audit metadata | Index/cache/backup scope tests, external key custody and incident runbook |
| License | Retain proprietary; revised commercial developer terms; separately reviewed community terms | Owner/legal decision and dependency rights; existing license remains in force |
| Pricing experiment | Workflow-value interview; per-team/workspace hypothesis; bounded usage hypothesis | Real workload cost and willingness-to-pay interviews; no published quote |
| Differentiation | Continuity, auditable lineage, governed correction and action-time evidence | Same-harness failure-rate comparisons and pilot outcomes; no unsupported novelty claim |

## Economics worksheet (inputs deliberately unfilled)

Collect workload volume, active agents/workspaces, retention period, source and
index bytes, replication/backup factor, ingestion/update frequency, model calls,
tokens, replay/rebuild work, egress, human review and support minutes. Attach the
provider price version and observation window to every unit rate.

Compute workload cost as compute-hours × observed rate + stored/backup volume ×
observed storage rate + model/embedding usage × versioned unit rate + measured
egress + human review/support work. Include failed calls, re-indexing, correction
propagation and incident recovery. Report P50/P95 workloads, not just averages.
Cost per safe successful task divides total attributable cost by externally
verified safe successes; report undefined when none succeeded. Do not treat
unpriced local hardware or unpaid review time as zero economic cost.

## Pilot evidence packet

Before a pilot, freeze the representative task set, no-memory/simple-memory
baseline, correction events, permissions, success oracle, budget and data terms.
Record setup time, first useful result, repeat use, failed integrations, recovery,
task outcomes, costs and operator trust. Separate owner observations from
participant reports, record consent for any case study, and retain regressions.
No participant, interview, conversion or willingness-to-pay result is invented.

## Qualification and contracts

Use exact-commit CI, install smoke, backup/key restoration, current erasure,
signed-retraction/freshness and incident tests as alpha inputs. Independent
review and pilot acceptance remain distinct gates. Document exclusions, supported
configurations and response expectations before promising availability or support.
Keep APIs versioned/deprecated under existing compatibility policy and route
protected effects through action gates. Nothing here claims SOC 2, ISO, GDPR or
other certification; obtain applicable independent review before such claims.
