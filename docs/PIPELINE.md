# Memory Fabric end to end

For someone who has just arrived. What happens to a memory from the moment it
is written to the moment its content is destroyed, what the system is measured
to do, what it is measured **not** to do, and what we are still trying to
establish.

Every number here cites a run. Where something is unmeasured, it says so.

---

## 0. What this is, in one paragraph

Memory Fabric is a **governed store for agent memory**. Agents write what they
learn, retrieve it later, and act on it. What distinguishes it from a vector
database is not retrieval quality — measured, it is **at or below** a plain
lexical baseline — but that every memory carries where it came from, every
decision to show or withhold one is recorded with the probability it was made
with, contradictions are kept rather than overwritten, a correction reaches
everywhere a memory travelled, and content can be destroyed while the
accountability survives.

It is **not** "memory that makes agents smarter". That claim was
pre-registered, measured against real models at five seeds, and **failed** —
see §8.

---

## 1. Write

```python
mid = fabric.remember(agent_id="engineer-coastal",
                      content="Fault E03 at the coastal site: swap the pilot cable.",
                      context={"site": "coastal", "fault": "E03"})
```

In order:

1. **Sensitive-data scan.** `governance/sensitive.py` runs over the content. A high-severity hit (credential, key, card, national ID) lands the memory in `quarantined` rather than refusing the write, so the fact of the attempt is on the record. 26 detector classes, measured against a corpus.
2. **Duplicate suppression.** The same content from the same agent *in the same episode* returns the existing memory and emits `DuplicateSuppressed`. Scoped to one episode deliberately: the same claim on two separate occasions is two observations, and that genuinely is more evidence.
3. **Copy recognition.** A re-ingested document that is a *subset* of an existing one is linked rather than counted again, so a withdrawn source re-added under a new id does not become independent support. Subset containment with a length guard — **not** Jaccard, which measured a copy at 0.722 against a worst near-miss of 0.800 across 152,640 pairs, i.e. unusable.
4. **Encryption.** Content is sealed per memory under authenticated encryption, with keys optionally held outside the database.
5. **Provenance.** `source_episodes`, `parents`, `method` and the creating agent are recorded. A memory with no provenance cannot exist — that is principle 2.
6. **Append.** A `MemoryCreated` event goes onto the hash-chained log. **The log is the source of truth**; everything else in this document is a projection that can be deleted and rebuilt from it.

The memory starts as `candidate`. Someone or something has to promote it.

## 2. Admit

Lifecycle: `candidate → active → contested → quarantined → deprecated →
deleted`. Scope (`private / team / federated`) is independent of it.

`validate()` promotes a candidate to active. Until then it is held but not
served. This is the firewall point for federation: **an unvalidated memory is
never shared** (principle 7).

## 3. Retrieve

```python
result = fabric.retrieve(agent_id="engineer-field", query=..., k=5,
                          context={...}, as_of=...)
```

Order matters, and the first two steps matter most:

1. **Eligibility.** Lifecycle state, tenant and granted capabilities filter the candidate set **before the index is queried**. A memory excluded before ranking cannot be ranked, scored, logged or leaked by a bug in a policy. That ordering is the enforcement guarantee, not a performance choice.
2. **Temporal applicability.** `valid_from`/`valid_to` are half-open, and `as_of` / `until` narrow the eligible set — again before ranking. This is why relevance can reverse when the world changes without any memory being edited.
3. **Search.** Lexical (length-normalised IDF), vector, or both fused with reciprocal rank fusion. One standing rule, with six confirmations: **do not fuse a weak arm into a strong one.**
4. **Optional mechanisms**, each off by default and each measured separately: reranking, lineage expansion, admission of scoped defaults and adjustments, relation following, grouping by source root.
5. **Value estimation** — only if the ranking policy will actually use it. Refitting an estimator and then ranking by relevance is pure waste that grows with the log.
6. **Exposure decision.** The policy picks `k`, and each choice is logged with **the probability it was made with** (`ExposureDecided`). Without that propensity, causal credit cannot be estimated later at all — principle 4.

## 4. Render

```python
prompt_block = build_context(fabric, result.exposed, query).render()
```

Three things, deliberately:

