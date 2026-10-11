# RELEVANCE_SPEC.md — the relevance contract

- **Contract version:** `1.0.0` (`memory_fabric.relevance.CONTRACT_VERSION`)
- **Status:** schemas and invariants implemented and tested. **No ranker exists**, deliberately — see §2.
- **Implements:** P0 of the end-to-end plan. The gate is §4, and every row maps to a test in `tests/test_relevance_contract.py`.

Words in the glossary in [AGENTS.md](../AGENTS.md) keep their meanings. This
document adds one axis to them and is careful not to disturb the others.

---

## 1. Why relevance is its own axis

The store already answers four questions about a memory:

| Question | Answered by |
|---|---|
| Is it **valid**? | lifecycle state, justification graph, contradiction set |
| May this agent **access** it? | scope, capabilities, tenant, `Enforcer` |
| Is it **current**? | version, supersession, retraction state |
| Has exposing it ever **helped**? | `ValueEstimate` (contrastive, with an interval) |

None of those is relevance. A memory can be relevant and false; true,
authorised and useless for the task in hand; irrelevant this hour and the only
thing that matters the next.

> **Irrelevant means "do not put this in this context". It never means
> "delete", "quarantine", "retract", or "stop trusting".**

That is not a style preference, it is a measured one. Phase A's withdrawal
policy took task success from **0.608 to 0.483** by removing memories that had
merely been present when an episode failed, and of naive blame's 87
withdrawals **57 were about a completely different fault**
([PA′](../research/results/phase-a-prime-attribution.md)). A relevance signal
with lifecycle authority would be that mistake with a new name, so the types in
`memory_fabric/relevance.py` have no route to one and a test asserts it
structurally.

## 2. Why there is no ranker in this contract

Both planning documents say to build the benchmark before the ranker, and the
project's own record says why: of the four simulated hypotheses, **three were
mis-operationalised, and in every case the fault was in the measurement rather
than the mechanism**. A ranker written before the thing that could falsify it
gets tuned on whichever examples flatter it.

So P0 ships the contract and its invariants. P1 ships the benchmark, the
baselines and the **oracle ceiling**. Only then does a ranker get written, and
it gets written against a held-out split that was frozen first.

### What the existing measurements predict

Stated here rather than discovered later. Across Phase A and PA′, success
tracked a single quantity — whether a correct memory reached the prompt.
Conversion given one was **93–98% in every arm**, and coverage-to-success
correlated at **ρ = +0.975**. Perfect *selection* over the existing corpus was
worth about **+5 points**; the rest of the gap was corpus **coverage**, which
is memory construction and not retrieval.

So on that world a perfect relevance engine had a ~5-point ceiling. That is not
an argument against this work — it is the reason the oracle arm is mandatory
([AGENTS.md](../AGENTS.md) principles 8a and 8b) and the reason the benchmark
comes first. If the new benchmark's oracle ceiling is also ~5 points, the
honest conclusion is that relevance ranking is not where the headroom is, and
an oracle is a far cheaper way to learn that than a tuned ranker.

## 3. The types

All in `memory_fabric/relevance.py`. The module imports nothing from
`fabric.py` and names no `LifecycleState`, which a test enforces.

| Type | Holds |
|---|---|
| `ContextSnapshot` | the task, goal, constraints, agent, tenant, `event_time`, observed `state_facts`, model-`inferred` fields, entities, token budget, policy version, and its own `context_id` |
| `RelevanceLabel` | `relevant` / `irrelevant` / `uncertain` |
| `RelevanceEvidence` | one signal's contribution and a human-checkable explanation; the contribution may be `MISSING` |
| `RelevanceAssessment` | a label for an exact `(memory_id, memory_version, context_id)`, with evidence and the model/feature versions behind it |
| `ReasonCode` | a closed set of inclusion and omission reasons, with hard gates marked |
| `SelectionDecision` | whether one memory entered the context and why, recorded for inclusions **and** omissions |
| `ContextPackage` | the assembled context, its omissions, unresolved conflicts, missing evidence, token count, and the `integrity_revision` it was built against |

### Scores are not probabilities

`score` is an ordering signal with no calibrated interpretation unless a
specific model documents one; `uncertainty` is a spread, not a posterior width.
`label` is what a caller should branch on. AGENTS.md principle 5 requires a
*value* estimate to carry a distribution — relevance makes the weaker claim
honestly rather than the stronger one falsely.

### Versioning

