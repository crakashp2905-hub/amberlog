"""Phase 7 — the stable SDK surface.

The roadmap's requirement is precise and worth quoting: *make the protocol
usable and inspectable **without allowing integrations to bypass enforcement***.
That shapes the whole module.

`MemoryFabric` is the engine and has to expose everything — including
`get()`, which returns a memory whatever its lifecycle state because `explain`,
the CLI and the dashboard must be able to show a withdrawn memory to a human.
That makes it the wrong thing to hand an integrator: the one call an adapter
should never make is right there next to the ones it should.

So `AgentClient` is a *narrower* object, not a thinner one. It has no method
that returns content without an enforcement decision, no way to write an
outcome it verified itself, and no access to another agent's memories. An
adapter written against it cannot reach past the checks, which is a stronger
guarantee than documenting that it shouldn't.

`OperatorClient` is the other half: read-only inspection, explicitly allowed to
see withdrawn content, and unable to write anything an agent would consume.

Both are thin wrappers over the engine. The point is what they *omit*.
"""

from __future__ import annotations

__stability__ = "stable"

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

from .enforcement import AccessDecision, EnforcedRead, ExposureToken, RiskLevel
from .identity import DEFAULT_TENANT, Credential
from .model import Memory, MemoryType, Scope
from .protocol import Acknowledgement, Retraction

__all__ = [
    "AgentClient",
    "OperatorClient",
    "SdkError",
    "NotUsable",
    "UsableMemory",
]


class SdkError(RuntimeError):
    """Base for everything this module raises deliberately."""


class NotUsable(SdkError):
    """A memory was requested and the enforcement layer refused.

    Carries the decision, so a caller can branch on `reason_code` rather than
    parse a message. Never carries the content — a refusal that quoted the
    memory would move it into every log that records an exception.
    """

    def __init__(self, decision: AccessDecision) -> None:
        super().__init__(
            f"{decision.memory_id} is not usable: {decision.reason_code}"
            + (f" ({decision.detail})" if decision.detail else "")
        )
        self.decision = decision


@dataclass(frozen=True)
class UsableMemory:
    """A memory that passed enforcement, with the token to re-check it.

    The token is not optional and not separable: an integration that wants the
    content gets the means to re-verify it at action time in the same object,
    so forgetting to is a visible omission rather than an invisible one.
    """

    memory_id: str
    version: int
    content: str
    type: str
    token: ExposureToken
    warnings: tuple[str, ...] = ()

    @property
    def contested(self) -> bool:
        return bool(self.warnings)


