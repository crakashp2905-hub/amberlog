"""Tenant and agent identity.

Until now `agent_id` and `actor` were caller-supplied strings, recorded
faithfully and believed completely. That was honest about what it was —
SECURITY.md has said so since Phase 0 — but it makes two things impossible:
telling one customer's knowledge from another's inside one store, and telling a
compromised adapter from a legitimate one.

Three ideas, and the distinction between the first two is the whole design:

**A store cannot enforce identity on a caller holding the store.** Anything
with a `MemoryFabric` in hand can write as anyone, and no amount of checking
inside the object changes that — the check and the bypass are on the same side
of the boundary. So identity is enforced at a *handle*: `fabric.as_principal`
verifies a credential and returns a view that can only act as that principal,
and the raw fabric is the operator path. This mirrors the existing
`AgentClient` / `OperatorClient` split rather than inventing a second idea of
privilege, and it is the same reasoning `PeerRegistry` already applies to
stores: the registry is the authorisation boundary, not a lookup table.

**A tenant is an authorisation boundary, not a physical one.** Memories carry
a `tenant_id`; the exposure path and the enforcement layer refuse to cross it.
What that buys is that a bug in a ranking policy, an index query or a
federation import cannot surface one tenant's knowledge to another. What it
does *not* buy is isolation against a caller with the file: one SQLite database
holding several tenants is one blast radius, and the stronger arrangement
remains one store per tenant. DEPLOYMENT.md says which to pick when.

**A credential is bearer, bounded and verifiable.** HMAC-SHA256 over a canonical
JSON body, with an expiry, keyed per agent. Not asymmetric: this is the same
trust model as `transport.Peer`, where the two sides already share a key, and
introducing a second and incompatible one would be a cost with no buyer yet.
The limitation is recorded in SECURITY.md rather than hidden: a leaked
credential is usable until it expires, and there is no revocation list.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Protocol

from .ids import new_ulid

TENANT_PREFIX = "tn_"

DEFAULT_TENANT = "tn_default"
"""The tenant a memory belongs to when nothing said otherwise.

