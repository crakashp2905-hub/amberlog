"""Phase 6 — crypto-erasure, and the content/audit split.

Invariant 12: *append-only audit history does not justify retaining sensitive
content indefinitely.* The two halves of that sentence are in tension, and the
tension is real rather than a wording problem:

* The event log is the source of truth and is append-only, enforced by database
  triggers. Rewriting it to delete a memory's text would destroy the property
  everything else rests on — and a log you can edit to remove embarrassing
  entries is not an audit trail.
* A subject asking for erasure, or a leaked credential, means the *content* has
  to stop being readable. "It is in an immutable log" is not an answer.

The resolution is the standard one and it works here because the log stores the
content as a field rather than as the whole record: **encrypt the content with a
per-memory key, keep the key outside the log, and destroy the key.** The events
stay exactly as they were, every projection still replays, the lineage and the
propagation record are untouched, and the text is unrecoverable.

What survives erasure is deliberately everything *about* the memory — who wrote
it, when, what it was derived from, what was derived from it, that it was
retracted and why. An auditor can still answer "was this handled correctly?"
about a memory nobody can read. That is the point: erasure removes the content,
not the accountability.

**This is not a substitute for encryption at rest.** A key destroyed here makes
one memory's content unrecoverable; it does nothing about the rest of the file,
which is still plaintext SQLite (see SECURITY.md and docs/AUDIT.md).
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import sqlite3
from dataclasses import dataclass
from typing import Any

_SCHEMA = """
CREATE TABLE IF NOT EXISTS content_keys (
    memory_id   TEXT PRIMARY KEY,
    key_material BLOB,
    created_ms  INTEGER NOT NULL,
    erased_ms   INTEGER,
    reason      TEXT NOT NULL DEFAULT ''
);
"""

ERASED_MARKER = "[CONTENT ERASED]"
"""What a reader sees instead of the text. A distinct marker rather than an empty
string, so "erased" and "was always blank" stay different facts."""


@dataclass(frozen=True)
class ErasureRecord:
    memory_id: str
    erased: bool
    reason: str
    erased_ms: int | None

    def to_json(self) -> dict[str, Any]:
        return {
            "memory_id": self.memory_id,
            "erased": self.erased,
            "reason": self.reason,
            "erased_ms": self.erased_ms,
        }


class ContentVault:
    """Per-memory content keys, kept beside the log but never in it.

    Lives in the same SQLite file for the same reason the outbox does — a single
    transactional boundary — but in its own table, so a deployment that wants
    the keys elsewhere can move one table rather than re-architect. That matters
    because keys in the same file as the ciphertext is the weakest defensible
    arrangement: it protects against *erasure* being impossible, not against
    someone who has the file.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        with self._conn:
            self._conn.executescript(_SCHEMA)

    def key_for(self, memory_id: str, now_ms: int) -> bytes | None:
        """The memory's content key, minting one if absent.

        Returns None when the key has been destroyed — the caller must then
        treat the content as gone rather than falling back to plaintext.
        """
        row = self._conn.execute(
            "SELECT key_material, erased_ms FROM content_keys WHERE memory_id = ?",
            (memory_id,),
        ).fetchone()
        if row is not None:
            if row["erased_ms"] is not None:
                return None
            return bytes(row["key_material"])
        material = secrets.token_bytes(32)
        self._conn.execute(
            "INSERT INTO content_keys (memory_id, key_material, created_ms) VALUES (?, ?, ?)",
            (memory_id, material, now_ms),
        )
        return material

    def erase(self, memory_id: str, reason: str, now_ms: int) -> bool:
        """Destroy the key. Irreversible by design.

        Overwrites the material with NULL rather than deleting the row, so the
        *fact* of erasure, its reason and its time remain auditable. A deleted
        row would make an erased memory indistinguishable from one that never
        had a key.
        """
        row = self._conn.execute(
            "SELECT erased_ms FROM content_keys WHERE memory_id = ?", (memory_id,)
        ).fetchone()
        if row is None:
            # Nothing was ever encrypted under this id. Record the request
            # anyway: "we were asked and there was nothing to erase" is a
            # different audit answer from silence.
            self._conn.execute(
                "INSERT INTO content_keys (memory_id, key_material, created_ms, "
                "erased_ms, reason) VALUES (?, NULL, ?, ?, ?)",
                (memory_id, now_ms, now_ms, reason),
            )
            return False
        if row["erased_ms"] is not None:
            return False
        self._conn.execute(
            "UPDATE content_keys SET key_material = NULL, erased_ms = ?, reason = ? "
            "WHERE memory_id = ?",
            (now_ms, reason, memory_id),
        )
        return True

    def status(self, memory_id: str) -> ErasureRecord:
        row = self._conn.execute(
            "SELECT erased_ms, reason FROM content_keys WHERE memory_id = ?",
            (memory_id,),
        ).fetchone()
        if row is None:
            return ErasureRecord(memory_id, erased=False, reason="", erased_ms=None)
        return ErasureRecord(
            memory_id=memory_id,
            erased=row["erased_ms"] is not None,
            reason=row["reason"] or "",
            erased_ms=row["erased_ms"],
        )

    def erased_ids(self) -> set[str]:
        return {
            row["memory_id"]
            for row in self._conn.execute(
                "SELECT memory_id FROM content_keys WHERE erased_ms IS NOT NULL"
            )
        }


def seal(content: str, key: bytes) -> str:
    """Encrypt content for storage in the log.

    A keyed stream cipher built from HMAC-SHA256 in counter mode, because the
    core is zero-dependency and the standard library has no AEAD. This is a
    deliberate, documented limitation: it gives confidentiality against someone
    without the key and **no integrity guarantee of its own** — the append-only
    log and the event digests provide that. A deployment that needs AEAD should
    install `cryptography` and swap this function; the vault's interface does
    not change.
    """
    nonce = os.urandom(16)
    stream = _keystream(key, nonce, len(content.encode("utf-8")))
    sealed = bytes(a ^ b for a, b in zip(content.encode("utf-8"), stream))
    return "enc:v1:" + nonce.hex() + ":" + sealed.hex()


def unseal(sealed: str, key: bytes | None) -> str:
    """Decrypt, or return the marker when the key is gone."""
    if not sealed.startswith("enc:v1:"):
        return sealed  # written before encryption was enabled
    if key is None:
        return ERASED_MARKER
    _, _, nonce_hex, payload_hex = sealed.split(":", 3)
    nonce = bytes.fromhex(nonce_hex)
    payload = bytes.fromhex(payload_hex)
    stream = _keystream(key, nonce, len(payload))
    return bytes(a ^ b for a, b in zip(payload, stream)).decode("utf-8", "replace")


def is_sealed(content: str) -> bool:
    return content.startswith("enc:v1:")


def _keystream(key: bytes, nonce: bytes, length: int) -> bytes:
    out = bytearray()
    counter = 0
    while len(out) < length:
        block = hmac.new(
            key, nonce + counter.to_bytes(8, "big"), hashlib.sha256
        ).digest()
        out.extend(block)
        counter += 1
    return bytes(out[:length])
