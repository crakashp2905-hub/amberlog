"""relevance_v1 — the retrieval benchmark, its baselines, and the oracle ceiling.

Built before any ranker exists, which is the point. Of four simulated
hypotheses in this project three were mis-operationalised, and every time the
fault was in the measurement rather than the mechanism; a ranker written before
the thing that could falsify it gets tuned on whichever examples flatter it.

**Retrieval only, no model calls.** Every arm is deterministic and the whole
suite runs in under a second, which matters because the decisive question —
*how much headroom does perfect selection actually have?* — is answerable
without a downstream agent. Phase C cost 8h14m of model calls to answer a
narrower question. A downstream arm comes later and only if the ceiling
justifies it.

## The gate pipeline, and why the oracle goes through it

Every arm, including the oracle, is filtered by the same gates: lifecycle,
capabilities, tenant. Principle 8b — the oracle gets the same budget, the same
`k` and the same mechanisms as the arms it bounds, differing only in knowing
the answer. This project has built the ceiling wrong three times by giving the
oracle an advantage nobody noticed until an arm beat it.

The oracle does reach 1.0, and the reason is worth stating because an earlier
draft of this docstring claimed the opposite. Recall and nDCG are scored
against the **reachable** relevant set — relevant minus `must_not_expose` —
because a memory a gate refuses is not something any arm should have returned,
and counting it as a miss would score correct behaviour as failure. So the
oracle returns the forbidden memories, the gate removes them, and both the
oracle and a well-behaved arm are judged on what was reachable.

The consequence is that `must_not_expose_rate` can only be non-zero for an arm
that **bypasses the gates**. That is the architecture working — invariant 4,
gates outside the score — and it is why `arm_broken_bypasses_gates` exists: a
metric that cannot fire is not a check, and the R1 gate requires a deliberately
broken ranker to fail this benchmark.
"""

from __future__ import annotations

import argparse
import json
import math
import pathlib
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Sequence

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from experiments.stats import report_ceiling  # noqa: E402
from memory_fabric.relevance import ReasonCode  # noqa: E402
from memory_fabric.vectors import HashingEmbedder, VectorIndex  # noqa: E402

BENCH_DIR = pathlib.Path(__file__).resolve().parent.parent / "research" / "bench"
BENCHMARK = "relevance_v1"
DEFAULT_K = 3

# k per benchmark, because the right k is a property of the data. v1 cases hold
# 1-2 relevant memories against 18; v2 holds up to 4 (a 4-hop chain) against
# ~500, and a k below the chain length would score a perfect selection as a
# miss -- the oracle would be handicapped, which principle 8b forbids.
BENCH_K = {"relevance_v1": 3, "relevance_v2": 5, "propagation_v1": 5}

BLOCKED_LIFECYCLE = frozenset({"quarantined", "deprecated", "deleted"})

_STOP = frozenset(
    "the a an is are was were be been it its of for to in on at and or not "
    "do does did should what which how why when who with from this that "
    "still can could we i me my our us".split()
)


# --- loading ----------------------------------------------------------------


def load(split: str, benchmark: str = BENCHMARK) -> list[dict[str, Any]]:
    path = BENCH_DIR / benchmark / f"{split}.json"
    if not path.exists():
        raise SystemExit(
            f"{path} is not built. relevance_v2 is generated rather than "
            f"committed (12 MB a split); run "
            f"`python -m research.bench.relevance_v2.build` first, and the "
            f"MANIFEST digests will confirm you got the same bytes.")
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["benchmark"] == benchmark, payload["benchmark"]
    return payload["cases"]


# --- the gates --------------------------------------------------------------


def gate(case: Mapping[str, Any], memory: Mapping[str, Any]) -> ReasonCode | None:
    """Why this memory may not be exposed, or None.

    Applied to every arm's output, after ranking and never as part of it. A
    hard gate is not a weight: `SelectionDecision` refuses to construct an
    inclusion carrying one, so an arm cannot trade authorisation for relevance
    even by accident.
    """
    task = case["task"]
    if memory["lifecycle_state"] in BLOCKED_LIFECYCLE:
        return (
            ReasonCode.RETRACTED
            if memory["lifecycle_state"] == "quarantined"
            else ReasonCode.SUPERSEDED
        )
    if memory.get("tenant_id", "tn_default") != task.get("tenant_id", "tn_default"):
        return ReasonCode.WRONG_TENANT
    ungranted = set(memory.get("capabilities") or ()) - set(
        task.get("granted_capabilities") or ()
    )
    if ungranted:
        return ReasonCode.UNAUTHORIZED
    return None


def apply_gates(
    case: Mapping[str, Any], ranked: Sequence[str]
) -> tuple[list[str], dict[str, ReasonCode]]:
    by_id = {m["id"]: m for m in case["corpus"]}
    allowed, refused = [], {}
    for memory_id in ranked:
        reason = gate(case, by_id[memory_id])
        if reason is None:
            allowed.append(memory_id)
        else:
            refused[memory_id] = reason
    return allowed, refused


