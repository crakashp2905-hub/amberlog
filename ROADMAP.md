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
| **B** | What should cross a federation boundary, and does retraction need to follow it? | [prereg](research/prereg/phase-b-federated-agents.md) | ❌ **PB1 killed** · ✅ **PB2 supported.** Filtering what crosses does not help; a retraction that follows a memory drove acting-on-withdrawn-knowledge from 17% to **0%**. [Result](research/results/phase-b-federated-agents.md) |
| **C** | Can a population learn what should propagate? | [prereg](research/prereg/phase-c-memory-ecology.md) | 🔬 **Exploratory** — gate not passed, so no verdict. The outcome channel the design requires made the population **worse**, −0.042 [−0.081, −0.005]. [Result](research/results/phase-c-memory-ecology.md) |

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

## The next sequence: contextual relevance (R0–R9)

Added 2026-10-11, from two planning documents that agree on the sequencing. This
replaces nothing above — the integrity substrate stays, and the research record
stays — but it is where the next work goes, and this table is the single source
of truth for it.

**The product question widens.** From "can we govern memory safely?" to "given
this task, which memories matter, why, what is uncertain, and what must not be
exposed?" Relevance and integrity are separate, jointly necessary capabilities:
a relevant memory can be false, stale, retracted or unauthorised, and a true
authorised memory can be irrelevant now and essential later.

| # | Milestone | Gate | State |
|---|---|---|---|
| **R0** | Relevance contract and invariants | 10 invariants enforced in code, each with a test: task-scoped, exact-version-bound, no lifecycle authority, no gate override, explicit uncertainty, missing ≠ zero, auditable, budget-respecting, observed/inferred separable | ✅ **done** — [spec](docs/RELEVANCE_SPEC.md), 35 tests |
| **R1** | Benchmark, baselines, **oracle ceiling** | A clean checkout runs it; deterministic arms repeat; a deliberately broken ranker fails it; the ceiling is measured *before* any threshold is registered | ✅ **done** — [relevance_v1](research/bench/relevance_v1/README.md), [ceiling **+0.222 nDCG**](research/results/relevance-v1-ceiling.md) |
| **R2** | Transparent hybrid ranker | Beats the strongest *simple* baseline by a registered share of the measured headroom, on a split frozen before tuning | ⛔ **not the next thing to build.** The benchmark grew to 50 cases and four arms still sit within 0.04 of each other; R6 measured the model recovering ~40% of what nDCG penalises, so a ranker chasing the last points is chasing something the model partly fixes for free. Fix the embedder first — SciFact puts the shipped one at **less than half** of lexical retrieval |
| **R3** | Budget-aware context assembly | Better context sufficiency than top-k at equal budget; critical omissions within tolerance; every omission has a reason | ⛔ **blocked on a benchmark that can measure it.** R6 showed a model reading 19 memories unaided, so a budget this benchmark can impose is not a budget that binds |
| **R4** | Bounded lineage-aware discovery | Improved indirect relevance with bounded false additions, runtime and candidate growth. No causal claim without causal evidence | ✅ **done** — premise promotion took the `indirect` family 0.613 → **1.000**; bounded by depth, limit and parents-only |
| **R5** | Temporal / context dynamics (bitemporal) | Relevance reverses when context changes without memory mutation; stale data is never presented as current; `valid_time` distinct from recorded time | ✅ **done** — `valid_from`/`valid_to` on `Memory` (schema 0.7.0), `applies_at()`, `retrieve(as_of=…)`; +0.074 nDCG on the frozen split |
| **R6** | Real-agent integration | The full loop runs against a live provider with a deterministic stub path still in CI. A downstream claim only if a controlled experiment supports it | 🔶 **run. dev inconclusive, test ABANDONED** — perfect selection was worth +0.000 on the frozen split, so the registered abandonment clause fired. The dev finding that retrieval beats a stuffed context **did not replicate**. What survived both splits: a ~3× token saving, and stuffing the context making the model less willing to abstain ([result](research/results/r6-downstream.md)) |
| **R7** | Security and reliability | ✅ crypto (AEAD, external key custody) · ✅ trust boundary · ✅ multi-process durability · ✅ **tamper-evident event chain** with external checkpoints · ✅ concurrency measured and documented · ✅ version-skew tests · ✅ [OPERATIONS.md](docs/OPERATIONS.md). ✅ erasure inventory (`erasure_scope` reports reached / kept / unreachable, with the third as *unknown* rather than guessed) · ✅ state-machine property tests | ✅ **done** |
| **R8** | Developer experience | An unfamiliar developer completes the quickstart unaided; demo matches docs | — |
| **R9** | Release qualification | Claims match measured evidence, per deployment model | — |