class AgentClient:
    """What an adapter is given. Deliberately narrow.

    Bound to one agent id **and one tenant**, so an adapter cannot attribute
    work to another agent or read another customer's knowledge — the same
    guarantee `AgentSession` gives for writes, extended to reads and to the
    tenant boundary.

    The tenant is a constructor argument rather than a parameter on `recall`
    for the same reason scope is not a parameter on `remember`: a boundary that
    can be passed per call is a boundary that can be omitted per call. Use
    `agent_for(fabric, credential)` where the binding should be *verified*
    rather than asserted.
    """

    def __init__(
        self, fabric: Any, agent_id: str, tenant_id: str = DEFAULT_TENANT
    ) -> None:
        self._fabric = fabric
        self._agent_id = agent_id
        self._tenant_id = tenant_id

    @property
    def agent_id(self) -> str:
        return self._agent_id

    @property
    def tenant_id(self) -> str:
        return self._tenant_id

    @property
    def store_id(self) -> str:
        return self._fabric.store_id

    # --- reading ---------------------------------------------------------

    def recall(
        self,
        query: str,
        k: int = 5,
        context: Mapping[str, Any] | None = None,
        include_contested: bool = False,
        episode_id: str | None = None,
        within: Iterable[str] | None = None,
    ) -> list[UsableMemory]:
        """Retrieve, enforced, with a token per result.

        `within` limits the search to these ids (an opened topic, `navigation.py`).

        Goes through `fabric.retrieve`, which filters on lifecycle before the
        index is consulted, and then through the enforcement layer again for the
        token. The second pass is not redundant: retrieval decides *what to
        show*, enforcement decides *whether it may be acted on*, and the token
        is what makes the second answer checkable later.
        """
        hits = self._fabric.retrieve(
            agent_id=self._agent_id,
            query=query,
            context=context,
            k=k,
            episode_id=episode_id,
            include_contested=include_contested,
            tenant_id=self._tenant_id,
            within=within,
        )
        from .conflicts import find_conflicts

        # A memory that gives a different value for the same claim as another
        # returned memory, by a different author, carries a warning naming it
        # (default since 0.12.0; G4b). The agent sees the disagreement instead
        # of whichever one ranked first.
        disputed: dict[str, set[str]] = {}
        for group in find_conflicts(list(hits.exposed)):
            ids = {m.id for m in group}
            for m in group:
                disputed.setdefault(m.id, set()).update(ids - {m.id})
        out: list[UsableMemory] = []
        for memory in hits.exposed:
            read = self._fabric.use(
                memory.id,
                self._agent_id,
                risk=RiskLevel.LOW,
                include_contested=include_contested,
                audit=False,
                tenant_id=self._tenant_id,
            )
            if read.usable:
                usable = self._wrap(read)
                from dataclasses import replace

                if memory.id in disputed:
                    usable = replace(usable, warnings=usable.warnings + (
                        "disputed: gives a different value for the same claim as "
                        + ", ".join(sorted(disputed[memory.id])),))
                from . import validation

                judged = validation.assess(self._fabric, memory.id)
                if judged.suspicious:
                    usable = replace(usable, warnings=usable.warnings + (
                        "implausible: " + "; ".join(
                            f"{k} ({v})" for k, v in judged.signals.items()
                            if k in validation.SUSPICIOUS),))
                out.append(usable)
        return out

    def fetch(
        self, memory_id: str, risk: RiskLevel = RiskLevel.LOW
    ) -> UsableMemory:
        """One memory, by id, enforced. Raises rather than returning None.

        There is no `get()` here on purpose. The engine's `get()` returns a
        withdrawn memory to an operator tool, and an adapter holding that method
        is one autocomplete away from serving retracted knowledge to a model.
        """
        read: EnforcedRead = self._fabric.use(
            memory_id, self._agent_id, risk=risk, tenant_id=self._tenant_id
        )
        if not read.usable:
            raise NotUsable(read.decision)
        return self._wrap(read)

    def verify(
        self, usable: UsableMemory, risk: RiskLevel = RiskLevel.HIGH
    ) -> AccessDecision:
        """Re-check immediately before a consequential action.

        Defaults to HIGH because the only reason to call this is that something
        consequential is about to happen. Returns the decision rather than
        raising, because the caller usually wants to degrade rather than crash.
        """
        return self._fabric.verify_before_action(usable.token, self._agent_id, risk=risk)

    def require(
        self, usable: UsableMemory, risk: RiskLevel = RiskLevel.HIGH
    ) -> AccessDecision:
        """`verify`, but raising. For a path that must not proceed."""
        decision = self.verify(usable, risk=risk)
        if not decision.usable:
            raise NotUsable(decision)
        return decision

    # --- writing ---------------------------------------------------------

    def remember(
        self,
        content: str,
        type: str | MemoryType = MemoryType.SEMANTIC,
        context: Mapping[str, Any] | None = None,
        source_episodes: Sequence[str] = (),
        episode_id: str | None = None,
    ) -> str:
        """Write through the governed path, as this agent.

        Scope is not a parameter. A new memory is private; promoting it is the
        firewall's decision and needs contrastive evidence, so letting an
        adapter pass `scope="federated"` would hand it the one thing the
        governance layer exists to withhold.
        """
        return self._fabric.remember(
            agent_id=self._agent_id,
            content=content,
            type=type,
            context=context,
            source_episodes=source_episodes,
            episode_id=episode_id,
            scope=Scope.PRIVATE,
            tenant_id=self._tenant_id,
        )

    def episode(self, task_id: str, context: Mapping[str, Any] | None = None):
        """A scoped session. Writes inside it are attributed to this agent and
        that episode, and an outcome recorded through it still requires a
        third-party verifier."""
        return self._fabric.session(self._agent_id, task_id, context or {})

    def record_outcome(self, episode_id: str, outcome: float, verifier_id: str) -> None:
        """Record a verified outcome.

        `verifier_id` is required and may not equal this agent: an agent that
        scores its own episodes can manufacture value for any memory it likes.
        The engine enforces it; the SDK does not offer a convenience that would
        tempt a caller to pass their own id.
        """
        if verifier_id == self._agent_id:
            raise SdkError(
                "an agent cannot verify its own outcome; supply a third-party "
                "verifier_id (see AGENTS.md: outcomes are never self-reported)"
            )
        self._fabric.record_outcome(episode_id, outcome=outcome, verifier_id=verifier_id)

    # --- plumbing --------------------------------------------------------

    def _wrap(self, read: EnforcedRead) -> UsableMemory:
        memory: Memory = read.memory
        if read.token is None:
            # A usable read always carries one. Refusing here keeps a memory
            # from reaching an agent without the token that `verify` needs.
            raise RuntimeError(f"enforced read of {memory.id} carried no token")
        return UsableMemory(
            memory_id=memory.id,
            version=memory.version,
            content=memory.content,
            type=memory.type.value,
            token=read.token,
            warnings=tuple(read.warnings),
        )


