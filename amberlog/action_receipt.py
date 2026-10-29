"""Action evidence receipts that anyone with the public key can verify.

When an agent asks to act, the action gate decides. Its decision is already
logged (`ActionGated`), but that record is only as trustworthy as the store
that holds it, and the store's other receipts are HMACs under a shared key
(`receipts.py`), so only the key holder can check them. An auditor, a
customer or a regulator needs something they can check with nothing but a
public key.

An **action receipt** (`mf-action-receipt/1`) is one canonical JSON document,
signed with Ed25519, that states:

- **the action**: tool, agent, tenant, target, and a SHA-256 of the
  parameters (the parameters themselves stay out, since they may be
  sensitive);
- **the decision**: allowed or refused, every reason code, and each check the
  verifier ran, with its result;
- **the evidence**: per memory, the id, version, a SHA-256 of its content at
  that version, its lifecycle state, its claim-check level and its freshness;
- **the position in the log**: sequence number and chain digest at the
  decision, which ties the receipt to the tamper-evident log;
- **the signer**: key id and public key.

`verify_receipt(doc, public_key)` needs no store: it checks the signature and
the format. `verify_against_store(doc, fabric)` also checks, for a holder of
the store, that the log position and each evidence hash match the history.

**What a receipt proves, stated.** It proves which claims were presented as
the basis for an action, what checks were run on them and with what result,
and that this record has not been altered since it was signed. It does **not**
prove the agent reasoned correctly from those claims, or that the claims were
true. A receipt also never contains memory content, only hashes of it.

Signing needs the optional `cryptography` package. Without it, `issue` raises
`ReceiptUnavailable` rather than producing an unsigned receipt.
"""

from __future__ import annotations

__stability__ = "beta"

import base64
import hashlib
import json
import time
from typing import TYPE_CHECKING, Any, Mapping

if TYPE_CHECKING:  # pragma: no cover
    from .actions import ActionDecision, ActionRequest
    from .certificates import EvidenceCertificate
    from .fabric import Amberlog

FORMAT = "mf-action-receipt/1"


class ReceiptUnavailable(RuntimeError):
    """Signing needs the `cryptography` package."""


class ReceiptInvalid(ValueError):
    """The receipt does not verify; the message says which check failed."""


def _canonical(doc: Mapping[str, Any]) -> bytes:
    body = {k: v for k, v in doc.items() if k != "signature"}
    return json.dumps(body, sort_keys=True, separators=(",", ":"), default=str).encode()


def _sha256(data: bytes | str) -> str:
    return hashlib.sha256(data.encode() if isinstance(data, str) else data).hexdigest()


def generate_key() -> tuple[bytes, bytes]:
    """(private key, public key) as raw 32-byte Ed25519 keys."""
    try:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    except Exception as exc:  # noqa: BLE001 - missing or broken install
        raise ReceiptUnavailable("action receipts need the 'cryptography' package") from exc
    key = Ed25519PrivateKey.generate()
    raw = serialization.Encoding.Raw
    private = key.private_bytes(raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())
    public = key.public_key().public_bytes(raw, serialization.PublicFormat.Raw)
    return private, public


def _evidence(fabric: "Amberlog", certificate: "EvidenceCertificate | None",
              leases: Any) -> list[dict[str, Any]]:
    if certificate is None:
        return []
    from .validation import assess

    out = []
    for ref in certificate.evidence:
        item: dict[str, Any] = {"memory_id": ref.memory_id, "version": ref.version,
                                "role": ref.role}
        versions = [m for m in fabric.history(ref.memory_id) if m.version == ref.version]
        if versions:
            item["content_sha256"] = _sha256(versions[-1].content)
        try:
            item["lifecycle_state"] = fabric.lifecycle_of(ref.memory_id).value
            item["claim_check"] = assess(fabric, ref.memory_id).level
        except KeyError:
            item["lifecycle_state"] = "unknown"
        if leases is not None:
            from .freshness import freshness_of

            item["freshness"] = freshness_of(fabric, ref.memory_id, leases)
        out.append(item)
    return out


