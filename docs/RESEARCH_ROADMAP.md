# Research roadmap

Where each research direction in the
[safety plan](AI_SAFETY_CYBER_RESEARCH_IMPLEMENTATION_PLAN.md) §5 stands, what
was measured, and what would change the picture. **No direction here is claimed
as novel.** The prior-art check below found close work for the two central
mechanisms. The defensible position is a specific combination, measured
against fair baselines on a hand-built benchmark. That is not general evidence,
and it is not a new mechanism.

## Prior-art check (2026-10-16, limited)

A short web search, not a systematic review. It found:

| Work | Mechanism | Relation to this repository |
|---|---|---|
| MemLineage (arXiv 2605.14421, May 2026) | Cryptographic provenance plus a derivation lineage graph per memory. Sensitive actions that depend on external ancestry are blocked | **Closest to R1/R3/Task 4.** Lineage-gated actions are not new. Differences here: independence-aware truth maintenance (selective, not ancestry-blanket) and cross-store retraction. Not compared head-to-head |
| Proof-Carrying Agent Actions (arXiv 2606.04104, June 2026) | A portable action certificate, pre-action admissibility checks, approval and audit receipts | **Closest to the certificate and gate.** Action certificates are not new. Ours differ in content: memory evidence, versions, premises and roots, re-verified against an event log |
| SMSR (arXiv 2606.12703, June 2026) | HMAC provenance at write time, a certified robustness bound for multi-session poisoning | Signed provenance overlaps. We make **no** certified-robustness claim |
| MemShield, Memward, Nous (2026 workshop/tools) | Retrieval-time screening, trust scores, rollback | Overlap with screens and rollback. Not evaluated here |
| Distributed ATMS (Malheiro, Jennings & Oliveira, 1994) and reason maintenance generally | Justification-based belief revision across agents | The foundation of `justification.py`. Long-established |

Searched for and not surveyed: patents; benchmarks for these mechanisms;
anything after the search date. A comparison against MemLineage or PCAA on a
shared benchmark would be needed before claiming any advantage over them.

## Directions

| | Direction | Status | Evidence | Next step |
|---|---|---|---|---|
| R1 | Proof-carrying memory | **Implemented, measured internally.** `certificates.py`, `actions.py` | P5: invalid-evidence actions 0.099 vs 0.285–0.375 for acting baselines. H5a not supported as registered | Re-register with M1 paired to a utility floor. Run a model-driven arm. Compare with MemLineage on its workloads |
| R2 | Incident reconstruction | **Implemented.** `incident.py` | P9: the replay agrees with live withdrawal after a measured 20% false-attribution bug was fixed | Multi-source withdrawal interactions. Real incident logs |
| R3 | Diversity-preserving memory | **Partial.** Copy-aware roots, a near-copy signal, opt-in strict independence | `test_independence.py`. P5 high-impact errors 0 vs 0.93 | A frozen benchmark before the strict check can become a default |
| R4 | Derivation-aware freshness | **Partial.** Version-bound certificates and recorded premises | P5 TOCTOU cases; `test_certificates.py` | Plan re-validation instead of abstention |
| R5 | Privacy-aware federation | **Partial.** Class inheritance through derivation, opt-in tenant concealment | `test_privacy_federation.py` (4 failures before the fix) | Minimum-sufficient disclosure. No DP or ZK claims |
| R6 | Active auditor | **Implemented, observation only.** `auditor.py` | P10: event-triggered and budgeted policies 100% on planted problems vs 37.5% periodic | Problems no trigger describes. A real traffic trace |
| R7 | Contextual ecology / multi-hop | **Partial.** `chains.py` with budgets, opt-in | P1 NOT SUPPORTED (33% of headroom vs 40%) | Unchanged: `retrieve` stays the default |
| R8 | Decision-aware credit | Earlier H1/Phase A work | `research/results/h1-*`, `phase-a-*` | Unchanged by this plan |
| R9 | Evidence-backed mental models | **Implemented.** `mental_models.py` | `test_mental_models.py` | Refresh cost on a real corpus |

## Gaps that block stronger claims

- **No model-driven run** of P5. The deterministic agent obeys every injection,
  so its injection numbers are an upper bound on harm.
- **No independent scenario family.** Every benchmark here was written in this
  repository.
- **No external comparison.** Hindsight, MemLineage and PCAA were not run.
- **Paraphrased injections pass the screen**: 65% of fabric's residual P5 harm.
- **Write contention.** See [P12](../research/results/p12-load.md).