# --- scoring helpers --------------------------------------------------------


def tokens(text: str) -> list[str]:
    cleaned = "".join(c.lower() if c.isalnum() else " " for c in text)
    return [t for t in cleaned.split() if t and t not in _STOP]


def idf(corpus: Sequence[Mapping[str, Any]]) -> dict[str, float]:
    total = len(corpus)
    counts: dict[str, int] = {}
    for memory in corpus:
        for term in set(tokens(memory["content"])):
            counts[term] = counts.get(term, 0) + 1
    return {
        term: math.log((total + 1) / (count + 0.5)) for term, count in counts.items()
    }


def query_text(case: Mapping[str, Any]) -> str:
    task = case["task"]
    parts = [task["task_text"], task.get("goal", "")]
    parts.extend(task.get("constraints") or ())
    parts.extend(task.get("entities") or ())
    return " ".join(p for p in parts if p)


# --- arms -------------------------------------------------------------------
#
# Each returns memory ids best-first, *before* gating and before truncation to
# k. Keeping ranking and gating separate is the contract's invariant 4 made
# operational: an arm cannot see the gates, so it cannot learn to route around
# them.


def arm_none(case: Mapping[str, Any], k: int) -> list[str]:
    """The floor, and the only arm the `unanswerable` family rewards."""
    return []


def arm_lexical(case: Mapping[str, Any], k: int) -> list[str]:
    weights = idf(case["corpus"])
    query = set(tokens(query_text(case)))
    scored = []
    for memory in case["corpus"]:
        terms = tokens(memory["content"])
        if not terms:
            continue
        overlap = sum(weights.get(t, 0.0) for t in set(terms) & query)
        # Length-normalised, or a long memory wins by containing more words.
        scored.append((overlap / math.sqrt(len(set(terms))), memory["id"]))
    # Deterministic: score descending, then id ascending. No ties left to luck.
    scored.sort(key=lambda pair: (-pair[0], pair[1]))
    return [memory_id for score, memory_id in scored if score > 0.0]


_REAL_EMBEDDER = None
_REAL_EMBEDDER_TRIED = False


def real_embedder():
    """A trained embedding model, when one is reachable. None otherwise.

    Shared across cases so its cache survives: the same distractor pool appears
    in every case, so a per-case embedder would pay for all fifteen of them
    twenty times over.

    Returns None rather than raising when Ollama is absent, because the whole
    benchmark must stay runnable in CI with nothing installed — but the arms
    that need it are then *skipped and reported as skipped*, never silently
    scored with the hashing embedder. Substituting one would make a real-model
    claim out of a hash.
    """
    global _REAL_EMBEDDER, _REAL_EMBEDDER_TRIED
    if _REAL_EMBEDDER_TRIED:
        return _REAL_EMBEDDER
    _REAL_EMBEDDER_TRIED = True
    try:
        from memory_fabric.adapters.ollama import OllamaClient, OllamaEmbedder

        client = OllamaClient()
        available = client.available()
        model = client.resolve("nomic-embed-text", available)
        if model is None:
            return None
        _REAL_EMBEDDER = OllamaEmbedder(client=client, model=model)
        _REAL_EMBEDDER.embed("warm-up")
    except Exception:
        _REAL_EMBEDDER = None
    return _REAL_EMBEDDER


def arm_real_vector(case: Mapping[str, Any], k: int) -> list[str]:
    """Vector retrieval with a **trained** embedder rather than a hash.

    The question R1 raised and could not answer: the hashing embedder is the
    single biggest limitation of every number in that result, and a real model
    might close most of the measured headroom with no new mechanism. Worth
    knowing before building a ranker.
    """
    embedder = real_embedder()
    if embedder is None:
        raise RuntimeError("no embedding model available")
    index = VectorIndex(embedder)
    texts = [m["content"] for m in case["corpus"]] + [query_text(case)]
    embedder.warm(texts)
    for memory in case["corpus"]:
        index.add(memory["id"], memory["content"])
    hits = index.search(query_text(case), k=len(case["corpus"]), min_relevance=0.0)
    return [memory_id for memory_id, score in hits if score > 0.0]


def arm_real_hybrid(case: Mapping[str, Any], k: int) -> list[str]:
    """Lexical fused with the trained embedder."""
    ranks: dict[str, float] = {}
    for arm in (arm_lexical, arm_real_vector):
        for position, memory_id in enumerate(arm(case, k)):
            ranks[memory_id] = ranks.get(memory_id, 0.0) + 1.0 / (60 + position + 1)
    fused = sorted(ranks.items(), key=lambda pair: (-pair[1], pair[0]))
    return [memory_id for memory_id, score in fused]


