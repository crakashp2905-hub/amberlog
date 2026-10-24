"""Lifecycle governance: validation, quarantine and its propagation, release, deprecation, challenges and resolutions, retention, and origin-bound authority.

A service mixin of `MemoryFabric`, built on `FabricCore`. Methods moved here
verbatim from `fabric.py`.
"""

from __future__ import annotations

__stability__ = "stable"



from typing import TYPE_CHECKING, Any, Iterable, Mapping, Sequence, cast

if TYPE_CHECKING:
    from ..fabric import MemoryFabric  # noqa: F401
    pass

from .. import events as ev
from ..governance.retention import RetentionDecision
from ..ids import new_ulid

from ..model import (
    EXPOSABLE_STATES,
    LifecycleState,
    Memory,
    WithdrawalBasis,
)


from .core import FabricCore
from .common import NotFound, PolicyViolation, _fresh


class LifecycleMixin(FabricCore):

    # --- lifecycle -------------------------------------------------------

    def _transition(
        self,
        memory_id: str,
        to_state: LifecycleState,
        reason: str,
        actor: str,
        basis: str | None = None,
    ) -> ev.Event:
        memory = self._require(memory_id)
        return ev.lifecycle_changed(
            ts=self.now(),
            memory_id=memory_id,
            from_state=memory.lifecycle_state.value,
            to_state=to_state.value,
            reason=reason,
            actor=actor,
            basis=basis,
        )

    @_fresh
    def validate(self, memory_id: str, actor: str, reason: str = "validated") -> Memory:
        """Promote a candidate to active."""
        memory = self._require(memory_id)
        if memory.lifecycle_state is LifecycleState.QUARANTINED:
            raise PolicyViolation(
                f"{memory_id} is quarantined; review and release it before validating"
            )
        self._emit(self._transition(memory_id, LifecycleState.ACTIVE, reason, actor))
        return self.state.memories[memory_id]

    @_fresh
    def quarantine(
        self,
        memory_id: str,
        reason: str,
        actor: str = "operator",
        propagate: bool = True,
        basis: str | WithdrawalBasis | None = None,
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

        `basis` says *what kind of evidence* this rests on
        (`WithdrawalBasis`). It is optional so that existing callers keep
        working, and an omitted basis is recorded as `unstated` — which the
        attention list then surfaces, because "nobody said" is exactly the case
        worth a second look.

        Returns the ids marked contested.
        """
        target = self._require(memory_id)
        basis_value = (
            basis.value if isinstance(basis, WithdrawalBasis) else basis
        ) or WithdrawalBasis.UNSTATED.value
        # Only on a finding that the *value* is wrong: notes repeating a value
        # withdrawn for containing a secret, say, say nothing wrong.
        from .. import validation

        left_behind = (validation.restatements(cast("MemoryFabric", self), target)
                       if propagate and self.contest_restatements
                       and basis_value == WithdrawalBasis.CONTRADICTED.value
                       and target.lifecycle_state is LifecycleState.ACTIVE else [])
        emitted = [
            self._transition(
                memory_id, LifecycleState.QUARANTINED, reason, actor, basis_value
            )
        ]
        contested: list[str] = []
        if propagate:
            # Recompute support rather than assume its loss.
            #
            # This loop used to mark *every* descendant contested, so a
            # conclusion resting on two independent premises was treated
            # exactly like one resting on a single invalidated premise.
            # `evidence_is_independent` existed to tell them apart and nothing
            # called it, which is why roadmap §4.2 — correct a belief without
            # withdrawing unrelated knowledge — was unimplemented.
            #
            # The quarantine is emitted first so the recomputation sees the
            # premise as already lost; otherwise every descendant would still
            # find it usable and nothing would be contested at all.
            self._emit(*emitted)
            emitted = []

            # Nearest first, recomputing each one *after* the previous
            # transition has been emitted. Batching the verdicts against a
            # single snapshot looked equivalent and was not: a grandchild was
            # evaluated while its parent was still active, so it stayed
            # justified and the cascade stopped one level short. The lineage
            # walk is already ordered by depth, so one pass suffices.
            for node in sorted(
                self.lineage_graph.descendants(memory_id), key=lambda n: n.depth
            ):
                descendant = self.state.memories.get(node.memory_id)
                if descendant is None:
                    continue
                if descendant.lifecycle_state in (
                    LifecycleState.QUARANTINED,
                    LifecycleState.DELETED,
                ):
                    continue

                verdict = self.justifications.recompute(node.memory_id)
                record = ev.support_recomputed(
                    ts=self.now(),
                    memory_id=verdict.memory_id,
                    trigger_memory_id=memory_id,
                    verdict=verdict.verdict,
                    surviving=list(verdict.surviving),
                    lost=list(verdict.lost),
                    independent_count=verdict.independent_count,
                    reason=verdict.reason,
                    actor=actor,
                )
                if verdict.still_justified:
                    # Independently justified knowledge survives the loss of one
                    # premise. Recorded anyway, so an operator can see that the
                    # recomputation happened and what carried the conclusion.
                    self._emit(record)
                    continue

                self._emit(
                    record,
                    self._transition(
                        verdict.memory_id,
                        LifecycleState.CONTESTED,
                        f"support recomputed after {memory_id} was quarantined: "
                        f"{verdict.reason}",
                        actor,
                    ),
                )
                contested.append(verdict.memory_id)

            # Copies, which are not descendants and must not be treated as
            # such. A re-ingestion is not *justified by* the original -- it is
            # the same document -- so `justifications.recompute` has nothing to
            # say about it and would leave it standing. Withdrawing a document
            # withdraws every copy of it, transitively, and then the normal
            # recomputation runs over whatever those copies support.
            #
            # Without this, withdrawal order decided the outcome: a copy
            # written *after* the original was withdrawn came in contested,
            # while one written before it stayed active. The same two memories
            # and the same finding, with opposite results depending on which
            # arrived first.
            for copy_id in self._copy_closure(memory_id):
                copy = self.state.memories.get(copy_id)
                if copy is None or copy.lifecycle_state in (
                    LifecycleState.QUARANTINED,
                    LifecycleState.DELETED,
                    LifecycleState.CONTESTED,
                ):
                    continue
                self._emit(self._transition(
                    copy_id,
                    LifecycleState.CONTESTED,
                    f"re-ingestion of {memory_id}, which was withdrawn: {reason}",
                    actor,
                    basis_value,
                ))
                contested.append(copy_id)
                for node in sorted(
                    self.lineage_graph.descendants(copy_id),
                    key=lambda n: n.depth,
                ):
                    downstream = self.state.memories.get(node.memory_id)
                    if downstream is None or downstream.lifecycle_state in (
                        LifecycleState.QUARANTINED,
                        LifecycleState.DELETED,
                        LifecycleState.CONTESTED,
                    ):
                        continue
                    verdict = self.justifications.recompute(node.memory_id)
                    self._emit(ev.support_recomputed(
                        ts=self.now(),
                        memory_id=verdict.memory_id,
                        trigger_memory_id=copy_id,
                        verdict=verdict.verdict,
                        surviving=list(verdict.surviving),
                        lost=list(verdict.lost),
                        independent_count=verdict.independent_count,
                        reason=verdict.reason,
                        actor=actor,
                    ))
                    if not verdict.still_justified:
                        self._emit(self._transition(
                            verdict.memory_id,
                            LifecycleState.CONTESTED,
                            f"support recomputed after copy {copy_id} was "
                            f"contested: {verdict.reason}",
                            actor,
                        ))
                        contested.append(verdict.memory_id)
        self._emit(*emitted)
        before = {m for m in left_behind
                  if self.state.memories[m].lifecycle_state is LifecycleState.ACTIVE}
        self._contest(sorted(before), f"restates the value of {memory_id}, withdrawn as "
                                      "contradicted", actor)
        return contested + sorted(before)

    def _copy_closure(self, memory_id: str) -> list[str]:
        """Every other memory that is the same document as this one.

        **Symmetric**, which the first version was not. "These are the same
        document" does not have a direction, but the recorded edge does: the
        newer write points at the older one. So when a corpus arrives shuffled
        and the copy happens to be stored *before* the original, the edge runs
        copy -> original the other way round, and a walk that followed only
        `copies` found nothing. Withdrawing the original then left the copy
        standing -- the same ingestion order deciding the outcome that the
        write-time check was added to remove, surviving one level down.

        The relation is therefore walked as an undirected component over both
        indexes. A copy of a copy is still the same document, so it is
        transitive too. Ordered and cycle-guarded: the edges come from the log,
        and a propagation walk is the wrong place to discover a malformed one.
        """
        out: list[str] = []
        seen = {memory_id}
        frontier = [memory_id]
        while frontier:
            current = frontier.pop()
            neighbours = set(self.state.copies.get(current, ()))
            original = self.state.copy_of.get(current)
            if original is not None:
                neighbours.add(original)
            for other in sorted(neighbours):
                if other in seen:
                    continue
                seen.add(other)
                out.append(other)
                frontier.append(other)
        return out

    @_fresh
    def release(self, memory_id: str, actor: str, reason: str = "reviewed and released") -> Memory:
        """Bring a quarantined memory back to candidate after human review."""
        memory = self._require(memory_id)
        if memory.lifecycle_state is not LifecycleState.QUARANTINED:
            raise PolicyViolation(f"{memory_id} is not quarantined")
        self._emit(self._transition(memory_id, LifecycleState.CANDIDATE, reason, actor))
        return self.state.memories[memory_id]

    @_fresh
    def forget(self, memory_id: str, reason: str, actor: str = "operator") -> Memory:
        """Deprecate. Deletion is the retention policy's decision, not the
        caller's, so that a single call can never destroy an audit trail."""
        self._emit(self._transition(memory_id, LifecycleState.DEPRECATED, reason, actor))
        self._unindex(memory_id)
        return self.state.memories[memory_id]

    @_fresh
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

    @_fresh
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

    @_fresh
    def sweep_retention(self, apply: bool = False, actor: str = "retention",
                        actions: Iterable[str] | None = None) -> list[RetentionDecision]:
        """The retention policy's decisions; with `apply`, carry them out.

        `actions` limits what is applied (for example `{"deprecate"}`). The
        background manager uses it: `delete` is terminal, so an unattended
        process applies it only when the owner has opted in (`manager.py`).
        """
        now = self.now()
        pairs = [
            (memory, self.state.stats_for(memory.id))
            for memory in self.state.memories.values()
        ]
        decisions = self.retention.sweep(pairs, now)
        # A premise of something still exposable is not retired: a summary
        # (`compaction.py`) or conclusion must never outlive the sources a
        # correction would need to follow. Raw turns age out after their
        # summary does.
        premises = {pid for m in self.state.memories.values()
                    if m.lifecycle_state in EXPOSABLE_STATES
                    for pid, _ in m.provenance.parents}
        decisions = [d for d in decisions if d.memory_id not in premises]
        if actions is not None:
            allowed = set(actions)
            decisions = [d for d in decisions if d.action in allowed]
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
                self._unindex(decision.memory_id)
            if emitted:
                self._emit(*emitted)
        return decisions

    @_fresh
    def elevate(self, memory_id: str, approver: str, reason: str,
                policy: str = "manual-review", revoke: bool = False) -> "Any":
        """Lift a memory version's *soft* authority reasons, after review.

        Refused when the approver wrote the memory, or when a hard reason
        (withdrawn or contested ancestor, hostile source, instruction) stands:
        those are removed at their cause, not overridden.
        """
        from .. import authority

        memory = self._require(memory_id)
        current = authority.of(cast("MemoryFabric", self), memory_id)
        if not revoke:
            if approver == memory.provenance.created_by or approver in current.origins:
                raise PolicyViolation("a memory's author or source cannot elevate it")
            if current.hard:
                raise PolicyViolation(
                    f"cannot elevate past hard reasons: {sorted(r for r in current.reasons if r in authority.HARD)}")
        self._emit(ev.authority_elevated(ts=self.now(), memory_id=memory_id,
                                         version=memory.version, approver=approver,
                                         policy=policy, reason=reason, revoked=revoke))
        return authority.of(cast("MemoryFabric", self), memory_id)

    def authority(self, memory_id: str) -> "Any":
        """Origin-bound authority of a memory (`authority.py`)."""
        from .. import authority

        self._require(memory_id)
        return authority.of(cast("MemoryFabric", self), memory_id)

    def _suspicious(self, agent_id: str, content: str, context: Any, tenant_id: str) -> bool:
        from ..validation import assess_write

        try:
            return assess_write(cast("MemoryFabric", self), agent_id, content, context, tenant_id).suspicious
        except Exception:  # noqa: BLE001 - validation never blocks a write
            return False
