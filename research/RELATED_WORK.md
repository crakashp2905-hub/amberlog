# Related work and what remains novel (blueprint §2.3, gap G11)

A web review on 24 October 2026, from abstracts, project pages and secondary
write-ups; **the full papers were not read**, so every comparison below is
provisional. It is a starting point for an expert review, not a substitute.
The blueprint asked that the "Governed Memory Evolution" contributions be
treated as hypotheses until a literature review; this is that review, and it
narrows them.

## Close prior work, by contribution

| blueprint contribution | closest prior work found | what that means for a novelty claim |
|---|---|---|
| Retraction propagates to derived memories | **Lemmalog** (J. Zomer, 2026): a Datalog memory engine that records which facts support each conclusion, so retracting a fact removes only conclusions that depended on it. Classic truth-maintenance systems (Doyle 1979; de Kleer 1986), which `lineage.py` already cites. | **Not novel as a mechanism.** What may be distinctive is enforcing it at *action time* (the fence) and across *federated stores* with signed retractions; that has not been found elsewhere, but was not searched for specifically. |
| Immutable versions with provenance, history ≠ permission | **Kumiho** (2026): beliefs as immutable revisions with provenance. A stale-constraints study (2026) models supersession as a change of current record while provenance stays immutable, and found agents inspected provenance in about one episode in five. | **Not novel as a data model.** The separation of "what was recorded" from "may this be used now", checked at use, is shared ground. |
| Branches, commits and merges for memory | **Git Context Controller** (arXiv 2508.00031), **Memoria** (MatrixOne; copy-on-write snapshots, branches, merges), **gitmem**, **agmem**, **pi-brain**. Their merges *synthesise* branch summaries with a model. | **Branching itself is not novel.** What was not found: a merge that classifies each change against a three-way base and **refuses to pick a winner between disagreeing claims**, rejects resurrection of withdrawn memories, and is refused when stale. The GME matrix measured this against a naive merge (H3 supported on ten fresh seeds). |
| Source-linked, invalidatable compression | **"From Lossy to Verified: A Provenance-Aware Tiered Memory for Agents"** (arXiv 2602.17913, Feb 2026) argues write-time summaries lose what future queries need and links tiers to verified sources. OptMem's append-only log with a summary tree (no licence; design only). | **Closest overlap; not novel as an idea.** Possibly distinctive: summaries served only while every source is current *and readable by the requesting agent*, and refused at submission if they state anything the sources do not. Our evaluation also found the limit: a 7B local model's summaries captured 0.12 of the headroom (research/results/decay-view.md). |
| Independent support vs derived copies | Not found in this search; MINJA-era defenses discuss lineage enforcement (emergentmind 2605.14421: untrusted ancestry may not authorise sensitive actions). | Possibly distinctive; needs a targeted search. |
| Context receipts | Not found as such; agent tracing tools log retrievals. | Possibly distinctive in form (ids, versions, exclusion reasons, no content); unclear as a research contribution. |
| Memory poisoning | **MINJA** (NeurIPS 2025), **AgentPoison** (NeurIPS 2024); defenses by moderation and trust-aware sanitisation (arXiv 2601.05504), lineage enforcement (2605.14421). | Our claim validation and quarantine are in this line; the comparison to these defenses has not been run. |
| Temporal knowledge | **Zep / Graphiti** (bi-temporal graph), Mem0, Letta/MemGPT tiers, A-MEM. | Our valid-time fields are the same idea; not novel. |

## What this changes

- Drop "novel" from retraction propagation, immutable versioning, branching
  and hierarchical compression. Claim, at most, the **combination** and the
  specific governance checks, each with its measured result.
- Next searches: action-time admissibility re-checks; federated retraction
  protocols; "independent support" under compression; a head-to-head with a
  synthesising merge (GCC, gitmem) on the GME matrix.

## Sources

- [Stale constraints in inherited agent memory (summary page)](https://academy.dair.ai/papers/stale-constraints-in-inherited-agent-memory-2608.25553)
- [From Lossy to Verified: A Provenance-Aware Tiered Memory for Agents, arXiv 2602.17913](https://arxiv.org/abs/2602.17913)
- [Autonomous Research Agents: A Survey of AI Scientists and the Verification Gap](https://arxiv.org/pdf/2608.05179)
- [Provenance and Lineage Tracking in LLM-Powered Agent Memory Systems (Zep, ZenML)](https://www.zenml.io/llmops-database/provenance-and-lineage-tracking-in-llm-powered-agent-memory-systems)
- [Kumiho (emergentmind)](https://www.emergentmind.com/topics/kumiho)
- [Lemmalog (runtimewire)](https://runtimewire.com/article/jordy-zomer-lemmalog-datalog-memory-llm-agents)
- [Git Context Controller, arXiv 2508.00031](https://arxiv.org/pdf/2508.00031)
- [Memoria (GitHub)](https://github.com/dengn/Memoria)
- [gitmem (PyPI)](https://pypi.org/project/gitmem/) · [agmem (PyPI)](https://pypi.org/project/agmem/)
- [Zep: a temporal knowledge graph architecture, arXiv 2501.13956](https://arxiv.org/pdf/2501.13956.pdf)
- [Agent memory systems: Letta, Mem0, Graphiti, Cognee](https://codepointer.substack.com/p/agent-memory-systems-and-knowledge)
- [MINJA: Memory Injection Attacks on LLM Agents, arXiv 2503.03704](https://arxiv.org/abs/2503.03704)
- [Memory Poisoning Attack and Defense on Memory Based LLM-Agents, arXiv 2601.05504](https://arxiv.org/html/2601.05504v1)
- [Lineage enforcement over filtering (emergentmind 2605.14421)](https://www.emergentmind.com/papers/2605.14421)
