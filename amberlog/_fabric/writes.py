"""Writes: episodes, outcomes, remember, revise, derive and citations.

A service mixin of `Amberlog`, built on `FabricCore`. Methods moved here
verbatim from `fabric.py`.
"""

from __future__ import annotations

__stability__ = "stable"



from typing import TYPE_CHECKING, Any, Mapping, Sequence, cast

if TYPE_CHECKING:
    from ..fabric import Amberlog  # noqa: F401
    from ..session import AgentSession

from .. import events as ev
from ..ids import new_ulid

from ..identity import (
    DEFAULT_TENANT,
)
from ..model import (
    WITHDRAWN_STATES,
    FirewallDecision,
    LifecycleState,
    Memory,
    MemoryStats,
    MemoryType,
    Provenance,
    ProvenanceMethod,
    Scope,
    SecurityClass,
    WithdrawalBasis,
    ValueEstimate,
    context_key,
)
from ..projections import Episode, _digest


from .core import FabricCore
from .common import NotFound, PolicyViolation, _screened_text, _fresh


class WritesMixin(FabricCore):

    # --- episodes --------------------------------------------------------

    @_fresh
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
        from ..session import AgentSession

        episode = self.start_episode(agent_id, task_id, context, seed)
        return AgentSession(fabric=cast("Amberlog", self), agent_id=agent_id, episode=episode)

    @_fresh
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

    @_fresh
    def end_episode(self, episode_id: str) -> Episode:
        episode = self.state.episodes.get(episode_id)
        if episode is None:
            raise NotFound(f"no episode {episode_id!r}")
        return episode

    # --- writing ---------------------------------------------------------

    @_fresh
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
        tenant_id: str = DEFAULT_TENANT,
        valid_from: int | None = None,
        valid_to: int | None = None,
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
        fed = (context or {}).get("federation") if isinstance(context, Mapping) else None
        self.limits.check_write(agent_id, content,
                                str(fed.get("store")) if isinstance(fed, Mapping) else None,
                                self.now())
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

        # A re-ingestion of something already held, across agents and
        # episodes. The exact-digest check above is scoped to one episode and
        # one agent on purpose -- the same claim observed twice really is more
        # evidence -- and it cannot see the case P3 measured: a document
        # withdrawn as wrong, then re-ingested months later from a shared drive
        # with a filing note appended, so its digest differs.
        #
        # Looked up *before* the write, and recorded after it, so the event
        # names a memory that exists.
        copy_of = None
        if self.recognise_copies:
            # Only within the writer's tenant: the same text in another tenant
            # is a separate origin, and linking them let a withdrawal in one
            # tenant reach the other (masterplan GOV-07).
            memories = self.state.memories
            copy_of = self.copy_index.find(
                content, accept=lambda mid: mid in memories and memories[mid].tenant_id == tenant_id)

        # Writing at a wider scope skips the firewall that `share` runs, which
        # is fine for host code except where a rule is absolute: a restricted
        # memory stays private (firewall.rule_restricted_stays_private), and
        # writing it straight into `team` would be the same leak by the side door.
        if (SecurityClass(security_class) is SecurityClass.RESTRICTED
                and Scope(scope) is not Scope.PRIVATE):
            raise PolicyViolation("a restricted memory stays private; it cannot be "
                                  f"written at scope {Scope(scope).value}")
        activate = self.auto_activate if auto_activate is None else auto_activate
        ruling = self.firewall.screen_ingest(
            _screened_text(content, context, structured))
        if ruling.decision is FirewallDecision.QUARANTINE:
            lifecycle = LifecycleState.QUARANTINED
        elif copy_of is not None and self.state.memories[
                copy_of.memory_id].lifecycle_state in WITHDRAWN_STATES:
            # Re-ingesting a withdrawn document does not restore it.
            #
            # CONTESTED rather than QUARANTINED: nobody has made a finding
            # about *this* write, and the original's withdrawal may itself have
            # been wrong. Contested is withheld from retrieval by default and
            # stays visible to an operator, which is the honest state for "this
            # arrived again and the reason it was withdrawn has not changed".
            lifecycle = LifecycleState.CONTESTED
        elif activate and self.hold_suspicious and self._suspicious(
                agent_id, content, context, tenant_id):
            # Checked against what the store already knows (`validation.py`):
            # a corrected value stated again, a value far out of range, or a
            # contradiction of an established fact. Held for review instead of
            # going live; nothing is refused.
            lifecycle = LifecycleState.CANDIDATE
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
            tenant_id=tenant_id,
            # Validity in the world, separate from `created_at` which is when
            # this store learned it. Both None means "applies always", which is
            # how every memory written before 0.7.0 behaves.
            valid_from=valid_from,
            valid_to=valid_to,
            lifecycle_state=lifecycle,
            security_class=SecurityClass(security_class),
            capabilities=tuple(capabilities),
            created_at=now,
        )
        # Seal on the way into the log. The projection unseals as it folds, so
        # every reader downstream still sees plaintext; what changes is that the
        # bytes on disk are ciphertext and destroying the key is therefore real
        # erasure rather than a cosmetic one.
        sealed = memory.evolve(
            content=self._seal_content(memory.content, memory.id, memory.version)
        )
        emitted = [ev.memory_created(ts=now, memory=sealed, episode_id=episode_id)]
        if copy_of is not None:
            # After the creation event, so the copy edge never names a memory
            # the log has not yet introduced -- a replay applies these in order
            # and a forward reference would leave `copy_of` pointing at nothing.
            emitted.append(ev.copy_recognised(
                ts=now, agent_id=agent_id, episode_id=episode_id,
                memory_id=memory.id, original_memory_id=copy_of.memory_id,
                containment=copy_of.score,
            ))
            if lifecycle is LifecycleState.CONTESTED:
                emitted.append(ev.lifecycle_changed(
                    ts=now, memory_id=memory.id,
                    from_state=LifecycleState.CANDIDATE.value,
                    to_state=LifecycleState.CONTESTED.value,
                    reason=(f"re-ingestion of withdrawn {copy_of.memory_id}"),
                    actor="copy-recognition",
                    # A finding about the content, inherited: the original was
                    # withdrawn for a reason that has not changed. Not
                    # CO_OCCURRENCE, which Phase A measured as a harmful
                    # withdrawal rule, and not UNSTATED, which would hide that
                    # a reason exists.
                    basis=self.state.withdrawal_basis.get(
                        copy_of.memory_id, WithdrawalBasis.UNSTATED.value),
                ))
        if ruling.decision is FirewallDecision.QUARANTINE:
            emitted.append(
                ev.lifecycle_changed(
                    ts=now,
                    memory_id=memory.id,
                    from_state=LifecycleState.CANDIDATE.value,
                    to_state=LifecycleState.QUARANTINED.value,
                    reason="; ".join(ruling.reasons),
                    actor=self.firewall.id,
                    # The firewall quarantines on a finding about the memory
                    # itself, which is the strong case and the one worth
                    # distinguishing from "it was present when something failed".
                    basis=WithdrawalBasis.SENSITIVE_DATA.value,
                )
            )
        self._emit(*emitted)
        # From the state, not the local object: see `revise` for why.
        self._index(memory.id, self._index_text(self.state.memories[memory.id]))
        return memory.id

    @_fresh
    def revise(
        self,
        memory_id: str,
        content: str,
        agent_id: str,
        reason: str,
        method: str | ProvenanceMethod = ProvenanceMethod.CONSOLIDATED,
    ) -> Memory:
        """Create the next version of a memory. The old version stays in history.

        Refused once the content has been erased. Erasure is terminal for a
        memory's content: writing a new version under the same id would make it
        readable again and would defeat the erasure record. A property-based
        walk found the sequence (erase, then revise) and it stored the new text
        in plaintext, because the destroyed key made the sealer fall back.
        """
        current = self._require(memory_id)
        if memory_id in self.state.erased:
            raise PolicyViolation(
                f"{memory_id} has been content-erased; record new information "
                "as a new memory rather than a new version"
            )
        # A revision is a write and passes the same screen as the first
        # version. It used to skip it, so a revision could put a secret or an
        # injection into a memory that was already active and retrievable.
        ruling = self.firewall.screen_ingest(
            _screened_text(content, current.context, current.structured))
        from .. import validation

        left_behind = (validation.restatements(cast("Amberlog", self), current) if self.contest_restatements
                       and validation.claim(content)[2] != validation.claim(current.content)[2]
                       else [])
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
        self._emit(
            ev.memory_versioned(
                ts=now,
                memory=revised.evolve(
                    content=self._seal_content(
                        revised.content, revised.id, revised.version
                    )
                ),
                reason=reason,
            ),
            *(
                [self._transition(
                    memory_id, LifecycleState.QUARANTINED, "; ".join(ruling.reasons),
                    self.firewall.id, basis=WithdrawalBasis.SENSITIVE_DATA.value,
                )]
                if ruling.decision is FirewallDecision.QUARANTINE
                and current.lifecycle_state is not LifecycleState.QUARANTINED
                else []
            ),
        )
        # The state's version, not `revised`: if another process revised the
        # same memory just after us, `_emit` has folded that later version in,
        # and indexing our own would put superseded text back in the index
        # under the current version. Found by tests/test_catch_up.py.
        current = self.state.memories[memory_id]
        self._index(memory_id, self._index_text(current))
        self._contest(left_behind, f"restates the value {memory_id} v{current.version - 1} "
                                   f"had before it was corrected", agent_id)
        return current

    @_fresh
    def derive(
        self,
        agent_id: str,
        content: str,
        parents: Sequence[str],
        type: str | MemoryType = MemoryType.SEMANTIC,
        method: str | ProvenanceMethod = ProvenanceMethod.CONSOLIDATED,
        context: Mapping[str, Any] | None = None,
        tenant_id: str | None = None,
        security_class: str | SecurityClass | None = None,
        scope: str | Scope = Scope.PRIVATE,
        auto_activate: bool | None = None,
    ) -> str:
        """Create a memory derived from existing ones, recording the edges.

        `auto_activate` overrides the store's default for this write, as in
        `remember`. A rulebook proposal must stay a candidate on a store
        that activates everything else (`rulebook.py`).

        These edges are what makes retraction work, so deriving through this
        method rather than writing a fresh memory is the difference between a
        rollback that holds and one that leaks (SECURITY.md T5).

        `tenant_id` None inherits the parents' tenant, and the parents must
        agree. Defaulting to the *store's* default instead was the first
        version, and it was an isolation hole: a tenant's conclusion landed in
        `tn_default` where any agent scoped to that tenant could read it, even
        though both the acting agent and every premise were elsewhere. Found by
        the test for the ordinary within-tenant case, not by the test for the
        attack.
        """
        parent_versions = [(pid, self._require(pid).version) for pid in parents]
        if tenant_id is None:
            tenants = {self._require(pid).tenant_id for pid in parents}
            if len(tenants) > 1:
                raise PolicyViolation(
                    "cannot derive from premises in different tenants: "
                    f"{sorted(tenants)}. Name the tenant explicitly if this is "
                    "deliberate."
                )
            tenant_id = tenants.pop() if tenants else DEFAULT_TENANT
        inherited: dict[str, Any] = {}
        for pid in parents:
            inherited.update(self._require(pid).context)
        inherited.update(dict(context or {}))
        # A conclusion is at least as restricted as its most restricted
        # premise. It used to be written at the default class, so a summary of
        # a `restricted` memory came out `internal` and could be shared and
        # offered: restricted content laundered through a derivation (plan
        # Task 11). A caller may raise the class, never lower it below this.
        order = (SecurityClass.PUBLIC, SecurityClass.INTERNAL, SecurityClass.RESTRICTED)
        floor = max((self._require(pid).security_class for pid in parents),
                    key=order.index, default=SecurityClass.PUBLIC)
        requested = SecurityClass(security_class or SecurityClass.INTERNAL)
        effective = max(requested, floor, key=order.index)
        # Visibility follows the same rule the other way: no wider than the
        # narrowest premise, so a conclusion cannot show teammates what a
        # private premise would not.
        narrowest = min((self._require(pid).scope for pid in parents),
                        key=lambda s: s.rank, default=Scope.FEDERATED)
        visible = min(Scope(scope), narrowest, key=lambda s: s.rank)
        derived = self.remember(
            agent_id=agent_id,
            content=content,
            type=type,
            context=inherited,
            parents=parent_versions,
            method=method,
            tenant_id=tenant_id,
            security_class=effective,
            scope=visible,
            auto_activate=auto_activate,
        )

        # Check the support of what was just written.
        #
        # Retraction propagated to conclusions drawn *before* a withdrawal and
        # not to ones drawn after: deriving from an already-quarantined premise
        # produced an ACTIVE memory. The same two memories and the same
        # finding, with opposite results depending on which arrived first --
        # the same order-dependence the copy relation had, one layer up.
        #
        # This is the recomputation `quarantine` already runs, applied at write
        # time, so there is no second rule about what counts as support. A
        # derivation from independently-supported premises is unaffected: the
        # verdict is about whether support survives, not about whether a
        # premise is unusual.
        if self.state.memories[derived].lifecycle_state is not LifecycleState.QUARANTINED:
            verdict = self.justifications.recompute(derived)
            if not verdict.still_justified:
                self._emit(
                    ev.support_recomputed(
                        ts=self.now(),
                        memory_id=verdict.memory_id,
                        trigger_memory_id=derived,
                        verdict=verdict.verdict,
                        surviving=list(verdict.surviving),
                        lost=list(verdict.lost),
                        independent_count=verdict.independent_count,
                        reason=verdict.reason,
                        actor=agent_id,
                    ),
                    self._transition(
                        derived,
                        LifecycleState.CONTESTED,
                        f"derived from premises that do not support it: "
                        f"{verdict.reason}",
                        agent_id,
                    ),
                )
        return derived

    @_fresh
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