def arm_vector(case: Mapping[str, Any], k: int) -> list[str]:
    """The store's own index.

    A **hashing embedder, not a trained model**, and that is the single biggest
    limitation of every number this benchmark reports. It is included rather
    than omitted because it is what the product actually ships today, and
    reporting it honestly is more useful than a vector arm this repository does
    not have.
    """
    index = VectorIndex(HashingEmbedder())
    for memory in case["corpus"]:
        index.add(memory["id"], memory["content"])
    hits = index.search(query_text(case), k=len(case["corpus"]), min_relevance=0.0)
    return [memory_id for memory_id, score in hits if score > 0.0]


def arm_hybrid(case: Mapping[str, Any], k: int) -> list[str]:
    """Reciprocal-rank fusion of lexical and vector.

    RRF rather than a weighted score sum, because the two arms' scores are on
    incomparable scales and tuning a weight here would be tuning on the dev
    split before a ranker milestone exists.
    """
    ranks: dict[str, float] = {}
    for arm in (arm_lexical, arm_vector):
        for position, memory_id in enumerate(arm(case, k)):
            ranks[memory_id] = ranks.get(memory_id, 0.0) + 1.0 / (60 + position + 1)
    fused = sorted(ranks.items(), key=lambda pair: (-pair[1], pair[0]))
    return [memory_id for memory_id, score in fused]


def _store_arm(
    mode: str = "hybrid", **options: Any
) -> Callable[[Mapping[str, Any], int], list[str]]:
    """The product, configured. One arm per mechanism, measured separately.

    Each of the three mechanisms R1 pointed at is its own arm rather than a new
    default, because turning one on by assumption is how a mechanism gets
    credit it has not earned — the H2/H3/H4a pattern this project keeps
    recording.
    """

    def arm(case: Mapping[str, Any], k: int) -> list[str]:
        return arm_current({**case, "_retrieval": mode, "_options": options}, k)

    arm.__name__ = f"arm_store_{mode}_{'_'.join(sorted(options)) or 'plain'}"
    return arm


def _as_of(case: Mapping[str, Any]) -> int | None:
    """The task's own event time, which is what temporal filtering is *for*.

    Passing `now` instead would make every historical question unanswerable,
    which is the `temporal_drift-02` case: the same corpus, the opposite
    answer, because the task is about last year.
    """
    return case["task"].get("event_time")


def insertion_order(corpus):
    """Parents before children, by dependency rather than by parent count.

    Sorting on `len(parents)` is not a topological order. It works only for
    chains of depth one: in `root -> interim -> restatement` the interim and
    the restatement both have one parent, so the restatement can be written
    first, its parent is not yet in the store, and the edge is dropped in
    silence. The memory then becomes its own source root and every propagation
    rule reads it as independent evidence.

    That is how `retracted_intermediate` first reported 1.500 stale citations
    for an arm that should have scored 0.000 -- the arm was correct and the
    fixture had no chain to traverse. It is the third time in this project that
    an absent provenance edge has looked like a result about a mechanism.
    """
    remaining = list(corpus)
    placed: set[str] = set()
    ordered = []
    while remaining:
        ready = [
            m for m in remaining
            if all(p[0] in placed for p in (m.get("parents") or ()))
        ]
        if not ready:
            raise AssertionError(
                f"cycle or dangling parent among {[m['id'] for m in remaining][:5]}")
        for m in ready:
            ordered.append(m)
            placed.add(m["id"])
        remaining = [m for m in remaining if m["id"] not in placed]
    return ordered


