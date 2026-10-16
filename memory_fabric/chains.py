"""Bounded search for a connected chain of evidence.

Selecting memories by individual relevance cannot answer a question whose
answer is distributed across several of them. Three measurements say so and
agree on why:

- `multi_hop_4` sufficiency is **0.000** for every arm that ranks candidates
  independently, against an oracle's 1.000 (`research/results/p2-context-sufficiency.md`).
- `multi_hop_4` nDCG@5 is 0.330 for lexical retrieval and 0.519 with premise
  promotion enabled (`research/results/relevance-v2-ceiling.md`).
- A coverage-greedy selector also scored 0.000, because a chain's middle hop
  has **zero marginal query-term coverage**: in "what pressure should the
  vehicle in bay 7 run in winter", the hop that says *"tug-3 was re-fitted with
  the heavy axle set"* contains no query token at all. Its whole value is
  joining the hop that names the bay to the hop that names the pressure.

So the missing thing is search over the graph the memories induce, and the unit
of the answer is a **set**, not a ranking.

## What this module is, and is not

It is a **bounded beam search** over candidate memories. Bounded is part of the
claim rather than a caveat: an unbounded graph search over a few hundred
candidates is not a retrieval mechanism, so every result carries
`nodes_explored` and whether the budget stopped it.

It is **not** a ranker and does not replace one. It consumes a ranked candidate
list and the terms of each candidate, and returns a connected subset. Callers
that want an ordering still want `retrieve`.

## Validity is the caller's to enforce, and the fabric does

This module never sees a lifecycle state, a tenant or a capability. It searches
whatever candidate set it is handed, and `MemoryFabric.reconstruct` hands it
the set `_eligible_ids` and `_applicable_at` have already narrowed — so a
retracted memory, a contested descendant of one, a wrong-tenant memory, an
unauthorised one and a memory outside its validity interval are never nodes in
the graph.

That ordering matters and is the same argument `_eligible_ids` makes for
itself: a memory excluded *before* the search cannot be reached by a bug in the
search. A chain filtered after the fact would put the boundary downstream of
the code most likely to be wrong.

## Necessity is computed, not asserted

A step is necessary iff removing it from the returned chain either leaves a
query term uncovered or disconnects what remains. Leave-one-out over the chain
itself, so the explanation is checkable against the chain a caller actually
received rather than being a story composed afterwards.

This is deliberately conservative. Where two memories each supply the same
term, neither is individually necessary and both are reported as supporting —
which is correct, and means necessity recall against a labelled critical set
will be below 1.0 by construction.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Callable, Iterable, Mapping, Sequence

from .relevance import ReasonCode
from .vectors import _STOPWORDS

# Identifiers stay whole. `LexicalIndex` tokenises on `[a-z0-9]+`, which is
# right for ranking -- "tug-3" matching a query that says "tug 3" is a feature
# there -- and wrong here, because it destroys the thing a chain search runs
# on. Split that way, "tug-3" yields "tug" and "3", and "3.0 bar" also yields
# "3", so the first version of this search joined "Bay 7 ... assigned to tug-3"
# to "Vehicles with the light axle set run 3.0 bar" through the token "3" and
# returned the wrong answer in two confident steps.
#
# An edge in this graph is a claim that two memories are about the same thing.
# A bare digit is not that claim.
_TOKEN = re.compile(r"[a-z0-9]+(?:[-.][a-z0-9]+)*")
_NUMERIC = re.compile(r"^[0-9]+(?:[.][0-9]+)?$")


def tokens(text: str) -> list[str]:
    """Content terms, with hyphenated and dotted identifiers preserved."""
    return [t for t in _TOKEN.findall(text.lower()) if t not in _STOPWORDS]


def is_numeric(term: str) -> bool:
    """A bare number, which may cover a query term but never link two memories.

    Exported so a caller can precompute the non-numeric sets once per memory
    instead of running the test inside the search's inner loop, where it
    accounted for 423,918 regex matches in three reconstructions.
    """
    return bool(_NUMERIC.match(term))

# Defaults. Chosen from the structure of the measured problem, not tuned on a
# metric: the deepest labelled chain in `relevance_v2` is four memories, so a
# five-step cap admits it with one spare, and the node budget is ~2x the
# largest candidate pool a single case presents.
MAX_STEPS = 5
BEAM = 8
NODE_BUDGET = 2_000
"""Backstop on generated successor states.