### Why the benchmark comes before the ranker

Of four simulated hypotheses, **three were mis-operationalised, and every time
the fault was in the measurement rather than the mechanism.** A ranker written
before the thing that could falsify it gets tuned on whichever examples flatter
it. Both planning documents say the same, and so does
[RETROSPECTIVE.md](research/RETROSPECTIVE.md).

### What R1 found

The prediction below was **wrong**, and it is left here rather than edited away
because a registered prediction that failed is worth more than one quietly
replaced. The measured ceiling is **+0.222 nDCG@3**, not ~5 points, and
critical-memory omission went from 28.6% to zero. Phase A's corpus was
generated by its own agents, so coverage was whatever the episodes produced and
selection was easy; a corpus with realistic distractor density leaves room.

The more immediately useful finding is not about ranking: **the shipping
retrieval path is the weakest non-broken arm**, losing to IDF-weighted token
overlap by up to 32 points, because it is a hashing embedder. And three of the
five highest-gap families are answerable with provenance, source roots and
recorded time — mechanisms the store already has and retrieval does not use.

### What R1 was expected to find

Worth registering as a prediction rather than discovering later. Phase A and PA′
both found success tracking one quantity — whether a correct memory reached the
prompt — with conversion at 93–98% in every arm and coverage-to-success at
**ρ = +0.975**. Perfect *selection* was worth **+5 points**; the rest was corpus
**coverage**, which is memory construction, not retrieval.

So if R1's oracle ceiling also comes out at ~5 points, the honest conclusion is
that relevance ranking is not where the headroom is — and an oracle is a far
cheaper way to learn that than a tuned ranker. That is the whole argument for
this ordering.

### What the external benchmark and R6 changed

**SciFact** ([result](research/results/scifact-external.md)) — 300 queries,
5,183 abstracts, third-party labels — showed the hashing embedder at **0.315
nDCG@10 against lexical's 0.621**, where `relevance_v1` had reported an 8% gap
rather than a 2× one. My own benchmark was flattering it through corpus size,
distractors I wrote, and memories short enough that token overlap nearly always
works. The parameter-free lexical arm landing just under published BM25 (0.621
against ~0.665) is the most reassuring number in the project: the harness
behaves the way a third party would expect.

**The product default changed from `hybrid` to `lexical`** as a result, because
fusing a near-noise arm into a good one costs 6.3 points there and loses on
`relevance_v1`'s held-out split too. `hybrid` is the recommendation once a
trained embedder is configured.

**R6** ([result](research/results/r6-downstream.md)) is inconclusive on dev and
**abandoned on the frozen split**, where perfect selection was worth +0.000 —
the registered clause for exactly that case fired on its own. The dev finding
that retrieval beats a stuffed context did not replicate; the frozen split
reverses it.

The strongest conclusion is about the benchmark rather than the retriever: **a
corpus a model can simply read does not pose a retrieval problem.** So the next
work is harder corpora and distractors that are near-misses rather than
obviously wrong — not a ranker, and not more mechanisms. Two effects did
survive both splits: a ~3× token saving for no measured quality loss, and
stuffing the context making a model less willing to admit it cannot tell.

### What R1's follow-up changed

A trained embedder (`nomic-embed-text` via the existing `OllamaEmbedder`)
closes **~70% of the dev headroom** and **+0.045 on the frozen split** — more
than every mechanism in this project combined, and it matches bounded premise
promotion on the `indirect` family with no lineage machinery at all.

Three consequences for this roadmap:

1. **R2 is blocked on the benchmark, not on the ranker.** Twenty cases cannot separate arms that differ by 0.05, and the two splits disagree about whether to fuse lexical with the real embedder. More labelled cases is the next useful work.
2. **Source-root grouping was measured against the wrong baseline.** It improves `copied_evidence` and `near_duplicate` relative to plain hybrid, and both are *worse* than plain `lexical` — so the comparison that mattered was never made. Re-measure before claiming it.
3. **The default embedder does not change.** Zero runtime dependencies is a stated commitment and `OllamaEmbedder` needs a running service; it is one line to switch, with the numbers as the argument.

### Explicitly deferred until evidence changes

A learned retrieval controller · online learning from unverified outcomes ·
relevance-driven deletion · default selective federation · P2P · graph ML ·
all-candidate counterfactual evaluation · a single score combining relevance,
trust, freshness and utility.

Phase C already measured the nearest thing to the first two: the learner did not
beat the fixed policy, and the outcome channel the design requires made the
population **worse** (−0.042 [−0.081, −0.005]).

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
