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
| **P3** | Adapters | ✅ `AgentSession` (capability-scoped writes), prompt-context builder with injection defences, Claude API adapter, transcript ingestion | ✅ **Met for a live Claude model over MCP** (2026-10-16): Sonnet 5.5 and Opus 5.5, 20 trials, every run recalled and verified, and a retraction from another process mid-session was refused 10/10 ([result](research/results/live-claude-mcp.md)). Open: `adapters/claude.py`'s request shape against the Messages API, which needs a key. See below. |
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

**Update 2026-10-16.** A live Claude model now runs the loop end to end
through the MCP server ([result](research/results/live-claude-mcp.md)), which
closes the gate's substance: the fabric works with a real Claude model, and
retraction reaches a running session. What remains is narrower than before —
whether the Messages API accepts `claude.py`'s exact request — and the text
below is about that adapter only.

The fabric-side path is real and tested: session scoping, retrieval, exposure logging, prompt assembly, the `remember` tool, governance on the agent's write, and the refusal of a self-reported outcome. The model is a stub, so what remains unproven is only the request shape — whether the live API accepts this exact combination of `thinking`, `output_config.effort`, `strict` tools and the `fallbacks` beta.

To close it: `pip install anthropic`, set credentials, and run `examples/agent_on_the_fabric.py` with the `client=` argument dropped. Until someone does, the gate is partly met and P4 should not be treated as unblocked on the strength of it.

### Postgres deferred out of P2 — then built as an option (2026-10-16)

**Update.** Built as an optional backend (`memory-fabric[postgres]`), not a
replacement: SQLite stays the default and the core stays dependency-free. It
earns its place for writers on more than one machine, which SQLite cannot
serve; it does not add throughput, because writers still serialise for the
hash chain. Every storage-touching test module runs against it in CI. The reasoning below for not
making it a P2 deliverable still stands.

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
| **R2** | Transparent hybrid ranker | Beats the strongest *simple* baseline by a registered share of the measured headroom, on a split frozen before tuning | ⛔ **still not next, and now for a measured reason.** [relevance_v2](research/bench/relevance_v2/README.md) puts the unclaimed headroom at **+0.193 nDCG@5** and says almost all of it is in multi-hop chains (`multi_hop_4` at 0.519), not in ranking near-misses: `direct` and `facet_trap` are already solved at 1.000 ([result](research/results/relevance-v2-ceiling.md)). Sufficiency has the larger headroom (+0.267) and is registered first. Earlier reason, still true: The benchmark grew to 50 cases and four arms still sit within 0.04 of each other; R6 measured the model recovering ~40% of what nDCG penalises, so a ranker chasing the last points is chasing something the model partly fixes for free. Fix the embedder first — SciFact puts the shipped one at **less than half** of lexical retrieval |
| **R3** | Budget-aware context assembly | Better context sufficiency than top-k at equal budget; critical omissions within tolerance; every omission has a reason | 🔶 **unblocked and registered.** relevance_v2's `budget_pressure` family costs ~25,000 prompt tokens for the full corpus against ~400 for a selection, so a budget now binds. Ceiling measured, threshold pre-registered as a share of it ([prereg](research/prereg/p2-context-sufficiency.md)); the selector itself is not built. The gap it has to close: **no arm abstains even once** on the nine dev cases where abstention is the only correct answer |
| **R4** | Bounded lineage-aware discovery | Improved indirect relevance with bounded false additions, runtime and candidate growth. No causal claim without causal evidence | ✅ **done** — premise promotion took the `indirect` family 0.613 → **1.000**; bounded by depth, limit and parents-only |
| **R5** | Temporal / context dynamics (bitemporal) | Relevance reverses when context changes without memory mutation; stale data is never presented as current; `valid_time` distinct from recorded time | ✅ **done** — `valid_from`/`valid_to` on `Memory` (schema 0.7.0), `applies_at()`, `retrieve(as_of=…)`; +0.074 nDCG on the frozen split |
| **R6** | Real-agent integration | The full loop runs against a live provider with a deterministic stub path still in CI. A downstream claim only if a controlled experiment supports it | 🔶 **run. dev inconclusive, test ABANDONED** — perfect selection was worth +0.000 on the frozen split, so the registered abandonment clause fired. The dev finding that retrieval beats a stuffed context **did not replicate**. What survived both splits: a ~3× token saving, and stuffing the context making the model less willing to abstain ([result](research/results/r6-downstream.md)) |
| **R7** | Security and reliability | ✅ crypto (AEAD, external key custody) · ✅ trust boundary · ✅ multi-process durability · ✅ **tamper-evident event chain** with external checkpoints · ✅ concurrency measured and documented · ✅ version-skew tests · ✅ [OPERATIONS.md](docs/OPERATIONS.md). ✅ erasure inventory (`erasure_scope` reports reached / kept / unreachable, with the third as *unknown* rather than guessed) · ✅ state-machine property tests | ✅ **done** |
| **R8** | Developer experience | An unfamiliar developer completes the quickstart unaided; demo matches docs | 🔶 **dry run passed, gate open.** Every README command and snippet runs verbatim from a clean venv (one snippet needed its imports); an MCP server now serves non-Python agents. The gate needs a person who has not seen the project, which a dry run by its authors cannot stand in for ([VALIDATION.md](docs/VALIDATION.md) row 6, 16) |
| **R9** | Release qualification | Claims match measured evidence, per deployment model | 🔶 **started.** Found and fixed: CI red on `main` for seven pushes while VALIDATION.md said it ran green; a fault-matrix invariant violation; `__version__` ≠ package version; stale test and layer counts; a macOS support claim CI never checked. Release workflow added. **Blocked on a name:** `memory-fabric` is taken on PyPI (open decision 6) |

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