It used to be the primary bound and was wrong twice over. Expansion scanned
every candidate for every state in the beam, so one round over 495 candidates
with a beam of 8 cost ~3,960 against a budget of 2,000: the search died
*mid-round*, having never looked past the first few hundred candidates, and
returned a one-memory chain while reporting `budget_exhausted`. Successor
generation is now bounded by `beam` per state, which caps a whole search at
`beam * beam * max_steps` states regardless of corpus size, and this is only a
guard against a pathological graph.
"""


@dataclass(frozen=True)
class ChainStep:
    """One memory in a chain, with why it is there.

    `covers` are query terms this memory supplies and `bridges` are the terms
    that connect it to the rest of the chain. A connector has an empty `covers`
    and a non-empty `bridges`, which is exactly the memory every
    relevance-ranked arm misses.
    """

    memory_id: str
    reason: ReasonCode
    covers: tuple[str, ...]
    bridges: tuple[str, ...]
    necessary: bool
    rank: int
    """Position in the candidate ranking the search was given. A connector
    typically sits deep, which is the quantitative form of "no single memory
    matches the query"."""


@dataclass(frozen=True)
class EvidenceChain:
    steps: tuple[ChainStep, ...] = ()
    covered: tuple[str, ...] = ()
    missing: tuple[str, ...] = ()
    nodes_explored: int = 0
    budget_exhausted: bool = False
    connected: bool = True
    """Whether the steps form one component under shared non-query terms.

    Reported separately from `missing` because a covering set whose members are
    unrelated fails for a different reason than an under-covering one, and the
    remedies differ: the first needs a memory that joins what was found, the
    second needs a memory nothing in the corpus supplies.
    """

    @property
    def complete(self) -> bool:
        """Every reachable query term covered, by a chain that holds together.

        Both halves are required. Coverage alone admitted two memories that
        between them used every query word and had nothing to do with each
        other -- see the note on `rank_key`.
        """
        return bool(self.steps) and not self.missing and self.connected

    @property
    def memory_ids(self) -> tuple[str, ...]:
        return tuple(step.memory_id for step in self.steps)

    @property
    def necessary_ids(self) -> tuple[str, ...]:
        return tuple(s.memory_id for s in self.steps if s.necessary)

    def why(self, memory_id: str) -> str:
        """A one-line account of this memory's role, for an operator.

        Generated from the search's own record rather than written after the
        fact, which is the same rule `ReasonCode` is under: an explanation
        composed later is a plausible story, not a decision path.
        """
        step = next((s for s in self.steps if s.memory_id == memory_id), None)
        if step is None:
            return f"{memory_id} is not in this chain"
        need = "necessary" if step.necessary else "supporting"
        if step.covers:
            what = "supplies " + ", ".join(step.covers)
        else:
            what = "supplies no query term directly"
        link = (" and links to the chain through " + ", ".join(step.bridges)
                if step.bridges else "")
        return f"{memory_id} ({need}, rank {step.rank}): {what}{link}"


@dataclass
class _State:
    ids: tuple[str, ...]
    covered: frozenset[str]
    cost: float
    terms: frozenset[str] = field(default_factory=frozenset)
    links: frozenset[str] = field(default_factory=frozenset)
    """The union of the chain's *linkable* terms: content terms that are
    neither query terms nor bare numerals.

    Carried on the state so an edge test is one set operation. Profiling found
    `_bridge_terms` taking 60% of a search -- 35,000 calls a query, each
    running the numeric regex once per shared term, 423,918 matches in three
    reconstructions. None of that work depends on the pair being compared, so
    all of it is done once up front.
    """


