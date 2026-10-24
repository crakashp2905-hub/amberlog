"""MemoryFabric: the public facade, per SPEC.md section 6.

Everything a caller does becomes an event first and state second. State is a
projection that can be thrown away and rebuilt, which is what makes the audit
trail trustworthy: there is no way to change a memory without leaving a record,
because the record *is* the change.
"""

from __future__ import annotations

__stability__ = "stable"


from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Sequence

if TYPE_CHECKING:
    pass


from .enforcement import (
    EnforcedRead,
    ExposureToken,
)
from .identity import (
    Credential,
    IdentityError,
    Principal,
)


from ._fabric.federation import FederationMixin
from ._fabric.sealing import SealingMixin
from ._fabric.retrieval import RetrievalMixin
from ._fabric.lifecycle import LifecycleMixin
from ._fabric.sharing import SharingMixin
from ._fabric.access import AccessMixin
from ._fabric.writes import WritesMixin
from ._fabric.core import FabricCore
from ._fabric.common import FabricError, NotFound, PolicyViolation, RetrievalResult, HealthReport, iso_timestamp, _screened_text, _fresh  # noqa: F401 - re-exported


class MemoryFabric(FederationMixin, SealingMixin, RetrievalMixin, LifecycleMixin, SharingMixin, AccessMixin, WritesMixin, FabricCore):
    """Single-process memory fabric with a governed write and share path."""

    def for_tenant(self, tenant_id: str, agent_id: str) -> "TenantView":
        """A handle that can only see and write one tenant's memories.

        The operator path: the caller asserts the tenant and nothing verifies
        the assertion, which is honest because a caller holding the fabric
        could act on any tenant anyway. What this buys is that code written
        against the view *cannot forget* to scope a read — the boundary is in
        the handle rather than in a keyword argument at every call site.

        `as_principal` is the same handle with the assertion checked.
        """
        return TenantView(
            self, Principal(agent_id=agent_id, tenant_id=tenant_id), verified=False
        )

    def __enter__(self) -> "MemoryFabric":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def as_principal(self, credential: Credential) -> "TenantView":
        """Verify a credential and return a handle bound to that principal.

        Raises `IdentityError` rather than returning an empty view: a caller
        whose credential does not verify has not asked a question that has an
        answer, and silently scoping them to nothing would look like "this
        tenant has no memories".
        """
        principal = self.principals.verify(credential, self.now())
        return TenantView(self, principal, verified=True)


# Re-exported for typing convenience at the bottom to avoid a circular import.

@dataclass
class TenantView:
    """One tenant's slice of a store, bound to one acting agent.

    Not a security perimeter against a caller holding the `MemoryFabric` — that
    perimeter does not exist inside a library and `identity.py` says so. What
    this is, is the shape that makes the boundary unforgettable: the methods
    here take no `tenant_id`, so there is no call site at which someone can
    omit it, and `agent_id` is supplied once rather than typed again at every
    write.

    `verified` records which door the handle came through. `as_principal`
    checked a signature; `for_tenant` took the caller's word. Keeping the two
    distinguishable matters because an audit question — "was this write made by
    an authenticated principal?" — has a different answer in each case, and a
    view that forgot could only answer it by guessing.
    """

    fabric: "MemoryFabric"
    principal: Principal
    verified: bool = False

    @property
    def tenant_id(self) -> str:
        return self.principal.tenant_id

    @property
    def agent_id(self) -> str:
        return self.principal.agent_id

    # --- writes ----------------------------------------------------------

    def remember(self, content: str, **kwargs: Any) -> str:
        kwargs.pop("tenant_id", None)
        kwargs.pop("agent_id", None)
        return self.fabric.remember(
            agent_id=self.agent_id, content=content, tenant_id=self.tenant_id, **kwargs
        )

    def derive(self, content: str, parents: Sequence[str], **kwargs: Any) -> str:
        """Derive within the tenant, refusing to inherit from outside it.

        Checked rather than assumed: `derive` copies its parents' context, and
        a conclusion drawn from another tenant's premise would carry that
        tenant's provenance into this one. The memory would be labelled with
        this tenant and justified by a memory nobody here may read.
        """
        for parent in parents:
            if self.fabric.tenant_of(parent) != self.tenant_id:
                if self.fabric.conceal_cross_tenant:
                    # Exactly what a missing id raises, so a derive cannot be
                    # used to learn that another tenant's id exists.
                    raise NotFound(f"no memory {parent!r}")
                raise IdentityError(
                    f"{parent} belongs to another tenant; a conclusion cannot "
                    "be justified by a premise this tenant may not read"
                )
        kwargs.pop("agent_id", None)
        kwargs.pop("tenant_id", None)
        return self.fabric.derive(
            agent_id=self.agent_id, content=content, parents=parents,
            tenant_id=self.tenant_id, **kwargs
        )

    # --- reads -----------------------------------------------------------

    def retrieve(self, query: str, **kwargs: Any) -> "RetrievalResult":
        kwargs.pop("tenant_id", None)
        kwargs.pop("agent_id", None)
        return self.fabric.retrieve(
            agent_id=self.agent_id, query=query, tenant_id=self.tenant_id, **kwargs
        )

    def use(self, memory_id: str, **kwargs: Any) -> "EnforcedRead":
        kwargs.pop("tenant_id", None)
        kwargs.pop("agent_id", None)
        return self.fabric.use(
            memory_id, agent_id=self.agent_id, tenant_id=self.tenant_id, **kwargs
        )

    def verify_before_action(self, token: "ExposureToken", **kwargs: Any):
        kwargs.pop("agent_id", None)
        return self.fabric.verify_before_action(token, self.agent_id, **kwargs)

    def certify(self, claim_id: str, evidence: Sequence[Any], **kwargs: Any):
        kwargs.pop("tenant_id", None)
        kwargs.pop("agent_id", None)
        return self.fabric.certify(claim_id, evidence, self.agent_id,
                                   tenant_id=self.tenant_id, **kwargs)

    def verify_certificate(self, certificate: Any, **kwargs: Any):
        kwargs.pop("tenant_id", None)
        kwargs.pop("agent_id", None)
        return self.fabric.verify_certificate(certificate, self.agent_id,
                                              tenant_id=self.tenant_id, **kwargs)

    def memory_ids(self) -> list[str]:
        """Every memory in this tenant, whatever its lifecycle state.

        Deliberately *not* filtered by lifecycle: this is the inventory, and an
        operator asking what a tenant holds needs the quarantined ones too.
        Reading one still goes through `use`.
        """
        return sorted(
            memory_id
            for memory_id, memory in self.fabric.state.memories.items()
            if memory.tenant_id == self.tenant_id
        )
