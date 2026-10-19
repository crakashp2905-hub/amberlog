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

__stability__ = "stable"

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
    tenant_id: str | None = None,
) -> OfferResult:
    """Offer one memory across a store boundary.

    `activate=False` (the default) leaves the import as a candidate, which is
    the honest state for knowledge that has never been tested here. Passing
    True is the "trust the sender" mode and should be a deliberate choice.

    `tenant_id` names the tenant the import lands in **at the recipient**, and
    defaults to the source memory's. That default is right for a single-tenant
    federation and is the only thing it can be, because a tenant id is local to
    a store: nothing in the protocol makes `tn_acme` at one store the same
    customer as `tn_acme` at another, and pretending otherwise would turn a
    naming coincidence into a cross-customer disclosure. A multi-tenant
    recipient should pass its own id explicitly.
    """
    prepared = prepare_offer(source, memory_id, target.store_id, granted_capabilities)
    if isinstance(prepared, OfferResult):
        return prepared
    result = accept_offer(target, prepared, recipient_agent, granted_capabilities,
                          activate=activate, tenant_id=tenant_id)
    if result.accepted and result.imported_memory_id:
        # Record the share on the *sender* side. Without it the sender has no
        # idea who holds a copy, and a retraction cannot follow a memory it
        # cannot find, which is what stopped retraction at one hop before
        # Phase D.
        source.record_share(memory_id=memory_id, recipient_store_id=target.store_id,
                            imported_memory_id=result.imported_memory_id,
                            actor=recipient_agent)
    return result


@dataclass(frozen=True)
class PreparedOffer:
    """What crosses the boundary: the memory as the recipient will import it.

    Built by the sender (`prepare_offer`) and accepted by the recipient
    (`accept_offer`), in one process (`offer`) or over the network
    (`offer_remote`, `/federation/offer`).
    """

    origin_store_id: str
    source_memory_id: str
    version: int
    content: str
    type: str
    context: dict[str, Any]
    structured: dict[str, Any] | None
    security_class: str
    capabilities: tuple[str, ...]
    tenant_id: str

    def to_json(self) -> dict[str, Any]:
        return {"origin_store_id": self.origin_store_id,
                "source_memory_id": self.source_memory_id, "version": self.version,
                "content": self.content, "type": self.type, "context": self.context,
                "structured": self.structured, "security_class": self.security_class,
                "capabilities": list(self.capabilities), "tenant_id": self.tenant_id}

    @classmethod
    def from_json(cls, d: Any) -> "PreparedOffer":
        return cls(origin_store_id=str(d["origin_store_id"]),
                   source_memory_id=str(d["source_memory_id"]), version=int(d["version"]),
                   content=str(d["content"]), type=str(d["type"]), context=dict(d["context"]),
                   structured=dict(d["structured"]) if d.get("structured") else None,
                   security_class=str(d["security_class"]),
                   capabilities=tuple(str(c) for c in d.get("capabilities", ())),
                   tenant_id=str(d["tenant_id"]))


def prepare_offer(source: "MemoryFabric", memory_id: str, target_store_id: str,
                  granted_capabilities: Iterable[str] = ()) -> "PreparedOffer | OfferResult":
    """The sender's half: its own firewall, the provenance chain, the envelope.

    Returns an `OfferResult` refusal, or the `PreparedOffer` to send.
    """
    from .protocol import MAX_HOPS

    memory = source.get(memory_id)
    # The sender's own firewall decides whether this may leave at all.
    outbound = source.firewall_check(memory_id, Scope.FEDERATED, granted_capabilities)
    if not outbound.permits_sharing:
        return OfferResult(source_memory_id=memory_id, accepted=False,
                           decision=outbound.decision,
                           reasons=[f"sender refused: {reason}" for reason in outbound.reasons])
    # Every store this memory has passed through, oldest first. A re-share of
    # an import names the intermediary as its origin, so without the chain a
    # memory shared A -> B -> A came home as a *new* import of A's own memory:
    # an echo. B never forwards A's retraction back to A (A is where it came
    # from), so when A corrected the memory its own older version stayed active
    # beside the new one, at the origin itself (found by S1's CorrectionSim).
    chain = _chain(memory)
    if target_store_id in chain or target_store_id == source.store_id:
        return OfferResult(source_memory_id=memory_id, accepted=False,
                           decision=FirewallDecision.DENY,
                           reasons=["recipient refused: it is already on this memory's "
                                    "provenance chain (an echo of a memory it holds)"])
    # A copy must not travel further than its retraction can follow. Forwarded
    # retractions stop at MAX_HOPS (recorded as `hop_limit`), so before this
    # check a 20-store chain left the last two copies live after a correction
    # at the origin (experiments/fed_scale.py).
    if len(chain) >= MAX_HOPS:
        return OfferResult(source_memory_id=memory_id, accepted=False,
                           decision=FirewallDecision.DENY,
                           reasons=[f"sender refused: this memory is {len(chain)} hops from "
                                    f"its origin; a retraction reaches at most {MAX_HOPS}"])

    from .independence import Independence, global_ref

    root_store, root_id = global_ref(source, memory_id)
    informed = sorted(Independence(source).informed_by(memory_id))
    context = dict(memory.context)
    context[ORIGIN_KEY] = {
        "agent": memory.provenance.created_by,
        "memory_id": memory_id,
        # The store's opaque identity, not its path.
        "store": source.store_id,
        # The exact version imported, so a retraction of v1 cannot withdraw an
        # import of v3.
        "version": memory.version,
        "chain": [*chain, source.store_id],
        # The original observation, named the same in every store, and the
        # originals its author had been shown before writing it: what lets a
        # recipient tell a laundered copy from an independent report (S2).
        "root": {"store": root_store, "memory_id": root_id},
        "informed_by": [list(ref) for ref in informed],
        # The origin's verdict on the memory's authority. The recipient
        # treats it as a floor: it can lower trust there, never raise it.
        "authority": source.authority(memory_id).to_wire(),
    }
    return PreparedOffer(
        origin_store_id=source.store_id, source_memory_id=memory_id, version=memory.version,
        content=memory.content, type=memory.type.value, context=context,
        structured=dict(memory.structured) if memory.structured else None,
        security_class=memory.security_class.value, capabilities=tuple(memory.capabilities),
        tenant_id=memory.tenant_id)


