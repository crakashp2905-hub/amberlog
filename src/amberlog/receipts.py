"""Correction receipts that prove enforcement without describing the recipient.

Research direction S5 (`research/prereg/s5-correction-receipts.md`).

## What an acknowledgement gives away

An `Acknowledgement` tells the origin that a recipient enforced a retraction.
It also tells the origin, every time:

- **`state_revision`**: the recipient's log head. Two acknowledgements a week
  apart say how much the recipient did in between.
- **`detail`**: "2 memory/ies withdrawn; forwarded to 3 peer(s)". That is how
  many copies the recipient held and how many stores it re-shared to, which
  is part of its sharing graph.

Neither is needed to know the correction landed. Both go to every origin that
ever sends a retraction.

## The receipt

`CorrectionReceipt` says exactly one thing: *this recipient enforced this
retraction*. It is fixed-size and carries no counts, no sequence and no time:

- `commitment`: `SHA-256(nonce || canonical opening)`. The opening is the
  local ids withdrawn, the log sequence of the last `RetractionApplied`, and
  the integrity-chain digest at that sequence. The nonce is an HMAC of the
  retraction id under the recipient's **binding key**, which only the
  recipient holds. So the commitment hides even the small fields, such as how
  many copies there were, and the recipient can recompute the opening at any
  time without storing anything new.
- `tag`: `HMAC-SHA256(peer key, receipt)`. It is authentic to the origin, which
  shares the peer key, and cannot be forged by anyone without it.

**What it proves, and to whom.** To the origin, only that the recipient
committed to an enforcement it can be held to. The binding comes at **audit**.
An auditor with access to the recipient's store, or the recipient proving
itself to a third party, opens the commitment with the binding key and
`audit` checks three things:

1. the opening matches the commitment;
2. the digest is the one the recipient's hash-chained log holds at that
   sequence;
3. replaying the log to that sequence, every opened copy was withdrawn.

A recipient that never applied the retraction cannot produce an opening that
matches. Nor can one that names a log point where the copy was still active,
or one that rewrites its log afterwards, because of the chain. `audit` also
reports a copy re-activated *since*, separately.

**What it does not hide.** The origin still sees *that* and *when* a receipt
arrives, because that is the network. A recipient that held no copy is not
distinguished from one that held several, which is the point. The
commitment is binding only if the auditor trusts the chain digest, which is
why `integrity.Checkpoint` exists. Taking checkpoints off-host is the
operator's job.

Opt-in: acknowledgements are unchanged on the wire.
"""

from __future__ import annotations

__stability__ = "experimental"

import hashlib
import hmac
import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Mapping

from .events import EventType

if TYPE_CHECKING:  # pragma: no cover
    from .fabric import Amberlog

RECEIPT_VERSION = "receipt-v1"


class ReceiptError(Exception):
    """The retraction is not enforced here, so there is nothing to sign."""


def _canonical(data: Mapping[str, Any]) -> bytes:
    return json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")


@dataclass(frozen=True)
class CorrectionReceipt:
    retraction_id: str
    origin_store_id: str
    recipient_store_id: str
    commitment: str
    tag: str
    version: str = RECEIPT_VERSION
    state: str = "enforced"

    def body(self) -> dict[str, str]:
        return {"version": self.version, "retraction_id": self.retraction_id,
                "origin_store_id": self.origin_store_id,
                "recipient_store_id": self.recipient_store_id, "state": self.state,
                "commitment": self.commitment}

    def to_json(self) -> dict[str, str]:
        return {**self.body(), "tag": self.tag}

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> "CorrectionReceipt":
        return cls(retraction_id=str(data["retraction_id"]),
                   origin_store_id=str(data["origin_store_id"]),
                   recipient_store_id=str(data["recipient_store_id"]),
                   commitment=str(data["commitment"]), tag=str(data["tag"]),
                   version=str(data.get("version", RECEIPT_VERSION)),
                   state=str(data.get("state", "enforced")))


@dataclass(frozen=True)
class Opening:
    nonce: str
    local_ids: tuple[str, ...]
    apply_seq: int
    chain_digest: str

    def commitment(self, retraction_id: str) -> str:
        material = _canonical({"retraction_id": retraction_id,
                               "local_ids": list(self.local_ids),
                               "apply_seq": self.apply_seq,
                               "chain_digest": self.chain_digest})
        return hashlib.sha256(bytes.fromhex(self.nonce) + material).hexdigest()


