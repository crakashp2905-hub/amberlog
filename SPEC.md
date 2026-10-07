# SPEC.md — Memory Fabric Specification v0

- **Schema version:** `0.2.0` (draft)
- **Status:** proposed, not yet implemented

Words in the glossary in [AGENTS.md](AGENTS.md) are used with those meanings.

---

## 1. Scope of v0

In scope:
- one or more agents in a single process
- episodic, semantic and procedural memory
- provenance and lineage
- an exposure log with propensities
- outcomes
- value estimation
- lifecycle states
- scoped sharing through a firewall policy

Out of scope for v0: networking, P2P, the learned controller, mutation and reproduction, working memory as a stored type (it is transient context only).

---

## 2. Memory object

A memory is **immutable per version**. Changing the content creates a new version; metadata projections (value estimate, counters) are updated separately and derived from events.

```text
Memory
├── id                 str     ULID, stable across versions
├── version            int     starts at 1
├── type               enum    episodic | semantic | procedural
├── content            str     human-readable statement / narrative / steps
├── structured         json?   optional typed payload (e.g. procedure steps, rule tuple)
├── embedding_ref      str?    reference into the vector index (not stored inline)
├── context            json    where it applies: {domain, env, tags...}; used for transferability
├── provenance
│   ├── created_by     agent_id
│   ├── source_episodes [episode_id]
│   ├── parents        [(memory_id, version)]   derivation edges
│   └── method         enum    observed | consolidated | specialized | generalized | imported | manual
├── scope              enum    private | team | federated
├── lifecycle_state    enum    candidate | active | contested | quarantined | deprecated | deleted
├── hypothesis_set     str?    id of the contradiction set it belongs to, if any
├── security_class     enum    public | internal | restricted
├── capabilities       [str]   procedural only: tools a procedure may invoke
├── created_at, superseded_at   timestamps
└── schema_version     str
```

**Projected fields** (recomputed from events; never written directly):

```text
MemoryStats
├── value_estimate     {mean, ci_low, ci_high, n_eff, estimator, updated_at}
├── value_by_context   {context_key: value_estimate}     (sparse)
├── exposures          int
├── validations        {passed, failed}
└── last_exposed_at
```

**Compared with the source document:** `utility`, `causal_value` and `reliability` are merged into one value estimate (see CRITICAL_REVIEW §3). `transferability` is `value_by_context` evaluated off the origin context. `age` and `obsolescence` are derived from timestamps and drift in value. `staging` is `scope` + `lifecycle_state`, not a separate field.

---

## 3. Lifecycle

```text
                 validate ok                     conflict detected
 candidate ──────────────────► active ──────────────────────────► contested
     │                          │  ▲                                  │
     │ firewall deny            │  │ resolved in favour              │ resolved against
     ▼                          │  └──────────────────────────────────┤
 quarantined ◄──────────────────┘ harmful evidence / poisoning       ▼
     │                                                           deprecated
     │ review / rollback                                             │
     └──────────────────────────► deprecated ──────► deleted (retention policy)
```

Rules:
- Only `active` memories may be exposed by default. `contested` memories may be exposed only under the exploration policy, with their hypothesis-set siblings flagged.
- `quarantined` memories are never exposed. The **retraction** of a memory (moving it to quarantined or deprecated) marks every memory derived from it as `contested` (TMS-style propagation through `parents`).
- `deleted` removes content; the event record of its existence remains for lineage.
- **Scope promotion** (private → team → federated) requires `active` state, a value-estimate lower bound > 0, and a firewall `ALLOW`.

---

## 4. Event log (source of truth)

Append-only. Every event has `event_id` (ULID), `ts`, `agent_id`, `episode_id?`, `schema_version`.

| Event | Key fields | Why it exists |
|---|---|---|
| `EpisodeStarted` | task_id, context, seed | Unit of outcome attribution |
| `MemoryCreated` | memory (full record) | Birth + provenance |
| `MemoryVersioned` | memory_id, new_version, parents, reason | Versioning |
| `RetrievalPerformed` | query, candidates [(memory_id, version, score)] | What was available |
| `ExposureDecided` | memory_id, version, exposed: bool, **propensity**, policy_id, step | **Required for causal credit** |
| `MemoryCited` | memory_id, step | Optional: the agent says it used the memory (weak signal) |
| `OutcomeRecorded` | episode_id, outcome: float, verifier_id | Verified by the environment or an evaluator, never by the agent |
| `ValueEstimated` | memory_id, context_key, estimate, estimator_id | Projection checkpoint |
| `LifecycleChanged` | memory_id, from, to, reason, actor | Audit |
| `ScopeChanged` | memory_id, from, to, firewall_decision | Federation audit |
| `ConflictDetected` | memory_ids, detector_id, confidence, hypothesis_set | Contradiction tracking |
| `ExperimentRun` | hypothesis_set, design, results | Disagreement resolution |
| `MemoryDuplicateSuppressed` | memory_id, content_digest | An agent wrote the same content twice in one episode |