def arm_current(case: Mapping[str, Any], k: int) -> list[str]:
    """`MemoryFabric.retrieve()` exactly as it ships.

    Built through the real store rather than reimplemented, so this arm cannot
    quietly diverge from the product. Memories are written with their labelled
    lifecycle state, so the store's own eligibility filter runs too.
    """
    from memory_fabric import MemoryFabric
    from memory_fabric.model import LifecycleState

    fabric = MemoryFabric(
        ":memory:", auto_activate=True, encrypt_content=False,
        # No default here. `current` means "the product exactly as it ships",
        # so it must follow `MemoryFabric`'s own default rather than carry a
        # copy of it — a hardcoded "hybrid" kept this arm reporting the old
        # ranking after the product default changed, which is the one thing
        # this arm exists not to do.
        **({"retrieval": case["_retrieval"]} if "_retrieval" in case else {}),
    )
    try:
        ids = {}
        local = {}
        to_quarantine: list[str] = []
        # Dependency order: parents must exist before a child can name them,
        # and the dataset lists corpora shuffled.
        for memory in insertion_order(case["corpus"]):
            parents = [
                (local[p[0]], 1) for p in (memory.get("parents") or []) if p[0] in local
            ]
            stored = fabric.remember(
                agent_id=case["task"]["agent_id"],
                content=memory["content"],
                tenant_id=memory.get("tenant_id", "tn_default"),
                parents=parents,
                method="consolidated" if parents else "observed",
                valid_from=memory.get("valid_from"),
                valid_to=memory.get("valid_to"),
            )
            local[memory["id"]] = stored
            ids[stored] = memory["id"]
            if memory["lifecycle_state"] in BLOCKED_LIFECYCLE:
                to_quarantine.append(stored)

        # Quarantine **after** every memory is written, never inside the loop.
        #
        # `quarantine(propagate=True)` contests the descendants, and CONTESTED
        # is excluded from `_eligible_ids` unless a caller asks for it. Done
        # inside the loop the children do not exist yet, so there is nothing to
        # propagate to and the store is left with a retracted parent and active
        # descendants -- a state the product never produces and which no
        # measurement taken against it describes.
        #
        # This is what made P3 report that the product has no retraction
        # propagation. It has, and on the case that experiment was built around
        # it behaves exactly like the `graph_traversal` arm that was said to
        # beat it.
        for stored in to_quarantine:
            fabric.quarantine(stored, reason="benchmark fixture", actor="bench",
                              basis="contradicted")
        options = case.get("_options") or {}
        result = fabric.retrieve(
            agent_id=case["task"]["agent_id"],
            query=query_text(case),
            k=len(case["corpus"]),
            tenant_id=case["task"].get("tenant_id", "tn_default"),
            min_relevance=0.0,
            **options,
        )
        return [ids[m.id] for m in result.exposed]
    finally:
        fabric.close()


def arm_oracle(case: Mapping[str, Any], k: int) -> list[str]:
    """The labelled relevant set, critical first.

    Knows the answer and nothing else: same `k`, same gates, same budget. It
    therefore scores below 1.0 wherever a gate removes a memory the labels call
    relevant, which is correct and is the headroom a ranker must not reach.
    """
    labels = case["labels"]
    critical = [m for m in labels["relevant"] if m in set(labels["critical"])]
    rest = [m for m in labels["relevant"] if m not in set(labels["critical"])]
    return critical + rest


def arm_broken_bypasses_gates(case: Mapping[str, Any], k: int) -> list[str]:
    """Deliberately broken: ranks well and ignores the gates.

    The R1 gate requires that a broken ranker *fails* the benchmark, and this
    is the specific breakage worth catching — a ranker good enough to surface
    the relevant memory, including the one it must not expose. It is scored
    through `run(..., bypass_gates=True)` so the harness really does skip the
    gate step rather than the arm pretending to.

    Never in `ARMS`: a normal run cannot include it by accident.
    """
    return arm_oracle(case, k)


def arm_broken_always_first(case: Mapping[str, Any], k: int) -> list[str]:
    """Deliberately broken: returns the corpus in storage order.

    The dull failure — no relevance signal at all — which must land near the
    `none` floor on nDCG while *not* abstaining. If this scored close to the
    baselines, the benchmark would not be measuring relevance.
    """
    return [m["id"] for m in case["corpus"]]


BROKEN_ARMS: dict[str, Callable[[Mapping[str, Any], int], list[str]]] = {
    "broken_bypasses_gates": arm_broken_bypasses_gates,
    "broken_no_signal": arm_broken_always_first,
}


ARMS: dict[str, Callable[[Mapping[str, Any], int], list[str]]] = {
    "none": arm_none,
    "lexical": arm_lexical,
    "vector": arm_vector,
    "hybrid": arm_hybrid,
    # `current` is whatever the product ships today. `store_vector` pins the
    # pre-2026-10-11 behaviour so a regression is visible rather than inferred.
    "current": arm_current,
    # `store_plain` pins the product with both mechanisms **off**, so the
    # before/after stays measurable now that they are the defaults. Without it
    # every comparison arm silently inherited them and two tests compared a
    # thing against itself.
    "store_plain": _store_arm(
        "hybrid", group_by_source_root=False, expand_lineage=0
    ),
    "store_vector": _store_arm(
        "vector", group_by_source_root=False, expand_lineage=0
    ),
    "store_lexical": _store_arm(
        "lexical", group_by_source_root=False, expand_lineage=0
    ),
    "real_vector": arm_real_vector,
    "real_hybrid": arm_real_hybrid,
    "store_temporal": None,  # filled below: needs the per-case event time
    # Lexical *with* the mechanisms: the configuration the lexical/hybrid
    # question never tested. Grouping and promotion are orthogonal to which
    # retrieval arm feeds them, so choosing between them without measuring the
    # combination would have been a false dichotomy.
    "lexical_all": _store_arm(
        "lexical", group_by_source_root=True, expand_lineage=1
    ),
    "store_roots": _store_arm(
        "hybrid", group_by_source_root=True, expand_lineage=0
    ),
    "store_lineage": _store_arm(
        "hybrid", group_by_source_root=False, expand_lineage=1
    ),
    "store_all": None,
    "oracle": arm_oracle,
}
def _temporal_arm(case: Mapping[str, Any], k: int) -> list[str]:
    """Temporal filtering **only**.

    Every option is named explicitly. Relying on a default made this arm
    silently become "all three mechanisms" the moment roots and lineage became
    the defaults, and the ablation table then showed `store_temporal` and
    `store_all` with identical numbers — which read as temporal filtering
    doing all the work.
    """
    return arm_current(
        {
            **case,
            "_retrieval": "hybrid",
            "_options": {
                "as_of": _as_of(case),
                "group_by_source_root": False,
                "expand_lineage": 0,
            },
        },
        k,
    )