- an **injection preamble** — a retrieved memory is text an earlier run wrote, and a poisoned one is a prompt-injection payload aimed at every later run (SECURITY.md T1), so memories are framed as evidence, never instructions;
- **delimiters** around the block;
- **per-memory annotations** — `[id | type | evidence | lifecycle | contradicts …]`, where evidence reads like *"used 3x, effect unmeasured"* or *"helped (+0.21, n=4)"*. A contested claim must not appear in the same voice as a well-evidenced one.

Whether this rendering costs task accuracy is **being measured now** (X5, §9).

## 5. Act and record

The agent acts. The **environment** verifies the outcome — never the agent
itself, which is what "outcome" means in this project's glossary.

```python
fabric.record_outcome(episode_id, outcome=1.0, verifier_id="depotworld")
```

Estimators then consume the new events and update value estimates, each a
posterior with a mean, a credible interval and an effective sample size.
**Credit is a distribution, not a number** — principle 5.

## 6. Correct

This is the part the measurements support best, and it has two shapes.

**Conflict.** `challenge()` turns two memories that disagree into a hypothesis
set where both keep posteriors. Nothing silently overwrites a conflicting
memory — principle 6.

**Retraction.** `request_retraction()` from the origin reaches the stores a
memory travelled to, including ones the origin never heard of. Descendants
become **contested** rather than vanishing, because a recipient may have built
on the memory and its conclusions need to become open questions rather than
disappear. It matches on provenance method as well as origin, because a memory
derived locally from an import inherits the parent's origin record and once
looked like a second copy of it.

The asymmetry is worth stating plainly, because it is the clearest pattern in
all the measurements: **acting on an authoritative correction works; inferring
that a memory is bad from outcomes does not** (§7 and §8).

## 7. Erase and prove

**Erasure.** `erase_content()` destroys the per-memory key. The text goes; the
provenance, lineage, retraction basis and audit trail stay. `erasure_scope()`
reports reached / kept / **unreachable**, and reports the third as *unknown*
rather than guessing — an old backup cannot be reached and saying otherwise
would be a lie.

**Proof.** Every event is in a hash chain: an edit breaks every later link and
verification names where. A wholesale rewrite is caught by an external
checkpoint. `audit_trail()`, `explain()`, `lineage()` and `history()` answer
"why do you believe this?", and `rebuild()` regenerates every projection from
the log.

**Operationally**: `memory-fabric overview | attention | audit | doctor |
backup | serve`. `doctor` exits non-zero when the installation's answers cannot
be believed. `backup` takes a consistent snapshot and then **replays the copy**,
failing if the event count does not match — because a truncated backup opens
perfectly well.

---

## 8. What it can do, measured

| Capability | Measured |
|---|---|
| A retraction follows a memory into other stores and drives acting-on-withdrawn-knowledge to zero | **17% → 0%** under both sharing policies, 240 decisions per arm ([PB2](../research/results/phase-b-federated-agents.md)) |
| Contradiction is preserved rather than collapsed | P(correct) **0.905 → 1.000**, recovery from a wrong belief **24% → 100%**, at *lower* cost ([H4b](../research/SCORECARD.md)) |
| A premise can be invalidated without destroying independently justified conclusions | Lose one of two independent premises and the conclusion stays active; lose both and it is contested, never deleted |
| A re-ingested copy does not become independent support | Product matches the oracle on both splits ([P2b](../research/results/p2b-copy-recognition.md)) |
| Causal value of a memory is estimable | ρ **0.76** against a naive 0.47, 8% overhead ([H1](../research/SCORECARD.md)) |
| A team does better than with an ordinary shared store | **86%** of measured headroom, holding to **100 agents** ([P3b](../research/results/p3b-agent-teams.md)) |
| It holds up operationally | Every concurrency, scale and failure condition passes ([P4](../research/results/p4-envelope.md)) |
| Content erased while accountability survives | Crypto-erasure, keys optionally outside the database |
| The log is tamper-**evident**, not merely append-only | Hash chain plus external checkpoints |
| All of it costs almost nothing | **0.2 ms** per episode, **1.16×** tokens against an ungoverned vector store |

## 9. What it cannot do, measured

