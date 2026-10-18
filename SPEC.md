# SPEC.md — Memory Fabric Specification v0

- **Schema version:** `0.12.0`
- **Status:** implemented. Where this document and `memory_fabric/` disagree,
  the code is authoritative and the disagreement is a bug in this file.

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

### 0.12.0 — the background memory manager

Additive: two event types, no projection change. A 0.11.0 log replays
unchanged, and a 0.11.0 reader skips both events.

- **`ManagerLease`**, payload `{holder, expires_ms}`. Taken and renewed inside
  a write transaction, so at most one manager maintains a store at a time.
- **`MaintenanceRan`**, payload `{since_seq, until_seq, tasks}`. One cycle:
  for each task, what it did or the error. The tasks are dispatch, retention,
  audit, conflicts, checkpoint and health. Ids and counts only, never
  content.

Behaviour: `serve`, `agent-api` and `mcp` start the manager unless
`--no-maintain` is given. `memory-fabric maintain` runs it on its own.
Retention deletions are applied only with `--retention-delete`.

### 0.11.0 — the action fence, exposure records and the provenance chain

Additive: one event type and three projection fields. A 0.10.0 log replays
unchanged. A 0.10.0 reader skips the new event, as it skips any type it does
not model, so it does not know which actions ran under the fence.

**`ActionExecuted`**, payload `{key, tool, outcome, fenced, watermark,
lease_ms, elapsed_ms, evidence: [[memory_id, version]], tenant_id}`. Emitted
by `ActionGate.execute`, inside the same write transaction as the
verification it follows (S6). `outcome` is `executed` / `failed` /
`timed_out`, and `fenced: false` marks a run whose lease expired. `key` is the
caller's idempotency key. Ids only, never content.

Projection, with no new event behind it:

- an exposure record carries `agent_id` and the log `seq` it came from;
- `created_seq[memory_id]` is the sequence of a memory's `MemoryCreated`;
- `independence.py` (S2) reads all three.

An import's `context.federation` gains three fields:

- `chain`: every store the memory passed through, oldest first. An offer into
  a store on the chain is refused (F12);
- `root`: the original's `{store, memory_id}`;
- `informed_by`: the originals its author had been shown before writing it.

Imports recorded earlier have none of the three. Their immediate origin is
used instead, which is all that can be recovered for them.

### 0.10.0 — collections, and scope enforced on reads

Additive: one event type and one projection field. A 0.9.0 log replays
unchanged; a 0.9.0 reader skips the new event, as it skips any type it does not
model, and so does not know who a collection admits.

**`CollectionChanged`**, payload `{tenant_id, collection, action, agent_id?,
memory_id?, permissions?}`, `agent_id` on the event is the actor. `action` is
`add` / `remove` (a memory) or `grant` / `revoke` (an agent's permissions:
`read`, `write`, `approve`, `retract`; a revoke naming none removes all).
Projected into `collections[(tenant, name)] = {members, grants}`.

**Behaviour, not schema: scope is enforced on reads.** A `private` memory is
readable by the agent that wrote it and by agents holding `read` on a
collection that contains it; `team` and `federated` by every agent in the
tenant. Before 0.10.0 retrieval checked only lifecycle and tenant. Restricted
memories cannot be written wider than private or join a collection. The
firewall's value rule applies to promotion to `federated` only.

### 0.9.0 — action gating

Additive: one event type, no projection change. A pre-0.9.0 log replays
unchanged; a 0.8.0 reader skips the new event, as it skips any type it does
not model.

**`ActionGated`**, payload `{tool, allowed, reason_codes, policy_id, claim_id,
certificate_digest, evidence: [[memory_id, version]], watermark}`. Emitted by
`actions.ActionGate` for every decision about a protected tool. Ids, versions
and a digest only, never content. It is the first record linking a memory to
an action, which incident reconstruction needs.

Evidence certificates (`certificates.py`) are not stored in the log. They are
a versioned JSON document with `certificate_version` 1. A verifier refuses any
other version, any unknown field and any check it cannot run.