def _bridge_terms(left: frozenset[str], right: frozenset[str],
                  need: frozenset[str]) -> frozenset[str]:
    """Shared terms that are *not* query terms and not bare numbers.

    A connector is joined to the chain by something the query never mentions —
    a vehicle id, a component name. Counting query terms as bridges would make
    every pair of query-matching memories look connected and the search would
    stop needing the connector at all.

    Bare numerals are excluded as well, and that exclusion is load-bearing
    rather than tidy: two memories sharing "3" or "400" are not thereby about
    the same thing, and the first version of this search produced a confident
    wrong answer by treating one as a link. A number can still *cover* a query
    term — "bay 7" needs the 7 — it just cannot be the evidence that two
    memories belong together.
    """
    return {t for t in (left & right) - need if not _NUMERIC.match(t)}


def search(
    candidates: Sequence[str],
    terms: Mapping[str, Iterable[str]],
    need: Iterable[str],
    *,
    max_steps: int = MAX_STEPS,
    beam: int = BEAM,
    node_budget: int = NODE_BUDGET,
    relevance: Mapping[str, float] | None = None,
    plain: Mapping[str, frozenset[str]] | None = None,
    deadline_ms: float | None = None,
) -> EvidenceChain:
    """Find a small connected set of `candidates` covering `need`.

    `candidates` is in ranked order, best first; `terms` maps each candidate to
    its content terms; `need` is the query terms that some candidate contains.
    Nothing here knows about memories, lifecycles or stores, so the whole
    search is testable on plain strings — which is how the connector case is
    pinned down without standing up a fabric.

    Returns the chain, or an incomplete one naming what it could not cover. An
    incomplete chain is a real answer: it is the shape of "the corpus does not
    join up", and the caller decides whether that means abstain.

    `deadline_ms` adds a wall-clock budget to the node budget. When it runs out,
    the search stops the way it does on `node_budget`: it reports the best
    partial chain with `budget_exhausted` set. Off by default, because a
    wall-clock limit makes the result depend on machine load, and every
    measured result in this repository is deterministic.
    """
    deadline = None if deadline_ms is None else time.perf_counter() + deadline_ms / 1000.0
    need_set = frozenset(need)
    term_sets = {c: frozenset(terms.get(c, ())) for c in candidates}
    rank_of = {c: i for i, c in enumerate(candidates)}
    score = relevance or {}

    if not need_set:
        return EvidenceChain(missing=())

    # Seeds: candidates that supply at least one query term. A chain has to be
    # anchored somewhere the query actually reaches; starting from a connector
    # would mean searching outward from a memory with no reason to be there.
    seeds = [c for c in candidates if term_sets[c] & need_set][:beam]
    if not seeds:
        return EvidenceChain(missing=tuple(sorted(need_set)))

    # How many candidates contain each term. Used only to rank bridges, so a
    # link through a near-ubiquitous word loses to a link through an identifier.
    doc_freq: dict[str, int] = {}
    for tokens_of in term_sets.values():
        for term in tokens_of:
            doc_freq[term] = doc_freq.get(term, 0) + 1

    # Linkable terms, once per candidate rather than once per comparison. A
    # query term cannot be a link (every query-matching pair would look
    # joined) and nor can a bare numeral (two memories sharing "3" are not
    # thereby about the same thing).
    # `plain` is the caller's cache of each candidate's non-numeric terms, so
    # the only per-query work is removing the query's own terms -- one set
    # difference instead of a regex pass. Computed here when absent, which is
    # what a direct `search()` call in a test does.
    links = {
        candidate: (plain[candidate] - need_set) if plain and candidate in plain
        else frozenset(
            t for t in tokens if t not in need_set and not _NUMERIC.match(t))
        for candidate, tokens in term_sets.items()
    }

    frontier = [
        _State(ids=(c,), covered=term_sets[c] & need_set,
               cost=1.0 - score.get(c, 0.0), terms=term_sets[c],
               links=links[c])
        for c in seeds
    ]
    explored = 0
    exhausted = False
    best: _State | None = None

    def connected(state: _State) -> bool:
        return _connected(state.ids, links)

    def rank_key(state: _State) -> tuple:
        # Coverage first, then **connectedness**, then length, then relevance.
        #
        # Connectedness has to be in here and in the goal test, not just
        # rewarded. The first version of this search scored coverage alone and
        # returned `h1 + h3` for a three-hop question: between them those two
        # mention every query term, they share nothing with each other, and the
        # memory that joins them -- "tug-3 was re-fitted with the heavy axle
        # set" -- was skipped. A covering set whose members are unrelated is
        # not a chain of evidence, it is two unrelated facts that happen to use
        # the right words.
        return (-len(state.covered), not connected(state), len(state.ids),
                state.cost)

    while frontier:
        frontier.sort(key=rank_key)
        frontier = frontier[:beam]
        for state in frontier:
            if state.covered == need_set and connected(state) and (
                best is None
                or (len(state.ids), state.cost) < (len(best.ids), best.cost)
            ):
                best = state
        if best is not None:
            break

        nxt: list[_State] = []
        for state in frontier:
            if len(state.ids) >= max_steps:
                continue
            still_needed = need_set - state.covered
            # The component of each member, computed **once**. The first
            # version called `_joins` per candidate and `_joins` computed the
            # components twice, so expansion was O(candidates x state^2) and
            # the cost tracked **query length** rather than corpus size: on
            # LongMemEval a 6-token question cost 34 ms and a 17-token one 182
            # ms over the same ~500 candidates, because a longer query admits
            # more bridge candidates and each one re-walked the whole state.
            #
            # A candidate joins the chain iff its bridge terms touch two
            # different components, which is one pass over the state.
            component_of = _components_of(state.ids, links)
            state_connected = len(set(component_of.values())) <= 1

            # Two kinds of successor, ranked separately and then capped, which
            # is what bounds the search independently of corpus size.
            covering: list[tuple[tuple, str]] = []
            bridging: list[tuple[tuple, str]] = []
            for candidate in candidates:
                if candidate in state.ids:
                    continue
                cand_terms = term_sets[candidate]
                gain = (cand_terms & need_set) - state.covered
                if gain:
                    covering.append(((-len(gain), rank_of[candidate]), candidate))
                    continue
                if not still_needed and state_connected:
                    # Complete and joined up: this state is already a goal, and
                    # a memory adding no query term could only lengthen it.
                    #
                    # The `state_connected` half is not a refinement, it is the
                    # whole case the mechanism exists for. A covering but
                    # disconnected pair needs exactly one more memory -- the
                    # connector -- and skipping bridges on completeness alone
                    # made that memory unreachable.
                    continue
                bridges = links[candidate] & state.links
                if not bridges:
                    continue
                # A connector supplies no query term by definition, so the
                # earlier rule -- admit a bridge only while the chain is
                # *disconnected* -- could never fire where it mattered: a
                # one-memory state is trivially connected, so the first hop
                # could never reach its own connector. The condition is instead
                # that coverage is still incomplete.
                #
                # Ranked by the **rarest** shared term. A term appearing in
                # four hundred of five hundred memories is not evidence that
                # two of them are about the same thing; "chiller-1" is. No
                # threshold, so nothing is tuned: the search simply prefers the
                # most discriminating links and takes a bounded number of them.
                # Joining a split chain is worth more than extending a whole
                # one, so a bridge that reduces the number of components sorts
                # first. Without this the search spends its bridge budget on
                # memories that merely share a word with something already in.
                touched = {
                    component_of[other] for other in state.ids
                    if not links[candidate].isdisjoint(links[other])
                }
                joins = 0 if len(touched) >= 2 else 1
                bridging.append(
                    ((joins, min(doc_freq[t] for t in bridges),
                      rank_of[candidate]), candidate))

            covering.sort()
            bridging.sort()
            chosen = [c for _, c in covering[:beam]] + [c for _, c in bridging[:beam]]
            for candidate in chosen:
                if explored >= node_budget or (
                        deadline is not None and time.perf_counter() >= deadline):
                    exhausted = True
                    break
                explored += 1
                cand_terms = term_sets[candidate]
                nxt.append(_State(
                    ids=state.ids + (candidate,),
                    covered=state.covered | (cand_terms & need_set),
                    cost=state.cost + (1.0 - score.get(candidate, 0.0)),
                    terms=state.terms | cand_terms,
                    links=state.links | links[candidate],
                ))
            if exhausted:
                break
        if exhausted or not nxt:
            # Fall back to the best partial chain found. Reporting the partial
            # set and what it misses is more useful than an empty result, and
            # `complete` stays False so a caller cannot mistake one for the
            # other.
            frontier.sort(key=rank_key)
            best = frontier[0] if frontier else None
            break
        frontier = nxt

    if best is None:
        return EvidenceChain(missing=tuple(sorted(need_set)),
                             nodes_explored=explored,
                             budget_exhausted=exhausted)

    # Only on a chain that actually holds together. Run on a partial chain it
    # added two more wrong memories to an already-broken answer, because the
    # "anchor" it compares against was itself a distractor.
    if best.covered == need_set and _connected(best.ids, links):
        best = _add_contradictions(
            best, candidates, term_sets, need_set, max_steps)
    return _explain(best, term_sets, need_set, rank_of, explored, exhausted,
                    doc_freq, links)