def issue(fabric: "Amberlog", decision: "ActionDecision", private_key: bytes, *,
          certificate: "EvidenceCertificate | None" = None,
          request: "ActionRequest | None" = None, tenant_id: str | None = None,
          key_id: str = "k1", leases: Any = None) -> dict[str, Any]:
    """A signed receipt for one gate decision."""
    try:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    except Exception as exc:  # noqa: BLE001
        raise ReceiptUnavailable("action receipts need the 'cryptography' package") from exc
    key = Ed25519PrivateKey.from_private_bytes(private_key)
    public = key.public_key().public_bytes(serialization.Encoding.Raw,
                                           serialization.PublicFormat.Raw)
    seq, chain_digest = fabric.log.chain.head()
    verification = decision.verification
    doc: dict[str, Any] = {
        "format": FORMAT,
        "issued_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "store_id": fabric.store_id,
        "action": {
            "tool": decision.tool, "agent_id": decision.agent_id, "tenant_id": tenant_id,
            "target": request.target if request else None,
            "parameters_sha256": (_sha256(json.dumps(dict(request.parameters), sort_keys=True,
                                                     default=str)) if request else None),
        },
        "decision": {
            "allowed": decision.allowed, "reason_codes": list(decision.reason_codes),
            "checks": dict(verification.checks) if verification else {},
            "independent_sources": verification.independent_sources if verification else None,
            "certificate_digest": verification.certificate_digest if verification else None,
        },
        "claim_id": certificate.claim_id if certificate else None,
        "policy_id": certificate.policy_id if certificate else None,
        "evidence": _evidence(fabric, certificate, leases),
        "log": {"seq": seq, "chain_digest": chain_digest},
        "signer": {"key_id": key_id, "algorithm": "ed25519",
                   "public_key": base64.b64encode(public).decode()},
    }
    doc["signature"] = base64.b64encode(key.sign(_canonical(doc))).decode()
    return doc


def verify_receipt(doc: Mapping[str, Any], public_key: bytes | None = None) -> None:
    """Raise `ReceiptInvalid` unless the receipt is well formed and its signature verifies.

    `public_key` is the key the verifier trusts. If omitted, the receipt's own
    embedded key is used, which proves only integrity, not who signed it.
    Pass the key you obtained independently.
    """
    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    except Exception as exc:  # noqa: BLE001
        raise ReceiptUnavailable("verifying receipts needs the 'cryptography' package") from exc
    if doc.get("format") != FORMAT:
        raise ReceiptInvalid(f"unknown format {doc.get('format')!r}")
    for field_name in ("action", "decision", "evidence", "log", "signer", "signature"):
        if field_name not in doc:
            raise ReceiptInvalid(f"missing {field_name}")
    embedded = base64.b64decode(doc["signer"]["public_key"])
    if public_key is not None and public_key != embedded:
        raise ReceiptInvalid("signed with a different key than the one trusted")
    try:
        Ed25519PublicKey.from_public_bytes(public_key or embedded).verify(
            base64.b64decode(doc["signature"]), _canonical(doc))
    except InvalidSignature:
        raise ReceiptInvalid("signature does not verify: the receipt was altered") from None


def verify_against_store(doc: Mapping[str, Any], fabric: "Amberlog") -> list[str]:
    """Problems found comparing a receipt with the store's own history (empty if none)."""
    problems = []
    if doc.get("store_id") != fabric.store_id:
        problems.append("receipt is for another store")
    seq = doc.get("log", {}).get("seq")
    if seq is not None and fabric.log.chain.digest_at(int(seq)) != doc["log"].get("chain_digest"):
        problems.append(f"log position {seq} does not match this store's chain")
    for item in doc.get("evidence", []):
        from ._fabric.common import FabricError

        try:
            history = fabric.history(item["memory_id"])
        except (KeyError, FabricError):  # not in this store at all
            history = []
        versions = [m for m in history if m.version == item["version"]]
        if not versions:
            problems.append(f"{item['memory_id']} v{item['version']} not in this store's history")
        elif item.get("content_sha256") and _sha256(versions[-1].content) != item["content_sha256"]:
            problems.append(f"{item['memory_id']} v{item['version']} content differs from the receipt")
    return problems