`derive` takes an optional `security_class` and writes the strictest of it,
`internal` and every premise's class, so a conclusion is never less restricted
than what it rests on. `MemoryFabric(conceal_cross_tenant=True)` makes a
cross-tenant refusal identical to a missing id. Mental models
(`mental_models.py`) are derived memories with the context keys
`mental_model` and `model_watermark`. No event type is added for them.

The ingest screen now reads the strings in `context` and `structured` as well
as `content`, and `revise` runs the same screen as `remember`. A memory that
passed before may now be quarantined on write. This is a behaviour change, not
a format change: logs written before still replay to the same state.

### 0.8.0 — copy recognition

Additive: one event type and two projection maps. A pre-0.8.0 log replays
unchanged and yields an empty copy relation, which is exactly the old
behaviour, so no migration script is needed.

**`MemoryCopyRecognised`** — payload `{memory_id, original_memory_id,
containment}`. Emitted when a write is recognised as a re-ingestion of content
already held. The memory is still stored: refusing the write would lose the
fact that someone re-ingested the document, and the log is the source of truth
about what happened. What the copy does not get is an independent source root.

Projection state gains `copy_of: dict[str, str]` and its reverse index
`copies: dict[str, set[str]]`.

Three behaviours follow, and all three are measured in
[p2b-copy-recognition.md](research/results/p2b-copy-recognition.md):

* `source_root()` resolves through copy edges, alternating with the lineage walk, so a conclusion derived from a copy also resolves to the original's root.
* `remember()` admits a re-ingestion of a **withdrawn** document as `contested` rather than `active`. Not `quarantined`: nobody has made a finding about this write, and the original's withdrawal may itself have been wrong.
* `quarantine(propagate=True)` walks the copy relation as an **undirected** component. The recorded edge runs newer → older, and "these are the same document" has no direction, so a one-way walk missed a copy stored before its original.

A copy is deliberately **not** a parent edge. `_group_by_root` spares a memory
that is derivation-related to something already kept — a premise and its
conclusion are not copies — so a copy recorded as a child would be exempted
from the grouping that exists to collapse it.

`derive()` additionally recomputes the support of what it just wrote, so a
conclusion drawn from an already-withdrawn premise arrives `contested` instead
of `active`. No new rule: it is the recomputation `quarantine` already runs,
applied at write time, because retraction previously reached conclusions drawn
*before* a withdrawal and not after.

### 0.7.0 — bitemporal validity

`Memory` gains `valid_from` and `valid_to`, both nullable. Additive: absent
means open-ended, so every memory in a pre-0.7.0 log applies at every time,
which is exactly how it behaved. No migration.

**Why one timestamp was not enough.** `created_at` is when this store *learned*
a claim. It cannot also say when the claim is *true of the world*, and
`relevance_v1`'s `temporal_drift` family is where conflating them costs: the
same corpus gives the opposite answer depending on whether the task asks "what
is the closing time now?" or "what did we believe it was last year?" A
retriever with only a recorded time cannot tell a fact that *was* true from one
that is.

`Memory.applies_at(when)` is half-open — `valid_from <= when < valid_to` —
because a closed upper bound makes two consecutive claims both apply at the
instant one replaces the other, and "both answers are current" is the one thing
a temporal filter must not say.

`retrieve(as_of=…)` filters the eligible set *before the index is queried*, for
the reason the tenant filter does: a memory excluded before ranking cannot be
ranked, scored, logged or leaked by a bug in a policy. It has **no default**,
and cannot have one — defaulting to `now` would make every historical question
unanswerable.

### 0.6.0 — authenticated content encryption

The `Memory.content` field's *stored* form changes. The memory schema itself is
untouched, but the bytes in the log are a different envelope, so this is a
version bump with a compatibility note rather than a silent fix.

**What was wrong.** `enc:v1` was an HMAC-SHA256 counter-mode keystream with no
authentication tag, which makes a ciphertext malleable: XOR a chosen delta into
it and the plaintext becomes whatever the attacker picked. The code justified
this by saying "the append-only log and the event digests provide [integrity]"
— and **there are no event digests.** The log carries `seq`, `event_id`, `ts`,
`type`, `agent_id`, `episode_id`, `schema_version` and `payload`, with nothing
chaining or signing them. The append-only triggers raise the bar (a tamper
needs file write access to drop them first, which `doctor` reports) but they do
not sign anything.