def _add_contradictions(
    state: _State,
    candidates: Sequence[str],
    term_sets: Mapping[str, frozenset[str]],
    need: frozenset[str],
    max_steps: int,
) -> _State:
    """Add any candidate that answers the same question differently.

    A search for *a* sufficient connected set stops at the first one, and on a
    question where two standing sources disagree that is the wrong answer: it
    returns one side and looks complete. Measured, not supposed --
    `conflicting` fell from 0.667 to 0.000 when the chain search was first
    scored, because one memory covered every query term on its own.

    So after a chain is found, any candidate covering **exactly the same query
    terms** as the chain's anchor while saying something **different** is added.
    Equal coverage is what makes it a rival answer rather than a distractor: a
    near-miss covers strictly less, because it differs from the question in one
    facet, and is not admitted.
    """
    anchor = state.ids[0]
    anchor_cover = term_sets[anchor] & need
    ids = list(state.ids)
    terms = state.terms
    for candidate in candidates:
        if len(ids) >= max_steps:
            break
        if candidate in ids:
            continue
        cand_terms = term_sets[candidate]
        if (cand_terms & need) == anchor_cover and cand_terms != term_sets[anchor]:
            ids.append(candidate)
            terms = terms | cand_terms
    if len(ids) == len(state.ids):
        return state
    return _State(ids=tuple(ids), covered=state.covered, cost=state.cost,
                  terms=terms, links=state.links)


