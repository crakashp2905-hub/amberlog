"""Retrieval: eligibility, search, ranking, lineage expansion, relations, defaults, grouping by source root, and evidence chains.

A service mixin of `MemoryFabric`, built on `FabricCore`. Methods moved here
verbatim from `fabric.py`.
"""

from __future__ import annotations

__stability__ = "stable"



from collections.abc import Set as AbcSet
from typing import TYPE_CHECKING, AbstractSet, Any, Callable, Iterable, Iterator, Mapping, Sequence, cast

if TYPE_CHECKING:
    from ..fabric import MemoryFabric  # noqa: F401
    pass

from .. import events as ev
from ..exposure import Candidate
from .. import chains
from .. import rerank as reranking
from .. import extraction as extracting
from ..relations import PULLS_IN_SUBJECT, RelationKind
from ..relevance import ReasonCode as _ReasonCode

from ..model import (
    BLOCKED_STATES,
    EXPLORATORY_STATES,
    EXPOSABLE_STATES,
    Memory,
    visible_to,
)
from ..vectors import (
    MIN_RELEVANCE,
    fuse,
)


from .core import FabricCore
from .common import PolicyViolation, RetrievalResult, _fresh


# `retrieve`'s defaults, for telling a profile setting from an explicit argument.
_RETRIEVE_DEFAULTS: dict[str, Any] = {
    "k": 5, "include_contested": False, "expand_lineage": 1, "follow_relations": False,
    "group_by_source_root": True, "min_relevance": MIN_RELEVANCE,
}


class Eligible(AbcSet):  # type: ignore[type-arg]
    """The memories a retrieval may consider, decided per memory rather than listed up front.

    `_eligible_ids` used to build this set by checking every memory in the
    store on every query, and the lexical index then copied it again; at
    20,000 memories that was most of what remained of a query's cost after
    the inverted index (research/results/product-bench.md). Membership is
    the same check on one memory, filters compose without copying, and the
    full list is built only if something iterates it.
    """

    def __init__(self, memories: Mapping[str, Memory],
                 predicates: tuple[Callable[[Memory], bool], ...]) -> None:
        self._memories = memories
        self._predicates = predicates
        self._listed: frozenset[str] | None = None

    def __contains__(self, memory_id: object) -> bool:
        memory = self._memories.get(memory_id) if isinstance(memory_id, str) else None
        return memory is not None and all(p(memory) for p in self._predicates)

    def _list(self) -> frozenset[str]:
        if self._listed is None:
            self._listed = frozenset(mid for mid, m in self._memories.items()
                                     if all(p(m) for p in self._predicates))
        return self._listed

    def __iter__(self) -> Iterator[str]:
        return iter(self._list())

    def __len__(self) -> int:
        return len(self._list())

    def narrow(self, predicate: Callable[[Memory], bool]) -> "Eligible":
        return Eligible(self._memories, self._predicates + (predicate,))

    @classmethod
    def _from_iterable(cls, it: Iterable[str]) -> set[str]:  # type: ignore[override]
        return set(it)