def _all_mechanisms_arm(case: Mapping[str, Any], k: int) -> list[str]:
    return arm_current(
        {
            **case,
            "_retrieval": "hybrid",
            "_options": {
                "as_of": _as_of(case),
                "group_by_source_root": True,
                "expand_lineage": 1,
            },
        },
        k,
    )


ARMS["store_temporal"] = _temporal_arm
ARMS["store_all"] = _all_mechanisms_arm

CEILING = "oracle"


# --- metrics ----------------------------------------------------------------


@dataclass
class CaseResult:
    case_id: str
    family: str
    returned: tuple[str, ...]
    refused: dict[str, str]
    precision: float
    recall: float
    ndcg: float
    reciprocal_rank: float
    critical_recall: float
    missed_critical: bool
    exposed_forbidden: tuple[str, ...]
    irrelevant_ratio: float
    abstained: bool
    expect_abstain: bool
    # Sufficiency (Priority 2). None where the case declares no critical
    # requirement -- the MISSING sentinel from the relevance contract rather
    # than a zero, because "this case cannot answer the question" and "this arm
    # assembled an insufficient context" are different facts and averaging them
    # together would report the first as the second.
    requirements_total: int = 0
    requirements_met: int = 0
    sufficient: bool | None = None
    # Stale evidence (Priority 3): a memory whose own lifecycle is active but
    # whose source root has been retracted.
    stale_declared: int = 0
    stale_cited: int = 0
    latency_ms: float = 0.0


def dcg(gains: Sequence[float]) -> float:
    return sum(g / math.log2(i + 2) for i, g in enumerate(gains))


def score_case(case: Mapping[str, Any], returned: Sequence[str],
               refused: Mapping[str, ReasonCode], k: int) -> CaseResult:
    labels = case["labels"]
    relevant = set(labels["relevant"])
    critical = set(labels["critical"])
    irrelevant = set(labels["irrelevant"])
    forbidden = set(labels["must_not_expose"])
    top = list(returned[:k])

    # The *reachable* relevant set: relevant minus anything a gate refuses. A
    # memory a gate removes is not something any arm should have returned, so
    # counting it as a miss would score correct behaviour as failure.
    reachable = relevant - forbidden

    # Gain is credited for reachable relevance only. Returning a forbidden
    # memory therefore earns **nothing** on the ranking metrics and is counted
    # separately as a violation — so bypassing a gate can only ever cost an
    # arm. Crediting it against `relevant` instead produced nDCG of 1.090,
    # because the ideal is computed over the reachable set; an impossible
    # number, and a scoring rule that paid an arm for the one thing it must
    # not do.
    hits = [1.0 if m in reachable else 0.0 for m in top]
    precision = (sum(hits) / len(top)) if top else 0.0
    recall = (sum(hits) / len(reachable)) if reachable else 1.0
    ideal = dcg([1.0] * min(len(reachable), k))
    ndcg = (dcg(hits) / ideal) if ideal > 0 else (1.0 if not reachable else 0.0)
    rr = next((1.0 / (i + 1) for i, m in enumerate(top) if m in reachable), 0.0)

    reachable_critical = critical - forbidden
    found_critical = len([m for m in top if m in reachable_critical])
    critical_recall = (
        found_critical / len(reachable_critical) if reachable_critical else 1.0
    )

    # --- sufficiency --------------------------------------------------------
    #
    # Ranking asks "did the arm order the corpus well". This asks the question
    # a decision actually turns on: does the assembled set *contain enough* to
    # answer defensibly? They come apart. A 4-hop chain with three hops
    # retrieved scores 0.75 recall and is worth nothing, because the conclusion
    # cannot be reached; a `conflicting` case holding one of two contradictory
    # sources scores 0.5 recall and is worse than nothing, because it looks
    # complete.
    #
    # Satisfiers are intersected with `top` *minus* the forbidden set, so a
    # requirement can never be satisfied by a memory a gate refuses. Without
    # that subtraction the gate-bypassing arm would report full sufficiency on
    # the `gated` family, which is the same mistake as crediting its nDCG.
    requirements = labels.get("requirements") or []
    visible = set(top) - forbidden
    critical_reqs = [r for r in requirements if r.get("critical")]
    met = [r for r in requirements if set(r["satisfied_by"]) & visible]
    critical_met = [r for r in critical_reqs if set(r["satisfied_by"]) & visible]
    sufficient = (
        (len(critical_met) == len(critical_reqs)) if critical_reqs else None
    )

    stale = set(labels.get("stale") or ())
    return CaseResult(
        case_id=case["case_id"],
        family=case["family"],
        returned=tuple(top),
        refused={m: r.value for m, r in refused.items()},
        precision=precision,
        recall=recall,
        ndcg=ndcg,
        reciprocal_rank=rr,
        critical_recall=critical_recall,
        missed_critical=bool(reachable_critical) and found_critical < len(reachable_critical),
        exposed_forbidden=tuple(m for m in top if m in forbidden),
        irrelevant_ratio=(len([m for m in top if m in irrelevant]) / len(top)) if top else 0.0,
        abstained=not top,
        expect_abstain=bool(labels["expect_abstain"]),
        requirements_total=len(requirements),
        requirements_met=len(met),
        sufficient=sufficient,
        stale_declared=len(stale),
        stale_cited=len([m for m in top if m in stale]),
    )


