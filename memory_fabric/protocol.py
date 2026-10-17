"""The federation protocol: identities, retraction events, acknowledgements.

Specified in docs/PROTOCOL.md, decided in
research/decisions/2026-10-10-phase0-protocol-architecture.md, and schema'd in
docs/protocol/*.json. This module is the Python side of those documents and is
validated against them by tests/test_protocol_schemas.py.

Three things here are load-bearing and were wrong before Phase 1:

**A store identity is an opaque id, never a path.** The old origin record wrote
`source.log.path`, so two containers each holding `./store.db` were
indistinguishable, moving a database broke every provenance match silently, and
`:memory:` was the identity of *every* in-memory store.

**A retraction names an exact version.** The old matching logic compared memory
ids only, so a retraction of v1 would withdraw an import of v3.

**Lifecycle and propagation are separate state machines.** A memory can be
retracted at its origin while one recipient has enforced it and another is
offline. `PropagationResult.acted: bool` could not express that; eight states
can.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from dataclasses import dataclass, replace
from enum import Enum
from typing import Any, Mapping

from .ids import new_ulid

PROTOCOL_VERSION = 1

MAX_HOPS = 16
"""A safety net, not the loop defence — deduplication on the campaign
identity is what terminates cycles. This bounds a pathological topology
that keeps finding new stores, and a refusal at the limit is auditable."""

STORE_ID_RE = re.compile(r"^st_[0-9A-HJKMNP-TV-Z]{26}$")
RETRACTION_ID_RE = re.compile(r"^rt_[0-9A-HJKMNP-TV-Z]{26}$")
TENANT_ID_RE = re.compile(r"^tn_[0-9A-HJKMNP-TV-Z]{26}$")


def new_store_id() -> str:
    return f"st_{new_ulid()}"


def new_retraction_id() -> str:
    return f"rt_{new_ulid()}"


def new_tenant_id() -> str:
    return f"tn_{new_ulid()}"


def evidence_digest(text: str) -> str:
    """Hash the evidence; never ship it.

    A memory's content can contain exactly what the governance layer exists to
    keep out of secondary surfaces, so a retraction carries a digest and an
    optional reference the recipient may or may not be authorised to follow.
    """
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


class PropagationState(str, Enum):
    """One `(retraction, recipient)` pair. Not a memory's lifecycle."""

    REQUESTED = "requested"
    """Committed in the origin's log, atomically with the outbox intent."""

    QUEUED = "queued"
    DELIVERED = "delivered"

    PERSISTED = "persisted"
    """The recipient committed the event to its own log."""

    ENFORCED = "enforced"
    """The recipient's projections no longer expose the version. Separate from
    PERSISTED because committing an event and rebuilding the projections that
    act on it are separate acts, and a crash between them is exactly the window
    invariant 6 is about."""

    VERIFIED = "verified"
    """The origin independently confirmed enforcement. A recipient never
    self-certifies this."""

    REJECTED = "rejected"
    SUPERSEDED = "superseded"
    RETRYING = "retrying"
    FAILED = "failed"

    UNKNOWN = "unknown"
    """No information. An unreachable recipient is UNKNOWN, never VERIFIED and
    never silently absent from a report."""


SETTLED_STATES = frozenset(
    {
        PropagationState.ENFORCED,
        PropagationState.VERIFIED,
        PropagationState.REJECTED,
        PropagationState.SUPERSEDED,
        PropagationState.FAILED,
    }
)
"""No longer **owed**: what `Outbox.pending` excludes.

An `enforced` delivery is settled — the recipient's projections no longer
expose the version, so the origin has nothing left to do — but it is not
terminal, because the origin may still independently confirm it and move the
pair to `verified`.
"""

TERMINAL_STATES = frozenset(
    {
        PropagationState.VERIFIED,
        PropagationState.REJECTED,
        PropagationState.SUPERSEDED,
        PropagationState.FAILED,
    }
)
"""No further transitions **at all**.

Split from `SETTLED_STATES` after a property test asserted that a terminal
state has no outgoing edges and found `enforced` declaring one to `verified`.
One constant was answering two questions — "is this still owed?" and "can this
still move?" — and `enforced` answers them differently. Collapsing them would
have meant either an unreachable `verified` or an `enforced` delivery that
`pending()` kept reporting forever.
"""
"""States the dispatcher will not retry out of. FAILED is terminal and visible:
a permanent failure that disappeared would be worse than one that keeps
complaining."""

