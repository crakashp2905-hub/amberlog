# Memory Fabric 2.0 — Product, Engineering & Research Masterplan

**Date:** 27 October 2026  
**Status:** Proposed roadmap; architecture decisions and pricing assumptions are not validated commercial results.  
**Current repository:** https://github.com/crakashp2905-hub/memory-fabric
**Current version observed:** alpha 0.13.0 (repository README)

## 0. Executive decision

Build **the trust and continuity infrastructure for autonomous AI agents**, not another generic vector memory store.

**Product promise:** Agents remember what matters, know where it came from, revise incorrect beliefs, share relevant experience without leaking sensitive context, and cannot use stale or withdrawn evidence to authorize protected actions.

**Market approach:** horizontal, industry-agnostic infrastructure for any team or organization deploying agents that need persistent, trustworthy and governable context. Segment by agent maturity, workflow risk, integration complexity and required governance—not by industry. Validate an initial customer profile through discovery instead of assuming a winning vertical. **Long-horizon research:** causal, temporal, adversarial, and diversity-preserving collective memory.

**Non-negotiable:** preserve existing event-sourced governance core; avoid a rewrite.

## 1. Current reality and evidence

The repository README reports:
- Alpha 0.13.0, Python 3.11–3.13, zero core runtime dependencies.
- Provenance/authority, correction propagation through federated stores, gated tools with evidence checks, tenant permissions, event log, retention, MCP/HTTP/Python/LangChain integration, a local Control Center.
- 2,117 tests and ~130 memory operations per second (single-machine benchmark). These figures have **not** been independently rerun here.
- Explicit limitations: weak default hashing embedder, retrieval may give nearest match rather than abstain, limited free-text semantic contradictions, imperfect injection screens, no external security audit, no multi-physical-machine benchmark, offline peers can serve outdated memories until reconnection (leases mitigate consequential actions).
- Beta/experimental modules already include consensus, conflicts, knowledge navigation, claim checking, adaptive objectives, and compaction: inspect these modules before adding new replacements.

**Required gate:** pin a commit SHA, reproduce CI and performance baselines, inventory stable/beta/experimental modules, and document the actual implemented interfaces. No product-readiness claim should rely on README claims alone.

