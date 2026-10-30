"""Sharing: the firewall decision on widening scope, and collections.

A service mixin of `Amberlog`, built on `FabricCore`. Methods moved here
verbatim from `fabric.py`.
"""

from __future__ import annotations

__stability__ = "stable"



from typing import TYPE_CHECKING, Any, Iterable

if TYPE_CHECKING:
    from ..fabric import Amberlog  # noqa: F401
    pass

from .. import events as ev
from ..governance.firewall import FirewallRequest, FirewallRuling

from ..identity import (
    DEFAULT_TENANT,
)
from ..model import (
    FirewallDecision,
    LifecycleState,
    Scope,
    SecurityClass,
    WithdrawalBasis,
)


from .core import FabricCore
from .common import PolicyViolation, _fresh


class SharingMixin(FabricCore):

    # --- sharing ---------------------------------------------------------

    @_fresh
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

    @_fresh
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
                        WithdrawalBasis.SENSITIVE_DATA.value,
                    )
                )
        self._emit(*emitted)
        return ruling

    # --- inspection ------------------------------------------------------

    # --- collections (schema 0.10.0) --------------------------------------

    def _collection_event(self, name: str, action: str, actor: str, tenant_id: str,
                          **fields: Any) -> None:
        if not name or not name.replace("-", "").replace("_", "").isalnum():
            raise PolicyViolation("a collection name is letters, digits, '-' and '_'")
        if not actor or actor == "operator":
            raise PolicyViolation("name who is changing this collection: it is audited")
        self._emit(ev.collection_changed(ts=self.now(), tenant_id=tenant_id, collection=name,
                                         action=action, actor=actor, **fields))

    @_fresh
    def collection_add(self, name: str, memory_id: str, actor: str) -> None:
        """Put a memory in a collection. Its readers can then read it, even if private.

        A restricted memory cannot join one: a collection is a way to widen
        who reads, and restricted memories stay private.
        """
        memory = self._require(memory_id)
        if memory.security_class is SecurityClass.RESTRICTED:
            raise PolicyViolation("a restricted memory stays private; it cannot join a collection")
        self._collection_event(name, "add", actor, memory.tenant_id, memory_id=memory_id)

    @_fresh
    def collection_remove(self, name: str, memory_id: str, actor: str) -> None:
        memory = self._require(memory_id)
        self._collection_event(name, "remove", actor, memory.tenant_id, memory_id=memory_id)

    @_fresh
    def collection_grant(self, name: str, agent_id: str, permissions: Iterable[str],
                         actor: str, tenant_id: str = DEFAULT_TENANT) -> None:
        """Attach an agent (`read`) or grant it more. See `model.PERMISSIONS`."""
        from ..model import PERMISSIONS

        perms = set(permissions)
        if not perms or not perms <= set(PERMISSIONS):
            raise PolicyViolation(f"permissions must be a non-empty subset of {PERMISSIONS}")
        self._collection_event(name, "grant", actor, tenant_id, agent_id=agent_id,
                               permissions=sorted(perms))

    @_fresh
    def collection_revoke(self, name: str, agent_id: str, actor: str,
                          permissions: Iterable[str] = (), tenant_id: str = DEFAULT_TENANT) -> None:
        """Detach an agent (no permissions named: all of them) or take some back."""
        self._collection_event(name, "revoke", actor, tenant_id, agent_id=agent_id,
                               permissions=sorted(set(permissions)))

    @_fresh
    def collections(self, tenant_id: str | None = None) -> dict[str, Any]:
        """Name -> members and grants, for one tenant or all (`tenant/name` keys)."""
        out = {}
        for (tenant, name), c in self.state.collections.items():
            if tenant_id is not None and tenant != tenant_id:
                continue
            key = name if tenant_id is not None else f"{tenant}/{name}"
            out[key] = {"members": sorted(c.members),
                        "grants": {a: sorted(p) for a, p in sorted(c.grants.items())}}
        return out