### What the open-item sweep changed

Five items were measured open; all five were worked, and four produced results
rather than mechanisms.

**The chain search is 2.9× faster, with recall unchanged.** 193 ms → 68 ms a
query on LongMemEval. The cost tracked **query length** rather than corpus
size, because `_bridge_terms` ran ~35,000 times a query with a regex per shared
term. My first guess at the cause — per-candidate component recomputation —
was worth 11 ms of the 193; the regex in the inner loop was worth 88.

**Abstention is not a retrieval problem at any operating point worth having**
([result](research/results/abstention-signals.md)). Three signal families
eliminated with numbers — term absence sits at the base rate, chain coverage is
1.000 on every instance, and three calibrations all made the score worse — and
a fourth, absolute match quality, rejected on its operating point: a global
threshold's best achievable F1 is 0.206, abstaining on 23% of answerable
questions to catch 53% of unanswerable ones.

**Corrected 2026-10-13.** That result reported absolute match quality
collapsing to **AUC 0.319** when pooled, and said I had nearly published
d = 0.68 from a confounded sample which the full-population AUC caught. Both
statements are wrong and in the same way: the pooled AUC is **0.682**, the
published figure being its own complement, and the sample agreed with the full
population all along. Every other figure in that result reproduces exactly, so
the F1 and the verdict stand — the right call was made on the strength of an
upside-down number ([abstention-signals.md §7](research/results/abstention-signals.md),
[x1-extraction.md §5](research/results/x1-extraction.md)).

**A model can extract the declarations, and the mechanism still scores 0.000** ([result](research/results/x1-extraction.md)). X1 put one model call on every write and measured the registered primary at **0.000 against a bar of 0.400**, proposing **zero** relations out of three. `gemma2` extracted both sides correctly; `infer_relations` matches `modifies` against `predicate` by string containment, and an *axle-set figure* and a *tyre pressure* do not contain one another. Zero of seven models form the edge. The matcher's own unit test supplied both strings. Extraction is also a batch job and not an ingest-path step: no discrete GPU here, so 10,000 memories cost 26 to 151 hours depending on the model.

**A feature reranker does make fusion safe, and that is not worth having**
([result](research/results/r2a-feature-reranker.md)). On four benchmarks it
converges both arms to within a point — which is exactly what was asked for —
at a level below the better arm on three of four. The mode that keeps the
retriever's score and adds phrase order and proximity changes **nothing
anywhere**: those features are worth zero. A feature reranker cannot beat a
retriever whose features are a superset of its own, so reranking needs a model.

