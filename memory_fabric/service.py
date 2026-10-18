"""The trust boundary: a host service that owns the fabric.

`MemoryFabric` is a library primitive and it trusts its caller completely — it
has to, because the check and the bypass would be on the same side of the
boundary. `identity.py` says so and `TenantView` makes the tenant boundary
unforgettable, but a caller still holds the fabric and can act as anyone.

This module is where that stops being true for application code. `MemoryService`
owns the fabric, does not expose it, and hands out nothing except handles
derived from a **verified** credential. Application code that only ever sees a
`MemoryService` cannot address another tenant, cannot act as another agent, and
cannot reach the unenforced reads.

## What this is and is not

It is an **API boundary**, not a sandbox. Python has no private attributes and
`service._fabric` is one underscore away; nothing here stops code that is
determined to go around it. What it does is make the safe path the only
*obvious* path, and make the unsafe one visibly deliberate — which is the
difference between a mistake and a decision, and the only thing an in-process
boundary can honestly offer.

For a boundary that holds against the code on the other side of it, the service
runs in its own process and the application talks to it over a socket. The
design is arranged so that is a deployment change rather than a rewrite: every
operation already takes a credential and returns data.

## Re-verification per call, which is the part that matters

`fabric.as_principal(credential)` verifies once and returns a view that keeps
working. That is correct for a short-lived request and wrong for a long-lived
session, because a credential revoked at 10:00 would still be acting at 11:00
through a view minted at 09:00 — revocation that does not revoke.

So a `Session` here holds the *credential*, not a verified principal, and
re-verifies on every operation. The cost is an HMAC and a set lookup per call,
which is nothing next to the SQLite write it precedes; the benefit is that
revocation, expiry and a role change all take effect at the next operation
rather than at the next restart.
"""

from __future__ import annotations

__stability__ = "stable"

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

from .enforcement import AccessDecision, RiskLevel
from .fabric import MemoryFabric, TenantView
from .identity import (
    ROLE_AGENT,
    ROLE_OPERATOR,
    Credential,
    IdentityError,
    Principal,
    PrincipalRegistry,
)