def _explain(
    state: _State,
    term_sets: Mapping[str, frozenset[str]],
    need: frozenset[str],
    rank_of: Mapping[str, int],
    explored: int,
    exhausted: bool,
    doc_freq: Mapping[str, int] | None = None,
    links: Mapping[str, frozenset[str]] | None = None,
) -> EvidenceChain:
    """Attach a reason and a leave-one-out necessity verdict to each step."""
    doc_freq = doc_freq or {}
    # Derived rather than defaulted to empty: necessity asks whether the chain
    # falls apart without a step, and with no link sets every chain would look
    # connected and nothing would ever be necessary.
    if not links:
        links = {
            memory_id: frozenset(
                t for t in term_sets.get(memory_id, frozenset()) - need
                if not _NUMERIC.match(t))
            for memory_id in state.ids
        }
    ids = list(state.ids)
    steps: list[ChainStep] = []
    for memory_id in ids:
        others = [m for m in ids if m != memory_id]
        covered_without = frozenset().union(
            *(term_sets[m] & need for m in others)) if others else frozenset()
        # Necessary if the chain loses coverage without it, or falls apart.
        loses_coverage = bool((state.covered - covered_without))
        disconnects = bool(others) and not _connected(others, links)
        necessary = loses_coverage or disconnects

        covers = tuple(sorted(term_sets[memory_id] & need))
        mine = links.get(memory_id) or _bridge_terms(
            term_sets[memory_id], term_sets[memory_id], need)
        theirs = (frozenset().union(*(links.get(m, frozenset()) for m in others))
                  if others else frozenset())
        raw_bridges = mine & theirs
        # Rarest first. A link through "chiller-1" and a link through
        # "assigned" are both shared non-query terms and only one of them is
        # evidence that two memories are about the same thing; ordering says
        # which without discarding the truth of the other.
        bridges = tuple(sorted(raw_bridges, key=lambda t: (doc_freq.get(t, 0), t)))
        steps.append(ChainStep(
            memory_id=memory_id,
            # A step that supplies no query term is in the chain only because
            # something else needed it. That is what DEPENDENCY_REQUIRED means,
            # and until now nothing in this codebase emitted it.
            reason=ReasonCode.DIRECT_MATCH if covers else ReasonCode.DEPENDENCY_REQUIRED,
            covers=covers,
            bridges=bridges,
            necessary=necessary,
            rank=rank_of.get(memory_id, -1),
        ))
    return EvidenceChain(
        steps=tuple(steps),
        covered=tuple(sorted(state.covered)),
        missing=tuple(sorted(need - state.covered)),
        nodes_explored=explored,
        budget_exhausted=exhausted,
        connected=_connected(ids, links),
    )