class OperatorClient:
    """Inspection and integrity operations. Never hands content to an agent.

    Allowed to see a withdrawn memory, because deciding whether a withdrawal was
    justified requires reading the thing that was withdrawn. That is exactly why
    it is a separate object from `AgentClient`.
    """

    def __init__(self, fabric: Any, actor: str) -> None:
        self._fabric = fabric
        self._actor = actor

    @property
    def store_id(self) -> str:
        return self._fabric.store_id

    # --- inspection ------------------------------------------------------

    def inspect(self, memory_id: str) -> Memory:
        """The memory whatever its state. Inspection, not an agent read."""
        return self._fabric.get(memory_id)

    def explain(self, memory_id: str):
        return self._fabric.explain(memory_id)

    def lineage(self, memory_id: str):
        return self._fabric.lineage(memory_id)

    def audit_trail(self, memory_id: str):
        return self._fabric.audit_trail(memory_id)

    def support(self, memory_id: str):
        """Why this conclusion does or does not still stand."""
        return self._fabric.justifications.recompute(memory_id)

    def attention(self):
        """The triage list: what needs a human, worst first."""
        from .observability import report

        return report.attention(self._fabric)

    def overview(self):
        from .observability import report

        return report.overview(self._fabric)

    def integrity_snapshot(self) -> dict[str, Any]:
        return self._fabric.integrity_snapshot()

    # --- propagation state (invariant 9) ---------------------------------

    def propagation(self) -> list[dict[str, Any]]:
        """Every retraction still in flight, with its state per recipient.

        This is what invariant 9 asks to be *visible*: offline, pending,
        retrying and failed are all explicit, and an unreachable recipient
        appears as itself rather than as healthy.
        """
        return [
            {
                "retraction_id": row.retraction_id,
                "recipient": row.recipient,
                "state": row.state.value,
                "attempts": row.attempts,
                "last_error": row.last_error,
                "origin_memory_id": row.retraction.origin_memory_id,
                "origin_memory_version": row.retraction.origin_memory_version,
            }
            for row in self._fabric.outbox.pending()
        ]

    def acknowledgements(self, retraction_id: str) -> dict[str, Acknowledgement]:
        return self._fabric.outbox.acknowledgements(retraction_id)

    # --- integrity operations --------------------------------------------

    def retract(
        self,
        memory_id: str,
        reason: str,
        recipients: Sequence[str] = (),
        basis: str | None = None,
    ) -> Retraction:
        """Quarantine locally and durably owe the retraction to each recipient.

        `basis` is surfaced here rather than defaulted away, because an omitted
        basis is recorded as `unstated` and the attention list flags it — the
        operator should see that choice at the point of making it.
        """
        return self._fabric.request_retraction(
            memory_id, reason=reason, recipients=list(recipients),
            actor=self._actor, basis=basis,
        )

    def release(self, memory_id: str, reason: str = "reviewed and released") -> Memory:
        """Undo a withdrawal. Returns the memory to `candidate`, not `active`:
        a reviewed retraction still leaves something nobody has re-tested."""
        return self._fabric.release(memory_id, actor=self._actor, reason=reason)

    def validate(self, memory_id: str, reason: str = "validated") -> Memory:
        return self._fabric.validate(memory_id, actor=self._actor, reason=reason)

    def share(self, memory_id: str, scope: str = "team",
              granted_capabilities: Sequence[str] = ()) -> Any:
        """Widen who may read a memory, through the firewall.

        An agent's own writes are private to it. `team` makes one readable by
        every agent in its tenant; `federated` also lets it leave the store.
        The decision and its reasons are logged either way, and a refusal
        leaves the scope unchanged.
        """
        return self._fabric.share(memory_id, scope, actor=self._actor,
                                  granted_capabilities=granted_capabilities)

    def erase_content(self, memory_id: str, reason: str) -> bool:
        """Crypto-erasure. Irreversible, and the audit trail survives it."""
        return self._fabric.erase_content(memory_id, reason=reason, actor=self._actor)

    def resolve(self, *args: Any, **kwargs: Any):
        return self._fabric.resolve(*args, **kwargs)


def agent(
    fabric: Any, agent_id: str, tenant_id: str = DEFAULT_TENANT
) -> AgentClient:
    """A client bound to an agent and tenant the caller *asserts*.

    Right for a single-tenant store and for a process that has already
    authenticated its callers some other way. Where the binding should be
    checked, use `agent_for`.
    """
    return AgentClient(fabric, agent_id, tenant_id)


def agent_for(fabric: Any, credential: "Credential") -> AgentClient:
    """A client bound to a **verified** principal.

    Raises `IdentityError` rather than returning a client scoped to nothing: an
    adapter whose credential does not verify has not asked a question that has
    an answer, and an empty client would read as "this tenant knows nothing".
    """
    principal = fabric.principals.verify(credential, fabric.now())
    return AgentClient(fabric, principal.agent_id, principal.tenant_id)


def operator(fabric: Any, actor: str) -> OperatorClient:
    return OperatorClient(fabric, actor)


def public_error(exc: BaseException) -> str:
    """What a remote caller may be told about a refused request.

    Expected refusals (a policy violation, an unknown id, a bad credential, a
    malformed argument) are answers and keep their message. Anything else is a
    fault, and its text can carry internals (a path, an SQL fragment, a value
    from another tenant), so the caller gets a fixed sentence. The operator
    gets the exception, logged by the server that caught it.
    """
    from .fabric import FabricError
    from .identity import IdentityError

    if isinstance(exc, (FabricError, IdentityError, ValueError)):
        return f"{type(exc).__name__}: {exc}"
    return "internal error; the request was refused"