@dataclass(frozen=True)
class Session:
    """A credential plus the service it was issued by. Re-verified per call.

    Deliberately holds the credential rather than a `Principal`: a verified
    principal is a snapshot, and acting on a snapshot is how a revoked
    credential keeps working. Every method below re-establishes who this is
    before doing anything.
    """

    service: "MemoryService"
    credential: Credential

    # --- identity --------------------------------------------------------

    def principal(self) -> Principal:
        """Re-verify now and return who this is.

        Raises `IdentityError` if the credential has expired, been revoked, or
        had its roles narrowed since it was issued.
        """
        return self.service._verify(self.credential)

    @property
    def agent_id(self) -> str:
        return self.credential.agent_id

    @property
    def tenant_id(self) -> str:
        return self.credential.tenant_id

    def _view(self) -> TenantView:
        return TenantView(self.service._fabric, self.principal(), verified=True)

    # --- agent operations ------------------------------------------------

    def remember(self, content: str, collection: str | None = None, **kwargs: Any) -> str:
        """Write as this agent; with `collection`, also add it there (needs `write`)."""
        if collection is not None:
            principal = self.principal()
            held = self.service._fabric.state.collections.get((principal.tenant_id, collection))
            if held is None or "write" not in held.grants.get(principal.agent_id, ()):
                raise IdentityError(f"{principal.agent_id} may not write to {collection}")
            memory_id = self._remember(content, **kwargs)
            self.service._fabric.collection_add(collection, memory_id, actor=principal.agent_id)
            return memory_id
        return self._remember(content, **kwargs)

    def _remember(self, content: str, **kwargs: Any) -> str:
        return self._view().remember(content, **kwargs)

    def derive(self, content: str, parents: Sequence[str], **kwargs: Any) -> str:
        return self._view().derive(content, parents, **kwargs)

    def retrieve(self, query: str, **kwargs: Any):
        return self._view().retrieve(query, **kwargs)

    def use(self, memory_id: str, **kwargs: Any):
        return self._view().use(memory_id, **kwargs)

    def verify_before_action(
        self, token: Any, risk: RiskLevel = RiskLevel.HIGH
    ) -> AccessDecision:
        return self._view().verify_before_action(token, risk=risk)

    def certify(self, claim_id: str, evidence: Sequence[Any], **kwargs: Any):
        return self._view().certify(claim_id, evidence, **kwargs)

    def verify_certificate(self, certificate: Any, **kwargs: Any):
        """Re-verifies the credential, then every piece of evidence: a
        credential revoked since the certificate was issued stops here."""
        return self._view().verify_certificate(certificate, **kwargs)

    def memory_ids(self) -> list[str]:
        return self._view().memory_ids()

    def record_outcome(self, episode_id: str, outcome: float, verifier_id: str) -> None:
        """Record a verified outcome.

        The verifier may not be this agent — the engine enforces it, and the
        service does not offer a convenience that would tempt a caller to pass
        their own id.
        """
        self.principal()
        self.service._fabric.record_outcome(
            episode_id, outcome=outcome, verifier_id=verifier_id
        )

    def start_episode(self, task_id: str, context: Mapping[str, Any] | None = None):
        principal = self.principal()
        return self.service._fabric.start_episode(
            principal.agent_id, task_id=task_id, context=dict(context or {})
        )

    # --- operator operations ---------------------------------------------
    #
    # Separate because they are a different privilege, not a different object:
    # an operator needs to read a withdrawn memory in order to judge whether
    # the withdrawal was justified, which is exactly what an agent must not do.

    def quarantine(self, memory_id: str, reason: str, basis: str | None = None):
        principal = self._require_operator_or("retract", memory_id)
        self.service._require_tenant(memory_id, principal)
        return self.service._fabric.quarantine(
            memory_id, reason=reason, actor=principal.agent_id, basis=basis
        )

    def release(self, memory_id: str, reason: str = "released"):
        principal = self._require_operator()
        self.service._require_tenant(memory_id, principal)
        return self.service._fabric.release(
            memory_id, actor=principal.agent_id, reason=reason
        )

    def validate(self, memory_id: str, reason: str = "validated"):
        principal = self._require_operator_or("approve", memory_id)
        self.service._require_tenant(memory_id, principal)
        return self.service._fabric.validate(
            memory_id, actor=principal.agent_id, reason=reason
        )

    def inspect(self, memory_id: str):
        """The unenforced read, and the only way to reach it through a session.

        Returns a withdrawn memory, which is the point: judging a withdrawal
        means reading what was withdrawn. Restricted to the operator role and
        still scoped to the session's tenant, so "may see withdrawn memories"
        never becomes "may see every tenant's memories".
        """
        principal = self._require_operator()
        self.service._require_tenant(memory_id, principal)
        return self.service._fabric.get(memory_id)

    def explain(self, memory_id: str):
        principal = self._require_operator()
        self.service._require_tenant(memory_id, principal)
        return self.service._fabric.explain(memory_id)

    def request_retraction(
        self,
        memory_id: str,
        reason: str,
        recipients: Sequence[str],
        basis: str | None = None,
    ):
        principal = self._require_operator_or("retract", memory_id)
        self.service._require_tenant(memory_id, principal)
        return self.service._fabric.request_retraction(
            memory_id,
            reason=reason,
            recipients=list(recipients),
            actor=principal.agent_id,
            basis=basis,
        )

    def erase_content(self, memory_id: str, reason: str) -> bool:
        principal = self._require_operator()
        self.service._require_tenant(memory_id, principal)
        return self.service._fabric.erase_content(
            memory_id, reason=reason, actor=principal.agent_id
        )

    def _require_operator_or(self, permission: str, memory_id: str) -> Principal:
        """The operator role, or `permission` on a collection holding the memory.

        Checked on the verified principal, so a collection grant is as real as
        a role: it is what lets a team lead approve their team's collection
        without being an operator of the whole store.
        """
        from .model import granted

        principal = self.service._verify(self.credential)
        if principal.may(ROLE_OPERATOR):
            return principal
        memory = self.service._fabric.state.memories.get(memory_id)
        if memory is not None and granted(self.service._fabric.state, principal.tenant_id,
                                          principal.agent_id, memory_id, permission):
            return principal
        principal.require(ROLE_OPERATOR)  # raises, naming the role it lacks
        return principal

    def _require_operator(self) -> Principal:
        principal = self.principal()
        principal.require(ROLE_OPERATOR)
        return principal