def accept_offer(target: "MemoryFabric", prepared: PreparedOffer, recipient_agent: str,
                 granted_capabilities: Iterable[str] = (), activate: bool = False,
                 tenant_id: str | None = None) -> OfferResult:
    """The recipient's half: the chain, its own firewall, and the import.

    Idempotent: the same origin memory and version offered twice returns the
    import already made, so a retried network offer does not duplicate it.
    """
    from .model import MemoryType, Provenance, SecurityClass

    origin = prepared.context.get(ORIGIN_KEY) or {}
    if target.store_id in list(origin.get("chain") or []):
        return OfferResult(source_memory_id=prepared.source_memory_id, accepted=False,
                           decision=FirewallDecision.DENY,
                           reasons=["recipient refused: it is already on this memory's "
                                    "provenance chain (an echo of a memory it holds)"])
    for existing in target.state.memories.values():
        held = (existing.context or {}).get(ORIGIN_KEY)
        if (isinstance(held, dict) and held.get("store") == prepared.origin_store_id
                and held.get("memory_id") == prepared.source_memory_id
                and held.get("version") == prepared.version):
            return OfferResult(source_memory_id=prepared.source_memory_id, accepted=True,
                               decision=FirewallDecision.ALLOW,
                               reasons=["already imported"], imported_memory_id=existing.id)
    candidate = Memory(
        id="offer", version=1, type=MemoryType(prepared.type), content=prepared.content,
        provenance=Provenance(created_by=str(origin.get("agent", "federation")),
                              method=ProvenanceMethod.IMPORTED),
        context=prepared.context, structured=prepared.structured,
        security_class=SecurityClass(prepared.security_class),
        capabilities=prepared.capabilities, tenant_id=prepared.tenant_id)
    inbound = _inbound_check(target, candidate, granted_capabilities)
    if not inbound.permits_sharing:
        return OfferResult(source_memory_id=prepared.source_memory_id, accepted=False,
                           decision=inbound.decision,
                           reasons=[f"recipient refused: {reason}" for reason in inbound.reasons])
    imported_id = target.remember(
        agent_id=recipient_agent,
        content=prepared.content,
        type=MemoryType(prepared.type),
        context=prepared.context,
        method=ProvenanceMethod.IMPORTED,
        structured=prepared.structured,
        security_class=SecurityClass(prepared.security_class),
        capabilities=prepared.capabilities,
        # Explicit, not inherited: a store with `auto_activate` on would
        # otherwise promote every import on arrival, which is exactly the
        # guarantee this function exists to make. An import is not a trusted
        # local observation, whatever the recipient's convenience setting says.
        auto_activate=activate,
        tenant_id=prepared.tenant_id if tenant_id is None else tenant_id,
    )
    return OfferResult(source_memory_id=prepared.source_memory_id, accepted=True,
                       decision=inbound.decision, reasons=inbound.reasons,
                       imported_memory_id=imported_id)


def offer_remote(source: "MemoryFabric", memory_id: str, transport: Any,
                 recipient_store_id: str, recipient_agent: str,
                 granted_capabilities: Iterable[str] = ()) -> OfferResult:
    """Offer one memory to a store on another machine, over a transport.

    The same rules as `offer`: the sender's firewall and chain checks here,
    the recipient's firewall and import there. Over the network the import
    always lands as a **candidate**: a remote sender cannot ask a recipient to
    activate its memory.
    """
    prepared = prepare_offer(source, memory_id, recipient_store_id, granted_capabilities)
    if isinstance(prepared, OfferResult):
        return prepared
    # The recipient records the import as `peer:<this store>`, whatever
    # `recipient_agent` says; the name is kept for the sender's share record.
    reply = transport.send_offer(recipient_store_id, prepared, recipient_agent)
    result = OfferResult(source_memory_id=memory_id, accepted=bool(reply.get("accepted")),
                         decision=FirewallDecision(reply.get("decision", "deny")),
                         reasons=list(reply.get("reasons") or []),
                         imported_memory_id=reply.get("imported_memory_id"))
    if result.accepted and result.imported_memory_id:
        source.record_share(memory_id=memory_id, recipient_store_id=recipient_store_id,
                            imported_memory_id=result.imported_memory_id,
                            actor=recipient_agent)
    return result


def _chain(memory: Memory) -> list[str]:
    """The stores a memory passed through before its current holder, oldest first.

    Imports made before the chain was recorded name only their immediate
    origin, which is the most that can be recovered for them.
    """
    origin = memory.context.get(ORIGIN_KEY)
    if not isinstance(origin, dict):
        return []
    chain = origin.get("chain")
    if isinstance(chain, list) and all(isinstance(s, str) for s in chain):
        return list(chain)
    return [origin["store"]] if isinstance(origin.get("store"), str) else []


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