`CONTRACT_VERSION` is separate from `SCHEMA_VERSION`. An assessment is derived,
not stored in the event log: it is reproducible from a context plus a corpus
state and cheaper to recompute than to migrate. Tying it to the log's version
would force a store migration every time a feature weight changed.

## 4. Invariants — the P0 gate

Every row is enforced in code and has a test. "Enforced" means the illegal
state cannot be constructed, not that a linter complains.

| # | Invariant | Enforced by | Test class |
|---|---|---|---|
| 1 | An assessment binds to an exact context **and** memory version | `applies()`; version < 1 refused | `Invariant1_TaskScoped` |
| 2 | Changing the task changes relevance without mutating the memory | `ContextSnapshot` frozen; `evolve()` mints a new `context_id` | `Invariant2_ChangingTheTaskChangesRelevance` |
| 3 | `irrelevant` never deletes, retracts, quarantines or changes lifecycle | `assert_no_lifecycle_authority`, plus a source check that the module imports no lifecycle API | `Invariant3_IrrelevanceIsNotAVerdictOnTheMemory` |
| 4 | A relevance score never overrides a hard gate | `SelectionDecision.__post_init__` refuses `included=True` with any hard-gate reason, **at any score** | `Invariant4_AScoreNeverOverridesAGate` |
| 5 | `uncertain` is a valid outcome and carries no score | label accepted; score with it refused | `Invariant5_UncertainIsAValidOutcome` |
| 6 | A missing feature stays missing, never 0.0 | `MISSING` singleton, falsey, surfaced in JSON as `contribution_missing` | `Invariant6_MissingIsNotZero` |
| 7 | Every assessment and decision is auditable and versioned | evidence required; reasons required; strict-JSON round trip | `Invariant7_Auditable` |
| 8 | Assembly omits rather than overflowing its budget | `ContextPackage.__post_init__` | `Invariant8_BudgetIsRespected` |
| 9 | Observed facts and model-inferred fields stay separable | overlapping keys refused | `Invariant9_ObservedAndInferredStaySeparate` |
| 10 | A context needs a task; `event_time` is distinct from recorded time | validated in `__post_init__` | `Invariant10_ContextValidity` |

**35 tests, 21 subtests.**

### Invariant 4 in detail

The one most likely to be eroded by a future convenience. Hard gates —
`unauthorized`, `wrong_tenant`, `retracted`, `superseded`,
`blocked_lifecycle` — are *gates*, not weights. `ReasonCode.is_hard_gate`
makes them distinguishable from ranking outcomes (`low_relevance`,
`over_budget`, `duplicate_or_redundant`) for a reason beyond tidiness: an
operator asking "why did the agent not see this?" needs to know whether it
ranked low or was refused, because a low rank is a tuning question and a
refusal is a policy question. Conflating them would let a weight change appear
to fix a permission bug. `ContextPackage.blocked_by_gate()` keeps the two apart
in reporting.

## 5. What P0 does **not** claim

- **No ranking quality claim.** Nothing here ranks anything.
- **No downstream claim.** Nothing here has been run against an agent.
- **No calibration.** `score` and `uncertainty` have no probabilistic reading.
- **No persistence.** Assessments are in-memory values; nothing writes them to the event log, so there is no migration and no new event type.
- **No integration.** The existing `retrieve()` path is untouched and remains the baseline. New ranking will be opt-in until a gate passes.

## 6. Next: P1, the benchmark

Required before any ranker:

1. A versioned dataset format and labelling guide.
2. Scenario families: direct, lexical trap, indirect dependency, rare-but-critical, temporal drift, superseded version, conflicting sources, copied evidence, near-duplicate overload, explicit constraints, negative evidence, unanswerable, authorised-but-irrelevant, relevant-but-unauthorised, retraction between retrieval and exposure.
3. Baselines: none, lexical, vector, simple hybrid, hybrid + rerank, current `retrieve()`.
4. **An oracle ceiling, measured before any threshold is registered** — with the same budget, the same `k` and the same mechanisms as the arms it bounds, differing only in knowing the answer (principle 8b). `stats.check_ceiling` runs the "did any arm beat the oracle?" check on every verdict.
5. A frozen held-out split, and a registered threshold expressed as a share of the measured headroom.

A labelling rule that comes directly from the measurements: **never label a
memory irrelevant because the agent's final answer failed.** That is the
causal-attribution error PA′ quantified, and it would bake the same mistake
into the ground truth.