class MemoryService:
    """Owns a fabric and exposes it only through verified sessions."""

    def __init__(
        self,
        fabric: MemoryFabric | None = None,
        durable_revocations: bool = True,
        **fabric_kwargs: Any,
    ) -> None:
        self._fabric = fabric if fabric is not None else MemoryFabric(**fabric_kwargs)
        self._principals = self._fabric.principals
        if durable_revocations:
            # On by default *here* and off in a bare `PrincipalRegistry`,
            # because a service is the thing that restarts. An in-memory list
            # un-revokes every leaked credential still inside its lifetime at
            # exactly the moment revocation is for.
            #
            # Shares the event log's connection, so a revocation commits with
            # the same transaction and busy timeout as everything else.
            from .identity import SqliteRevocations

            self._principals.revocations = SqliteRevocations(
                self._fabric.log._conn, self._fabric.now
            )

    # --- administration --------------------------------------------------
    #
    # Not reachable through a Session on purpose. Registering an agent and
    # minting credentials are the operations that *create* privilege, so they
    # belong to whatever bootstraps the service — a deployment script, an admin
    # CLI — and not to anything holding a credential. A session that could
    # issue credentials could issue itself a better one.

    @property
    def principals(self) -> PrincipalRegistry:
        return self._principals

    @property
    def store_id(self) -> str:
        return self._fabric.store_id

    def register_agent(
        self,
        agent_id: str,
        key: bytes,
        tenant_id: str,
        roles: Iterable[str] = (ROLE_AGENT,),
    ) -> Principal:
        with self._fabric.lock:
            return self._principals.register(
                agent_id, key=key, tenant_id=tenant_id, roles=roles
            )

    def issue(self, agent_id: str, ttl_seconds: int = 3600, **kwargs: Any) -> Credential:
        with self._fabric.lock:
            return self._principals.issue(
                agent_id, now=self._fabric.now(), ttl_seconds=ttl_seconds, **kwargs
            )

    @property
    def revocations_are_durable(self) -> bool:
        """Whether a revocation survives a restart.

        Readable rather than inferred, because the answer changes what short
        credential lifetimes are protecting against.
        """
        return bool(getattr(self._principals.revocations, "durable", False))

    def revoke(self, credential: Credential | str) -> bool:
        with self._fabric.lock:
            return self._principals.revoke(credential)

    def revoke_agent(self, agent_id: str) -> None:
        with self._fabric.lock:
            self._principals.revoke_agent(agent_id)

    # --- the only way in ------------------------------------------------

    def session(self, credential: Credential) -> Session:
        """A handle bound to this credential.

        Verified now so a bad credential fails at the door rather than at the
        first operation, and re-verified on every call so revocation is not
        advisory.
        """
        self._verify(credential)
        return Session(service=self, credential=credential)

    def close(self) -> None:
        self._fabric.close()

    def __enter__(self) -> "MemoryService":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    # --- internals -------------------------------------------------------

    def precheck(self, credential: Credential) -> str:
        """Signature and expiry only, without the store. See `authenticate`.

        For a server that must refuse before queuing on the store. It is not
        authorisation: `session` still verifies everything, revocation
        included, before anything is served.
        """
        return self._principals.authenticate(credential, self._fabric.now())

    def _verify(self, credential: Credential) -> Principal:
        # Revocations are rows on the store's connection, so verifying one
        # is a read that must not interleave with another thread's statement.
        with self._fabric.lock:
            return self._principals.verify(credential, self._fabric.now())

    def _require_tenant(self, memory_id: str, principal: Principal) -> None:
        """An operator's reach stops at their own tenant.

        Checked here rather than left to `Enforcer`, because these are the
        operator paths that *deliberately* bypass enforcement — `inspect`
        returns a withdrawn memory, `erase_content` destroys a key. Without
        this, "may see withdrawn memories" would quietly mean "may see and
        erase every tenant's memories".

        Reports a plain not-found rather than a tenant mismatch, for the reason
        `Enforcer.check` does: naming the owning tenant turns the check into an
        enumeration oracle.
        """
        memory = self._fabric.state.memories.get(memory_id)
        if memory is None or memory.tenant_id != principal.tenant_id:
            raise IdentityError(f"no memory {memory_id!r} in this tenant")