def _ratio(flags: Sequence[bool]) -> float | None:
    """A rate over the cases that declare the property, or None.

    None rather than 0.0: a benchmark whose cases carry no requirements has no
    sufficiency, and reporting that as zero would make v1 look like a total
    failure at a question it never asked.
    """
    return round(sum(1 for f in flags if f) / len(flags), 4) if flags else None


def _mean_of(values: Sequence[float]) -> float | None:
    return round(sum(values) / len(values), 4) if values else None


@dataclass
class ArmReport:
    arm: str
    cases: list[CaseResult] = field(default_factory=list)

    def _mean(self, attribute: str) -> float:
        values = [getattr(c, attribute) for c in self.cases]
        return sum(values) / len(values) if values else 0.0

    @property
    def answerable(self) -> list[CaseResult]:
        return [c for c in self.cases if not c.expect_abstain]

    def summary(self) -> dict[str, Any]:
        answerable = self.answerable
        unanswerable = [c for c in self.cases if c.expect_abstain]
        mean = lambda rows, attr: (  # noqa: E731
            sum(getattr(r, attr) for r in rows) / len(rows) if rows else 0.0
        )
        return {
            "arm": self.arm,
            "cases": len(self.cases),
            "precision_at_k": round(mean(answerable, "precision"), 4),
            "recall_at_k": round(mean(answerable, "recall"), 4),
            "ndcg_at_k": round(mean(answerable, "ndcg"), 4),
            "mrr": round(mean(answerable, "reciprocal_rank"), 4),
            "critical_recall": round(mean(answerable, "critical_recall"), 4),
            "critical_omission_rate": round(
                mean(answerable, "missed_critical"), 4
            ),
            # Any non-zero value here is a failure regardless of every other
            # number, which is why it is not folded into a composite.
            "must_not_expose_rate": round(
                (len([c for c in self.cases if c.exposed_forbidden]) / len(self.cases))
                if self.cases else 0.0, 4
            ),
            "irrelevant_ratio": round(mean(answerable, "irrelevant_ratio"), 4),
            "abstention_precision": round(
                (len([c for c in unanswerable if c.abstained]) / len(unanswerable))
                if unanswerable else 1.0, 4
            ),
            "false_abstention": round(
                (len([c for c in answerable if c.abstained]) / len(answerable))
                if answerable else 0.0, 4
            ),
            # --- Priority 2: sufficiency, over the cases that declare it ----
            "sufficiency": _ratio([c.sufficient for c in self.cases
                                   if c.sufficient is not None]),
            "requirement_recall": _mean_of([
                c.requirements_met / c.requirements_total
                for c in self.cases if c.requirements_total
            ]),
            # --- Priority 3: use of evidence whose source root was retracted -
            "stale_citation_rate": _ratio([
                bool(c.stale_cited) for c in self.cases if c.stale_declared
            ]),
            # The rate alone cannot see the mechanism working. Grouping by
            # source root collapses four derived restatements of one retracted
            # survey into one, which takes the count from 4 to 1 and leaves the
            # "did it cite any" rate at 1.000 either way. A binary that cannot
            # distinguish four wrong citations from one is not measuring the
            # thing the mechanism does.
            "stale_citations_mean": _mean_of([
                float(c.stale_cited) for c in self.cases if c.stale_declared
            ]),
        }

    def timing(self) -> dict[str, float]:
        """Wall clock, kept out of `summary()` deliberately.

        Metrics must be byte-identical across two runs of one commit -- that is
        how a hidden source of state gets caught. A timing figure never will
        be, so folding it in would have meant loosening the reproducibility
        test to accommodate a measurement rather than keeping the two kinds of
        number apart.
        """
        if not self.cases:
            return {"latency_ms": 0.0, "latency_ms_max": 0.0}
        return {
            "latency_ms": round(
                sum(c.latency_ms for c in self.cases) / len(self.cases), 3),
            "latency_ms_max": round(max(c.latency_ms for c in self.cases), 3),
        }

    def by_family(self) -> dict[str, dict[str, float]]:
        families: dict[str, list[CaseResult]] = {}
        for result in self.cases:
            families.setdefault(result.family, []).append(result)
        out = {}
        for family, rows in sorted(families.items()):
            answerable = [r for r in rows if not r.expect_abstain]
            out[family] = {
                "cases": len(rows),
                "ndcg": round(
                    sum(r.ndcg for r in answerable) / len(answerable), 4
                ) if answerable else None,
                "critical_recall": round(
                    sum(r.critical_recall for r in answerable) / len(answerable), 4
                ) if answerable else None,
                "violations": len([r for r in rows if r.exposed_forbidden]),
                "abstained": len([r for r in rows if r.abstained]),
            }
        return out