This list is as load-bearing as the one above, and most of it was learned the
expensive way.

- **It does not retrieve better than plain lexical search.** On an external corpus the shipped hashing embedder scored **0.315 against lexical's 0.621**. Retrieval quality is not the product.
- **It cannot decide what to forget from outcome evidence.** Five results, all losses: credit-driven retention killed; governed memory **0.283 against a pooled vector store's 0.583**; genuine leave-one-out attribution **0.483 against withdrawing nothing at 0.608**; selective sharing killed. The product now *warns against* quarantine-on-failure in the CLI, because blaming what was in context destroys more correct memory than wrong.
- **It cannot reliably say "I don't know."** Four signal families eliminated; the fifth is real but unshippable at **best F1 0.206**. A typed decision model with calibrated probabilities was tried and lost to a one-line lexical score (**AUC 0.629 against 0.711**), and recalibration provably cannot fix that — a monotone rescaling cannot change a threshold-free metric ([X2b](../research/results/x2b-recalibration.md)).
- **It cannot reach a rule that names neither the thing nor the place asked about**, except through an explicit admission rule. Extraction at ingest scored **0.000** against a bar of 0.400 ([X1](../research/results/x1-extraction.md)); a scoped-adjustment admission rule then took the same family **0.000 → 1.000 on dev and 0.000 on test** ([X3](../research/results/x3-scoped-adjustments.md)).
- **It does not accept concurrent writers.** SQLite with WAL: concurrent readers are fine, concurrent writers are not supported and not tested.
- **Its HTTP surface has one shared token and no user model.** The library *does* have identity — signed, expiring per-agent credentials — but the two have not been joined up. Put it behind something with a user model.
- **The database is not encrypted, only the content**, and erasure cannot reach an older backup.
- **The value estimators are not validated for live exposure decisions.** Estimating value works; acting on the estimate is the part that keeps losing.

## 10. What we are trying to make sure it does

Three things, in order of how much they matter.

**That the claims match the measurements, permanently.** This is the actual
discipline of the project and it is enforced in [AGENTS.md](../AGENTS.md)
principles 8 and 8a–8d, every one of which exists because a specific published
number here was wrong: a threshold larger than its own ceiling; an oracle
bounded by its retrieval budget; a metric a baseline already maxed; and a
baseline quoted at the wrong metric and budget. `experiments/checks.py` now
runs those checks on **every** experiment, because the faults are invisible on
inspection — one of them was an AUC published as its own complement (0.319 for
a signal whose value is 0.682) while three other figures in the same document
reproduced exactly.

The newest addition is **power**: nothing in 8a–8d stopped a threshold sitting
*below the noise floor*. One experiment spent 1.72 hours of inference on arm
differences an order of magnitude below its own resolution. Experiments now
pre-register a minimum detectable effect.

**That the governed configuration is worth having.** Still open, and honestly
so. The losses in §9 all used withdrawal-on-failure, which the product no
longer recommends; whether the *recommended* configuration beats a pooled store
has not been established. The attempt ([X4](../research/results/x4-governed-vs-pooled.md))
was **abandoned** under its own clause because the test world turned out to
have almost no headroom — perfect memory selection there is worth at most **5
points** over cosine similarity. That is a statement about the venue, not an
answer, and finding a world where selection matters is the open work.

**That it is honestly shippable for one writer.** The gaps in §9 are known
engineering with clear acceptance criteria, not open questions: Postgres behind
the existing storage seam, joining the identity registry to the HTTP surface,
database-level encryption, backup-aware erasure. The two unstarted roadmap
gates are developer experience and release qualification.

---

## 11. Where to go next

- [README.md](../README.md) — the guarantees, with evidence links
- [AGENTS.md](../AGENTS.md) — the constitution; read principles 8a–8d before designing an experiment
- [SPEC.md](../SPEC.md) — the memory record and schema versioning
- [docs/INVARIANTS.md](INVARIANTS.md) — the 14 integrity invariants and the fault matrix
- [DEPLOYMENT.md](../DEPLOYMENT.md) — capacity, operations, and §6's plain list of what this is not ready for
- [research/SCORECARD.md](../research/SCORECARD.md) — every hypothesis and its verdict, including the killed ones