class RetrievalMixin(FabricCore):

    # --- the three mechanisms the store had and retrieval did not use -----
    #
    # `relevance_v1` found the five families with the largest oracle gap, and
    # three of them — indirect evidence, copied evidence, temporal drift — are
    # answerable with provenance edges, source roots and recorded time. All
    # three already existed; retrieval simply never consulted them.
    #
    # Each is **off by default** and measured as its own benchmark arm. Turning
    # one on by assumption is how a mechanism gets credit it has not earned,
    # which is the H2/H3/H4a pattern this project keeps recording.

    def _applicable_at(self, memory_ids: Iterable[str], when: int | None,
                       until: int | None = None) -> AbstractSet[str]:
        """Narrow by validity: a point in time, or a history through a time.

        `when` is **state at a point** -- `valid_from <= when < valid_to` --
        and `until` is **everything known through a point**, which ignores
        `valid_to` and keeps a claim that has since been superseded.

        The two are different questions and conflating them is measured to
        cost. On LongMemEval's temporal-reasoning questions -- "which did I do
        first, X or Y?" -- passing the question's own date as `when` discards
        **20% of the turns and 19 points of turn recall**, because the evidence
        for an ordering question is spread across the whole history and some of
        it postdates the moment the question is asked. `applies_at` is right
        and the call was wrong: a question about when things happened is not a
        question about what was true at a moment.

        Neither mode set does nothing, which is right for a task that does not
        say what time it is about. A memory with no window applies always, so a
        store written before 0.7.0 is unaffected.
        """
        if when is None and until is None:
            # Unchanged, and not copied: copying the eligible set was a pass
            # over every memory on every query.
            return memory_ids if isinstance(memory_ids, Eligible) else set(memory_ids)
        out = set()
        for memory_id in memory_ids:
            memory = self.state.memories[memory_id]
            if when is not None and not memory.applies_at(when):
                continue
            if until is not None:
                begins = memory.valid_from
                if begins is not None and begins > until:
                    continue
            out.add(memory_id)
        return out

    def source_root(self, memory_id: str) -> str:
        """The earliest observation this memory traces back to.

        Its own id when it has no parents. Used to tell corroboration from
        repetition: four memories quoting one report are one piece of evidence,
        and a context assembled from all four *looks* four times as supported.
        `relevance_v1`'s `copied_evidence` family is that case.

        The lexicographically smallest root when there are several, so the
        grouping key is deterministic — an id that varied by walk order would
        make deduplication depend on insertion order.

        **A recognised re-ingestion resolves to its original's root.** That is
        the whole of the fix for the one case [P3](../research/results/p3-correction-propagation.md)
        could not solve: a withdrawn document re-ingested under its own id was
        two roots and two votes, because provenance correctly recorded two
        ingestions and was correctly wrong about the evidence. Resolved here
        rather than at write time, so the copy keeps its own identity, its own
        provenance and its own place in the log, and only loses the claim to be
        independent support.
        """
        # Alternating resolution: follow a copy edge, then a lineage walk,
        # until neither moves. The first version resolved copies only for the
        # memory it was handed, so a conclusion *derived from a copy* still
        # reported the copy as its root -- the lineage walk found the copy, and
        # nothing resolved it onward to the original. Grouping then treated the
        # conclusion as independent of everything under the original's root,
        # which is the exact failure the copy relation exists to prevent, one
        # level down.
        seen: set[str] = set()
        current = memory_id
        while current not in seen:
            seen.add(current)
            original = self.state.copy_of.get(current)
            if original is not None and original not in seen:
                current = original
                continue
            roots = self.lineage_graph.roots(current)
            if not roots:
                return current
            candidate = min(roots)
            if candidate == current or candidate in seen:
                return candidate
            current = candidate
        return current

    def _group_by_root(
        self, ranked: Sequence[tuple[str, float]], limit: int
    ) -> list[tuple[str, float]]:
        """Keep the best-ranked memory per source root — **except** a premise
        of something already kept.

        The purpose is to stop copies counting as corroboration: four memories
        quoting one report are one piece of evidence, and a context assembled
        from all four *looks* four times as supported.
        `relevance_v1`'s `copied_evidence` family is that case.

        A premise and the conclusion drawn from it share a root and are **not**
        copies. Grouping them cost the whole lineage gain when both mechanisms
        were enabled: the `indirect` family scored 1.000 with lineage promotion
        alone and 0.613 with grouping as well, because grouping discarded
        exactly the premise promotion had just surfaced. The two mechanisms
        were undoing each other.

        So the rule is narrower than "one per root": a candidate is dropped
        only when something already kept shares its root *and* is not related
        to it by derivation. Copies collapse; evidence chains survive.

        Not content deduplication, deliberately. Two memories can be
        near-identical and independently observed, which is real
        corroboration, while two differently-worded memories can share one root
        and be none.
        """
        kept: list[tuple[str, float]] = []
        kept_by_root: dict[str, list[str]] = {}
        for memory_id, score in ranked:
            root = self.source_root(memory_id)
            siblings = kept_by_root.get(root, [])
            if siblings and not any(
                self._derivation_related(memory_id, other) for other in siblings
            ):
                continue
            kept.append((memory_id, score))
            kept_by_root.setdefault(root, []).append(memory_id)
            if len(kept) >= limit:
                break
        return kept

    def _derivation_related(self, left: str, right: str) -> bool:
        """Whether one of these is an ancestor of the other.

        Checked through the parent edges rather than by content, because that
        is the difference between "a conclusion and its premise" and "two
        copies of one report" — and only the first pair belongs in a context
        together.
        """
        graph = self.lineage_graph
        if any(node.memory_id == right for node in graph.ancestors(left)):
            return True
        return any(node.memory_id == left for node in graph.ancestors(right))

    def _expand_lineage(
        self,
        ranked: Sequence[tuple[str, float]],
        eligible: AbstractSet[str],
        limit: int,
        depth: int = 1,
    ) -> list[tuple[str, float]]:
        """**Promote** the premises of what was retrieved, not merely include them.

        A conclusion is not assessable without the premise it rests on, and no
        lexical or vector signal connects them: the premise may share no words
        with the task at all. `relevance_v1`'s `indirect` family is exactly
        that, and it is one of the largest oracle gaps.

        The first version of this only *appended* absent parents, and measured
        **exactly zero** effect — because the candidate pool is four times `k`
        and already contained the premise, ranked below the distractors. Adding
        something already present changes nothing. What the case needs is for a
        premise to be pulled *up* to sit beside the conclusion that depends on
        it, so this raises a parent's score to just under its child's whenever
        that is an increase.

        Bounded, and the bounds are the design: `depth` hops, `limit` results,
        parents only, and a parent is promoted once. An unbounded walk over a
        dense graph returns the store.

        The 0.99 factor keeps the child ahead of its own premise, so the
        ordering still reads as "the answer, then what it rests on".
        """
        if depth < 1:
            return list(ranked)
        scores = dict(ranked)
        order = [memory_id for memory_id, _ in ranked]
        frontier = list(order)
        promoted: set[str] = set()
        for _ in range(depth):
            next_frontier: list[str] = []
            for memory_id in frontier:
                child_score = scores.get(memory_id, 0.0)
                # `state.parents` holds ids, not (id, version) pairs — the
                # versions live on `state.parent_versions`. Sorted so the walk
                # is deterministic.
                for parent_id in sorted(self.state.parents.get(memory_id, ())):
                    if parent_id in promoted or parent_id not in eligible:
                        continue
                    if parent_id not in self.state.memories:
                        continue
                    promoted.add(parent_id)
                    inherited = child_score * 0.99
                    if scores.get(parent_id, -1.0) < inherited:
                        scores[parent_id] = inherited
                        if parent_id not in order:
                            order.append(parent_id)
                    next_frontier.append(parent_id)
            frontier = next_frontier
            if not frontier:
                break
        ordered = sorted(order, key=lambda mid: (-scores[mid], mid))
        return [(memory_id, scores[memory_id]) for memory_id in ordered][:limit]

    def _search(
        self,
        query: str,
        k: int,
        eligible: AbstractSet[str],
        min_relevance: float,
        method: str | None = None,
    ) -> list[tuple[str, float]]:
        """Candidate discovery, by configured mode (or `method` for this call).

        **`lexical` is the default, and it was `hybrid` until an external
        benchmark said otherwise.**

        `hybrid` is reciprocal-rank fusion of the vector and lexical arms, and
        it was chosen on `relevance_v1` because it beat vector-only and omitted
        fewer critical memories. On SciFact — 5,183 real abstracts, 339
        third-party judgements — it scores **0.558 nDCG@10 against lexical's
        0.621**, because the default embedder is a hashed bag of words scoring
        0.315 and RRF gives a near-noise arm real rank votes. Noise with a vote
        is worse than no vote.

        Not an isolated reading: on `relevance_v1`'s own expanded test split
        `lexical` scores 0.733 against hybrid's 0.693. **Lexical wins the
        held-out split of both benchmarks.**

        The rule is not "fusion is bad". On the same 300 SciFact queries with a
        *trained* embedder, the vector arm scores 0.701 and fusing it with
        lexical scores **0.726** — above published BM25 (~0.665). Fusion costs
        6.3 points with a hashed arm and gains 2.5 with a trained one, same
        mechanism, opposite sign. So `retrieval="hybrid"` is the measured
        recommendation once `embedder=` is a real model, and the rule is: do
        not fuse a weak arm into a strong one.

        `vector` reproduces the pre-2026-10-11 behaviour exactly, for anyone
        who needs the old ranking while validating.

        Numbers: `research/results/scifact-external.md` and
        `research/results/relevance-v1-real-embedder.md`.
        """
        mode = method or self.retrieval_mode
        if mode == "vector":
            return self.index.search(
                query, k=k, restrict_to=eligible, min_relevance=min_relevance
            )
        if mode == "lexical":
            return self.lexical.search(
                query, k=k, restrict_to=eligible, min_relevance=min_relevance
            )
        if mode != "hybrid":
            raise ValueError(
                f"unknown retrieval mode {mode!r}; expected hybrid, lexical or vector"
            )
        # Each arm is asked for the whole pool before fusion: truncating an arm
        # to k first would let a memory ranked k+1 by one arm and 1 by the
        # other drop out, which is exactly the case fusion exists to catch.
        dense = self.index.search(
            query, k=k, restrict_to=eligible, min_relevance=min_relevance
        )
        sparse = self.lexical.search(
            query, k=k, restrict_to=eligible, min_relevance=min_relevance
        )
        return fuse(dense, sparse, k=k)

    def _index(self, memory_id: str, text: str) -> None:
        """Both retrieval arms, always, plus the copy index.

        A memory indexed in one arm and not the other would make
        `retrieval_mode` change *what exists* rather than how it is ranked.

        The copy index is maintained here rather than in `remember` for the
        same reason: it is built on replay too, and a store whose copy index
        was populated only by live writes would stop recognising
        re-ingestions after a restart.
        """
        self.index.add(memory_id, text)
        self.lexical.add(memory_id, text)
        if self.recognise_copies:
            self.copy_index.add(memory_id, text)
        # Chain terms, cached for the same reason the IDF is: `reconstruct`
        # tokenised every candidate on every call, so a question over 413
        # turns cost 38.8 ms **before the search expanded a single node**.
        # Tokenisation does not depend on the query, so none of it needed
        # repeating.
        self.chain_terms[memory_id] = frozenset(chains.tokens(text))
        self.chain_plain[memory_id] = frozenset(
            t for t in self.chain_terms[memory_id] if not chains.is_numeric(t))

    def _unindex(self, memory_id: str) -> None:
        self.index.remove(memory_id)
        self.lexical.remove(memory_id)
        self.chain_terms.pop(memory_id, None)
        self.chain_plain.pop(memory_id, None)

    @staticmethod
    def _index_text(memory: Memory) -> str:
        """Context is indexed alongside content so retrieval is at least
        context-aware, even with the placeholder embedder."""
        parts = [memory.content]
        for key, value in sorted(memory.context.items()):
            if key == "tags" and isinstance(value, (list, tuple, set)):
                parts.extend(str(v) for v in value)
            else:
                parts.append(f"{key} {value}")
        return " ".join(parts)

    # --- retrieval -------------------------------------------------------

    @_fresh
    def retrieve(
        self,
        agent_id: str,
        query: str,
        context: Mapping[str, Any] | None = None,
        k: int = 5,
        episode_id: str | None = None,
        pool: int | None = None,
        include_contested: bool = False,
        step: int = 0,
        min_relevance: float = MIN_RELEVANCE,
        tenant_id: str | None = None,
        as_of: int | None = None,
        until: int | None = None,
        group_by_source_root: bool = True,
        expand_lineage: int = 1,
        follow_relations: bool = False,
        entities: Sequence[str] = (),
        use_extraction: bool = False,
        objective: Any = None,
        profile: str | None = None,
        method: str | None = None,
    ) -> RetrievalResult:
        """Retrieve, decide exposure, log both, return what was exposed.

        `profile` names a workload setting (`retrieval_profiles.PROFILES`:
        `precise`, `conversational`, `semantic`, `multi_hop`, `audit`), and
        `method` picks the ranking for this call only (`lexical`, `hybrid`,
        `vector`). An argument passed explicitly wins over the profile.

        `objective` (an `objective.MemoryObjective`) narrows the eligible set to
        what the session said is relevant, before ranking (M1).

        Candidates below `min_relevance` are not considered at all, so a query
        with nothing to match returns nothing rather than the least-bad rows in
        the store.

        `tenant_id` None searches every tenant, which is the operator view and
        the behaviour every single-tenant store has always had. A caller acting
        for one tenant should not be passing it by hand at all — use
        `for_tenant` or `as_principal`, which cannot be forgotten.

        **`group_by_source_root` and `expand_lineage` default on, because they
        were measured.** On `relevance_v1` the two together take this arm from
        0.752 to 0.795 nDCG@3 on dev and 0.658 to 0.732 on the frozen test
        split, with critical-memory omission falling from 0.214 to 0.143. Both
        can be switched off; the numbers are in
        `research/results/relevance-v1-ceiling.md` so the choice is informed.

        **`as_of` does not default**, and cannot. Defaulting it to `now` would
        make every historical question unanswerable — `temporal_drift-02` is
        the case: the same corpus, the opposite answer, because the task is
        about last year.

        **And a caller that knows its task's time should still think about
        which temporal question it is asking**, because passing the task's own
        event time is not always right. `as_of` means *state at a point*:
        `valid_from <= as_of < valid_to`. On LongMemEval's temporal-reasoning
        questions — "which did I do first, X or Y?" — doing that discards
        **20% of the turns and 19 points of turn recall**, because the evidence
        for an ordering question is spread across the whole history and some of
        it postdates the moment the question is asked
        (`research/results/longmemeval.md`). An earlier version of this
        docstring recommended passing the event time without qualification,
        and every internal benchmark agreed with it because none of them put
        evidence after the task's event time. It took an external benchmark to
        show the gap.

        So there are three temporal questions and the caller picks:

        * **what is true now, or was true at T** — `as_of=T`. Supersession applies.
        * **what did we know through T**, including claims since superseded — `until=T`. Half-open upper bounds are ignored.
        * **when did things happen** — neither. An ordering question needs the whole history, and filtering it is how 19 points go missing.
        """
        if profile is not None:
            from ..retrieval_profiles import resolve

            chosen = resolve(profile, getattr(self, "retrieval_profiles", None))
            defaults = _RETRIEVE_DEFAULTS
            given: dict[str, Any] = {"k": k, "include_contested": include_contested,
                     "expand_lineage": expand_lineage, "follow_relations": follow_relations,
                     "group_by_source_root": group_by_source_root, "min_relevance": min_relevance}
            for key, value in chosen.settings.items():
                if key in given and given[key] == defaults[key]:
                    given[key] = value
            k = given["k"]
            include_contested = given["include_contested"]
            expand_lineage = given["expand_lineage"]
            follow_relations = given["follow_relations"]
            group_by_source_root = given["group_by_source_root"]
            min_relevance = given["min_relevance"]
            if method is None:
                method = chosen.method
        eligible: AbstractSet[str] = self._eligible_ids(
            include_contested=include_contested, tenant_id=tenant_id,
            agent_id=agent_id,
        )
        pool_size = pool if pool is not None else max(k * 4, k)
        # Temporal applicability narrows the *eligible set*, before the index
        # is queried, for the reason the tenant filter does: a memory excluded
        # before ranking cannot be ranked, scored, logged or leaked by a bug
        # in a policy.
        eligible = self._applicable_at(eligible, as_of, until)
        eligible = self._without_hostile_sources(eligible)
        if objective is not None:
            # The session's own statement of relevance, at the same chokepoint
            # as tenancy and lifecycle, for the same reason: an excluded memory
            # is never ranked, exposed, or logged as a withheld candidate.
            eligible = (eligible.narrow(lambda m: objective.admits(m.context))
                        if isinstance(eligible, Eligible)
                        else {m for m in eligible
                              if objective.admits(self.state.memories[m].context)})
        hits = self._search(query, pool_size, eligible, min_relevance, method=method)
        if objective is not None and hasattr(objective, "rank"):
            # V2: evidence-aware ranking within what is eligible. It can only
            # re-order or drop, never add (`objective_v2.py`).
            hits = objective.rank(self, hits)
        if self.rerank:
            # After fusion and before grouping. Reranking a *fused* pool is
            # the claim under test -- that a reranker makes fusion safe -- so
            # it has to see what fusion produced, and grouping afterwards still
            # collapses copies in the new order.
            hits = reranking.rerank(
                query, hits,
                {mid: self.state.memories[mid].content for mid, _ in hits},
                self.lexical._idf(),
                mode=self.rerank if isinstance(self.rerank, str) else "tiebreak",
            )
        if expand_lineage:
            hits = self._expand_lineage(
                hits, eligible, limit=pool_size, depth=expand_lineage
            )
        if use_extraction:
            # Before relation-following, so a default admitted here can then
            # drag in whatever qualifies it.
            hits = self._admit_defaults(
                hits, eligible, entities, pool_size, k)
        if follow_relations:
            # After lineage expansion and before grouping: a qualifier should
            # travel with whatever it qualifies even if that arrived by
            # premise promotion, and grouping afterwards still collapses
            # copies in the new order.
            hits = self._follow_relations(hits, eligible, limit=pool_size)
        if group_by_source_root:
            hits = self._group_by_root(hits, limit=pool_size)

        # Only estimate values when the policy will actually rank on them.
        # Refitting the estimator on every retrieval and then ranking by
        # relevance is pure waste, and it grows with the log.
        wants_value = bool(getattr(self.policy, "needs_value", True))
        if wants_value:
            self._refresh_estimator()
        candidates: list[Candidate] = []
        for memory_id, score in hits:
            memory = self.state.memories[memory_id]
            candidates.append(
                Candidate(
                    memory_id=memory_id,
                    version=memory.version,
                    relevance=score,
                    value=self.estimator.estimate(memory_id, context) if wants_value else None,
                )
            )

        now = self.now()
        emitted: list[ev.Event] = [
            ev.retrieval_performed(
                ts=now,
                agent_id=agent_id,
                episode_id=episode_id,
                query=query,
                candidates=[(c.memory_id, c.version, c.relevance) for c in candidates],
                context=context,
            )
        ]

        decisions = self.policy.decide(candidates, k, self.rng)
        result = RetrievalResult(policy_id=self.policy.id)
        for decision in decisions:
            candidate = decision.candidate
            emitted.append(
                ev.exposure_decided(
                    ts=now,
                    agent_id=agent_id,
                    episode_id=episode_id,
                    memory_id=candidate.memory_id,
                    version=candidate.version,
                    exposed=decision.exposed,
                    propensity=decision.propensity,
                    policy_id=self.policy.id,
                    step=step,
                )
            )
            memory = self.state.memories[candidate.memory_id]
            result.scores[candidate.memory_id] = candidate.relevance
            (result.exposed if decision.exposed else result.withheld).append(memory)

        self._emit(*emitted)
        return result

    @_fresh
    def reconstruct(
        self,
        agent_id: str,
        query: str,
        k: int = chains.MAX_STEPS,
        episode_id: str | None = None,
        tenant_id: str | None = None,
        as_of: int | None = None,
        until: int | None = None,
        include_contested: bool = False,
        follow_relations: bool = False,
        max_steps: int = chains.MAX_STEPS,
        beam: int = chains.BEAM,
        node_budget: int = chains.NODE_BUDGET,
        deadline_ms: float | None = None,
    ) -> "chains.EvidenceChain":
        """Reconstruct a connected chain of **currently valid** evidence.

        For the question `retrieve` cannot answer: one where no single memory
        matches, because the answer is distributed across several and the
        memory in the middle shares no word with the query.

        Measured need, not a speculative feature. `multi_hop_4` sufficiency is
        **0.000** for every arm that ranks candidates independently, against an
        oracle's 1.000, and a coverage-greedy selector scored 0.000 too because
        a connector's marginal query-term coverage is zero
        (`research/results/p2-context-sufficiency.md`). Premise promotion lifts
        the same family from 0.330 to 0.519 nDCG and cannot start from a query
        that matches nothing, because it promotes a parent only once the child
        has already ranked.

        **The candidate set is the eligible set, not the search results.** A
        connector scores zero on the index, so a candidate list taken from
        `_search` would not contain the one memory this method exists to find —
        the defect that made an earlier experiment's own oracle score 0.000 on
        both chain families. Ranking supplies the order; eligibility supplies
        the pool.

        **Validity is by construction.** The pool is what `_eligible_ids` and
        `_applicable_at` produce, so a retracted memory, a contested descendant
        of one, a wrong-tenant memory, an unauthorised one and a memory outside
        its validity interval are never nodes in the graph. Same argument
        `_eligible_ids` makes for itself: a memory excluded before the search
        cannot be reached by a bug in the search.

        An **incomplete** chain is a real answer rather than a failure. It names
        the query terms nothing could supply, which is the shape of "the corpus
        does not join up"; `complete` stays False so a caller cannot mistake one
        for the other, and deciding whether that means abstain is the caller's.

        Every step carries why it is there and a leave-one-out necessity
        verdict — see `chains.EvidenceChain.why`.
        """
        eligible: AbstractSet[str] = self._eligible_ids(
            include_contested=include_contested, tenant_id=tenant_id,
            agent_id=agent_id,
        )
        eligible = self._applicable_at(eligible, as_of, until)
        if not eligible:
            return chains.EvidenceChain()

        # Ranked first, then everything else eligible in a stable order. The
        # tail is where connectors live.
        scored = self._search(query, len(eligible), eligible, 0.0)
        relevance = {memory_id: score for memory_id, score in scored}
        ordered = [memory_id for memory_id, _ in scored]
        seen = set(ordered)
        ordered += sorted(memory_id for memory_id in eligible if memory_id not in seen)

        # `chains.tokens`, not the lexical index's: identifiers must stay
        # whole or the graph's edges stop meaning "about the same thing".
        # Read from the cache `_index` maintains, falling back for a memory
        # written before the cache existed in this process.
        terms = {
            memory_id: self.chain_terms.get(memory_id)
            or frozenset(chains.tokens(self.state.memories[memory_id].content))
            for memory_id in ordered
        }
        # Query terms some candidate actually contains. A term nothing supplies
        # cannot be covered, and demanding it would make every chain
        # incomplete -- the defect that once abstained on 79% of answerable
        # cases.
        present: set[str] = set()
        for tokens in terms.values():
            present.update(tokens)
        need = [t for t in chains.tokens(query) if t in present]

        chain = chains.search(
            ordered, terms, need,
            max_steps=max_steps, beam=beam, node_budget=node_budget,
            relevance=relevance,
            plain=self.chain_plain,
            deadline_ms=deadline_ms,
        )
        if follow_relations and chain.steps:
            # A qualifier is not reachable by the search: it supplies no query
            # term, so it has no coverage to gain, and it links nothing the
            # chain needs, so it is not a bridge either. That is exactly why
            # `multi_hop_4` fails -- the memory that *modifies* the answer is
            # invisible to coverage and connectedness both. A declared relation
            # is the only thing that can put it in.
            extra: list[chains.ChainStep] = []
            present = {step.memory_id for step in chain.steps}
            for step in chain.steps:
                for kind in PULLS_IN_SUBJECT:
                    for subject in sorted(
                        self.state.related_to.get(
                            (step.memory_id, kind.value), ())
                    ):
                        if subject in present or subject not in eligible:
                            continue
                        present.add(subject)
                        extra.append(chains.ChainStep(
                            memory_id=subject,
                            reason=_ReasonCode.DEPENDENCY_REQUIRED,
                            covers=(),
                            bridges=(),
                            # Necessary by declaration rather than by
                            # leave-one-out: a qualification changes the
                            # answer, so the chain is wrong without it in a way
                            # the coverage test cannot see.
                            necessary=True,
                            rank=-1,
                        ))
            if extra:
                chain = chains.EvidenceChain(
                    steps=chain.steps + tuple(extra),
                    covered=chain.covered, missing=chain.missing,
                    nodes_explored=chain.nodes_explored,
                    budget_exhausted=chain.budget_exhausted,
                    connected=chain.connected,
                )

        if k is not None and len(chain.steps) > k:
            # Truncating can only break a chain, so `connected` is
            # recomputed rather than carried over -- a k that cuts the
            # connector out must not leave the result claiming to hold
            # together.
            kept = chain.steps[:k]
            chain = chains.EvidenceChain(
                steps=kept, covered=chain.covered,
                missing=chain.missing, nodes_explored=chain.nodes_explored,
                budget_exhausted=chain.budget_exhausted,
                connected=chains._connected(
                    [s.memory_id for s in kept],
                    {
                        s.memory_id: (
                            self.chain_plain.get(s.memory_id, frozenset())
                            - set(need)
                        )
                        for s in kept
                    },
                ),
            )

        now = self.now()
        emitted: list[ev.Event] = [
            ev.retrieval_performed(
                ts=now, agent_id=agent_id, episode_id=episode_id, query=query,
                candidates=[
                    (step.memory_id, self.state.memories[step.memory_id].version,
                     relevance.get(step.memory_id, 0.0))
                    for step in chain.steps
                ],
                context=None,
            )
        ]
        for step in chain.steps:
            emitted.append(ev.exposure_decided(
                ts=now, agent_id=agent_id, episode_id=episode_id,
                memory_id=step.memory_id,
                version=self.state.memories[step.memory_id].version,
                exposed=True,
                # Deterministic search, so the propensity is 1.0 and is
                # recorded rather than omitted. Principle 4 is unconditional:
                # without a logged propensity this exposure cannot carry credit
                # later, and "it was deterministic" is a value, not an excuse
                # to leave the field empty.
                propensity=1.0,
                policy_id=f"chain/beam={beam},steps={max_steps}",
                step=0,
            ))
        self._emit(*emitted)
        return chain

    def index_extraction(self, record: "extracting.Extracted") -> None:
        """Record the structure extracted from a memory.

        Separate from `remember` on purpose. Extraction is one model call per
        memory, so putting it on the write path would make every write depend
        on a model being reachable — and the registered prediction is that the
        cost makes it a batch job. Indexing it afterwards keeps that a
        deployment's decision.
        """
        self._require(record.memory_id)
        self.extracted[record.memory_id] = record

    def _admit_defaults(
        self, ranked: Sequence[tuple[str, float]], eligible: AbstractSet[str],
        entities: Sequence[str], limit: int, k: int | None = None,
    ) -> list[tuple[str, float]]:
        """Add default rules and scoped adjustments that cover the asked entities.

        The `implied_by_default` mechanism, and the one a memory-to-memory
        relation could not provide: *"all yard vehicles run 3.9 bar in winter,
        except at the harbour and quarry sites"* names neither the unit nor the
        site asked about, so it is **not similar to the query** and no ranking
        can surface it. Its applicability is a property of what it *excludes*,
        which is a fact about the record rather than a relation between two
        memories (`research/results/relations-ceiling.md` section 3).

        **Admitted inside the exposed set, which the first version was not.**
        A default has no similarity score to compete on, so the first version
        appended it below everything in the candidate pool and called that
        neutral. It is not neutral: the pool is `max(k * 4, k)` and the policy
        then exposes the top `k`, so an admitted memory was ranked 21st of 21
        for a k of 5 and could never be exposed. The mechanism was inert in any
        store large enough to have a pool, and its unit test passed because
        that store held **one memory**.

        So an admitted record is placed just above the weakest candidate that
        would otherwise be exposed, which makes a design claim worth stating
        rather than burying: **an applicable rule is worth more than the k-th
        similarity match.** That is the whole point of admitting it — a rule
        that names neither the unit nor the site asked about cannot win on
        similarity, and if it loses to the k-th nearest neighbour it will never
        be seen.

        At most `k - 1` records are admitted, so at least one similarity match
        survives and a query matching many rules cannot have its context
        replaced by them.

        **And it drops a default that does not apply**, which is the half the
        first version missed. A rule saying *"except at the harbour site"*
        shares enough words with a question about the harbour site to be
        retrieved by similarity, and serving it there is not an incomplete
        answer but a wrong one. Applicability has to exclude as well as admit,
        or the mechanism only ever adds.
        """
        if not entities or not self.extracted:
            return list(ranked)
        wanted = [e for e in entities if e]
        out: list[tuple[str, float]] = []
        for memory_id, score in ranked:
            record = self.extracted.get(memory_id)
            if (record is not None and record.is_default
                    and not record.applies_to(wanted)):
                continue
            out.append((memory_id, score))
        present = {memory_id for memory_id, _ in out}
        records = [r for mid, r in self.extracted.items() if mid in eligible]
        # Defaults *and* scoped adjustments, by the same rule and for the same
        # reason. A default is reached through what it excludes; an adjustment
        # through what it scopes to. Neither is similar to the query and
        # neither is a relation between two memories -- twelve adjustments in
        # one corpus differ only by site name, so each qualifies every rule
        # equally and only the query says which applies. Admitting defaults
        # alone left every adjustment unreachable, which is why X1's mechanism
        # scored 0.000 with correct extractions
        # (`research/results/x1-extraction.md` section 11).
        candidates = list(extracting.applicable_defaults(records, wanted))
        candidates += [
            memory_id
            for memory_id in extracting.applicable_adjustments(records, wanted)
            if memory_id not in candidates
        ]
        # Every applicable record is promoted, **not only the ones similarity
        # missed entirely**. The first version appended only records absent
        # from the pool, so a record that ranked 6th of 60 -- inside the pool
        # of 20, outside the exposed 5 -- kept its losing similarity score and
        # was cut, while the same record in a larger store ranked below the
        # pool, counted as new, and was admitted. The mechanism helped only
        # when similarity failed *completely*, and the symptom was a
        # sufficiency that went **down** as the corpus grew: 1.000 at 486
        # memories and 0.333 at 60. Admission is a statement that the record
        # applies, which does not depend on where similarity put it.
        fresh = list(candidates)
        if not fresh:
            return out[:limit]
        out = [(m, score) for m, score in out if m not in set(fresh)]

        # The score that lands a record inside the exposed set: just above the
        # weakest candidate the policy would otherwise expose. Without `k` --
        # an older caller -- fall back to the previous behaviour rather than
        # guessing a budget.
        if k is None or k <= 0:
            floor = out[-1][1] if out else 1.0
            bump = 0.0
        else:
            exposed = [score for _m, score in out[:k]]
            floor = exposed[-1] if exposed else 1.0
            bump = 1e-6

        # Recompute the floor after removing the promoted records, so a
        # record already in the exposed set does not set its own floor.
        if k is not None and k > 0:
            exposed = [score for _m, score in out[:k]]
            floor = exposed[-1] if exposed else floor
        room = max(0, (k - 1) if k else len(fresh))
        for position, memory_id in enumerate(fresh[:room] if k else fresh):
            present.add(memory_id)
            # Descending by a hair so the admitted records keep a stable order
            # among themselves and the sort is deterministic.
            out.append((memory_id, floor + bump * (len(fresh) - position)))
        out.sort(key=lambda row: (-row[1], row[0]))
        return out[:limit]

    @_fresh
    def relate(
        self,
        subject_memory_id: str,
        kind: str | RelationKind,
        object_memory_id: str,
        actor: str = "operator",
    ) -> None:
        """Declare a typed relation that is not a derivation.

        `memory_fabric/relations.py` has the three kinds and why each exists.
        Deliberately **not** a parent edge: `_group_by_root` spares anything
        derivation-related to a kept memory, so a qualification recorded as a
        parent would inherit an exemption meant for premises.

        Nothing discovers these. A caller declares them, or an extraction step
        at ingest does, and this project has measured neither — the first
        measurement is a ceiling given perfect declarations, because the two
        families they target are text its own generators wrote and a pattern
        fitted to that phrasing would pass by construction
        (`research/results/relations-ceiling.md`).
        """
        self._require(subject_memory_id)
        self._require(object_memory_id)
        if subject_memory_id == object_memory_id:
            raise PolicyViolation("a memory cannot stand in a relation to itself")
        self._emit(ev.memories_related(
            ts=self.now(), actor=actor,
            subject_memory_id=subject_memory_id,
            kind=RelationKind(kind).value,
            object_memory_id=object_memory_id,
        ))

    @_fresh
    def relations_of(self, memory_id: str, kind: str | RelationKind
                     ) -> list[str]:
        """Objects this memory stands in `kind` to. Content-free."""
        return sorted(
            self.state.relations.get((memory_id, RelationKind(kind).value), ()))

    def _follow_relations(
        self, ranked: Sequence[tuple[str, float]], eligible: AbstractSet[str],
        limit: int,
    ) -> list[tuple[str, float]]:
        """Pull in whatever qualifies a selected memory.

        Towards the qualifier, not away from it: a qualification changes the
        answer, so its absence makes the answer *wrong* rather than
        incomplete. Placed just below the memory it qualifies, so it travels
        with it rather than competing with it on a score it was never given.

        `EXCEPTS` is not followed here on purpose — an exception is a reason
        *not* to use a rule, and pulling it in on selection would add a memory
        arguing against the one beside it. Its use is deciding applicability,
        which is a different step.
        """
        if not ranked:
            return list(ranked)
        out: list[tuple[str, float]] = []
        present = {memory_id for memory_id, _ in ranked}
        for memory_id, score in ranked:
            out.append((memory_id, score))
            for kind in PULLS_IN_SUBJECT:
                for subject in sorted(
                    self.state.related_to.get((memory_id, kind.value), ())
                ):
                    if subject in present or subject not in eligible:
                        continue
                    present.add(subject)
                    out.append((subject, score * (1 - 1e-6)))
        return out[:limit]

    def _eligible_ids(
        self, include_contested: bool = False, tenant_id: str | None = None,
        agent_id: str | None = None,
    ) -> "Eligible":
        """The one chokepoint every retrieval narrows through.

        The tenant filter belongs here rather than after ranking, for the same
        reason the lifecycle filter does: a memory excluded *before* the index
        is queried cannot be ranked, cannot be scored, cannot appear in a
        `RetrievalPerformed` event and cannot leak through a bug in a policy.
        Filtering afterwards would put the boundary downstream of the code most
        likely to be wrong.
        """
        allowed = set(EXPOSABLE_STATES)
        if include_contested:
            allowed |= EXPLORATORY_STATES
        state = self.state

        def admits(memory: Memory) -> bool:
            return (memory.lifecycle_state in allowed
                    and memory.lifecycle_state not in BLOCKED_STATES
                    and (tenant_id is None or memory.tenant_id == tenant_id)
                    and visible_to(memory, agent_id, state))

        return Eligible(state.memories, (admits,))

    def hostile_authors(self) -> frozenset[str]:
        """Authors caught injecting, here or by a peer's authenticated notice. Cached per log head."""
        from .. import hindsight

        head = self._seen_seq
        if self._hostile_cache[0] != head:
            self._hostile_cache = (head, frozenset(
                hindsight.discredited_authors(cast("MemoryFabric", self), hindsight.HOSTILE, federated=True)))
        return self._hostile_cache[1]

    def _without_hostile_sources(self, eligible: AbstractSet[str]) -> AbstractSet[str]:
        if not self.withhold_hostile_sources:
            return eligible
        bad = self.hostile_authors()
        if not bad:
            return eligible
        from ..hindsight import author

        if isinstance(eligible, Eligible):
            return eligible.narrow(lambda m: author(m) not in bad)
        return {m for m in eligible if author(self.state.memories[m]) not in bad}
