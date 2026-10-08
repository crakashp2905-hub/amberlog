"""MemoryFabric: the public facade, per SPEC.md section 6.

Everything a caller does becomes an event first and state second. State is a
projection that can be thrown away and rebuilt, which is what makes the audit
trail trustworthy: there is no way to change a memory without leaving a record,
because the record *is* the change.
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterable, Mapping, Sequence

if TYPE_CHECKING:  # pragma: no cover
    from .session import AgentSession

from . import events as ev
from .estimators import ValueEstimator, build_estimator
from .eventlog import EventLog
from .exposure import Candidate, ExposurePolicy, build_policy
from .governance.firewall import Firewall, FirewallRequest, FirewallRuling
from .governance.retention import RetentionDecision, RetentionPolicy
from .ids import new_ulid
from .lineage import LineageGraph, LineageView
from .model import (
    BLOCKED_STATES,
    EXPLORATORY_STATES,
    EXPOSABLE_STATES,
    FirewallDecision,
    LifecycleState,
    Memory,
    MemoryStats,
    MemoryType,
    Provenance,
    ProvenanceMethod,
    Scope,
    SecurityClass,
    ValueEstimate,
    context_key,
)
from .projections import Episode, Projection, _digest
from .vectors import MIN_RELEVANCE, Embedder, VectorIndex


class FabricError(RuntimeError):
    pass


class NotFound(FabricError):
    pass


class PolicyViolation(FabricError):
    """Raised when a caller asks for something governance forbids."""


@dataclass
class RetrievalResult:
    """What the agent gets back, plus the record of what it did not get.

    `withheld` is returned deliberately: callers that log their own traces
    should be able to see that a candidate existed and was held back, because
    that is exactly the information a relevance-only system throws away.
    """

    exposed: list[Memory] = field(default_factory=list)
    withheld: list[Memory] = field(default_factory=list)
    scores: dict[str, float] = field(default_factory=dict)
    policy_id: str = ""

    def __iter__(self):
        return iter(self.exposed)

    def __len__(self) -> int:
        return len(self.exposed)

    @property
    def contents(self) -> list[str]:
        return [m.content for m in self.exposed]


@dataclass
class HealthReport:
    total: int
    by_state: dict[str, int]
    by_scope: dict[str, int]
    by_type: dict[str, int]
    unverified: int
    contested: int
    quarantined: int
    never_exposed: int
    open_hypothesis_sets: int
    episodes: int
    episodes_with_outcome: int
    events: int


class MemoryFabric:
    """Single-process memory fabric with a governed write and share path."""

    def __init__(
        self,
        path: str | Path = ":memory:",
        estimator: str | ValueEstimator = "naive_usage",
        exposure_policy: str | ExposurePolicy = "top_k",
        firewall: Firewall | None = None,
        retention: RetentionPolicy | None = None,
        embedder: Embedder | None = None,
        seed: int | None = None,
        clock=None,
        auto_activate: bool = False,
    ) -> None:
        self.log = EventLog(path)
        self.projection = Projection()
        self.index = VectorIndex(embedder)
        self.firewall = firewall or Firewall()
        self.retention = retention or RetentionPolicy()
        self.estimator = build_estimator(estimator)
        self.policy = build_policy(exposure_policy)
        self.rng = random.Random(seed)
        self._clock = clock or (lambda: int(time.time() * 1000))
        # When true, a clean memory becomes active immediately. Off by default:
        # a new memory is a candidate until something validates it.
        self.auto_activate = auto_activate
        self._estimator_dirty = True
        self._replay()

    # --- plumbing --------------------------------------------------------

    @property
    def state(self):
        return self.projection.state

    @property
    def lineage_graph(self) -> LineageGraph:
        return LineageGraph(self.state)

    def now(self) -> int:
        return self._clock()

    def _emit(self, *events: ev.Event) -> list[ev.Event]:
        stored = self.log.append_many(events)
        for event in stored:
            self.projection.apply(event)
        self._estimator_dirty = True
        return stored

    def _replay(self) -> None:
        """Rebuild all state from the log, including the vector index."""
        self.projection = Projection.rebuild(self.log)
        for memory in self.state.memories.values():
            if memory.lifecycle_state is not LifecycleState.DELETED:
                self.index.add(memory.id, self._index_text(memory))
        self._estimator_dirty = True

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

    def _require(self, memory_id: str) -> Memory:
        memory = self.state.memories.get(memory_id)
        if memory is None:
            raise NotFound(f"no memory {memory_id!r}")
        return memory

    def _refresh_estimator(self) -> None:
        if self._estimator_dirty:
            self.estimator.fit(self.state)
            self._estimator_dirty = False

    # --- episodes --------------------------------------------------------

    def start_episode(
        self,
        agent_id: str,
        task_id: str,
        context: Mapping[str, Any] | None = None,
        seed: int | None = None,
    ) -> Episode:
        episode_id = new_ulid()
        self._emit(
            ev.episode_started(
                ts=self.now(),
                agent_id=agent_id,
                episode_id=episode_id,
                task_id=task_id,
                context=dict(context or {}),
                seed=seed,
            )
        )
        return self.state.episodes[episode_id]

    def session(
        self,
        agent_id: str,
        task_id: str,
        context: Mapping[str, Any] | None = None,
        seed: int | None = None,
    ) -> "AgentSession":
        """Start an episode and return a handle scoped to it.

        This is what adapters are given, rather than the fabric itself, so they
        cannot write as another agent or against another episode (session.py).
        """
        from .session import AgentSession

        episode = self.start_episode(agent_id, task_id, context, seed)
        return AgentSession(fabric=self, agent_id=agent_id, episode=episode)

    def record_outcome(self, episode_id: str, outcome: float, verifier_id: str) -> None:
        """Record a verified outcome.

        `verifier_id` is mandatory and must not be the acting agent. An agent
        that can score its own episodes can manufacture value for any memory it
        likes (SECURITY.md T2), which would corrupt every estimate downstream.
        """
        episode = self.state.episodes.get(episode_id)
        if episode is None:
            raise NotFound(f"no episode {episode_id!r}")
        if not verifier_id:
            raise PolicyViolation("record_outcome requires a verifier_id")
        if verifier_id == episode.agent_id:
            raise PolicyViolation(
                f"agent {verifier_id!r} may not verify its own episode outcome"
            )
        self._emit(
            ev.outcome_recorded(
                ts=self.now(),
                episode_id=episode_id,
                outcome=float(outcome),
                verifier_id=verifier_id,
            )
        )

    def end_episode(self, episode_id: str) -> Episode:
        episode = self.state.episodes.get(episode_id)
        if episode is None:
            raise NotFound(f"no episode {episode_id!r}")
        return episode

    # --- writing ---------------------------------------------------------

    def remember(
        self,
        agent_id: str,
        content: str,
        type: str | MemoryType = MemoryType.SEMANTIC,
        context: Mapping[str, Any] | None = None,
        source_episodes: Sequence[str] = (),
        parents: Sequence[tuple[str, int]] = (),
        method: str | ProvenanceMethod = ProvenanceMethod.OBSERVED,
        structured: Mapping[str, Any] | None = None,
        security_class: str | SecurityClass = SecurityClass.INTERNAL,
        capabilities: Sequence[str] = (),
        scope: str | Scope = Scope.PRIVATE,
        episode_id: str | None = None,
        auto_activate: bool | None = None,
    ) -> str:
        """Store a new memory. Runs the ingest screen before anything is stored.

        A high-severity sensitive-data hit lands the memory in `quarantined`
        rather than dropping it: the fact that an agent tried to memorise a
        secret is itself worth auditing.

        `auto_activate` overrides the store's default for this one write. A
        caller that knows the content is not a trusted local observation — an
        import from another store, for instance — passes False so the store's
        convenience setting cannot silently promote it.
        """
        # An agent that writes the same thing twice in one episode is looping,
        # not observing twice. Found live: a model called the `remember` tool
        # four times in a single run and produced two distinct memories, which
        # inflates apparent consensus exactly the way several agents parroting
        # one source does (SECURITY.md T3) — except from a single agent, which
        # the evidence-independence check does not look at.
        #
        # Scoped to one episode on purpose. The same claim recorded in two
        # different episodes is two observations, and that *is* more evidence.
        if episode_id:
            key = (agent_id, episode_id, _digest(content))
            existing = self.state.written.get(key)
            if existing is not None:
                self._emit(
                    ev.duplicate_suppressed(
                        ts=self.now(),
                        agent_id=agent_id,
                        episode_id=episode_id,
                        existing_memory_id=existing,
                        content_digest=key[2],
                    )
                )
                return existing

        activate = self.auto_activate if auto_activate is None else auto_activate
        ruling = self.firewall.screen_ingest(content)
        if ruling.decision is FirewallDecision.QUARANTINE:
            lifecycle = LifecycleState.QUARANTINED
        elif activate:
            lifecycle = LifecycleState.ACTIVE
        else:
            lifecycle = LifecycleState.CANDIDATE

        now = self.now()
        memory = Memory(
            id=new_ulid(),
            version=1,
            type=MemoryType(type),
            content=content,
            provenance=Provenance(
                created_by=agent_id,
                source_episodes=tuple(source_episodes),
                parents=tuple((p[0], int(p[1])) for p in parents),
                method=ProvenanceMethod(method),
            ),
            context=dict(context or {}),
            structured=dict(structured) if structured else None,
            scope=Scope(scope),
            lifecycle_state=lifecycle,
            security_class=SecurityClass(security_class),
            capabilities=tuple(capabilities),
            created_at=now,
        )
        emitted = [ev.memory_created(ts=now, memory=memory, episode_id=episode_id)]
        if ruling.decision is FirewallDecision.QUARANTINE:
            emitted.append(
                ev.lifecycle_changed(
                    ts=now,
                    memory_id=memory.id,
                    from_state=LifecycleState.CANDIDATE.value,
                    to_state=LifecycleState.QUARANTINED.value,
                    reason="; ".join(ruling.reasons),
                    actor=self.firewall.id,
                )
            )
        self._emit(*emitted)
        self.index.add(memory.id, self._index_text(memory))
        return memory.id

    def revise(
        self,
        memory_id: str,
        content: str,
        agent_id: str,
        reason: str,
        method: str | ProvenanceMethod = ProvenanceMethod.CONSOLIDATED,
    ) -> Memory:
        """Create the next version of a memory. The old version stays in history."""
        current = self._require(memory_id)
        now = self.now()
        revised = current.evolve(
            version=current.version + 1,
            content=content,
            provenance=Provenance(
                created_by=agent_id,
                source_episodes=current.provenance.source_episodes,
                parents=current.provenance.parents,
                method=ProvenanceMethod(method),
            ),
            created_at=now,
            superseded_at=None,
        )
        self._emit(ev.memory_versioned(ts=now, memory=revised, reason=reason))
        self.index.add(memory_id, self._index_text(revised))
        return revised

    def derive(
        self,
        agent_id: str,
        content: str,
        parents: Sequence[str],
        type: str | MemoryType = MemoryType.SEMANTIC,
        method: str | ProvenanceMethod = ProvenanceMethod.CONSOLIDATED,
        context: Mapping[str, Any] | None = None,
    ) -> str:
        """Create a memory derived from existing ones, recording the edges.

        These edges are what makes retraction work, so deriving through this
        method rather than writing a fresh memory is the difference between a
        rollback that holds and one that leaks (SECURITY.md T5).
        """
        parent_versions = [(pid, self._require(pid).version) for pid in parents]
        inherited: dict[str, Any] = {}
        for pid in parents:
            inherited.update(self._require(pid).context)
        inherited.update(dict(context or {}))
        return self.remember(
            agent_id=agent_id,
            content=content,
            type=type,
            context=inherited,
            parents=parent_versions,
            method=method,
        )

    # --- retrieval -------------------------------------------------------

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
    ) -> RetrievalResult:
        """Retrieve, decide exposure, log both, return what was exposed.

        Candidates below `min_relevance` are not considered at all, so a query
        with nothing to match returns nothing rather than the least-bad rows in
        the store.
        """
        eligible = self._eligible_ids(include_contested=include_contested)
        pool_size = pool if pool is not None else max(k * 4, k)
        hits = self.index.search(
            query, k=pool_size, restrict_to=eligible, min_relevance=min_relevance
        )

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

    def _eligible_ids(self, include_contested: bool = False) -> set[str]:
        allowed = set(EXPOSABLE_STATES)
        if include_contested:
            allowed |= EXPLORATORY_STATES
        return {
            memory_id
            for memory_id, memory in self.state.memories.items()
            if memory.lifecycle_state in allowed
            and memory.lifecycle_state not in BLOCKED_STATES
        }

    def cite(self, agent_id: str, episode_id: str, memory_id: str, step: int = 0) -> None:
        """Record that the agent says it used a memory. Diagnostic only: it is
        self-reported, so it never feeds value estimation."""
        self._emit(
            ev.memory_cited(
                ts=self.now(),
                agent_id=agent_id,
                episode_id=episode_id,
                memory_id=memory_id,
                step=step,
            )
        )

    # --- value -----------------------------------------------------------

    def value(
        self, memory_id: str, context: Mapping[str, Any] | None = None, persist: bool = False
    ) -> ValueEstimate:
        self._require(memory_id)
        self._refresh_estimator()
        estimate = self.estimator.estimate(memory_id, context)
        if persist:
            self._emit(
                ev.value_estimated(
                    ts=self.now(),
                    memory_id=memory_id,
                    context_key=context_key(context),
                    estimate=estimate.to_json(),
                    estimator_id=self.estimator.id,
                )
            )
        return estimate

    def stats(self, memory_id: str) -> MemoryStats:
        self._require(memory_id)
        return self.state.stats_for(memory_id)

    # --- lifecycle -------------------------------------------------------

    def _transition(
        self, memory_id: str, to_state: LifecycleState, reason: str, actor: str
    ) -> ev.Event:
        memory = self._require(memory_id)
        return ev.lifecycle_changed(
            ts=self.now(),
            memory_id=memory_id,
            from_state=memory.lifecycle_state.value,
            to_state=to_state.value,
            reason=reason,
            actor=actor,
        )

    def validate(self, memory_id: str, actor: str, reason: str = "validated") -> Memory:
        """Promote a candidate to active."""
        memory = self._require(memory_id)
        if memory.lifecycle_state is LifecycleState.QUARANTINED:
            raise PolicyViolation(
                f"{memory_id} is quarantined; review and release it before validating"
            )
        self._emit(self._transition(memory_id, LifecycleState.ACTIVE, reason, actor))
        return self.state.memories[memory_id]

    def quarantine(
        self, memory_id: str, reason: str, actor: str = "operator", propagate: bool = True
    ) -> list[str]:
        """Quarantine a memory and contest everything derived from it.

        This is the retraction step. Quarantining alone is not enough: the
        descendants were justified by this memory, so they lose their
        justification and must be re-examined. Without the propagation, a
        poisoned memory survives its own rollback through its children.

        **Do not drive this from "it was in context when something failed."**
        Phase A measured that policy and it made an agent substantially worse:
        it cut the rate at which a correct memory reached the prompt from 60% of
        episodes to 18%, because the memory that asserted what the agent wrongly
        said was usually a *correct* memory about a different situation that
        happened to name the same action. Agreement with a mistake is not
        evidence of having caused it. Quarantine on evidence about the memory —
        a sensitive-data finding, a contradiction with a verified fact, a
        contrastive estimate showing harm — not on co-occurrence with a failure.
        See research/results/phase-a-real-agent-benchmark.md.

        Returns the ids marked contested.
        """
        self._require(memory_id)
        emitted = [
            self._transition(memory_id, LifecycleState.QUARANTINED, reason, actor)
        ]
        contested: list[str] = []
        if propagate:
            for node in self.lineage_graph.descendants(memory_id):
                descendant = self.state.memories.get(node.memory_id)
                if descendant is None:
                    continue
                if descendant.lifecycle_state in (
                    LifecycleState.QUARANTINED,
                    LifecycleState.DELETED,
                ):
                    continue
                emitted.append(
                    self._transition(
                        node.memory_id,
                        LifecycleState.CONTESTED,
                        f"justification retracted: ancestor {memory_id} quarantined ({reason})",
                        actor,
                    )
                )
                contested.append(node.memory_id)
        self._emit(*emitted)
        return contested

    def release(self, memory_id: str, actor: str, reason: str = "reviewed and released") -> Memory:
        """Bring a quarantined memory back to candidate after human review."""
        memory = self._require(memory_id)
        if memory.lifecycle_state is not LifecycleState.QUARANTINED:
            raise PolicyViolation(f"{memory_id} is not quarantined")
        self._emit(self._transition(memory_id, LifecycleState.CANDIDATE, reason, actor))
        return self.state.memories[memory_id]

    def forget(self, memory_id: str, reason: str, actor: str = "operator") -> Memory:
        """Deprecate. Deletion is the retention policy's decision, not the
        caller's, so that a single call can never destroy an audit trail."""
        self._emit(self._transition(memory_id, LifecycleState.DEPRECATED, reason, actor))
        self.index.remove(memory_id)
        return self.state.memories[memory_id]

    def challenge(
        self,
        memory_ids: Sequence[str],
        evidence: str,
        detector_id: str = "manual",
        confidence: float = 1.0,
        hypothesis_set: str | None = None,
        actor: str = "operator",
    ) -> str:
        """Open or extend a hypothesis set over contradictory memories.

        Nothing is deleted and no winner is chosen. The memories become
        `contested` and travel together from here on, because a disagreement is
        information and collapsing it early is the failure mode this whole
        design is built to avoid.
        """
        for memory_id in memory_ids:
            self._require(memory_id)
        set_id = hypothesis_set or f"hset_{new_ulid()}"
        now = self.now()
        emitted: list[ev.Event] = [
            ev.conflict_detected(
                ts=now,
                memory_ids=list(memory_ids),
                detector_id=detector_id,
                confidence=confidence,
                hypothesis_set=set_id,
                actor=actor,
            )
        ]
        for memory_id in memory_ids:
            memory = self.state.memories[memory_id]
            if memory.lifecycle_state in (LifecycleState.ACTIVE, LifecycleState.CANDIDATE):
                emitted.append(
                    self._transition(
                        memory_id,
                        LifecycleState.CONTESTED,
                        f"conflict: {evidence}",
                        actor,
                    )
                )
        self._emit(*emitted)
        return set_id

    def resolve(
        self,
        hypothesis_set: str,
        winner_id: str | None,
        design: Mapping[str, Any],
        results: Mapping[str, Any],
        actor: str = "operator",
    ) -> None:
        """Close a hypothesis set with evidence.

        Losers are deprecated rather than deleted, so that later contradictory
        evidence can bring the question back rather than meeting a store that
        has forgotten the alternative ever existed.
        """
        hset = self.state.hypothesis_sets.get(hypothesis_set)
        if hset is None:
            raise NotFound(f"no hypothesis set {hypothesis_set!r}")
        payload = dict(results)
        payload["resolved"] = True
        emitted: list[ev.Event] = [
            ev.experiment_run(
                ts=self.now(),
                hypothesis_set=hypothesis_set,
                design=design,
                results=payload,
            )
        ]
        for memory_id in sorted(hset.memory_ids):
            if memory_id == winner_id:
                emitted.append(
                    self._transition(
                        memory_id, LifecycleState.ACTIVE, "won experiment", actor
                    )
                )
            else:
                emitted.append(
                    self._transition(
                        memory_id,
                        LifecycleState.DEPRECATED,
                        f"lost experiment in {hypothesis_set}",
                        actor,
                    )
                )
        self._emit(*emitted)

    # --- sharing ---------------------------------------------------------

    def firewall_check(
        self,
        memory_id: str,
        target_scope: str | Scope,
        granted_capabilities: Iterable[str] = (),
    ) -> FirewallRuling:
        memory = self._require(memory_id)
        hset = (
            self.state.hypothesis_sets.get(memory.hypothesis_set)
            if memory.hypothesis_set
            else None
        )
        siblings = sorted(hset.memory_ids) if hset else [memory_id]
        return self.firewall.evaluate(
            FirewallRequest(
                memory=memory,
                target_scope=Scope(target_scope),
                value=self.value(memory_id),
                hypothesis_open=bool(hset and not hset.resolved),
                granted_capabilities=frozenset(granted_capabilities),
                evidence_independent=self.lineage_graph.evidence_is_independent(siblings)
                if len(siblings) > 1
                else True,
            )
        )

    def share(
        self,
        memory_id: str,
        scope: str | Scope,
        actor: str = "operator",
        granted_capabilities: Iterable[str] = (),
    ) -> FirewallRuling:
        """Promote a memory's scope, if the firewall allows it.

        Default-deny: the scope changes only on ALLOW or ALLOW_WITH_WARNING, and
        the ruling is recorded either way so a refusal is as auditable as a
        grant.
        """
        memory = self._require(memory_id)
        target = Scope(scope)
        ruling = self.firewall_check(memory_id, target, granted_capabilities)

        emitted: list[ev.Event] = []
        if ruling.permits_sharing:
            emitted.append(
                ev.scope_changed(
                    ts=self.now(),
                    memory_id=memory_id,
                    from_scope=memory.scope.value,
                    to_scope=target.value,
                    firewall_decision=ruling.decision.value,
                    reasons=ruling.reasons,
                    actor=actor,
                )
            )
        else:
            # A denial is a scope_changed event to the *same* scope: the attempt
            # and its reasons belong in the audit trail.
            emitted.append(
                ev.scope_changed(
                    ts=self.now(),
                    memory_id=memory_id,
                    from_scope=memory.scope.value,
                    to_scope=memory.scope.value,
                    firewall_decision=ruling.decision.value,
                    reasons=ruling.reasons,
                    actor=actor,
                )
            )
            if ruling.decision is FirewallDecision.QUARANTINE:
                emitted.append(
                    self._transition(
                        memory_id,
                        LifecycleState.QUARANTINED,
                        "; ".join(ruling.reasons),
                        self.firewall.id,
                    )
                )
        self._emit(*emitted)
        return ruling

    # --- inspection ------------------------------------------------------

    def get(self, memory_id: str) -> Memory:
        return self._require(memory_id)

    def history(self, memory_id: str) -> list[Memory]:
        self._require(memory_id)
        return list(self.state.history.get(memory_id, ())) + [self.state.memories[memory_id]]

    def lineage(self, memory_id: str) -> LineageView:
        self._require(memory_id)
        return self.lineage_graph.view(memory_id)

    def audit_trail(self, memory_id: str) -> list[ev.Event]:
        """Every event that mentions this memory, in log order."""
        self._require(memory_id)
        out: list[ev.Event] = []
        for event in self.log.read():
            payload = event.payload
            if payload.get("memory_id") == memory_id:
                out.append(event)
            elif memory_id in (payload.get("memory_ids") or ()):
                out.append(event)
            elif isinstance(payload.get("memory"), dict) and payload["memory"].get("id") == memory_id:
                out.append(event)
            elif any(
                c.get("memory_id") == memory_id for c in (payload.get("candidates") or ())
            ):
                out.append(event)
        return out

    def explain(self, memory_id: str) -> "Explanation":
        from .explain import explain_memory

        return explain_memory(self, memory_id)

    def health(self) -> HealthReport:
        by_state: dict[str, int] = {}
        by_scope: dict[str, int] = {}
        by_type: dict[str, int] = {}
        unverified = never_exposed = 0
        self._refresh_estimator()
        for memory in self.state.memories.values():
            by_state[memory.lifecycle_state.value] = by_state.get(memory.lifecycle_state.value, 0) + 1
            by_scope[memory.scope.value] = by_scope.get(memory.scope.value, 0) + 1
            by_type[memory.type.value] = by_type.get(memory.type.value, 0) + 1
            stats = self.state.stats_for(memory.id)
            # The live estimate, not the projected one. `stats.value_estimate` is
            # only populated by value(persist=True), so counting it here would
            # report every memory as unverified in the normal case and contradict
            # anything that asks the estimator directly.
            if self.estimator.estimate(memory.id).n_eff <= 0.0:
                unverified += 1
            if stats.exposures == 0:
                never_exposed += 1
        return HealthReport(
            total=len(self.state.memories),
            by_state=by_state,
            by_scope=by_scope,
            by_type=by_type,
            unverified=unverified,
            contested=by_state.get(LifecycleState.CONTESTED.value, 0),
            quarantined=by_state.get(LifecycleState.QUARANTINED.value, 0),
            never_exposed=never_exposed,
            open_hypothesis_sets=sum(
                1 for h in self.state.hypothesis_sets.values() if not h.resolved
            ),
            episodes=len(self.state.episodes),
            episodes_with_outcome=sum(1 for e in self.state.episodes.values() if e.has_outcome),
            events=len(self.log),
        )

    def sweep_retention(self, apply: bool = False, actor: str = "retention") -> list[RetentionDecision]:
        now = self.now()
        pairs = [
            (memory, self.state.stats_for(memory.id))
            for memory in self.state.memories.values()
        ]
        decisions = self.retention.sweep(pairs, now)
        if apply:
            emitted: list[ev.Event] = []
            for decision in decisions:
                to_state = (
                    LifecycleState.DELETED
                    if decision.action == "delete"
                    else LifecycleState.DEPRECATED
                )
                emitted.append(
                    self._transition(decision.memory_id, to_state, decision.reason, actor)
                )
                self.index.remove(decision.memory_id)
            if emitted:
                self._emit(*emitted)
        return decisions

    def rebuild(self) -> None:
        """Throw away all derived state and rebuild it from the log."""
        self._replay()

    def close(self) -> None:
        self.log.close()

    def __enter__(self) -> "MemoryFabric":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


# Re-exported for typing convenience at the bottom to avoid a circular import.
from .explain import Explanation  # noqa: E402