**Declared relations have a ceiling of 1.000**
([result](research/results/relations-ceiling.md)). A `QUALIFIES` relation takes
`multi_hop_4` from 0.000 to **1.000 sufficiency** on dev — the first arm ever
sufficient there — and does nothing on the frozen split, because the chain
picks the wrong axle rule and a qualifier can only attach to a memory the chain
found. No extractor was built, deliberately: the target text is this project's
own, so a pattern fitted to it would pass by construction.

**And a published table was stale.** The quarantine-timing fix changed which
memories are eligible, so it moved `relevance_v2`'s nDCG as well as its
stale-citation numbers. §7 of that result was corrected at the time and §1 was
not: headroom is **+0.193**, not +0.232, and the R4/R5 mechanisms' nDCG gain is
**+0.000**, not +0.022. That is the third correction to land on those
mechanisms, after R6's downstream gain and their stale-citation advantage.

### What LongMemEval changed

**A second external benchmark, and the first that tests what this project is
for.** [LongMemEval](research/results/longmemeval.md) (Wu et al., ICLR 2025) is
500 questions over long chat histories with turn-level gold evidence, covering
knowledge updates (78), temporal reasoning (133), multi-session reasoning (133)
and abstention (30) — four things SciFact cannot test and that had only ever
been measured on fixtures written here. Found by way of
[Hindsight](research/HINDSIGHT.md), which evaluates on it.

It earned its place immediately, in three ways.

**It found a shipped mechanism mis-specified.** `retrieve(as_of=T)` means state
at a point, and its docstring recommended passing the task's own time. On
ordering questions — *"which did I do first?"* — that costs **19 points of turn
recall**, because a fifth of their evidence postdates the question. Every
internal benchmark agreed with the old advice because **none ever placed
evidence after the task's event time**; `relevance_v2` uses one event time for
every case. `retrieve` and `reconstruct` now take `until` as well as `as_of`,
so the three temporal questions are distinct, and `tests/test_bitemporal.py`
pins them — a file that did not exist, though schema 0.7.0 added the fields.

**It gave the first controlled demonstration of the fusion rule.** Same corpus,
same queries, same two arms, varying only the haystack:

| haystack | vector | lexical | hybrid | fusion worth |
|---|---|---|---|---|
| 23 turns | 0.820 | 0.817 | **0.851** | +0.034 |
| 491 turns | 0.456 | **0.753** | 0.693 | −0.060 |

Every earlier confirmation compared *across* benchmarks. This one holds
everything else fixed, and reproduces the SciFact result on an independent
corpus. It is also the clearest argument that the rule is a **workaround**: RRF
gives every arm equal rank votes and cannot notice one has gone bad.

**It confirmed the abstention gap externally.** On 30 deliberately unanswerable
questions the fabric reports insufficiency **0–7%** of the time — the number
`relevance_v2`, P1 and P2 all reported internally, now on data I did not write.
LongMemEval's own retrieval evaluation *skips* these instances, so this is a
metric defined here on their data rather than one they endorse.

One encouraging number, and not the one I would have guessed:
**knowledge-update is the easiest question type at 0.935.** The hardest are
preference (0.528) and temporal reasoning (0.593), neither of which this project
has a mechanism aimed at.

### What the agent-team comparison and the envelope sweep changed

**[P3b](research/results/p3b-agent-teams.md) is the first end-to-end result:
SUPPORTED at 86% of a registered 40% bar, and 85% with ten times the agents.**

| metric | `local` | `shared` | `shared_blanket` | `fabric` | `oracle` |
|---|---|---|---|---|---|
| task success | 0.120 | 0.780 | 0.730 | **0.960** | 1.000 |
| acted on withdrawn knowledge | 0.050 | **0.180** | 0.000 | **0.000** | 0.000 |
| had to re-measure | 0.430 | 0.000 | **0.250** | **0.000** | 0.000 |
| duplicate discoveries | **13.6** | 5.0 | **10.0** | **5.0** | 5.0 |
| retrieval latency | 0.0 ms | 0.1 ms | 0.1 ms | **0.7 ms** | 0.0 ms |