**What replaces it.** Three envelope generations, all readable at once:

| envelope | suite | status |
|---|---|---|
| `enc:v1:` | HMAC-CTR, unauthenticated | **read-only**, never written again |
| `enc:v2:` | HMAC-CTR + HMAC-SHA256 encrypt-then-MAC | zero-dependency default |
| `enc:v3:` | AES-256-GCM via `cryptography` | automatic when installed |

`v2` is a textbook composition of standard primitives — independent encryption
and MAC subkeys via HKDF-Expand, encrypt-then-MAC in that order, constant-time
tag comparison *before* decrypting — not a new cipher. `v3` exists because "use
a maintained cryptographic library" is the right default advice and this module
should not be the reason someone cannot follow it; installing `cryptography`
switches new writes with no configuration and no migration.

**Associated data.** A tag proves the bytes were not edited. It does not prove
they belong here. The AAD binds `store_id`, `memory_id` and `version`, so
sealed content cannot be copied between memories or between stores, and an old
version's ciphertext cannot be pasted over the current one to roll a memory
back after a correction — which would defeat the retraction machinery by
editing one column.

**Key custody is now a deployment choice.** `KeyProvider` has three
implementations: `SqliteKeyProvider` (the default, keys beside the ciphertext),
`DirectoryKeyProvider` (keys in a directory with its own permissions, so a
stolen `.db` is not enough), and `CallbackKeyProvider` (a KMS). A provider that
cannot destroy declares `supports_destroy = False` and the erasure record says
the key outlived the erasure, because a store reporting an erasure it could not
perform is worse than one that cannot erase. The erasure *record* is
authoritative over the provider, so a restored key directory cannot resurrect
content behind an audit row saying it is gone.

**Migration.** None required, and none offered. `v1` stays readable; revising a
memory re-seals it under the current suite; `doctor` counts what remains. There
is deliberately no bulk re-encryption, because rewriting the log is the one
thing this design forbids.

**Forward compatibility is one-way.** A 0.6.0 store opened by 0.5.0 code would
not recognise `enc:v2:`/`enc:v3:` as sealed and would hand the envelope back as
content. Older *stores* open fine on newer code; older *code* must not be
pointed at a newer store.

### 0.5.0 — tenant identity

`Memory` gains `tenant_id`, defaulting to `tn_default`. Additive: a store
written before this replays into the default tenant with no migration and
identical behaviour, which is why the default is a real id rather than `None` —
a nullable boundary is one every comparison has to remember to handle, and the
first place that forgot would be a cross-tenant read.

Enforced at two points, both chosen because they are chokepoints rather than
conveniences:

- `_eligible_ids` filters by tenant **before the index is queried**, so an excluded memory cannot be ranked, scored, logged in a `RetrievalPerformed` event or leaked by a bug in a policy.
- `Enforcer.check` refuses a cross-tenant request **before resolving the lifecycle**, and reports only `wrong_tenant` with version 0 and no detail. "Withdrawn on weak evidence" is a true and useful reason code and also a statement that the memory exists and what was done to it, which a caller from another tenant may not learn.

`ExposureToken` carries the tenant, so the time-of-use re-check is scoped the
same way the time-of-check was. `derive` inherits its parents' tenant and
refuses premises from two different ones; defaulting to the store's default
instead was the first version and was an isolation hole, found by the test for
the ordinary within-tenant case rather than by the test for the attack.

`offer` takes the recipient's tenant explicitly. A tenant id is local to a
store: nothing makes `tn_acme` at one store the same customer as `tn_acme` at
another, and letting a matching string decide would turn a naming coincidence
into a cross-customer disclosure.

Agent identity is **not** part of the schema. `identity.PrincipalRegistry` and
`Credential` live beside the store rather than in the log, because identity can
only be enforced at a boundary and a caller holding the fabric is inside it.
SECURITY.md states the limits; `fabric.as_principal` is the enforcing handle.

