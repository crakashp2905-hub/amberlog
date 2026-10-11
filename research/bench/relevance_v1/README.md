# relevance_v1 — the contextual relevance benchmark

- **Version:** `relevance_v1` (frozen; a change means a new directory, not an edit)
- **Built:** 2026-10-11, **before** any ranker existed
- **Split:** `dev.json` (tunable) and `test.json` (**frozen, do not look at while tuning**)
- **Runner:** `python -m experiments.relevance_bench`

## Why this exists before the ranker

Of four simulated hypotheses in this project, **three were mis-operationalised,
and every time the fault was in the measurement rather than the mechanism**
([RETROSPECTIVE.md](../../RETROSPECTIVE.md)). A ranker written before the thing
that could falsify it gets tuned on whichever examples flatter it. So the
dataset, the baselines and the oracle ceiling are committed first, and the
commit history shows it.

## What a case is

One `corpus` of memories, one `task` with its context, and labels saying which
memories a perfect retriever would return. Memories carry the metadata the
store really has — provenance method, parents, lifecycle state, scope,
capabilities, tenant, `recorded_at`, `valid_from` / `valid_to` — so a case can
express a superseded version or a retracted premise without the harness
inventing a parallel data model.

```json
{
  "case_id": "direct-01",
  "family": "direct",
  "task": {"task_text": "...", "goal": "...", "constraints": [],
           "entities": ["valve-7"], "event_time": 1700000000,
           "token_budget": 400, "agent_id": "ag", "tenant_id": "tn_default"},
  "corpus": [{"id": "m1", "content": "...", "lifecycle_state": "active", ...}],
  "labels": {
    "relevant": ["m1"],
    "critical": ["m1"],
    "irrelevant": ["m2", "m3"],
    "must_not_expose": [],
    "expect_abstain": false,
    "roles": {"m1": "necessary"}
  },
  "rationale": "why these labels, in one sentence"
}
```

### Label semantics

| Field | Meaning |
|---|---|
| `relevant` | a perfect retriever returns these for this task |
| `critical` | omitting this one changes the answer — scored separately, because a mean over cases hides the expensive failure |
| `irrelevant` | present in the corpus and should **not** be returned; this is what makes a lexical trap a trap |
| `must_not_expose` | relevant *and* refused by a hard gate. Returning it is a **failure even though it is relevant**, and it is counted apart from precision so a ranker cannot trade one for the other |
| `expect_abstain` | the corpus cannot answer the task; the right behaviour is to return nothing |
| `roles` | `necessary` / `sufficient` / `corroborative` / `contradictory` / `background` |

### The labelling rule that comes from a measurement

> **Never label a memory irrelevant because an agent's answer failed.**

That is the causal-attribution error PA′ quantified — of naive blame's 87
withdrawals, 57 were about a completely different fault — and labelling this
way would bake it into the ground truth. Every label here is justified by the
*task and the memory*, and `rationale` says how.

## Scenario families

Fifteen, from the two planning documents, each one a different way for a
retriever to be wrong.

| Family | What it tests | The failure it catches |
|---|---|---|
| `direct` | same fact, different wording | nothing — it is the sanity floor |
| `lexical_trap` | overlapping words, wrong entity or fault | lexical scoring without entity awareness |
| `indirect` | the answer is a parent or child of the match | no lineage expansion |
| `rare_critical` | low similarity, decisive content | similarity-only ranking |
| `temporal_drift` | a fact that was true and is not | no `valid_time` reasoning |
| `superseded` | an older version still in the corpus | version-blind retrieval |
| `conflicting` | two claims that disagree under overlapping conditions | silently resolving a live disagreement |
| `apparent_conflict` | two claims that differ because conditions differ | treating a scope difference as a contradiction |
| `copied_evidence` | four memories, one root | counting copies as corroboration |
| `near_duplicate` | redundancy crowding out a rare fact | top-k without diversity |
| `constrained` | an explicit task constraint rules candidates out | ignoring stated constraints |
| `negative_evidence` | a fact that rules out the tempting answer | ranking only positive support |
| `unanswerable` | nothing in the corpus answers it | returning the best available insufficient evidence |
| `unauthorized` | the relevant memory is refused by a gate | letting relevance override a gate |
| `retracted` | the relevant memory was withdrawn at its origin | exposing withdrawn knowledge |

The last three overlap with integrity rather than relevance, and that is the
point: they are the cases where a *better ranker scores worse* unless the gates
sit outside the score.

## Baselines

Every arm gets the same corpus, the same `k`, the same budget.

| Arm | What it is |
|---|---|
| `none` | returns nothing. The floor, and the only arm `unanswerable` rewards |
| `lexical` | normalised token overlap, IDF-weighted |
| `vector` | the store's own `VectorIndex`. **A hashing embedder, not a trained model** — reported as such, since it is the single biggest limitation of these numbers |
| `hybrid` | lexical + vector, fixed equal weights |
| `current` | `MemoryFabric.retrieve()` exactly as it ships today |
| `oracle` | returns the labelled relevant set, truncated to the same `k` |

### The oracle gets no handicap

Principle 8b, and this project has built the ceiling wrong three times. The
oracle here runs through the **same gate pipeline** as every other arm, with
the **same `k`** and the **same budget**, differing only in knowing the labels.
It therefore does *not* score 1.0: on `unauthorized` and `retracted` cases the
gate removes memories the labels call relevant, which is correct behaviour and
exactly the headroom a ranker cannot reach. `stats.check_ceiling` runs on every
report and fails loudly if any arm beats it.

## Metrics

Reported separately. There is no aggregate score, deliberately — collapsing
precision, critical recall and gate violations into one number is how a ranker
comes to look good while exposing a retracted memory.

- `precision@k`, `recall@k`, `ndcg@k`, `mrr`
- `critical_recall` — share of `critical` memories returned
- `critical_omission_rate` — cases where at least one `critical` memory was missed
- `must_not_expose_rate` — **gate violations. Any non-zero value is a failure regardless of every other metric**
- `abstention_precision` / `false_abstention` — on `unanswerable` cases
- `irrelevant_ratio` — share of returned memories labelled irrelevant

## Reproduction

```bash
python -m experiments.relevance_bench --split dev
python -m experiments.relevance_bench --split test --out research/results/relevance-v1.md
```

Deterministic: no model calls, no sampling, fixed `k`. Two runs of the same
commit produce byte-identical reports, which `tests/test_relevance_bench.py`
asserts.