def run(
    split: str,
    k: int = DEFAULT_K,
    arms: Sequence[str] | None = None,
    bypass_gates: bool = False,
    benchmark: str = BENCHMARK,
) -> dict[str, Any]:
    """Score every arm over one split.

    `bypass_gates` is for the broken-ranker check only. It exists so a test can
    prove `must_not_expose_rate` fires, because a metric that cannot fire is
    not a check.
    """
    cases = load(split, benchmark)
    chosen = list(arms) if arms else list(ARMS)
    registry = {**ARMS, **BROKEN_ARMS}
    reports: dict[str, ArmReport] = {}
    for name in chosen:
        report = ArmReport(arm=name)
        for case in cases:
            # Wall clock around the arm only, not the scoring. Reported because
            # a selector that wins on nDCG and costs 500 ms a query has not
            # won; P9 was declined on a 4.39 ms figure that turned out to be
            # the wrong embedder's.
            started = time.perf_counter()
            ranked = registry[name](case, k)
            elapsed = (time.perf_counter() - started) * 1000.0
            if bypass_gates:
                allowed, refused = list(ranked), {}
            else:
                allowed, refused = apply_gates(case, ranked)
            scored = score_case(case, allowed, refused, k)
            scored.latency_ms = elapsed
            report.cases.append(scored)
        reports[name] = report
    return {
        "benchmark": benchmark,
        "split": split,
        "k": k,
        "cases": len(cases),
        "arms": {name: report.summary() for name, report in reports.items()},
        "timing": {name: report.timing() for name, report in reports.items()},
        "by_family": {name: report.by_family() for name, report in reports.items()},
        "_reports": reports,
    }


# --- reporting --------------------------------------------------------------


def headroom(result: Mapping[str, Any], metric: str = "ndcg_at_k") -> dict[str, float]:
    """The gap between the best simple baseline and the ceiling.

    The number this whole milestone exists to produce. A threshold for a ranker
    is a share of *this*, never an absolute margin — principle 8a, which came
    from H3 registering +0.030 when only +0.027 existed.
    """
    arms = result["arms"]
    simple = [n for n in arms if n not in (CEILING, "none")]
    best_simple = max(simple, key=lambda n: arms[n][metric]) if simple else None
    ceiling = arms[CEILING][metric]
    base = arms[best_simple][metric] if best_simple else 0.0
    return {
        "metric": metric,
        "best_simple_arm": best_simple or "",
        "best_simple": base,
        "ceiling": ceiling,
        "headroom": round(ceiling - base, 4),
    }


