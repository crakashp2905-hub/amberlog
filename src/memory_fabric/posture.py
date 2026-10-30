"""Security posture and audit export.

**Posture** answers "which controls are on in *this* store, and what is not
covered at all?" Each control's state is read from the running store, not
asserted; the accepted gaps come from docs/SECURITY_REVIEW.md §3, so the page
and the review cannot disagree. It is evidence for a reviewer, not a
certification: a control being on says what the store does, not that the
deployment around it is sound.

**Audit export** writes decisions, changes, access events and deletion
receipts as JSON lines, **without content**: a memory's text never leaves in
an export, only ids, versions, actors and reasons. The last line is a
checkpoint of the hash chain at the head the export was taken from, so a
reviewer holding it can check later that the log still agrees
(`memory_fabric checkpoint --verify`).
"""

from __future__ import annotations

__stability__ = "beta"

import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterable

from .events import EventType

if TYPE_CHECKING:  # pragma: no cover
    from .fabric import MemoryFabric


@dataclass(frozen=True)
class Control:
    name: str
    state: str
    """`on`, `off` or `partial`."""
    detail: str
    evidence: str

    def to_json(self) -> dict[str, Any]:
        return dict(self.__dict__)


# docs/SECURITY_REVIEW.md §3, open items. Kept here so the posture page shows
# what no setting changes.
ACCEPTED_GAPS = (
    ("O1", "Paraphrased prompt injection passes the write-time pattern screen",
     "retrieved memories are delimited as data and a memory never grants a tool"),
    ("O2", "A residual race between `verify` and the action itself",
     "verification is pinned to the log head immediately before acting"),
    ("O3", "A writer with full database access can rewrite log and chain consistently",
     "detected only against an external checkpoint the operator keeps"),
    ("O4", "Tenancy is logical, not physical",
     "a store per tenant is the physical option"),
    ("O5", "Federation peer keys do not rotate automatically",
     "manual rotation: docs/RUNBOOKS.md §3"),
    ("O6", "The dashboard access log is a plain file, not chained",
     "changes are in the chained event log"),
    ("O7", "No external audit and no formal verification", ""),
)


def posture(fabric: "MemoryFabric") -> dict[str, Any]:
    from .governance.cipher import aead_available

    postgres = getattr(fabric.log, "dialect", "sqlite") != "sqlite"
    custody = type(fabric.vault.keys).__name__
    controls = [
        Control("authenticated encryption at rest",
                "on" if aead_available() else "partial",
                "AES-GCM" if aead_available() else
                "encrypt-then-MAC (HMAC-SHA256); install `cryptography` for AES-GCM",
                "governance/cipher.py; tests/test_cipher.py"),
        Control("content keys kept outside the database",
                "off" if custody == "SqliteKeyProvider" else "on",
                "keys sit beside the ciphertext: erasure works, a copy of the file reads content"
                if custody == "SqliteKeyProvider" else f"external key provider ({custody})",
                "`migrate-keys`; docs/RUNBOOKS.md §5"),
        Control("append-only event log enforced by the database",
                "on" if postgres else "partial",
                "Postgres triggers refuse UPDATE, DELETE and TRUNCATE" if postgres else
                "SQLite: file permissions and the hash chain; nothing in the database refuses an edit",
                "tests/test_postgres.py; tests/test_integrity_chain.py"),
        Control("tamper-evident hash chain", "on",
                "every event is chained; a full rewrite needs an external checkpoint to detect",
                "integrity.py; `checkpoint`"),
        Control("new memories wait for review",
                "off" if fabric.auto_activate else "on",
                "auto_activate is on: clean writes are active without review"
                if fabric.auto_activate else "writes start as candidates",
                "review.py; status label 'reviewed'"),
        Control("scope enforced on reads", "on",
                "private memories are readable by their author and collection readers only",
                "tests/test_scope_visibility.py (security review F10)"),
        Control("cross-tenant refusals conceal existence",
                "on" if getattr(fabric, "conceal_cross_tenant", False) else "off",
                "a cross-tenant refusal is identical to a missing id"
                if getattr(fabric, "conceal_cross_tenant", False)
                else "a cross-tenant refusal says `wrong_tenant`, confirming the id exists",
                "tests/test_privacy_federation.py"),
        Control("secret and injection screens at ingest", "on",
                "every write path, metadata included; known patterns only",
                "governance/sensitive.py, governance/injection.py"),
        Control("value evidence required to leave the store", "on",
                "the firewall refuses `federated` without contrastive value evidence",
                "governance/firewall.py"),
        Control("durable revocations", "on",
                "revocations are rows in the store and survive restarts",
                "identity.SqliteRevocations; `agent-api-revoke`"),
    ]
    return {"store_id": fabric.store_id,
            "controls": [c.to_json() for c in controls],
            "accepted_gaps": [{"id": i, "gap": g, "mitigation": m} for i, g, m in ACCEPTED_GAPS]}


# --- export ------------------------------------------------------------------

KINDS = {
    "decisions": (EventType.LIFECYCLE_CHANGED, EventType.SCOPE_CHANGED, EventType.ACTION_GATED,
                  EventType.RETRACTION_REQUESTED, EventType.RETRACTION_APPLIED,
                  EventType.RETRACTION_REJECTED),
    "changes": (EventType.MEMORY_CREATED, EventType.MEMORY_VERSIONED,
                EventType.COLLECTION_CHANGED, EventType.MEMORY_SHARED),
    "access": (EventType.ACCESS_DENIED, EventType.EXPOSURE_DECIDED),
    "deletions": (EventType.CONTENT_ERASED,),
}
_KEEP_FROM_MEMORY = ("id", "version", "type", "tenant_id", "scope", "security_class")


def _without_content(event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    out = {k: v for k, v in payload.items() if k not in ("memory", "candidates", "content")}
    memory = payload.get("memory")
    if isinstance(memory, dict):
        out["memory"] = {k: memory[k] for k in _KEEP_FROM_MEMORY if k in memory}
        prov = memory.get("provenance") or {}
        out["memory"]["created_by"] = prov.get("created_by")
        out["memory"]["method"] = prov.get("method")
    return out


def export_audit(fabric: "MemoryFabric", path: str | Path,
                 kinds: Iterable[str] = ("decisions", "changes", "access", "deletions"),
                 since_seq: int = 0) -> dict[str, Any]:
    """Write the export; return its manifest (also the file's first line)."""
    wanted = [k for k in kinds if k in KINDS]
    types = sorted({t for k in wanted for t in KINDS[k]})
    kind_of = {t: k for k in wanted for t in KINDS[k]}
    rows = [e for e in fabric.log.read_types(types) if (e.seq or 0) > since_seq]
    checkpoint = fabric.log.chain.checkpoint()
    counts: dict[str, int] = {}
    for event in rows:
        counts[kind_of[event.type]] = counts.get(kind_of[event.type], 0) + 1
    manifest = {"export": "memory_fabric audit", "store_id": fabric.store_id,
                "kinds": wanted, "since_seq": since_seq, "events": len(rows), "counts": counts,
                "content": "excluded"}
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(manifest) + "\n")
        for event in rows:
            fh.write(json.dumps({"seq": event.seq, "ts": event.ts, "type": event.type,
                                 "kind": kind_of[event.type], "actor": event.agent_id,
                                 "payload": _without_content(event.type, dict(event.payload))},
                                default=str) + "\n")
        fh.write(json.dumps({"checkpoint": checkpoint.to_json()}) + "\n")
    return manifest