Verdict holds from 10 to 100 agents and 20 to 200 facts, with retrieval latency
rising **1.6×** and the seed spread narrowing.

Three things worth carrying:

- **A plain shared store lets agents act on withdrawn knowledge in 18% of tasks and the fabric in none.** A correction in a plain store is just another write that ranks as well as it always did.
- **The naive fix is worse than it looks.** `shared_blanket` eliminates stale actions and destroys the fact next door — which does not register as wrongful invalidation, because it *repairs itself* by sending someone out to re-measure. It is visible only as a 0.250 re-measure rate and twice the duplicate discoveries. A metric can be satisfied by a system that did the wrong thing and then paid to undo it.
- **The world was wrong three times before it could pose the question**, each caught by principle 8c's check. The most useful: *a memory system's value is invisible in task success when the task can simply be redone.* With free rediscovery every baseline reached the ceiling.

**The agent is deterministic**, so this measures whether the right evidence
arrives and not whether a model uses it. R6 measured the other half and did not
replicate; mixing them would hide which half moved.

**[P4](research/results/p4-envelope.md) passes every condition and earned its
place by finding a defect the correctness tests could not.** 500 appends from 50
processes with nothing lost and no sequence gaps, per-write cost up only **22%
for 5× the writers**, zero cross-tenant leaks across 1,600 exposures, and a log
that reopens clean and writable after 16 of 50 writers are killed mid-write.

Two departures from the naive expectation, in opposite directions: contention
scales **better** than linear, and retrieval is flat to 1,000 memories and
**linear beyond it** — 19 ms at 10,000, so the envelope has a knee and 100,000
would need a different approach rather than a bigger budget.

And the defect: **copy recognition cost 32 ms a write at 10,000 memories**,
168× the baseline and linear in store size — right at a hundred memories and
unusable at ten thousand. Now **1.27 ms** via a bounded index that covers both
directions of the subset test and is checked against the exhaustive scan it
replaced. The fix is in the product, not in a note advising people to switch it
off.

### What copy recognition changed

P3's residual was one family and it is now **zero on both splits**: the
product's default matches the oracle at 0.000 stale citations, 0.000
unnecessary invalidation and 1.000 sufficiency, while `blanket_invalidation`
still pays 0.500 unnecessary invalidation and half its sufficiency. P3's
registered comparison is abandoned by its own clause again — but because the
headroom is gone, not because the fixture could not pose the question
([result](research/results/p2b-copy-recognition.md)).

A withdrawn document re-ingested under its own id is now recognised at **write**
time: it shares its original's source root, arrives `contested` rather than
`active`, and is reached by the original's withdrawal whichever of the two was
stored first. Schema 0.8.0, additive.

Three things worth carrying forward:

- **Measurement chose the rule against my first design.** Jaccard overlap scores a real re-ingestion at 0.722 and the worst of **152,640** near-miss pairs at 0.800. The orders cross, so a Jaccard threshold would have put two memories about different sites under one source root and called it deduplication. The shipped rule is subset containment, which has nothing to tune.
- **A copy is deliberately not a parent edge.** `_group_by_root` spares derivation-related memories, so a copy recorded as a child would have been exempted from the grouping meant to collapse it.
- **`derive` had a pre-existing hole.** Retraction reached conclusions drawn before a withdrawal and not after: deriving from an already-quarantined premise produced an `active` memory. Fixed with the recomputation `quarantine` already runs, applied at write time.

One published number moved. Copy recognition fires once in all of
`relevance_v1` — on two statements of one yard speed limit — and `store_all`
falls 0.0034 there. A test asserting an ordering across that 0.003 gap was
removed rather than the mechanism, and the reasoning is in §5 of the result.

### What P1 changed

**[P1](research/results/p1-evidence-chain-reconstruction.md) answers the
question the previous three experiments located and missed its own bar doing
it.** `MemoryFabric.reconstruct()` searches for a connected set of currently
valid memories that jointly cover a query, rather than ranking candidates
individually.

