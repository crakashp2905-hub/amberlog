# Literature check for S1–S6, 2026-10-18

Every work the research directions in [WORKPLAN.md](../docs/WORKPLAN.md) cite,
checked to exist and read at the abstract level before any question was
registered. Not a systematic review: a citation check plus what each paper
establishes, so a pre-registration can bound its novelty claim by it. The
earlier prior-art check (MemLineage 2605.14421, SMSR 2606.12703, Proof-Carrying
Agent Actions 2606.04104) is in [RESEARCH_ROADMAP.md](../docs/RESEARCH_ROADMAP.md).

| Work | Verified | What it establishes | Bears on |
|---|---|---|---|
| Bridgeland & Huhns, *Distributed Truth Maintenance*, AAAI-90, pp. 72–77 | DBLP record | Justification-based belief revision across agents is decades old; the first single-context multi-agent TMS | S1 |
| Yu et al., *From Faulty Memories to Corrected Actions: Dependency-Guided Rollback Repair*, arXiv 2608.10502 (11 Aug 2026) | abstract | Provenance graph from memories to actions; keeps independently supported information, deactivates the rest, replays affected computation; 85.3% recovery on a 150-case benchmark. **Single-store**: no cross-store propagation | S1, S2 |
| Chen et al., *MemSecBench*, arXiv 2607.27080 (29 Jul 2026) | abstract | Write–Execute–Forget protocol, 310 cases, 7 lifecycle checkpoints, 24 configurations; poison persisted in 84.2%, full chain succeeded in 50.3%. **Single store, no federation** | S3, G4 |
| Dash et al., *From Untrusted Input to Trusted Memory* (MPBench), arXiv 2606.04329 (Jun 2026) | abstract | Four write channels, nine weaknesses, six attack classes; prompt-injection defences do not cover memory poisoning | S3, G4 |
| Huang et al., *PMPA*, arXiv 2609.13889 (12 Sep 2026) | abstract | Instructions hidden in benign sources get saved to memory and resurface cross-session (55.5–81.7%); prompt-level defence weak once memory is poisoned | S3, G4 |
| Bara, *Epistemic Sybil Resistance*, arXiv 2609.01873 (1 Sep 2026) | abstract | Report-only aggregators cannot tell copied agreement from corroboration; similarity deduplication fails; evidential ancestry is the limit | S2 |
| Rezazadeh et al., *Collaborative Memory*, arXiv 2505.18279 (May 2025) | abstract | Multi-user sharing with dynamic access control, private/shared tiers, provenance per fragment | S4, S5 |
| Tang et al., *Agent KB*, arXiv 2507.06229 (Jul 2025) | abstract | Cross-framework shared experience base; gains on GAIA | S4 |
| Hu et al., *ShareMem*, arXiv 2609.32511 (26 Sep 2026) | abstract | Cross-user experience sharing with recipient-specific tailoring; best when local experience is scarce. Measures utility, not harmful reliance | S4 |
| Zhou et al., *MemTrust*, arXiv 2601.07004 (Jan 2026) | abstract | TEE-protected zero-trust memory architecture with a cross-application sharing protocol. Hardware trust, not correction receipts | S5 |
| Xu, *Governed Persistent Memory*, arXiv 2608.12476 (Aug 2026) | abstract | Bitemporal source-bound state, fail-closed release; 2,400/2,400 vs 600/2,400 for an ungoverned Qwen2.5-7B. Fresh-state release at output time, single store | S6, S1 |

## What this leaves open, per direction

- **S1** — dependency-guided repair exists within a store (Yu et al.); correction
  of exact versions **across independently operated stores**, under partitions
  and re-sharing, was not found in this check.
- **S2** — the problem is formalised (Bara); measuring ancestry-tracking through
  paraphrase and summaries *inside a memory system*, against blocked
  independent evidence, was not found.
- **S3 / G4** — single-store lifecycle benchmarks exist (MemSecBench, MPBench);
  write → share → act → retract → recover **across stores** was not found.
- **S4** — sharing for utility exists (ShareMem, Agent KB); estimating
  transferability at the recipient from its own outcomes, scored on harmful
  reliance as well as utility, was not found.
- **S5** — TEE-based trust (MemTrust) and access-controlled sharing exist;
  privacy-preserving *correction receipts* need a separate review of
  revocation accumulators and verifiable deletion before any claim.
- **S6** — fail-closed release (GPM) and action certificates (PCAA) exist; a
  protocol coupling a fresh memory state to an external side effect under
  timeout and retry was not found.

"Not found" means not found in this check, not shown to be absent.