def _components_of(
    ids: Sequence[str],
    links: Mapping[str, frozenset[str]],
) -> dict[str, int]:
    """Which connected component each member of the chain belongs to.

    Avoids the word a benchmark answer key would be called:
    `tests/test_chains.py` asserts this module never names one, because the
    registered constraint is that the mechanism uses content, edges and gates
    and not a benchmark's answer key. A crude check, deliberately -- and a variable name is
    not worth weakening it for.

    One pass, reused for every candidate in the expansion. Replaced a
    per-candidate `_joins` that recomputed the components twice; see the note
    in `search`.
    """
    found: dict[str, int] = {}
    group = 0
    for start in ids:
        if start in found:
            continue
        found[start] = group
        stack = [start]
        while stack:
            current = stack.pop()
            for other in ids:
                if other in found:
                    continue
                if not links[current].isdisjoint(links[other]):
                    found[other] = group
                    stack.append(other)
        group += 1
    return found


def _components(
    ids: Sequence[str],
    links: Mapping[str, frozenset[str]],
) -> int:
    seen: set[str] = set()
    count = 0
    for start in ids:
        if start in seen:
            continue
        count += 1
        stack = [start]
        seen.add(start)
        while stack:
            current = stack.pop()
            for other in ids:
                if other in seen:
                    continue
                if not links[current].isdisjoint(links[other]):
                    seen.add(other)
                    stack.append(other)
    return count


def _connected(
    ids: Sequence[str],
    links: Mapping[str, frozenset[str]],
) -> bool:
    """Whether these memories form one component under non-query shared terms.

    Query terms are excluded from the edges for the same reason they are
    excluded from `bridges`: two memories that merely both mention the query's
    subject are not thereby joined, and treating them as joined would make
    every chain look connected and necessity meaningless.
    """
    if len(ids) <= 1:
        return True
    seen = {ids[0]}
    stack = [ids[0]]
    while stack:
        current = stack.pop()
        for other in ids:
            if other in seen:
                continue
            if not links[current].isdisjoint(links[other]):
                seen.add(other)
                stack.append(other)
    return len(seen) == len(ids)


def necessity_of(
    chain: EvidenceChain, predicate: Callable[[str], bool] | None = None
) -> dict[str, bool]:
    """The chain's own necessity verdicts, optionally filtered.

    A convenience for reporting, kept here so an experiment never recomputes
    necessity with a different rule than the one the chain reported.
    """
    return {
        step.memory_id: step.necessary
        for step in chain.steps
        if predicate is None or predicate(step.memory_id)
    }