def to_markdown(result: Mapping[str, Any]) -> str:
    gap = headroom(result)
    lines = [
        f"# {result['benchmark']} — {result['split']} split",
        "",
        f"- **Arms:** {', '.join(result['arms'])}",
        f"- **Cases:** {result['cases']} · **k:** {result['k']}",
        "- **Deterministic** unless a `real_*` arm is present: those call an "
        "embedding model, and the rest are byte-identical across runs of one "
        "commit.",
        "",
        "## Arms",
        "",
        "| arm | nDCG@k | P@k | R@k | MRR | critical recall | critical omission | "
        "must-not-expose | irrelevant | abstain precision | false abstain |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for name, row in result["arms"].items():
        lines.append(
            f"| `{name}` | {row['ndcg_at_k']:.3f} | {row['precision_at_k']:.3f} | "
            f"{row['recall_at_k']:.3f} | {row['mrr']:.3f} | "
            f"{row['critical_recall']:.3f} | {row['critical_omission_rate']:.3f} | "
            f"**{row['must_not_expose_rate']:.3f}** | {row['irrelevant_ratio']:.3f} | "
            f"{row['abstention_precision']:.3f} | {row['false_abstention']:.3f} |"
        )
    has_sufficiency = any(
        row.get("sufficiency") is not None for row in result["arms"].values()
    )
    if has_sufficiency:
        lines += [
            "",
            "## Sufficiency, stale evidence and cost",
            "",
            "Ranking asks whether the arm ordered the corpus well. These ask "
            "whether the assembled context would support a defensible answer, "
            "whether any of it rests on a retracted source, and what it cost.",
            "",
            "| arm | sufficient | requirement recall | stale citation | "
            "stale cited / case | latency ms |",
            "|---|---|---|---|---|---|",
        ]
        for name, row in result["arms"].items():
            fmt = lambda v: "—" if v is None else f"{v:.3f}"  # noqa: E731
            lines.append(
                f"| `{name}` | {fmt(row.get('sufficiency'))} | "
                f"{fmt(row.get('requirement_recall'))} | "
                f"{fmt(row.get('stale_citation_rate'))} | "
                f"{fmt(row.get('stale_citations_mean'))} | "
                f"{result['timing'][name]['latency_ms']:.2f} |"
            )
        lines += [
            "",
            "`sufficient` is the share of cases where **every** critical "
            "evidence requirement was met by something the gates allowed. A "
            "requirement satisfiable only by a refused memory cannot be met, "
            "so an arm that bypasses a gate gains nothing here either. `—` "
            "means the benchmark declares no requirement of that kind, which "
            "is not the same as scoring zero.",
        ]

    lines += [
        "",
        "## Headroom",
        "",
        f"- Best simple baseline: `{gap['best_simple_arm']}` at {gap['best_simple']:.3f} {gap['metric']}",
        f"- Ceiling (`{CEILING}`): {gap['ceiling']:.3f}",
        f"- **Headroom: {gap['headroom']:+.3f}**",
        "",
        "A ranker's threshold is a share of that headroom, never an absolute "
        "margin (AGENTS.md principle 8a). The oracle runs through the same "
        "gates with the same `k`, so it scores below 1.0 wherever a gate "
        "refuses a memory the labels call relevant — correct behaviour, and "
        "headroom no ranker may reach (principle 8b).",
        "",
        "## By family",
        "",
    ]
    for name in result["arms"]:
        lines += [f"### `{name}`", "",
                  "| family | cases | nDCG | critical recall | violations | abstained |",
                  "|---|---|---|---|---|---|"]
        for family, row in result["by_family"][name].items():
            ndcg = "—" if row["ndcg"] is None else f"{row['ndcg']:.3f}"
            crit = "—" if row["critical_recall"] is None else f"{row['critical_recall']:.3f}"
            lines.append(
                f"| {family} | {row['cases']} | {ndcg} | {crit} | "
                f"{row['violations']} | {row['abstained']} |"
            )
        lines.append("")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--split", default="dev", choices=["dev", "test"])
    parser.add_argument("--benchmark", default=BENCHMARK, choices=sorted(BENCH_K))
    parser.add_argument(
        "--k", type=int, default=None,
        help="defaults to the benchmark's own k (see BENCH_K)")
    parser.add_argument("--arms", nargs="*", choices=list(ARMS) + list(BROKEN_ARMS))
    parser.add_argument(
        "--bypass-gates", action="store_true",
        help="skip the gate step; for the broken-ranker check only",
    )
    parser.add_argument("--out", help="write the Markdown report here")
    parser.add_argument("--json", dest="as_json", action="store_true")
    args = parser.parse_args(argv)

    k = args.k if args.k is not None else BENCH_K[args.benchmark]
    result = run(
        args.split, k=k, arms=args.arms, bypass_gates=args.bypass_gates,
        benchmark=args.benchmark,
    )
    serialisable = {k: v for k, v in result.items() if not k.startswith("_")}

    if args.as_json:
        print(json.dumps(serialisable, indent=2))
    else:
        print(to_markdown(result))

    scores = {name: row["ndcg_at_k"] for name, row in result["arms"].items()}
    held = True
    if CEILING in scores:
        print()
        held = report_ceiling(scores, CEILING)

    violations = {
        name: row["must_not_expose_rate"]
        for name, row in result["arms"].items()
        if row["must_not_expose_rate"] > 0
    }
    if violations:
        print("\n  GATE VIOLATIONS (a failure regardless of every other metric):")
        for name, rate in violations.items():
            print(f"    {name}: {rate:.3f}")

    if args.out:
        pathlib.Path(args.out).write_text(to_markdown(result) + "\n", encoding="utf-8")
        print(f"\n  wrote {args.out}")

    return 0 if held and not violations else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