ALLOWED_TRANSITIONS: dict[PropagationState, frozenset[PropagationState]] = {
    PropagationState.REQUESTED: frozenset({PropagationState.QUEUED, PropagationState.FAILED}),
    PropagationState.QUEUED: frozenset(
        {
            PropagationState.DELIVERED,
            PropagationState.RETRYING,
            PropagationState.REJECTED,
            PropagationState.SUPERSEDED,
            PropagationState.FAILED,
            PropagationState.UNKNOWN,
        }
    ),
    PropagationState.RETRYING: frozenset(
        {
            PropagationState.QUEUED,
            PropagationState.DELIVERED,
            PropagationState.FAILED,
            PropagationState.UNKNOWN,
        }
    ),
    PropagationState.DELIVERED: frozenset(
        {
            PropagationState.PERSISTED,
            PropagationState.REJECTED,
            PropagationState.SUPERSEDED,
            PropagationState.RETRYING,
        }
    ),
    PropagationState.PERSISTED: frozenset({PropagationState.ENFORCED, PropagationState.FAILED}),
    PropagationState.ENFORCED: frozenset({PropagationState.VERIFIED}),
    PropagationState.UNKNOWN: frozenset(
        {PropagationState.QUEUED, PropagationState.RETRYING, PropagationState.FAILED}
    ),
    # Terminal.
    PropagationState.VERIFIED: frozenset(),
    PropagationState.REJECTED: frozenset(),
    PropagationState.SUPERSEDED: frozenset(),
    PropagationState.FAILED: frozenset(),
}
"""The state machine, as data rather than as scattered `if` statements.

`ENFORCED` cannot go back to `PERSISTED` and nothing leaves `REJECTED`: a
recipient that has refused a retraction has refused it, and an origin that
retries gets the same refusal rather than a second chance at a different answer.
"""


def can_transition(current: PropagationState, target: PropagationState) -> bool:
    return target in ALLOWED_TRANSITIONS.get(current, frozenset())


class RejectionCode(str, Enum):
    UNAUTHENTICATED = "unauthenticated"
    UNAUTHORIZED = "unauthorized"
    SCHEMA_UNSUPPORTED = "schema_unsupported"
    PROTOCOL_VERSION_UNSUPPORTED = "protocol_version_unsupported"
    UNKNOWN_MEMORY = "unknown_memory"
    VERSION_SUPERSEDED = "version_superseded"
    MALFORMED = "malformed"
    HOP_LIMIT = "hop_limit"
    """A forwarded retraction reached MAX_HOPS. Recorded rather than dropped:
    the loop defence is deduplication on the campaign identity, so reaching the
    backstop means something is wrong with the topology or the dedup key."""