Registered verdict: **NOT SUPPORTED, 33% of headroom against 40%, identical on
both splits.** `multi_hop_3` passes on its own at 0.667 sufficiency against
every baseline's 0.000; `multi_hop_4` scores 0.000; the registration pooled the
two families, so 0.333 is the number.

What it does, on a real case: it recovers the memory *"chiller-1 was re-fitted
with the standard axle set in March"* — which contains **no query term at
all** — from **rank 462 of ~486**, labels it `DEPENDENCY_REQUIRED`, and reports
it as necessary by leave-one-out. That reason code had sat in the relevance
contract with no producer anywhere in the codebase since R0.

| | dev | test |
|---|---|---|
| nDCG@5, `lexical` → `chain` | 0.654 → **0.873** | 0.549 → **0.743** |
| precision@5 | 0.267 → **0.778** | 0.242 → **0.586** |
| families regressing | **0** | **0** |
| search latency | **13 ms** (vs lexical's 10) | 16 ms |

Three things it does not do, all measured:

- **`multi_hop_4` fails for an instructive reason.** Its missing memory says *"add 0.35 bar as a salt-corrosion margin"*: it supplies no query term and links nothing, so a chain that is already complete and connected has no reason to want it. It **modifies** the answer. The mechanism solves distributed evidence needing a connector and not evidence that qualifies a conclusion — and `implied_by_default` was read as the same gap from another angle — **wrongly**, as it turns out: that family's 0.000 was a k=3 result and plain lexical solves it on dev at k=5 ([x1-extraction.md §1](research/results/x1-extraction.md)). `multi_hop_4` is 0.000 at k=3, 5 and 10 on both splits and stands on its own.
- **Abstention is still unsolved**: 1 of 9 dev cases, 0 of 9 on test, and it reports `complete` on `unanswerable` cases because token coverage can be completed from memories that are not about the question.
- **It is not a default.** `reconstruct` is opt-in, beside `retrieve`, because a mechanism that misses its registered bar does not become the default and chain reconstruction is a different operation from ranking.

A disclosure is on the record in §4 of the result: diagnosing `multi_hop_4` I
inspected a **frozen-split** case and found a second failure mode that does not
appear on dev. The plausible fix would therefore be tuned on the frozen split,
so it has not been made.

### What facet_v1 changed

relevance_v2 recorded a defect in its own hardest family: `facet_trap` made
every distractor one facet from the answer and `lexical` scored **1.000**,
because the query names every facet so the discriminating token is present in
both. [facet_v1](research/results/facet-v1-implied.md) makes the deciding facet
**implied** instead, and adds the thing `facet_trap` lacked — a **stated
control** over the same questions, facts, values and distractors.

`lexical`, both splits, identical:

| family | nDCG@3 |
|---|---|
| `stated_control` | **1.000** |
| `implied_by_exclusion` | **0.000** |
| `implied_by_default` | **0.000** |
| `implied_by_paraphrase` | **0.000** |

1.000 against 0.000 with everything else held fixed, so the difficulty is
attributable to the implication and nothing else. `facet_trap` could not make
that argument at all: with no control, its 1.000 could have meant the family was
easy or the whole benchmark was.

Two findings beyond the separation:

- **`implied_by_default` is 0.000 for every arm on both splits** at **k=3**, trained embedder included. The answer — "all yard vehicles run 3.9 bar in winter, except at the harbour and quarry sites" — names neither the unit nor the site, so it ranks below four distractors that name both. **Corrected 2026-10-13:** at k=5 it ranks 4th and plain `lexical` reaches 1.000 sufficiency on dev (0.000 on test), so the claim that no similarity measure can rank it is withdrawn, and the family is abandoned as an X1 target ([facet-v1-implied.md §11](research/results/facet-v1-implied.md), [x1-extraction.md §1](research/results/x1-extraction.md)).
- **A trained embedder refutes a prediction written into the generator.** It was expected to close `implied_by_paraphrase` and not the others; it does the opposite, recovering `implied_by_exclusion` (0.250 dev, 0.816 test) and leaving the paraphrase family near zero.

Taken with relevance_v2's headroom sitting in multi-hop chains, the shape of
what is missing is now specific: **the unclaimed headroom in this project is not
waiting for a better similarity function.** It is waiting for something that
reasons about what a memory entails.

And a fourth confirmation of the fusion rule, with the roles reversed:
`real_hybrid` (0.250) drags `real_vector` (0.516) back to `lexical`'s score on
test. Every earlier case had a weak vector arm pulling down a strong lexical
one; here a strong vector arm is pulled down by a weak lexical one. **Do not
fuse a weak arm into a strong one**, whichever arm is weak.

### What P2 changed, which was mostly my own registration

**[P2](research/results/p2-context-sufficiency.md) was abandoned on both splits
because I registered a primary metric that one of my own registered baselines
maximises for free.** `full_context` holds every satisfier by definition and
scores exactly the oracle's 0.800 sufficiency, so `C − B = 0.000` before any
method existed. Prediction 1 said it would win on sufficiency and lose on tokens
— it did, by **219× in tokens** — and I did not follow that through to the fact
that it made the threshold unreachable.

**Sufficiency can always be bought with context.** The non-degenerate question
is sufficiency at a fixed budget, which the registration already contained as
`budget_matched_top_k` and then made decisive for nothing. Checking that a
primary metric is not trivially maximised by a registered baseline is now a step
this project owes every future registration, in the same way principle 8a's
ceiling is owed to every threshold.

At equal budget there is no reliable gain: a tie on dev, +0.100 on test, 33
cases a split.

**The selector does not work, and the defect is structural rather than a
parameter.** It greedily adds whatever covers the most uncovered query terms,
and a chain's middle hop covers none — its whole value is connecting the other
two, so its marginal gain is zero and it can never be selected. `multi_hop_3`
and `multi_hop_4` score **0.000**, identical to budget-matched top-k. Assembly
for multi-hop evidence is path-finding over an entity graph, not coverage
maximisation.

**Abstention is still at zero, and now has a diagnosis.** Demanding full lexical
coverage abstains on 79% of answerable cases; demanding coverage of only the
terms the corpus contains abstains on none. Token presence is not evidence about
a conjunction, and nothing between those settings is either.

**Nothing in P2 replicates.** An earlier version of this section claimed the
selector's zero stale citations as a surviving effect. Every arm scores zero
once the fixture lets the product's retraction propagation run and the
experiment stops re-admitting memories the store had already excluded from its
candidate pool — the comparison was the product's own behaviour, measured twice
with it switched off.

### What P3 changed, after three invalid runs

**[P3](research/results/p3-correction-propagation.md) ended up a correction to
itself.** It first reported that the product's dependency-aware behaviour loses
to a five-line baseline by 150% of the headroom, and that *"nothing in the
retrieval path asks whether a memory descends from something withdrawn"*. Both
claims were false.

`quarantine(propagate=True)` contests the descendants of a retracted memory and
contested memories are withheld by default, so the product already follows
derivation edges — at write time, through the lineage graph whose
`descendants()` docstring has always called it "the retraction set". My fixture
quarantined **inside the write loop**, so when a parent was retracted its
children did not exist yet, nothing propagated, and every arm was measured
against a state the product never produces.

Corrected, dev and test identical on every cell:

| arm | stale cited / case | unnecessary invalidation | sufficient |
|---|---|---|---|
| `no_propagation` (the product as it ships) | 0.500 | 0.000 | 1.000 |
| `blanket_invalidation` | 0.500 | **0.500** | **0.500** |
| `graph_traversal` | 0.500 | 0.000 | 1.000 |
| `source_root_grouping` | 0.500 | 0.000 | 1.000 |
| `oracle_propagation` | 0.000 | 0.000 | 1.000 |

On `retracted_intermediate` — a retracted memory that is *derived*, under a root
that still carries standing evidence — the product withholds the restatements
and keeps the sibling conclusion. That is the discrimination the fixture exists
to test, and it passes it. **A traversal rule at exposure time would duplicate
work already done at write time**, which is why `graph_traversal` and the
product score identically.

What survives:

- **The conservative rule is still wrong.** Blanket invalidation ties on stale evidence and discards the standing source in two families of four, halving sufficiency from 1.000 to 0.500. Registering two primary metrics is what caught it.
- **One family is 100% of the remaining gap.** A withdrawn document re-ingested under its own root is two source roots and two votes; provenance is right about the sources and wrong about the evidence. `_group_by_root` is deliberately not content deduplication, so it cannot see it, and neither can any arm tested. **This is the only actionable finding**, and it is an identity question at ingestion rather than a propagation rule.

Three invalid runs preceded the valid one, all on the record. The first fixture
could not separate the rules (its standing source had a different root, so
blanket invalidation scored the oracle). The second wrote memories in order of
`len(parents)` — not a topological order — so a two-level chain lost its edges.
The third quarantined before the descendants existed. Each time the measurement
failed in a way that read as a result about a mechanism, and the third time it
produced a false negative about shipped behaviour.

### What relevance_v2 changed

**[relevance_v2](research/bench/relevance_v2/README.md)** is the benchmark both
SciFact and R6 said was needed, built for the specific deficiency each had
found: ~495 memories a case against v1's 18, distractors that are the
answer-bearing sentence with **exactly one facet changed**, 4-hop chains with no
direct statement of the asked quantity, and labels that carry evidence
*requirements* rather than only relevance.

The line everything else rests on: a deliberately broken arm returning storage
order scores **0.000**, where on v1 it scored **0.843** and once beat the real
baseline. Headroom is **+0.193 nDCG@5** on dev (corrected from +0.232), and the per-family breakdown
names where: `multi_hop_4` 0.519, `multi_hop_3` 0.600, `independent_support`
0.693, against `direct` and `facet_trap` already at 1.000.

Three results worth separating from the ranking number
([full result](research/results/relevance-v2-ceiling.md)):

- **Sufficiency headroom is larger than ranking headroom** (+0.267 against +0.193) and the two do not move together. Ordering well and assembling enough are not the same question.
- **No arm abstains, ever** — 0.000 abstention precision on the nine dev cases where abstention is the only correct answer. Nothing in the retrieval path can say *the corpus does not answer this*, even when the reachable relevant set is empty and the store knows it.
- **Stale evidence: the store already handles it completely, and an earlier version of this line said grouping cut it by 70%.** Every store-backed arm cites **zero** with every mechanism off, because quarantining contests descendants and contested memories are withheld. The 70% was measured against a store whose own propagation the fixture had prevented from running. The only arm that cites stale evidence is the harness's non-store reference implementation.

And it found three defects in itself plus one in its fixture *before* measuring
anything, including an answer-key leak that would have graded wrong retrievals
as correct answers 185 times. On v1 that class of defect shipped twice and was
caught by a broken arm outscoring a real one.

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
`relevance_v1`'s held-out split too.

The same run with a **trained** embedder settles the other half, which the two
internal splits had disagreed about: `real_vector` 0.701, `real_hybrid`
**0.726** — fusion *gains* 2.5 points when the second arm carries signal, and
`real_hybrid` is **above published BM25**. Same mechanism, opposite sign, so the
rule is **do not fuse a weak arm into a strong one**, and `hybrid` is the
measured recommendation once a trained embedder is configured.

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

1. **R2 was blocked on the benchmark, not on the ranker — and that is now addressed.** Twenty cases could not separate arms differing by 0.05. [relevance_v2](research/bench/relevance_v2/README.md) is 66 cases at ~495 memories each with near-misses one facet from the answer, and it separates them: a no-signal arm scores **0.000** where v1 gave it 0.843. It also says where the headroom is, which v1 could not.
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
6. **Project name**, given the MemOS / MemoryOS collision — **and now a release blocker**: the distribution name `memory-fabric` is taken on PyPI by an unrelated MCP memory project (checked 2026-10-16).
7. **Numeric thresholds** for H1–H5 — the numbers above are proposals and must be pre-registered before P4 starts.
8. **Embedding model.** P1 ships a deterministic, dependency-free hashing embedder so tests are reproducible. A real model is swappable behind the `Embedder` protocol; choosing one is a P2/P3 decision.
