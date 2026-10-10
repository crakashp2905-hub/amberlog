# ROADMAP.md — the single roadmap (product-first)

**Decision (2026-09-27): product-first.** Open decision #1 is settled. Governance and provenance lead; causal credit becomes an upgrade for customers who have outcome signals.

Rationale (from [research/CRITICAL_REVIEW.md](research/CRITICAL_REVIEW.md) §11): most deployments cannot supply the verified outcome signal that causal credit needs, but every deployment already faces the questions governance answers — where did this memory come from, why does the agent believe it, who may see it, how do we pull it back. Those need no outcome data.

This replaces the three roadmaps in the source document (Phases 1–7, Milestones 0–8, the 20-item list).

## Carried over from the research-first plan

Two things are built in P1 even though they only pay off at P4, because **they cannot be retrofitted**:

1. **Propensity logging on every exposure decision** (SPEC §4). Without it, no historical data can ever support unbiased credit estimation. It costs one float per decision.
2. **Verified-outcome plumbing** (`record_outcome` with a `verifier_id`, self-reports rejected). Cheap now, impossible to backfill.

## Milestones

| # | Milestone | Deliverables | Gate to proceed |
|---|---|---|---|
| **P0** | Specs | This doc set + the critical review | ✅ done |
| **P1** | **Governance core** | Memory model; append-only event log as source of truth; projections rebuilt from the log; lineage graph; provenance; sensitive-data detection; firewall; scopes; lifecycle; TMS retraction; `explain()`; SDK facade; tests | A poisoned memory can be traced to its source and retracted with every descendant marked contested, proven by tests; projections rebuild byte-identically from the log |
| **P2** | Observability | ✅ Shared read model, triage list, CLI, read-only HTTP API, web dashboard, demo seeder. **Postgres deferred** — see below | ✅ Someone outside the project can answer "why did this agent remember this?" unaided, from either surface |
| **P3** | Adapters | ✅ `AgentSession` (capability-scoped writes), prompt-context builder with injection defences, Claude API adapter, transcript ingestion | ⚠️ **Partly met.** The full loop runs against a stub client; **not yet run against the live API** (no key in this environment). See below. |
| **P4** | Causal credit (H1) | ✅ RuleWorld with analytic ground truth, DR + amortized estimators, power sweeps, pre-registered experiment | ✅ **H1 supported**: ρ=0.604 at 1.8% overhead, +0.366 over naive (ρ=0.761 at ε=0.20). [Result](research/results/h1-causal-credit.md) · [decision](research/decisions/2026-09-28-h1-proceed.md) |
| **P5** | Credit-driven lifecycle (H2) | ✅ v2 world (harm bites, drift, rare events), retention arms, pre-registered experiment | ❌ **H2 killed**: amortized beats the heuristics but loses to naive usage-success (−0.012). Naive captures 93% of the oracle's gain. [Result](research/results/h2-credit-driven-retention.md) · [decision](research/decisions/2026-10-01-h2-killed.md) |
| **P6** | Selective federation (H3) | ✅ `federation.py` (recipient decides, imports unvalidated, provenance crosses), two-context world, overlap sweep | ⚠️ **H3 inconclusive**: crossover curve confirmed, but the registered +0.030 margin exceeded the +0.027 ceiling, so no method could pass. [Result](research/results/h3-selective-federation.md) · [decision](research/decisions/2026-10-05-h3-inconclusive.md) |
| **P7** | Conflicts, diversity, topology (H4) | ✅ Bandit world, 5 topologies, minority-preservation mechanism | ⚠️ **H4a inconclusive** (effect is an inverted U; registered test point was the extreme) · ✅ **H4b supported**: preserving contested hypotheses takes P(correct) 0.905→1.000, recovery 24%→100%, at *lower* regret. [Result](research/results/h4-topology-and-diversity.md) |
| **P8** | Learned controller (H5) | ❌ **Not built, by measurement.** The memory path makes **zero** LLM calls at 0.26 ms/episode, so H5's denominator is zero and the hypothesis is unaskable. [Decision](research/decisions/2026-10-07-h5-premise-false.md) | Re-registerable once an LLM-dependent memory operation exists |
| **P9** | Distribution | ❌ **Declined, by measurement.** 25× more memories costs 1.7× latency; 4.39 ms/retrieval at 2,000 memories and 120k events. [Decision](research/decisions/2026-10-07-p9-declined.md) | Gate not met and not close |

## After P9: the live-agent phases

P1–P9 answered whether the mechanisms work. They did not answer the question a
buyer asks first, because every result was either simulation or a single-mechanism
live check: **does any of this beat a vector store for a real agent?** An external
review said so directly, and it was right.