Sources: [Memory Fabric](https://github.com/crakashp2905-hub/memory-fabric), [limitations](https://github.com/crakashp2905-hub/memory-fabric/blob/main/docs/LIMITATIONS.md), [stability](https://github.com/crakashp2905-hub/memory-fabric/blob/main/STABILITY.md).

## 2. Competitive inspiration and differentiation

| Capability | Sarvam Knowledge Fabric | TencentDB Agent Memory | Memory Fabric direction |
|---|---|---|---|
| Information organization | Hierarchical knowledge trees, typed ontologies, navigable source data | Chat L0–L3, Skills, Wiki, CodeGraph | Add optional knowledge compiler and evidence indexes |
| Persistent/reusable memory | Shared memory described as next direction | Implemented memory-asset emphasis | Already has governed memories; deepen intelligence and workflows |
| Sharing | Enterprise knowledge access | Team assets, owner/role/agent access | Federation, provenance, corrections, tenant policies |
| Main research/proof | Structured enterprise QA and efficiency | Persona/profile continuity | Causal, temporal, adversarial, multi-agent outcome quality |
| Differentiating promise | Query complete enterprise knowledge | Reuse agent/team experience | **Trust, correction, continuity, safe action** |

Sarvam reports 84.2% expert rubric criteria on Harvey LAB versus 55.1% for its agentic RAG baseline. TencentDB describes four assets (Chat Memory, Skill, LLM-Wiki, CodeGraph) and L0–L3 hierarchy. Do not compare scores from dissimilar benchmarks as if they measure the same thing.

**Product differentiation hypothesis (not proven):** Once autonomous agents take consequential actions, the buying need changes from “can the agent recall a useful fact?” to “can we show why it believed this, correct the fact everywhere it propagated, and prevent an action based on invalid evidence?”

Competitors to benchmark rather than dismiss: Mem0, Zep/Graphiti, Hindsight, TencentDB, simple RAG, plain relational memory, and our earlier release. Avoid unsupported novelty claims; validate exact functionality on pinned versions.

Sources: [Sarvam](https://www.sarvam.ai/blogs/knowledge-fabric-enterprise-agents), [TencentDB](https://github.com/TencentCloud/TencentDB-Agent-Memory), [MemEval](https://github.com/ProsusAI/MemEval).

## 3. Product design: customer, job-to-be-done, wedge

### 3.1 Market-agnostic customer profiles

**Segment A — Individual builders and small teams.** Users operating one or more persistent agents across recurring tasks. User/buyer may be the same person. Typical need: reliable continuity, straightforward installation, understandable retrieval and corrections. **Potential wedge:** low-friction MCP/SDK setup, local-first operation, observable memory behavior and exportability.

**Segment B — Multi-agent teams and growing organizations.** Groups sharing context and workflows among agents, people and services. Buyers vary by organizational structure. Typical need: scoped sharing, reusable knowledge assets, review workflows, identity, and reliable updates. **Potential wedge:** governed shared memory with provenance and change propagation.

**Segment C — Organizations with stronger risk and governance requirements.** Any organization where decisions based on stale, inaccurate or unauthorized context have significant consequences. Buyers may include platform owners, operations leaders, security/governance stakeholders or procurement. **Potential wedge:** verifiable authority, auditability, bounded permissions, correction impact and optional action-time evidence checks. Higher-assurance claims require independent testing.

**Segmentation principle:** these are usage and maturity profiles, not industries, geographic markets or exclusive sales channels. The same features may matter in any domain. Prioritize customer groups only after testing urgency, buying authority, integration effort, deployment constraints and willingness to pay.

### 3.2 Core jobs-to-be-done

1. “When a new agent joins a project, load the *right approved context* without repeating everything.”
2. “When a fact, requirement or SOP changes, show who used the old version and remove/revoke dependent knowledge.”
3. “When agents disagree, show the independent evidence and the unresolved question rather than silently picking a winner.”
4. “Before an irreversible action, verify authorizations and evidence freshness.”
5. “When a task succeeds, convert the result into a reviewable reusable skill without treating success as proof of every claimed fact.”

### 3.3 Product surfaces

- **Developer SDK + CLI + MCP server:** install, ingest, remember, recall, explain, correct, verify, inspect incidents.
- **Memory Control Center:** timeline of a belief, evidence lineage, correction impact, federation health, access policies, skill candidates, retrieval traces.
- **Knowledge Compiler:** navigate documents, query typed entities, preserve citations and tables. Optional connector boundary; no dependence for zero-core install.
- **Team Memory Hub:** workspaces, collections, asset bundles, role/agent permissions, approval workflow, skill library.
- **Enterprise Control Plane:** deployment health, policy versions, audit export, incident review, safe-action policies; deployment-specific identity and encryption.

### 3.4 Five industry-neutral customer demos

**Demo 1: Correct once, update everywhere.** Multiple agents receive an outdated instruction. An authorized reviewer corrects it; dependent summaries and plans are re-evaluated, and connected agents stop using the superseded claim.

**Demo 2: Why did this action happen?** Show an action receipt with agent identity, input evidence, permissions, policy version and verification status. If the evidence changes, a repeat protected action requires fresh authorization.

**Demo 3: Continuity across sessions.** A new session or agent receives approved, task-relevant context and reusable skills. Compare tokens, latency, success and failure rates with a no-memory baseline.

**Demo 4: Knowledge change impact.** An authoritative source is revised; the system identifies affected memories and derived decisions while preserving historical context and a readable audit.

**Demo 5: Adversarial information.** An untrusted source attempts to inject instructions or impersonate authority. Measure whether the system prevents trust escalation and contains contamination while keeping independently valid knowledge available.

## 4. Product positioning and packaging

**Category:** General-purpose Agent Memory Trust & Governance Infrastructure (working positioning).  
**One-liner:** “Memory you can trace, correct, and trust across every agent.”  
**Buyer-facing headline:** “Give any agent reliable continuity, accountable knowledge and governed action.”

Avoid claiming *perfect safety, guaranteed truth, universal poisoning prevention,* or *full enterprise readiness.*

### 4.1 Package hypotheses (test with customers; not published prices)

| Edition | Buyer | Proposed feature bundle | Pricing experiment |
|---|---|---|---|
| Individual | Individual builder or evaluator | Single-node self-host, MCP, SDK, audit, limited workspaces, example apps | Free pilot with license permitting it; current repo license is proprietary, so decide license before public promises |
| Team | Any collaborating group | Shared workspaces, policies, approvals, SSO integration roadmap, skill assets, observability | Interview-test $49–199/team/month **or** usage-based billing; not a quote |
| Organization | Organizations needing stronger governance | VPC/on-prem, tenant isolation, service agreements, support, private data handling, advanced audit/policies | Custom annual agreement; collect willingness-to-pay evidence first |

*Do not publish tier boundaries or pricing until unit economics, security posture and licensing decisions are resolved.* Separate self-hosted license from hosted service costs. No customer should be billed for unbounded LLM calls; show and cap ingestion/query spend.

### 4.2 Business model and unit economics

Candidate revenue: commercial self-host license, hosted managed service, enterprise support, and professional deployment services (last one should not dominate). Meter optional hosted workloads by workspaces/active agents plus bounded operations or stored evidence volume, not token count alone.

Cost per tenant = hosting + database/storage + embeddings + extraction/inference + audit retention + observability + support + egress. Track gross margin only after observed customer workloads. Forecast at P50/P95 and include re-indexing and correction propagation costs. Price for **value captured**, e.g. developer time saved and risk avoided, while admitting those values must be experimentally measured.

### 4.3 Why customers would switch / why they might not

**Switching reasons:** auditable provenance, correction across copied memories, approval/policy workflow, framework portability, safe tool execution, measurable reduction in stale-memory failures.

**Objections:** another infrastructure dependency, latency at every tool call, private data concerns, integration effort, immature security review, uncertain value vs Redis/vector DB + app code, vendor lock-in, difficulty proving ROI. Address each with migration tooling, opt-in action fences, threat model, transparent benchmarks, export formats, local-only mode, and a 10-minute proof-of-value.

## 5. Architectural evolution (preserve existing core)

```text
Agents across any task or domain
        |
   MCP / Python SDK / HTTP / Framework adapters
        |
 Identity, tenant boundaries, access policy, agent asset routing
        |
 +--------------------------+--------------------------+
 | Knowledge Plane          | Memory Plane             |
 | documents / tree / index | episodes / facts / skills|
 | typed ontology / joins   | summaries / outcomes     |
 | tables / provenance      | session and team context |
 +--------------------------+--------------------------+
        |
 Collective Intelligence (experimental; opt-in)
 causal hypotheses, temporal validity, evidence independence,
 belief reconciliation, outcome-guided retention
        |
 Existing Governance Core (source of truth)
 event log, provenance, authority, signed retractions,
 action-time policy/evidence checks, audit, access control
        |
 SQLite / PostgreSQL, rebuildable indexes & projections
```

**Design invariants:**
1. Do not allow an LLM, parser, or compiler to bypass provenance and permissions.
2. Event log remains canonical. Vector indexes, ontologies, knowledge trees and graph indexes are projections.
3. Every derived fact identifies source versions; revocation invalidates dependent projections.
4. Evidence independence must account for copied/derived sources, not only apparent author count.
5. Separate epistemic confidence, policy authority, relevance, and task utility.
6. Protected actions require policy checks at execution time, not just earlier retrieval.
7. Tenant/private content cannot be promoted by summarization or federation.
8. Preserve human review and reversible promotion of experimental mechanisms.

### 5.1 New Knowledge Compiler

Input: PDF, markdown, documentation, transcripts, CSV, approved connectors.  
Output: document tree; stable section/page/table anchors; typed entity-relation records; citations; extraction-confidence and verification state; source validity dates; exportable query API.

Pipeline: source intake -> parser -> structural tree -> entity extraction -> ontology alignment -> normalization/dedup -> evidence validation -> approval -> indexes -> retrievable assets.

Query paths: `browse`, `search`, `filter`, `join`, `aggregate`, `read_source`. A completeness claim must identify its bounded corpus and query constraints; otherwise report unknown coverage. Strong retrieval can improve recall but does not magically prove completeness.

### 5.2 Reusable Skills

Skills are versioned procedural candidates with source episodes, input conditions, required permissions, expected outputs, evaluator rules, rollback instructions and approval status. A success episode is **not** sufficient to grant authoritative status; independent validation is required.

### 5.3 Temporal and causal representations

Represent **transaction time** and **valid time** separately. Store fact revisions, dependent claims, counterexamples, uncertainty and evidence support. Causal relations are **hypotheses** until supported by appropriate interventions/designs; do not convert correlation to causation via prompting.

### 5.4 Multi-agent reconciliation

Retain independent conflicting evidence; classify duplicate sources; expose unresolved competing hypotheses; use explicit decision policies rather than majority voting alone. When a claim is withdrawn, update directly and indirectly dependent records while preserving unrelated independently grounded claims.

### 5.5 Security and observability

Threats: prompt injection, poisoned records, authority laundering, compromised agent identity, cross-tenant leakage, stale federation peers, rollback/replay attacks, malicious skill extraction, unauthorized tool invocation. Cover in adversarial tests and deployment documentation. A self-reported passing test suite is not independent certification.

## 6. Research program

### R1. Governed correction and propagation
**Hypothesis:** traceable provenance and cascade-aware corrections reduce downstream invalid decisions versus plain RAG/shared KV memory.
- Experiments: linear, star, mesh federation; offline partitions; copied and derived claims; multi-hop withdrawal.
- Metrics: contamination rate, time to converge, surviving independent support, false invalidations, recall, latency.
- Baselines: no federation, naive broadcast, current Memory Fabric release.

### R2. Diversity-preserving collective beliefs
**Hypothesis:** retaining independent minority explanations improves decisions when majority claims share a common source or are wrong.
- Treatments: naive merge, majority vote, confidence ranker, origin-aware evidence sets, calibrated belief reconciliation.
- Metrics: accuracy, calibration, belief diversity, consensus error, decision regret, explanation stability.
- Failure risk: artificial diversity can preserve irrelevant or harmful misinformation. Diversity is not an end in itself.

### R3. Temporal truth maintenance
**Hypothesis:** bitemporal storage and dependent invalidation reduce stale-action failure and improve historical audit reconstruction.
- Tests: late corrections, retroactive effective dates, concurrent revisions, deleted source, offline agents.
- Metrics: as-of query accuracy, recall of superseded facts, retraction coverage, causal chain reconstruction.

### R4. Causal memory and counterfactuals
**Hypothesis:** retaining intervention/outcome structure improves future planning over flat episodic similarity memory.
- Build a simulation with known structural causal model; hide its causal graph from agents.
- Compare observational-only, naive narratives, causal hypotheses and intervention-aware learners.
- Metrics: counterfactual accuracy, intervention selection reward, causal discovery precision, regret.
- Guardrail: label unsupported causal edges as hypotheses.

### R5. Adaptive retention and meta-memory
**Hypothesis:** outcome-based retrieval and selective retention improve task reward per stored token without erasing rare critical facts.
- Compare TTL, LRU, embedding similarity, current outcome estimators, risk-aware utility with uncertainty.
- Metrics: downstream task success, storage cost, rare-critical recall, calibration, deleted-data recovery guarantees.
- A privacy-driven erasure request overrides inferred usefulness.

### R6. Safe procedural memory / learning from experience
**Hypothesis:** reviewed, validated skill candidates improve repeated workflows without amplifying errors.
- Compare raw transcript reuse, unreviewed skills, verified skills.
- Metrics: success rate, time to task, tool errors, unsafe authorizations, skill transfer across frameworks.

### R7. Evidence-complete enterprise retrieval
**Hypothesis:** knowledge tree plus ontology plus governed provenance beats current retrieval on cross-document constrained queries.
- Compare lexical+vector RAG, knowledge tree, ontology, full combined system.
- Metrics: entity set precision/recall, citation correctness, abstention, tokens, latency, per-task cost.

### Evaluation design
Use deterministic MemoryWorld and public retrieval/memory benchmarks (LoCoMo, LongMemEval, MemoryAgentBench as appropriate). Evaluate against Mem0, Graphiti, Hindsight, TencentDB where reproducible and license-compatible. Sarvam's commercial architecture may only permit architectural reimplementation, not exact reproduction. Pin model versions and all prompts. Use paired random seeds, confidence intervals, failure reports, and fixed budget ceilings. Ensure evaluation judges cannot read hidden task solutions when agent tasks run.

## 7. MemoryWorld: first research testbed

Scenario: five agents with different roles (observer, planner, analyst, reviewer and executor) work in a simulated shared task environment. Unknown to them, some source facts are outdated, observations have noise, an information source is compromised, and an operating constraint changes after a delay. Agents must answer questions, reconcile information, make plans, and request actions using evidence certificates. A separate simulator independently verifies outcomes. Use several interchangeable synthetic domain skins so improvements are not tied to one industry.

Episodes: source ingestion -> independent observations -> conflicting beliefs -> shared decisions -> correction -> federation delay -> subsequent tasks -> skill distillation -> regression tests.

**Metrics:** task utility, stale-decision rate, unsafe-action rate, provenance precision, evidence independence, retraction coverage, time-to-containment, recall, calibrated abstention, useful minority fact survival, latency P50/P95/P99, cost/task.

**Ablations:** governance off/on; flat retrieval/tree/ontology; isolated/shared memory; reconciliation off/on; causal engine off/on; outcomes off/on; weak/strong embedding.

**Reproducibility:** fixed seeds, synthetic data and licenses, benchmark split locked before tuning, commit SHA, hardware details, budgets, JSONL traces, independent outcome oracle, open reports.

## 8. Delivery roadmap and gates

### Phase 0 — Evidence and product validation (weeks 1–2, planning target)
- [ ] Freeze Git commit and rerun test suite/CI.
- [ ] Inventory existing relevant code before new features.
- [ ] Reproduce latency/throughput on local machine.
- [ ] Run 10 discovery interviews across user roles, organization sizes and agent use cases.
- [ ] Record existing workflows, alternatives, willingness to pilot, risk triggers.
- [ ] Select two design partners based on problem intensity and measurable outcomes, without assuming an industry.

**Gate:** verified technical baseline plus >=2 teams willing to test a real workflow (target, not a known result).

### Phase 1 — Developer wedge & retrieval (weeks 3–6)
- [ ] One-command MCP quickstart, sample agent workflow, zero data egress default.
- [ ] Hybrid retriever/reranker adapters and better abstention.
- [ ] Knowledge tree with source/page/table anchors.
- [ ] Typed ontology prototype and scoped query completeness measures.
- [ ] Existing correction/federation coverage for derived indexes.
- [ ] Visualize provenance, correction fan-out and policy outcomes.

**Gate:** 10-minute onboarding target and significant benchmark improvements with no governance regression.

### Phase 2 — Team Memory Hub (weeks 7–10)
- [ ] Verified reusable skill cards with versioning and permissions.
- [ ] Scoped memory asset bundles per agent/task.
- [ ] Review and approvals interface.
- [ ] Export/import and migration adapters.
- [ ] Multi-user identity integration and tenant isolation tests.

**Gate:** real multi-agent demo with human review, verified access controls and time/cost telemetry.

### Phase 3 — Research engines (weeks 11–16)
- [ ] MemoryWorld and baselines.
- [ ] Temporal truth maintenance.
- [ ] Belief reconciliation with common-source awareness.
- [ ] Causal experiment harness.
- [ ] Retention policy ablations and rare-critical preservation.
- [ ] Adversarial memory poisoning evaluation.

**Gate:** preregistered experiments show repeatable improvement on primary metrics without unacceptable regressions.

### Phase 4 — Commercial pilots and independent validation (after phase 3)
- [ ] Design partner pilots with data processing and retention terms.
- [ ] Independent threat-model and security review.
- [ ] SaaS/on-prem architecture decision with operating cost model.
- [ ] Reliability, backup/restore, incident runbooks, SSO/RBAC and audit exports.
- [ ] Customer-facing dashboard and documentation.
- [ ] First case study with reproducible outcomes and customer approval.

**Gate:** paid pilots and credible security posture, not arbitrary feature count.

## 9. MVP specifications and acceptance criteria

**MVP definition:** a team can install Memory Fabric, attach two agents, ingest approved project material, receive source-cited relevant memory, correct a shared incorrect fact, see its propagation, prevent a policy-protected unsafe action, and inspect an auditable report.

**Product acceptance (proposed targets, revise after baseline):**
- Setup <=10 minutes on documented supported platform.
- Clear source provenance for 100% of surfaced governed memories in test suite.
- No access-control bypass in adversarial tenant tests.
- Withdrawn fact and dependent derivative withheld from connected test agents after acknowledgement.
- Offline stale-peer behavior explicitly surfaced; consequential actions blocked when required freshness lease expires.
- Knowledge retrieval improvement supported by paired benchmark with disclosed cost and confidence intervals.
- P95 retrieval and action-check budget measured under representative load rather than declared in advance.

**Developer experience:** useful errors, reproducible examples, compatibility matrix, no silent fallback to lower safety, telemetry opt-in, observability without secret exposure, export and delete flows.

## 10. GTM and customer development

**First 30 days:** publish a general-purpose technical demo, integration guides and one reproducible benchmark narrative. Interview ~20 potential users and seek 5 in-depth problem interviews spanning different task types and organizational contexts; these are activity targets, not forecast conversions. Use accessible communities and professional networks without presuming that one sector will adopt first. Do not make high-assurance or safety-critical claims before independent review.

**Pilot playbook (4 weeks per design partner):** pre-register a task corpus and baseline; integrate one representative agent workflow; measure time, failures, token spend, rework and correction incidents; present success and regressions; discuss pricing only after perceived value established.

**Product-led distribution:** neutral documentation, MCP installer, plugin/adapter examples, interactive local demo, traceable comparison tests, tutorials. Carefully decide license (repository currently proprietary) before marketing an open-source community edition.

**Organization-scale deployment:** security and architecture brief, isolation and deployment patterns, penetration test findings, compliance roadmap only where relevant, data-handling and deletion semantics, support model, disaster recovery tests. Avoid saying certified when not.

**North-star metric:** weekly *verified agent tasks completed with correct, current, authorized evidence* per active team. Support metrics: retained teams, onboarding time, corrective action success, stale-action prevention, cost per verified task, reported customer hours saved, time to incident recovery.

## 11. Risks and mitigation

| Risk | Mitigation |
|---|---|
| Competitors ship similar governance | Differentiate by independently measured correction/retraction integrity, safe action and developer UX |
| Correctness mistaken for truth | Transparent epistemic uncertainty, independent corroboration, human review and abstention |
| Features create latency and cost | Optional mechanisms, caching with invalidation, P95 SLOs, cost budgets, failure-safe defaults |
| Compromised source creates false evidence | Origin tracing, dependency checks, bounded privileges, quarantine, drills |
| Compromised operator changes history | Off-host checkpoint anchoring, role separation, independent audit |
| Commercial promises outrun tests | Label alpha, pilot-only commitments, explicit security assessment |
| Proprietary license prevents community adoption | Evaluate dual-license, source-available, or commercial license deliberately |
| Overlong research roadmap delays product | Commercial wedge and one research hypothesis per milestone |
| Competitor scores not directly comparable | Same dataset, agents, budget, and evaluation protocol |

## 12. Prioritized build backlog

**P0 — Do first:** reproducible baseline, retrieval/abstention, source-aware knowledge tree, evidence citation correctness, regression tests, product wedge demonstration.

**P1 — Next:** ontology queries and completeness reporting; scoped asset bundles; verified procedural skills; operator review workflows; versioned temporal claims.

**P2 — Research:** common-source-aware belief reconciliation; MemoryWorld; causal intervention/outcome evaluation; adaptive retention; adversarial fault injection.

**P3 — Scale:** multi-host federation tests, external audit, isolation/identity hardening, commercial pilot operational readiness.

Do **not** build a new graph database, distributed event bus, large native application, or model training pipeline until measurements justify them.

## 13. Copy-ready Codex implementation brief

> Work in `crakashp2905-hub/memory-fabric`. Start by reading `AGENTS.md`, `README.md`, `SPEC.md`, `ARCHITECTURE.md`, `STABILITY.md`, `docs/LIMITATIONS.md`, tests, current relevant modules, and current CI. Do not rewrite the core, silently change stable APIs, or remove existing coverage. Pin the baseline commit and document exact current capabilities. Implement on a new branch in small reviewed commits. Phase 1 goal: optional knowledge compiler and evidence-complete hybrid retrieval as rebuildable event-log projections, with original source pointers, typed entity extraction, filters/joins, constrained completeness reporting, and abstention. All derived claims must maintain lineage and inherit governance constraints; withdrawal must invalidate/rebuild indexes. Preserve zero core dependencies and use optional extras for embeddings/parsers. Add deterministic integration tests with manipulated documents and correction propagation, retrieval baselines and token/cost measurements. Include migrations, architecture decision record, API docs, demonstration script, sample corpus, benchmark harness and limitations. Run existing full suite and new tests. Do not claim success or benchmark gains unless reproduced; list every unresolved gap.

## 14. Open business/technical decisions

- Brand name (Memory Fabric is a working name); trademark/domain clearance needed before launch.
- License: current proprietary vs community-usable developer edition.
- First paid product: self-hosted deployments, hosted service, or team-level subscriptions, selected from evidence rather than industry assumptions.
- Hosted inference providers and data residency requirements.
- Privacy retention/erasure expectations, encryption key custody, and audit tradeoffs.
- Source connectors in first pilot (start with local documents/Git repositories; integrations should be demand-driven).
- Exact SLOs after real customer workloads.
- Which one of R1–R7 yields meaningful, reproducible gains first.

## 15. References (accessed 27 Oct 2026)

- Sarvam: https://www.sarvam.ai/blogs/knowledge-fabric-enterprise-agents
- TencentDB Agent Memory: https://github.com/TencentCloud/TencentDB-Agent-Memory
- Memory Fabric: https://github.com/crakashp2905-hub/memory-fabric
- Memory Fabric limitations: https://github.com/crakashp2905-hub/memory-fabric/blob/main/docs/LIMITATIONS.md
- Memory Fabric architecture: https://github.com/crakashp2905-hub/memory-fabric/blob/main/ARCHITECTURE.md
- Memory Fabric stability: https://github.com/crakashp2905-hub/memory-fabric/blob/main/STABILITY.md
- MemEval: https://github.com/ProsusAI/MemEval

---

**Final principle:** Ship trust, continuity, and corrective action as a practical product; use carefully designed experiments to earn the claim of collective intelligence.
