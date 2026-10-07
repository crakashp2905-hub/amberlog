# RESEARCH.md

## 1. Thesis (narrowed)

> Agent memory should be retained, exposed and shared according to its **estimated causal value**: the expected improvement in outcomes from exposing it in a given context. That value can be estimated online, correcting for the selection bias that retrieval introduces, and amortized across memories so that it scales.

The broader vision (memory ecology, a learned lifecycle controller, distributed federation) stays the long-term program. Every later stage depends on this thesis holding. The reasoning is in [research/CRITICAL_REVIEW.md](research/CRITICAL_REVIEW.md).

## 2. Novelty boundary

**Not claimed as new:**
- multi-store (episodic / semantic / procedural) memory
- consolidation, decay, and memory linking or evolution (A-MEM)
- trajectory-to-skill methods (Voyager, ExpeL, AWM)
- learned memory operations (Memory-R1)
- shared multi-agent memory (G-Memory, Collaborative Memory)
- provenance graphs
- distributed training techniques

**Candidate contributions:**
1. Online, propensity-corrected, amortized estimation of memory value in LLM agents, validated against ground truth.
2. Selective federation driven by transferability, characterized as a crossover curve over context overlap.
3. The effect of topology on collective memory correctness (the Zollman effect) in LLM memory federation.
4. TMS-style retraction propagating through derived agent memories (secondary).

## 3. Hypotheses

Pre-register the thresholds before each milestone starts (`research/prereg/`).

| id | Statement (short) | Milestone | Outcome |
|---|---|---|---|
| H1 | The propensity-corrected, amortized estimator reaches ρ ≥ 0.6 with true value at ≤ 10% exploration overhead, and beats naive usage by ≥ 0.15 | P4 | ✅ **supported** — [result](research/results/h1-causal-credit.md) |
| H2 | Credit-ranked retention and exposure beat relevance, relevance + recency + importance, and naive usage at equal budget, under drift and injected harm | P5 | ❌ **killed** — beats the heuristics, loses to naive ([result](research/results/h2-credit-driven-retention.md)) |
| H3 | Selective sharing ≥ max(none, full) for every overlap o, and strictly better for intermediate o | P6 | ⚠️ **inconclusive** — curve confirmed; threshold exceeded the ceiling ([result](research/results/h3-selective-federation.md)) |
| H4a | Sparse topologies are more often correct (but slower) under a misleading early signal | P7 | ⚠️ **inconclusive** — effect is an inverted U; registered test point was the extreme ([result](research/results/h4-topology-and-diversity.md)) |
| H4b | Preserving minority hypotheses raises P(correct) and shortens recovery | P7 | ✅ **supported** — 0.905→1.000, recovery 24%→100%, at lower regret |
| H5 | A distilled small controller matches the LLM controller (≥ 90% agreement, ≤ 2 pp loss) while replacing ≥ 50% of memory-management LLM calls | P8 | ⛔ **unaskable** — the memory path makes zero LLM calls, so the denominator is zero ([decision](research/decisions/2026-10-07-h5-premise-false.md)) |

The original H6 ("the full closed loop beats every mechanism alone") is not a hypothesis. It is answered by the ablation matrix in EVALUATION.md.

## 4. Related work to read and cite (verify each)

- **Agent memory:** Generative Agents (2023); MemGPT/Letta (2023); A-MEM (2025); Mem0 (2025); Zep/Graphiti (2025); MemoryBank (2023); MIRIX (2025); MemOS (2025); MemoryOS (2025)
- **Experience → skills:** Reflexion (2023); Voyager (2023); ExpeL (2023); Agent Workflow Memory (2024)
- **Learned memory operations:** Memory-R1 (2025); Mem-α (2025)
- **Multi-agent memory:** G-Memory (2025); Collaborative Memory (2025)
- **Valuation and attribution:** Data Shapley (2019); TracIn (2020); Datamodels (2022); eRAG (2024)
- **Off-policy evaluation:** IPS / doubly robust estimators for contextual bandits (Dudík et al. 2011 and later)
- **Belief maintenance:** JTMS (Doyle 1979); ATMS (de Kleer 1986); AGM belief revision
- **Collective epistemics:** transactive memory (Wegner 1987); the Zollman effect (2007, 2010); Hong & Page on diversity
- **Security:** AgentPoison (2024); MINJA (2025)
- **Benchmarks:** LoCoMo; LongMemEval; MemoryAgentBench (these measure recall, not value)

## 5. Experiment protocol

Hypothesis → pre-registration (thresholds, seeds, configs) → baseline runs → intervention runs → ablations → failure analysis → replication on the LLM agent → decision (proceed / kill / pivot), recorded in `research/decisions/`.