| Phase | Question | Registration | Gate |
|---|---|---|---|
| **A** | Does governed memory beat an ungoverned vector store for a real agent? | [prereg](research/prereg/phase-a-real-agent-benchmark.md) | ❌ **Killed.** Governed memory lost by 34 points, because withdrawal-on-failure withdrew the *correct* memories. [Result](research/results/phase-a-real-agent-benchmark.md) |
| **A′** | If not blame, then what? Leave-one-out and contrastive attribution | [prereg](research/prereg/phase-a-prime-attribution.md) | ❌ **PA′1 killed**, ✅ **PA′2 supported.** Real attribution recovers 71% of blame's damage and still loses to withdrawing nothing. [Result](research/results/phase-a-prime-attribution.md) |
| **B** | What should cross a federation boundary, and does retraction need to follow it? | [prereg](research/prereg/phase-b-federated-agents.md) | Running |
| **C** | Can a population learn what should propagate? | [prereg](research/prereg/phase-c-memory-ecology.md) | **Only if PB1 is supported** |

Three things about this set are deliberate.

**The baseline is not a strawman.** Phase A's decisive arm is
`shared_memory_decay` — a pooled vector store that deletes whatever was in
context when an episode failed. One line of code that reacts to outcomes.
Governance beating a *naive* vector store would establish nothing; H2 is the
standing precedent, where a propensity-corrected estimator tied a smoothed
success rate and the oracle showed the cheap baseline already captured 93% of
the available gain.

**Every phase builds its oracle first.** H3 registered a margin of +0.030 when
perfect knowledge could only deliver +0.027, so no method could have passed and
nobody noticed until the run was over. Principle 8a came from that, and all three
registrations express thresholds as a share of a measured ceiling.

**Phase C is gated on Phase B, in writing, before anyone is attached to the
result.** If selective sharing does not beat sharing everything and sharing
nothing, then "learning what to propagate" is a search over a flat surface and
the memory-ecology idea does not get built. This is principle 9 applied to the
project's favourite idea rather than to its least favourite.

**Explicitly parked** (revisit after P7): mutation and reproduction; one-bit / low-bit policy communication; FSDP / ZeRO sharding; Hyperspace or P2P substrate; marketplace and pricing tiers.

### P5 outcome and the H2b follow-up

H2 was killed at the registered budget of 40. An exploratory post-hoc sweep found amortized beats naive by +0.060 at budget 20 and +0.032 at budget 10, reversing at 40 and 80 — the estimator's advantage shows only when the budget binds hard enough that harmless memories compete with valuable ones for slots.

That is a new hypothesis, not a rescue of the old one. **H2b** (credit-ranked retention at a binding budget) needs its own pre-registration with fresh seeds before it counts. Until then the product default is naive usage-success.

### P3 gate: what is and is not proven

The fabric-side path is real and tested: session scoping, retrieval, exposure logging, prompt assembly, the `remember` tool, governance on the agent's write, and the refusal of a self-reported outcome. The model is a stub, so what remains unproven is only the request shape — whether the live API accepts this exact combination of `thinking`, `output_config.effort`, `strict` tools and the `fallbacks` beta.

To close it: `pip install anthropic`, set credentials, and run `examples/agent_on_the_fabric.py` with the `client=` argument dropped. Until someone does, the gate is partly met and P4 should not be treated as unblocked on the strength of it.

### Postgres deferred out of P2

P2 listed a Postgres backend. It was dropped from the milestone because it does not serve the gate — observability is about what the surfaces can explain, not where the bytes live — and because a driver (`psycopg`) would be the project's first runtime dependency, costing the zero-dependency property for no gain at current scale. Postgres belongs with the first deployment that actually needs concurrent writers or a store larger than one machine's SQLite file; the storage seam already exists (ARCHITECTURE.md §4).

## Settled decisions

| # | Decision | Choice |
|---|---|---|
| 1 | Research-first or product-first | **Product-first** |
| 2 | Language and storage for v0 | **Python 3.13, stdlib only, SQLite** — zero dependencies, reproducible single-file runs |

## Still open (for discussion)

3. **LLM for the agent tier**, and the budget for LLM-agent runs (see CRITICAL_REVIEW §2.1 for the scale).
4. **Real benchmark** for validation at P4 (ALFWorld, WebShop, τ-bench, a SWE-style set).
5. **Memory types in v0:** all three, or semantic + procedural with episodic left as the raw log. *(P1 implements all three; the question is which the product surfaces.)*
6. **Project name**, given the MemOS / MemoryOS collision.
7. **Numeric thresholds** for H1–H5 — the numbers above are proposals and must be pre-registered before P4 starts.
8. **Embedding model.** P1 ships a deterministic, dependency-free hashing embedder so tests are reproducible. A real model is swappable behind the `Embedder` protocol; choosing one is a P2/P3 decision.