@dataclass
class AuditResult:
    ok: bool
    reasons: list[str] = field(default_factory=list)
    reactivated_since: list[str] = field(default_factory=list)


def _nonce(binding_key: bytes, retraction_id: str) -> str:
    return hmac.new(binding_key, b"mf-receipt-nonce:" + retraction_id.encode("utf-8"),
                    hashlib.sha256).hexdigest()


def _tag(peer_key: bytes, body: Mapping[str, str]) -> str:
    return hmac.new(peer_key, _canonical(body), hashlib.sha256).hexdigest()


def open_receipt(fabric: "Amberlog", retraction_id: str, binding_key: bytes) -> Opening:
    """Recompute this store's opening for a retraction, from its own log."""
    applied = [e for e in fabric.log.read_types([EventType.RETRACTION_APPLIED])
               if e.payload.get("retraction_id") == retraction_id]
    if not applied:
        raise ReceiptError(f"retraction {retraction_id} was not applied here")
    apply_seq = max(int(e.seq or 0) for e in applied)
    digest = fabric.log.chain.digest_at(apply_seq)
    if digest is None:
        raise ReceiptError(f"log sequence {apply_seq} is not covered by the integrity chain")
    local_ids = tuple(sorted({str(e.payload["local_memory_id"]) for e in applied}))
    return Opening(_nonce(binding_key, retraction_id), local_ids, apply_seq, digest)


def issue(fabric: "Amberlog", retraction_id: str, *, binding_key: bytes,
          peer_key: bytes) -> CorrectionReceipt:
    """A receipt for a retraction this store has applied and still enforces."""
    from .model import EXPOSABLE_STATES

    opening = open_receipt(fabric, retraction_id, binding_key)
    if any(fabric.state.memories[m].lifecycle_state in EXPOSABLE_STATES
           for m in opening.local_ids if m in fabric.state.memories):
        raise ReceiptError("a withdrawn copy is exposable again; not signing enforcement")
    origin = next(e.payload["origin_store_id"] for e in
                  fabric.log.read_types([EventType.RETRACTION_APPLIED])
                  if e.payload.get("retraction_id") == retraction_id)
    unsigned = CorrectionReceipt(retraction_id=retraction_id, origin_store_id=str(origin),
                                 recipient_store_id=fabric.store_id,
                                 commitment=opening.commitment(retraction_id), tag="")
    return CorrectionReceipt(**{**unsigned.__dict__, "tag": _tag(peer_key, unsigned.body())})


def authentic(receipt: CorrectionReceipt, peer_key: bytes) -> bool:
    """What the origin can check: the receipt came from a holder of the peer key."""
    return hmac.compare_digest(receipt.tag, _tag(peer_key, receipt.body()))


def audit(fabric: "Amberlog", receipt: CorrectionReceipt,
          binding_key: bytes) -> AuditResult:
    """Hold the recipient to its receipt, against its own hash-chained log."""
    from .model import EXPOSABLE_STATES
    from .projections import Projection

    result = AuditResult(ok=True)
    if receipt.recipient_store_id != fabric.store_id:
        return AuditResult(False, ["receipt names another store"])
    try:
        opening = open_receipt(fabric, receipt.retraction_id, binding_key)
    except ReceiptError as exc:
        return AuditResult(False, [str(exc)])
    if not hmac.compare_digest(opening.commitment(receipt.retraction_id), receipt.commitment):
        return AuditResult(False, ["the log does not open the commitment"])
    verification = fabric.log.chain.verify(fabric.log.read())
    if not verification.ok:
        result.ok = False
        result.reasons.append(f"integrity chain does not verify: {verification.detail}")
    projection = Projection()
    for event in fabric.log.read():
        if (event.seq or 0) > opening.apply_seq:
            break
        projection.apply(event)
    for memory_id in opening.local_ids:
        memory = projection.state.memories.get(memory_id)
        if memory is None or memory.lifecycle_state in EXPOSABLE_STATES:
            result.ok = False
            result.reasons.append(f"{memory_id} was not withdrawn at the receipt's log point")
        now = fabric.state.memories.get(memory_id)
        if now is not None and now.lifecycle_state in EXPOSABLE_STATES:
            result.reactivated_since.append(memory_id)
    return result