class ProtocolError(ValueError):
    """A message that cannot be processed. Carries a rejection code so the
    recipient's refusal is itself auditable."""

    def __init__(self, code: RejectionCode, detail: str) -> None:
        super().__init__(f"{code.value}: {detail}")
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class Retraction:
    """One retraction, for one exact memory version, from one origin store."""

    retraction_id: str
    origin_store_id: str
    origin_memory_id: str
    origin_memory_version: int
    origin_sequence: int
    reason_code: str
    requested_by: str
    issued_at: str
    tenant_id: str | None = None
    evidence_digest: str | None = None
    evidence_reference: str | None = None
    protocol_version: int = PROTOCOL_VERSION

    # --- transitive forwarding (Phase D) ---------------------------------
    #
    # `retraction_id` + `origin_store_id` identify the **campaign** and never
    # change along a chain, which is what makes a cycle terminate: a store that
    # has already seen the pair returns its first outcome instead of applying
    # again.
    #
    # The *target* is per hop. A store two hops out imported from the store one
    # hop out, so its provenance points there, not at the origin. These default
    # to the origin fields, so a direct retraction is byte-identical to before
    # and a 0.3.0 peer that ignores them still behaves correctly.
    target_store_id: str | None = None
    target_memory_id: str | None = None
    target_memory_version: int | None = None
    hop: int = 0
    forwarded_by: str | None = None

    @property
    def applies_to_store(self) -> str:
        return self.target_store_id or self.origin_store_id

    @property
    def applies_to_memory(self) -> str:
        return self.target_memory_id or self.origin_memory_id

    @property
    def applies_to_version(self) -> int:
        return (
            self.target_memory_version
            if self.target_memory_version is not None
            else self.origin_memory_version
        )

    def forward(
        self,
        from_store_id: str,
        local_memory_id: str,
        local_version: int,
    ) -> "Retraction":
        """The same campaign, retargeted for the next hop.

        The campaign identity is preserved deliberately. Minting a fresh
        `retraction_id` per hop would make every hop a distinct event, so a
        cycle would never deduplicate and a diamond-shaped topology would apply
        the same withdrawal twice.
        """
        return replace(
            self,
            target_store_id=from_store_id,
            target_memory_id=local_memory_id,
            target_memory_version=local_version,
            hop=self.hop + 1,
            forwarded_by=from_store_id,
        )

    def to_json(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "protocol_version": self.protocol_version,
            "retraction_id": self.retraction_id,
            "origin_store_id": self.origin_store_id,
            "origin_memory_id": self.origin_memory_id,
            "origin_memory_version": self.origin_memory_version,
            "origin_sequence": self.origin_sequence,
            "reason_code": self.reason_code,
            "requested_by": self.requested_by,
            "issued_at": self.issued_at,
        }
        for key in (
            "tenant_id",
            "evidence_digest",
            "evidence_reference",
            "target_store_id",
            "target_memory_id",
            "target_memory_version",
            "forwarded_by",
        ):
            value = getattr(self, key)
            if value is not None:
                payload[key] = value
        if self.hop:
            payload["hop"] = self.hop
        return payload

    def canonical(self) -> bytes:
        """Stable bytes for signing. Sorted keys, no whitespace, so two
        processes that agree on the content agree on the signature."""
        return json.dumps(self.to_json(), sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )

    def sign(self, key: bytes, key_id: str = "k1") -> dict[str, str]:
        return {
            "alg": "hmac-sha256",
            "key_id": key_id,
            "value": hmac.new(key, self.canonical(), hashlib.sha256).hexdigest(),
        }

    def verify(self, signature: Mapping[str, str], key: bytes) -> bool:
        """Constant-time comparison, and it proves origin and integrity only.

        It says nothing about whether the retracted claim was false. Nothing
        downstream may treat a valid signature as evidence about the memory.
        """
        if signature.get("alg") != "hmac-sha256":
            return False
        expected = hmac.new(key, self.canonical(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, str(signature.get("value", "")))

    @classmethod
    def from_json(cls, payload: Mapping[str, Any]) -> "Retraction":
        """Parse and validate. Raises `ProtocolError` with a rejection code, so
        a malformed message produces an auditable refusal rather than a
        traceback."""
        version = payload.get("protocol_version")
        if version != PROTOCOL_VERSION:
            raise ProtocolError(
                RejectionCode.PROTOCOL_VERSION_UNSUPPORTED,
                f"protocol_version {version!r}, this store speaks {PROTOCOL_VERSION}",
            )

        required = (
            "retraction_id",
            "origin_store_id",
            "origin_memory_id",
            "origin_memory_version",
            "origin_sequence",
            "reason_code",
            "requested_by",
            "issued_at",
        )
        missing = [key for key in required if key not in payload]
        if missing:
            raise ProtocolError(
                RejectionCode.MALFORMED, f"missing {', '.join(sorted(missing))}"
            )

        if not RETRACTION_ID_RE.match(str(payload["retraction_id"])):
            raise ProtocolError(RejectionCode.MALFORMED, "retraction_id is not an rt_ ULID")
        if not STORE_ID_RE.match(str(payload["origin_store_id"])):
            # The specific defence against the old behaviour: a filesystem path
            # must not be accepted as a store identity.
            raise ProtocolError(
                RejectionCode.MALFORMED,
                "origin_store_id is not an st_ ULID (a path is not an identity)",
            )
        tenant = payload.get("tenant_id")
        if tenant is not None and not TENANT_ID_RE.match(str(tenant)):
            raise ProtocolError(RejectionCode.MALFORMED, "tenant_id is not a tn_ ULID")

        try:
            memory_version = int(payload["origin_memory_version"])
            sequence = int(payload["origin_sequence"])
        except (TypeError, ValueError) as exc:
            raise ProtocolError(RejectionCode.MALFORMED, f"non-integer version: {exc}") from exc
        if memory_version < 1:
            raise ProtocolError(RejectionCode.MALFORMED, "origin_memory_version must be >= 1")
        if sequence < 0:
            raise ProtocolError(RejectionCode.MALFORMED, "origin_sequence must be >= 0")

        return cls(
            retraction_id=str(payload["retraction_id"]),
            origin_store_id=str(payload["origin_store_id"]),
            origin_memory_id=str(payload["origin_memory_id"]),
            origin_memory_version=memory_version,
            origin_sequence=sequence,
            reason_code=str(payload["reason_code"]),
            requested_by=str(payload["requested_by"]),
            issued_at=str(payload["issued_at"]),
            tenant_id=None if tenant is None else str(tenant),
            evidence_digest=_optional_str(payload.get("evidence_digest")),
            evidence_reference=_optional_str(payload.get("evidence_reference")),
            target_store_id=_optional_str(payload.get("target_store_id")),
            target_memory_id=_optional_str(payload.get("target_memory_id")),
            target_memory_version=(
                None
                if payload.get("target_memory_version") is None
                else int(payload["target_memory_version"])
            ),
            hop=int(payload.get("hop", 0)),
            forwarded_by=_optional_str(payload.get("forwarded_by")),
        )

    @property
    def dedupe_key(self) -> tuple[str, str, str]:
        """`(origin_store_id, retraction_id, target_key)`.

        The campaign identity, plus **which copy this hop is about**.

        Not the memory id alone: a replay and a genuinely new second retraction
        of the same memory are different events, and state convergence cannot
        tell them apart.

        Not the campaign alone either, which it was before transitive
        forwarding existed. A diamond — origin A reaching store C both directly
        and through B — delivers the same campaign twice with *different*
        targets, because C's copy from A and C's copy from B have different
        provenance. Keyed on the campaign alone, whichever arrived first
        recorded its outcome for both: a forwarded hop that found nothing would
        make the direct retraction return "unknown memory" and C would keep
        acting on knowledge the origin had withdrawn. That is the exact failure
        PB2 measured away in the one-hop case.

        Termination still holds, which is the thing this key had to not break.
        A target is a concrete `(store, memory, version)` triple and a
        federation holds finitely many, so a cycle re-arrives with a triple
        already recorded and stops there."""
        return (
            self.origin_store_id,
            self.retraction_id,
            f"{self.applies_to_store}/{self.applies_to_memory}@{self.applies_to_version}",
        )


@dataclass(frozen=True)
class Acknowledgement:
    """A recipient's statement of **committed** state.

    `persisted` only after its own commit; `enforced` only once its projections
    no longer expose the version. Acknowledging on receipt would be the most
    damaging lie available here — the origin would record the correction as
    landed while the recipient kept serving withdrawn knowledge.
    """

    retraction_id: str
    recipient_store_id: str
    state: PropagationState
    at: str
    state_revision: int = 0
    origin_sequence_seen: int = 0
    detail: str = ""
    rejection_code: str | None = None
    protocol_version: int = PROTOCOL_VERSION

    def to_json(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "protocol_version": self.protocol_version,
            "retraction_id": self.retraction_id,
            "recipient_store_id": self.recipient_store_id,
            "state": self.state.value,
            "state_revision": self.state_revision,
            "origin_sequence_seen": self.origin_sequence_seen,
            "at": self.at,
        }
        if self.detail:
            # Bounded and operator-facing. An unbounded free-text field is where
            # memory content ends up in somebody's log aggregator.
            payload["detail"] = self.detail[:512]
        if self.rejection_code is not None:
            payload["rejection_code"] = self.rejection_code
        return payload

    @classmethod
    def from_json(cls, payload: Mapping[str, Any]) -> "Acknowledgement":
        if payload.get("protocol_version") != PROTOCOL_VERSION:
            raise ProtocolError(
                RejectionCode.PROTOCOL_VERSION_UNSUPPORTED,
                f"acknowledgement protocol_version {payload.get('protocol_version')!r}",
            )
        for key in ("retraction_id", "recipient_store_id", "state", "at"):
            if key not in payload:
                raise ProtocolError(RejectionCode.MALFORMED, f"acknowledgement missing {key}")
        try:
            state = PropagationState(str(payload["state"]))
        except ValueError as exc:
            raise ProtocolError(
                RejectionCode.MALFORMED, f"unknown propagation state {payload['state']!r}"
            ) from exc
        return cls(
            retraction_id=str(payload["retraction_id"]),
            recipient_store_id=str(payload["recipient_store_id"]),
            state=state,
            at=str(payload["at"]),
            state_revision=int(payload.get("state_revision", 0)),
            origin_sequence_seen=int(payload.get("origin_sequence_seen", 0)),
            detail=str(payload.get("detail", "")),
            rejection_code=_optional_str(payload.get("rejection_code")),
        )

    @property
    def overstates_persistence(self) -> bool:
        """True when a state claims more than `received` without the recipient
        having committed anything. Used by the origin to refuse an
        acknowledgement rather than record a guarantee it was not given."""
        return self.state in (
            PropagationState.PERSISTED,
            PropagationState.ENFORCED,
            PropagationState.VERIFIED,
        ) and self.state_revision <= 0


def _optional_str(value: Any) -> str | None:
    return None if value is None else str(value)