Every store written before tenancy existed replays into this one, so an
existing single-tenant deployment keeps working with no migration and no change
in behaviour. It is a real tenant id rather than `None` on purpose: a nullable
boundary is one every comparison has to remember to handle, and the first place
that forgot would be a cross-tenant read.
"""

ROLE_AGENT = "agent"
ROLE_OPERATOR = "operator"
ROLE_AUDITOR = "auditor"

DEFAULT_TTL_SECONDS = 3600


def new_tenant_id() -> str:
    return TENANT_PREFIX + new_ulid()


class IdentityError(Exception):
    """A credential that cannot be believed, or a principal that is not known.

    Deliberately not a subclass of `PolicyViolation`: a policy refusal is a
    decision the system made about a legitimate request, and an identity
    failure is a request that was never established as legitimate. Collapsing
    them would make "we refused this" and "we do not know who this is" the same
    line in an audit.
    """


@dataclass(frozen=True)
class Principal:
    """Who is acting, and on whose data."""

    agent_id: str
    tenant_id: str = DEFAULT_TENANT
    roles: frozenset[str] = frozenset({ROLE_AGENT})

    def may(self, role: str) -> bool:
        return role in self.roles

    def require(self, role: str) -> None:
        if not self.may(role):
            raise IdentityError(
                f"{self.agent_id} has roles {sorted(self.roles)}; {role} is required"
            )

    def to_json(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "tenant_id": self.tenant_id,
            "roles": sorted(self.roles),
        }


@dataclass(frozen=True)
class Credential:
    """A signed, expiring assertion that a caller is a principal.

    Bearer: holding it is sufficient. That is a real limitation and it is
    stated in SECURITY.md rather than mitigated here with something that would
    look stronger than it is.
    """

    agent_id: str
    tenant_id: str
    roles: tuple[str, ...]
    issued_at: int
    expires_at: int
    key_id: str = "k1"
    credential_id: str = ""
    """A unique id for *this* credential, so one can be revoked without
    rotating the agent's key and invalidating every other credential it holds.
    Signed, so it cannot be swapped for an unrevoked id."""
    signature: str = ""

    def body(self) -> dict[str, Any]:
        """What is signed. Canonical, so two encoders agree on the bytes."""
        return {
            "agent_id": self.agent_id,
            "tenant_id": self.tenant_id,
            "roles": sorted(self.roles),
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
            "key_id": self.key_id,
            "credential_id": self.credential_id,
        }

    def signed_bytes(self) -> bytes:
        return json.dumps(self.body(), sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )

    def sign(self, key: bytes) -> "Credential":
        from dataclasses import replace

        mac = hmac.new(key, self.signed_bytes(), hashlib.sha256).hexdigest()
        return replace(self, signature=mac)

    def verify_signature(self, key: bytes) -> bool:
        if not self.signature:
            return False
        expected = hmac.new(key, self.signed_bytes(), hashlib.sha256).hexdigest()
        # Constant-time: a timing oracle on a MAC comparison is the classic way
        # to turn "cannot forge" into "can forge, slowly".
        return hmac.compare_digest(expected, self.signature)

    def is_expired(self, now: int) -> bool:
        return now >= self.expires_at

    def to_json(self) -> dict[str, Any]:
        return {**self.body(), "signature": self.signature}

    @staticmethod
    def from_json(data: Mapping[str, Any]) -> "Credential":
        try:
            return Credential(
                agent_id=str(data["agent_id"]),
                tenant_id=str(data["tenant_id"]),
                roles=tuple(str(r) for r in data["roles"]),
                issued_at=int(data["issued_at"]),
                expires_at=int(data["expires_at"]),
                key_id=str(data.get("key_id", "k1")),
                credential_id=str(data.get("credential_id", "")),
                signature=str(data.get("signature", "")),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise IdentityError(f"malformed credential: {exc}") from None


@dataclass
class _Registration:
    tenant_id: str
    roles: frozenset[str]
    key: bytes
    key_id: str


class RevocationStore(Protocol):
    """Where revocations live.

    A seam rather than a hard-coded table, because the honest answer to "does
    revocation survive a restart?" is a deployment choice: a one-process tool
    wants nothing on disk, and a service wants the list where its other session
    state already lives.
    """

    durable: bool

    def revoke_credential(self, credential_id: str) -> bool: ...

    def revoke_agent(self, agent_id: str) -> None: ...

    def reinstate_agent(self, agent_id: str) -> None: ...

    def is_revoked(self, agent_id: str, credential_id: str) -> bool: ...


class InMemoryRevocations:
    """The default. Fast, shared with nothing, gone on restart.

    Right for a one-process tool and wrong for a service, which is why
    `SqliteRevocations` exists and why `durable` is a readable flag rather than
    something an operator has to infer from the class name.
    """

    durable = False

    def __init__(self) -> None:
        self._credentials: set[str] = set()
        self._agents: set[str] = set()

    def revoke_credential(self, credential_id: str) -> bool:
        already = credential_id in self._credentials
        self._credentials.add(credential_id)
        return not already

    def revoke_agent(self, agent_id: str) -> None:
        self._agents.add(agent_id)

    def reinstate_agent(self, agent_id: str) -> None:
        self._agents.discard(agent_id)

    def is_revoked(self, agent_id: str, credential_id: str) -> bool:
        return agent_id in self._agents or (
            bool(credential_id) and credential_id in self._credentials
        )


class SqliteRevocations:
    """Revocations on disk, shared by every process on that database.

    Takes a connection rather than a path so it can share the event log's —
    and with it the transaction and the busy timeout — when a caller wants a
    revocation to commit alongside whatever else it is doing.

    Deliberately **not** in the event log. A revocation is operational state
    that can be reinstated, and the log is append-only history: a reinstatement
    would have to be a second event contradicting the first, and every reader
    would fold both to answer a yes/no question a row answers directly.
    """

    durable = True

    _SCHEMA = """
    CREATE TABLE IF NOT EXISTS revoked_credentials (
        credential_id TEXT PRIMARY KEY,
        revoked_ms    INTEGER NOT NULL
    );
    CREATE TABLE IF NOT EXISTS revoked_agents (
        agent_id   TEXT PRIMARY KEY,
        revoked_ms INTEGER NOT NULL
    );
    """

    def __init__(self, conn: Any, now_ms: Any = None) -> None:
        self._conn = conn
        self._now_ms = now_ms or (lambda: 0)
        # Outside any transaction: `executescript` issues its own COMMIT.
        self._conn.executescript(self._SCHEMA)

    def revoke_credential(self, credential_id: str) -> bool:
        cursor = self._conn.execute(
            "INSERT INTO revoked_credentials (credential_id, revoked_ms) "
            "VALUES (?, ?) ON CONFLICT(credential_id) DO NOTHING",
            (credential_id, self._now_ms()),
        )
        return cursor.rowcount > 0

    def revoke_agent(self, agent_id: str) -> None:
        self._conn.execute(
            "INSERT INTO revoked_agents (agent_id, revoked_ms) VALUES (?, ?) "
            "ON CONFLICT(agent_id) DO NOTHING",
            (agent_id, self._now_ms()),
        )

    def reinstate_agent(self, agent_id: str) -> None:
        self._conn.execute(
            "DELETE FROM revoked_agents WHERE agent_id = ?", (agent_id,)
        )

    def is_revoked(self, agent_id: str, credential_id: str) -> bool:
        if self._conn.execute(
            "SELECT 1 FROM revoked_agents WHERE agent_id = ?", (agent_id,)
        ).fetchone():
            return True
        if not credential_id:
            return False
        return bool(
            self._conn.execute(
                "SELECT 1 FROM revoked_credentials WHERE credential_id = ?",
                (credential_id,),
            ).fetchone()
        )


class PrincipalRegistry:
    """Who this store will act as, and the key each agent's credentials use.

    Explicit rather than discovered, for the reason `PeerRegistry` is: an
    unknown agent is not authorised, and a store cannot be talked into acting
    for a principal it was never configured to know.
    """

    def __init__(self, store: "RevocationStore | None" = None) -> None:
        self._agents: dict[str, _Registration] = {}
        self._tenants: set[str] = {DEFAULT_TENANT}
        # Durable when a store is supplied, in memory otherwise. The default
        # stayed in memory for one release and SECURITY.md said so; what that
        # meant in practice is that a restart un-revoked every leaked
        # credential still inside its lifetime, which is the one moment
        # revocation exists for.
        self.revocations: RevocationStore = store or InMemoryRevocations()

    # --- configuration ---------------------------------------------------

    def add_tenant(self, tenant_id: str) -> str:
        self._tenants.add(tenant_id)
        return tenant_id

    @property
    def tenants(self) -> frozenset[str]:
        return frozenset(self._tenants)

    def register(
        self,
        agent_id: str,
        key: bytes,
        tenant_id: str = DEFAULT_TENANT,
        roles: Iterable[str] = (ROLE_AGENT,),
        key_id: str = "k1",
    ) -> Principal:
        if not key:
            raise IdentityError(f"{agent_id}: a registration needs a key")
        self._tenants.add(tenant_id)
        self._agents[agent_id] = _Registration(
            tenant_id=tenant_id,
            roles=frozenset(roles),
            key=key,
            key_id=key_id,
        )
        return Principal(agent_id=agent_id, tenant_id=tenant_id, roles=frozenset(roles))

    def __contains__(self, agent_id: object) -> bool:
        return agent_id in self._agents

    def __len__(self) -> int:
        return len(self._agents)

    def principal(self, agent_id: str) -> Principal:
        registration = self._agents.get(agent_id)
        if registration is None:
            raise IdentityError(f"unknown agent: {agent_id}")
        return Principal(
            agent_id=agent_id,
            tenant_id=registration.tenant_id,
            roles=registration.roles,
        )

    # --- credentials -----------------------------------------------------

    def issue(
        self,
        agent_id: str,
        now: int,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
        roles: Iterable[str] | None = None,
    ) -> Credential:
        """Mint a credential for a registered agent.

        `roles` may only *narrow* the registration. Widening here would make
        the issuer the authority rather than the registry, and then a caller
        that could ask for a credential could ask for an operator's.
        """
        registration = self._agents.get(agent_id)
        if registration is None:
            raise IdentityError(f"unknown agent: {agent_id}")
        if ttl_seconds <= 0:
            raise IdentityError("a credential needs a positive lifetime")
        granted = frozenset(roles) if roles is not None else registration.roles
        excess = granted - registration.roles
        if excess:
            raise IdentityError(
                f"{agent_id} is not registered for {sorted(excess)}; "
                "a credential can only narrow a registration"
            )
        credential = Credential(
            agent_id=agent_id,
            tenant_id=registration.tenant_id,
            roles=tuple(sorted(granted)),
            issued_at=now,
            expires_at=now + ttl_seconds,
            key_id=registration.key_id,
            credential_id="cr_" + new_ulid(),
        )
        return credential.sign(registration.key)

    # --- revocation ------------------------------------------------------

    def revoke(self, credential: "Credential | str") -> bool:
        """Revoke one credential by id, effective immediately.

        Needed because a credential is a bearer token with a lifetime: without
        this the only remedy for a leak was rotating the agent's key, which
        invalidates every *other* credential that agent holds and takes the
        whole agent offline to deal with one leaked token.

        Durability depends on the `RevocationStore` behind the registry.
        `SqliteRevocations` survives a restart and is shared by every process
        on that database; `InMemoryRevocations` is the default and does not.
        Short credential lifetimes remain the primary control either way —
        revocation is the fast remedy inside a lifetime, not a substitute for
        bounding one.
        """
        credential_id = (
            credential if isinstance(credential, str) else credential.credential_id
        )
        if not credential_id:
            raise IdentityError(
                "this credential has no id and cannot be revoked individually; "
                "rotate the agent's key instead"
            )
        return self.revocations.revoke_credential(credential_id)

    def revoke_agent(self, agent_id: str) -> None:
        """Revoke every credential this agent holds, present and future.

        The blunt instrument, for a compromised agent rather than a leaked
        token. Distinct from removing the registration: the agent stays known,
        so its past actions remain attributable and a later `register` can
        bring it back deliberately.
        """
        self.revocations.revoke_agent(agent_id)

    def reinstate_agent(self, agent_id: str) -> None:
        self.revocations.reinstate_agent(agent_id)

    def is_revoked(self, credential: "Credential") -> bool:
        return self.revocations.is_revoked(
            credential.agent_id, credential.credential_id
        )

    def verify(self, credential: Credential, now: int) -> Principal:
        """Establish a principal, or raise.

        The order matters and is the same reasoning as the retraction protocol's:
        resolve *who this claims to be* and whether the claim is authentic before
        looking at anything the claim says. An expiry check on an unverified body
        is a check on attacker-controlled data.
        """
        registration = self._agents.get(credential.agent_id)
        if registration is None:
            raise IdentityError(f"unknown agent: {credential.agent_id}")
        if credential.key_id != registration.key_id:
            raise IdentityError(
                f"{credential.agent_id}: credential names key {credential.key_id}, "
                f"registration uses {registration.key_id}"
            )
        if not credential.verify_signature(registration.key):
            raise IdentityError(f"{credential.agent_id}: signature does not verify")
        if credential.is_expired(now):
            raise IdentityError(
                f"{credential.agent_id}: credential expired at {credential.expires_at}"
            )
        # After the signature, so a revocation check never runs on an
        # unverified id — and before the tenant and role checks, because a
        # revoked credential should not be told *why else* it would have failed.
        if self.is_revoked(credential):
            raise IdentityError(
                f"{credential.agent_id}: credential has been revoked"
            )
        if credential.tenant_id != registration.tenant_id:
            # Authentic but wrong: a validly signed credential naming another
            # tenant means the registration moved after it was issued, and the
            # registration wins.
            raise IdentityError(
                f"{credential.agent_id}: credential claims tenant "
                f"{credential.tenant_id}, registration says {registration.tenant_id}"
            )
        granted = frozenset(credential.roles) & registration.roles
        if not granted:
            raise IdentityError(
                f"{credential.agent_id}: no role in the credential is still registered"
            )
        return Principal(
            agent_id=credential.agent_id,
            tenant_id=registration.tenant_id,
            roles=granted,
        )