### 0.4.0 — the share record, and a per-hop retraction target

Two additive changes to the event schema, plus one storage migration.

**`MemoryShared`.** A sender now records that a memory left for a named
recipient store, and what that store called its copy:

```
{"memory_id", "version", "recipient_store_id", "imported_memory_id"}
```

Not derivable after the fact. The recipient's copy is a new memory in the
recipient's log with its own id, and until this event existed nothing in the
sender's log mentioned it. Retraction therefore stopped at one hop: an origin
could address the stores it had shared with, and no store anywhere could answer
"who did I pass this on to?". `offer` emits it on every accepted offer — and
only on an accepted one, or a refusal would create a permanent delivery
obligation to a store that never held anything.

**A retraction carries a per-hop target.** `Retraction` gains
`target_store_id`, `target_memory_id`, `target_memory_version`, `hop` and
`forwarded_by`, all optional and all defaulting to the origin fields. Hop 0 is
byte-identical to 0.3.0 on the wire, and a 0.3.0 peer that ignores the new
fields behaves correctly because every retraction it can receive is hop 0.

`retraction_id` + `origin_store_id` identify the **campaign** and never change
along a chain; the target is what each hop can actually find, because a store
two hops out imported from the store one hop out and not from the origin.

**Migration (storage, not the log).** The `inbox` and `outbox` tables gain
`target_key`, which enters both primary keys. SQLite cannot widen a primary key
in place, so `Outbox.__init__` rebuilds each table once and carries existing
rows with `target_key = ''`. That value is correct and not merely convenient:
every row written under 0.3.0 was a hop-0 retraction whose target *was* the
origin, so a re-delivery of one computes the same empty key and still
deduplicates. The event log itself is untouched, so the projections rebuild
from it unchanged.

Widening that key was a correctness fix rather than a convenience. Keyed on the
campaign alone, a store reached by two paths recorded the first arrival's
outcome for both, so the second — a real retraction of a real second copy — was
answered "already handled" and the copy stayed live. `diamond_both_copies` in
the fault matrix fails in exactly that way when the key is narrowed back.

### 0.3.0 — withdrawal basis, store identity, retraction protocol

Recorded here after the fact; it shipped across roadmap phases 0–7 without a
changelog entry, which this file should not have allowed.

- `LifecycleChanged` carries a `basis` (`WithdrawalBasis`, 7 values), so a withdrawal records *why*. `CO_OCCURRENCE` and `UNSTATED` are marked weak, and the observability attention list reports a withdrawal made on a weak basis as the finding.
- `StoreIdentified` gives each store an opaque `store_id`, replacing the database path as federation identity. The path made two containers each holding `./store.db` indistinguishable, broke every provenance match when a database moved, and gave every in-memory store the identity `:memory:`.
- A federation origin record carries the exact `version` imported, so a retraction of v1 cannot withdraw an import of v3.
- New event types: `RetractionRequested`, `RetractionApplied`, `RetractionRejected`, `PropagationStateChanged`, `AccessDenied`, `SupportRecomputed`, `ContentErased`.
- Memory content may be sealed per memory (`encrypt_content`), with keys outside the log, so destroying a key erases content while the provenance, lineage, retraction basis and audit trail survive.

Additive throughout: a 0.2.0 log replays unchanged.

### 0.2.0 — duplicate suppression

`remember` returns the existing memory, and emits `MemoryDuplicateSuppressed`, when an agent writes content it has already written **in the same episode** (compared after normalising whitespace and case).

Found by running real agents: a model called the `remember` tool four times in one run, producing two distinct memories and two exact duplicates. Duplicates inflate apparent consensus the same way several agents repeating one source do (SECURITY.md T3) — but from a *single* agent, which the evidence-independence check does not examine.

Scoped to one episode deliberately. The same claim recorded in two different episodes is two observations, and that genuinely is more evidence.

Additive: no migration needed. Older logs replay unchanged, and the suppression only affects new writes.

## 8. Versioning of this spec

Semver on `schema_version`. A minor bump means additive fields; a major bump needs a migration script and a changelog entry here.