**Exposure invariant:** for every candidate returned by retrieval, exactly one `ExposureDecided` event is logged, including those *not* exposed. Its propensity must be in (0, 1] for exposed memories, and the probability of *not* exposing must be recorded for withheld ones. A policy that is deterministic in some cells must declare it; estimators treat those cells as having no overlap.

---

## 5. Value estimation interface

```python
class ValueEstimator(Protocol):
    id: str
    def update(self, events: Iterable[Event]) -> None: ...
    def estimate(self, memory_id: str, context: Context | None = None) -> ValueEstimate: ...

@dataclass(frozen=True)
class ValueEstimate:
    mean: float
    ci_low: float
    ci_high: float
    n_eff: float
    estimator: str
```

Reference estimators (v0):

| id | Method | Role |
|---|---|---|
| `naive_usage` | Laplace-smoothed success rate when exposed | **Baseline to beat** |
| `ips` | Inverse-propensity-weighted difference exposed vs withheld | Unbiased, high variance |
| `dr` | Doubly robust (outcome model + IPS correction) | Primary online estimator |
| `paired_replay` | Same task and seed, with vs without the memory | Gold standard, expensive |
| `amortized` | V̂(features(m), context) regression, with shrinkage of per-memory estimates toward it | Handles the sample-size problem |

---

## 6. API v0 (Python SDK)

```python
fabric = MemoryFabric(store=..., estimator="dr", exposure_policy="eps_greedy", seed=0)

ep  = fabric.start_episode(agent_id, task_id, context)
mid = fabric.remember(agent_id, content, type="semantic", context=..., source_episodes=[ep.id])
ctx = fabric.retrieve(agent_id, query, context, k=5)      # logs retrieval + exposure decisions
                                                            # returns only exposed memories
fabric.record_outcome(ep.id, outcome=1.0, verifier_id="env")   # verified outcomes only
fabric.end_episode(ep.id)

fabric.value(mid, context=None)       # -> ValueEstimate
fabric.lineage(mid)                   # ancestors, descendants, source episodes
fabric.explain(mid)                   # "why does the system remember this?" trace
fabric.challenge(mid, evidence=...)   # opens / updates a hypothesis set
fabric.quarantine(mid, reason)        # propagates contested state to descendants
fabric.share(mid, scope="team")       # runs firewall; may be denied
fabric.forget(mid, reason)            # deprecate; deletion by retention policy
```

v0 deliberately **omits** `mutate`, `experiment` (manual only in v0), `query_agent` and the directory APIs; they come in later milestones (ROADMAP.md).

---

## 7. Firewall policy (v0, rule-based)

Input: memory, target scope, value estimate, lifecycle state, security class, hypothesis set, and capabilities (for procedural memories).
Output: `ALLOW | ALLOW_WITH_WARNING | REQUIRE_VALIDATION | QUARANTINE | DENY`, plus reasons.

Default rules:
1. `security_class = restricted` → DENY beyond private.
2. `lifecycle_state ≠ active` → DENY.
3. `value.ci_low ≤ 0` → REQUIRE_VALIDATION.
4. Member of an open hypothesis set → ALLOW_WITH_WARNING (the siblings travel with it).
5. Procedural memory with capabilities not granted to the target → DENY.
6. Sensitive-data detector positive → QUARANTINE.

---

### 0.2.0 — duplicate suppression

`remember` returns the existing memory, and emits `MemoryDuplicateSuppressed`, when an agent writes content it has already written **in the same episode** (compared after normalising whitespace and case).

Found by running real agents: a model called the `remember` tool four times in one run, producing two distinct memories and two exact duplicates. Duplicates inflate apparent consensus the same way several agents repeating one source do (SECURITY.md T3) — but from a *single* agent, which the evidence-independence check does not examine.

Scoped to one episode deliberately. The same claim recorded in two different episodes is two observations, and that genuinely is more evidence.

Additive: no migration needed. Older logs replay unchanged, and the suppression only affects new writes.

## 8. Versioning of this spec

Semver on `schema_version`. A minor bump means additive fields; a major bump needs a migration script and a changelog entry here.
