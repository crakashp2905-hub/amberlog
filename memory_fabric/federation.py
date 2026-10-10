"""Offering a memory from one store to another.

Federation here means **separate stores**. A single store with visibility flags
is a different thing — useful, but it shares one event log, one estimator and
one administrator. Crossing a real boundary is what raises the questions this
module exists to answer: does the recipient trust it, is it worth anything
*here*, and where did it come from.

Three rules hold on every import:

* **The recipient decides.** The offer runs through the *recipient's* firewall,
  with the recipient's policies and capability grants. A sender cannot push a
  memory past rules it does not control.
* **An import is a candidate, not a fact.** It arrives unvalidated and is not
  retrievable until the recipient activates it. Value earned in one context is
  not evidence about another — that is the whole premise of H3.
* **Provenance crosses with it.** The imported memory records the origin agent,
  the origin memory id and the origin store, so "why do we believe this?"
  survives the boundary. Without that, a federated store cannot explain itself
  and a retraction cannot follow a memory to where it travelled.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Iterable, Sequence

from .model import (
    FirewallDecision,
    LifecycleState,
    WithdrawalBasis,
    Memory,
    ProvenanceMethod,
    Scope,
)

if TYPE_CHECKING:  # pragma: no cover
    from .fabric import MemoryFabric

ORIGIN_KEY = "federation"


@dataclass
class OfferResult:
    """What happened to one offered memory."""

    source_memory_id: str
    accepted: bool
    decision: FirewallDecision
    reasons: list[str] = field(default_factory=list)
    imported_memory_id: str | None = None

    def __bool__(self) -> bool:
        return self.accepted


@dataclass
class FederationSummary:
    offered: int = 0
    accepted: int = 0
    refused: int = 0
    results: list[OfferResult] = field(default_factory=list)

    @property
    def acceptance_rate(self) -> float:
        return self.accepted / self.offered if self.offered else 0.0


def describe(fabric: "MemoryFabric", memory_id: str) -> dict[str, Any]:
    """The metadata a recipient needs to decide, without the content.

    Sending this first and fetching the body only on acceptance is the
    metadata-first protocol: a capability advertisement rather than a bulk
    copy. The body is usually far larger than the description, so this is where
    the communication saving lives.
    """
    memory = fabric.get(memory_id)
    value = fabric.value(memory_id)
    return {
        "memory_id": memory_id,
        "type": memory.type.value,
        "context": dict(memory.context),
        "security_class": memory.security_class.value,
        "capabilities": list(memory.capabilities),
        "lifecycle_state": memory.lifecycle_state.value,
        "value": {
            "mean": value.mean if value.n_eff > 0 else None,
            "n_eff": value.n_eff,
            "contrastive": value.contrastive,
        },
        "content_chars": len(memory.content),
    }


def offer(
    source: "MemoryFabric",
    memory_id: str,
    target: "MemoryFabric",
    recipient_agent: str,
    granted_capabilities: Iterable[str] = (),
    activate: bool = False,
) -> OfferResult:
    """Offer one memory across a store boundary.

    `activate=False` (the default) leaves the import as a candidate, which is
    the honest state for knowledge that has never been tested here. Passing
    True is the "trust the sender" mode and should be a deliberate choice.
    """
    memory = source.get(memory_id)

    # The sender's own firewall decides whether this may leave at all.
    outbound = source.firewall_check(memory_id, Scope.FEDERATED, granted_capabilities)
    if not outbound.permits_sharing:
        return OfferResult(
            source_memory_id=memory_id,
            accepted=False,
            decision=outbound.decision,
            reasons=[f"sender refused: {reason}" for reason in outbound.reasons],
        )

    inbound = _inbound_check(target, memory, granted_capabilities)
    if not inbound.permits_sharing:
        return OfferResult(
            source_memory_id=memory_id,
            accepted=False,
            decision=inbound.decision,
            reasons=[f"recipient refused: {reason}" for reason in inbound.reasons],
        )

    context = dict(memory.context)
    context[ORIGIN_KEY] = {
        "agent": memory.provenance.created_by,
        "memory_id": memory_id,
        # The store's opaque identity, not its path. `log.path` made two
        # containers each holding `./store.db` indistinguishable, broke every
        # provenance match when a database moved, and gave every in-memory
        # store the identity `:memory:`.
        "store": source.store_id,
        # The exact version imported, so a retraction of v1 cannot withdraw an
        # import of v3. Provenance has always carried versions for parents;
        # imports did not record one at all.
        "version": memory.version,
    }

    imported_id = target.remember(
        agent_id=recipient_agent,
        content=memory.content,
        type=memory.type,
        context=context,
        method=ProvenanceMethod.IMPORTED,
        structured=memory.structured,
        security_class=memory.security_class,
        capabilities=memory.capabilities,
        # Explicit, not inherited: a store with `auto_activate` on would
        # otherwise promote every import on arrival, which is exactly the
        # guarantee this function exists to make. An import is not a trusted
        # local observation, whatever the recipient's convenience setting says.
        auto_activate=activate,
    )

    # Record the share on the *sender* side. Without it the sender has no idea
    # who holds a copy, and a retraction cannot follow a memory it cannot find
    # — which is what stopped retraction at one hop before Phase D.
    source.record_share(
        memory_id=memory_id,
        recipient_store_id=target.store_id,
        imported_memory_id=imported_id,
        actor=recipient_agent,
    )

    return OfferResult(
        source_memory_id=memory_id,
        accepted=True,
        decision=inbound.decision,
        reasons=inbound.reasons,
        imported_memory_id=imported_id,
    )


def _inbound_check(target: "MemoryFabric", memory: Memory, granted: Iterable[str]):
    """Run the recipient's firewall against a memory it does not hold yet.

    `MemoryFabric.firewall_check` works on a stored memory; an offer has not
    been stored, and storing it first in order to ask permission would defeat
    the point. So the request is built directly against the recipient's policy.
    """
    from .governance.firewall import FirewallRequest

    return target.firewall.evaluate(
        FirewallRequest(
            memory=memory.evolve(lifecycle_state=LifecycleState.ACTIVE),
            target_scope=Scope.FEDERATED,
            # The sender's value evidence says nothing about this context, so
            # the recipient is told it has none. H3 is the test of that claim.
            value=None,
            hypothesis_open=False,
            granted_capabilities=frozenset(granted),
            evidence_independent=True,
        )
    )


def offer_many(
    source: "MemoryFabric",
    target: "MemoryFabric",
    recipient_agent: str,
    memory_ids: Sequence[str] | None = None,
    granted_capabilities: Iterable[str] = (),
    activate: bool = False,
) -> FederationSummary:
    """Offer a set of memories, defaulting to everything currently active."""
    if memory_ids is None:
        memory_ids = [
            memory_id
            for memory_id, memory in source.state.memories.items()
            if memory.lifecycle_state is LifecycleState.ACTIVE
        ]

    summary = FederationSummary()
    for memory_id in memory_ids:
        result = offer(
            source, memory_id, target, recipient_agent, granted_capabilities, activate
        )
        summary.offered += 1
        summary.results.append(result)
        if result.accepted:
            summary.accepted += 1
        else:
            summary.refused += 1
    return summary


def imported_from(fabric: "MemoryFabric", memory_id: str) -> dict[str, Any] | None:
    """The origin record of an imported memory, or None if it is native."""
    origin = fabric.get(memory_id).context.get(ORIGIN_KEY)
    return dict(origin) if isinstance(origin, dict) else None


@dataclass
class PropagationResult:
    """What happened to one importer when a retraction followed a memory."""

    store: str
    memory_id: str
    acted: bool
    state: str
    reason: str = ""


def descendants_of(
    source: "MemoryFabric", memory_id: str, targets: Sequence["MemoryFabric"]
) -> list[tuple["MemoryFabric", str]]:
    """Every import of `memory_id` held by any of `targets`.

    Three conditions, and each one was needed:

    * **The origin store as well as the origin id.** Ids are per-store, so two
      unrelated stores can mint the same one, and matching on the id alone would
      withdraw a memory that merely shares an identifier.
    * **Provenance method `IMPORTED`.** A memory *derived* locally from an
      import inherits the parent's context, origin record included, so it looks
      like a second copy of the imported memory. Without this condition a
      retraction quarantined the recipient's own conclusion directly instead of
      contesting it — which overstates what the origin's retraction establishes.
      The origin can say "my observation was wrong"; only the recipient can say
      what follows for the reasoning it built on top.
    * **The import itself, not its children.** The children are reached by
      `quarantine`'s own lineage propagation, which marks them *contested* — the
      correct weaker claim.
    """
    found: list[tuple["MemoryFabric", str]] = []
    for target in targets:
        for candidate in target.state.memories:
            memory = target.get(candidate)
            if memory.provenance.method != ProvenanceMethod.IMPORTED:
                continue
            origin = imported_from(target, candidate)
            if (
                origin
                and origin.get("memory_id") == memory_id
                and origin.get("store") == source.store_id
            ):
                found.append((target, candidate))
    return found


def propagate_retraction(
    source: "MemoryFabric",
    memory_id: str,
    targets: Sequence["MemoryFabric"],
    actor: str = "federation",
    reason: str = "retracted at origin",
) -> list[PropagationResult]:
    """Carry a retraction to the stores a memory travelled to.

    This is the operation the module docstring promises and the one PRIOR_ART.md
    identifies as the strongest surviving novelty claim: none of the four
    adjacent papers carries provenance across a federation boundary, so none can
    do this at all. It was previously done by hand inside an experiment, which
    meant the product did not actually have it.

    **Quarantine, not delete.** An importer may have built on the memory, and its
    descendants need to become contested rather than vanish — which is what
    `quarantine` does and a deletion cannot. It is also reversible: if the origin
    turns out to have retracted in error, `release` undoes this, and nothing was
    thrown away in the meantime.

    The importer's existing state is respected. A memory already quarantined
    locally is left alone and reported as such, because overwriting the local
    reason with the remote one would lose the fact that the recipient had
    independently found the problem — which is exactly the evidence that matters
    when deciding whether to trust that sender again.
    """
    results: list[PropagationResult] = []
    for target, imported_id in descendants_of(source, memory_id, targets):
        state = target.get(imported_id).lifecycle_state
        if state in (LifecycleState.QUARANTINED, LifecycleState.DELETED):
            results.append(
                PropagationResult(
                    store=target.log.path,
                    memory_id=imported_id,
                    acted=False,
                    state=state.value,
                    reason="already withdrawn locally",
                )
            )
            continue
        target.quarantine(
            imported_id,
            reason=reason,
            actor=actor,
            # Not a local finding: the origin store withdrew it. Recorded as its
            # own basis so an importer can tell "we found a problem" from
            # "someone else did", which is what decides whether to trust that
            # sender next time.
            basis=WithdrawalBasis.RETRACTED_AT_ORIGIN,
        )
        results.append(
            PropagationResult(
                store=target.log.path,
                memory_id=imported_id,
                acted=True,
                state=target.get(imported_id).lifecycle_state.value,
            )
        )
    return results


def imports(fabric: "MemoryFabric") -> list[str]:
    return [
        memory_id
        for memory_id in fabric.state.memories
        if imported_from(fabric, memory_id) is not None
    ]
