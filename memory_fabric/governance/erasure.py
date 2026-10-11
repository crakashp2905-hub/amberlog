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

**Where the keys live is a deployment choice, not a fixed fact.** The default
`SqliteKeyProvider` keeps them in their own table in the same file, which is
the weakest defensible arrangement: it makes erasure *possible* and does
nothing against someone holding the file. `DirectoryKeyProvider` and
`CallbackKeyProvider` move them out — to a directory with its own permissions,
or to a KMS behind a callable. Erasure then means asking the provider to
destroy, which a provider may be unable to do; `supports_destroy` says so
rather than letting a caller believe an erasure happened that did not.

The cipher itself is in `cipher.py`, including why `enc:v1` was replaced.
"""

from __future__ import annotations

import secrets
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Protocol

from ..txn import transaction
from .cipher import IntegrityError, default_suite, is_sealed, suite_for

_SCHEMA = """
CREATE TABLE IF NOT EXISTS content_keys (
    memory_id   TEXT PRIMARY KEY,
    key_material BLOB,
    created_ms  INTEGER NOT NULL,
    erased_ms   INTEGER,
    reason      TEXT NOT NULL DEFAULT ''
);
"""

class KeyUnavailable(Exception):
    """A key that should exist cannot be retrieved.

    Distinct from erasure, and the distinction is load-bearing: erasure is
    expected and recorded, while a missing key store is an operational fault.
    Returning the erased marker for this would tell an operator their data was
    deliberately destroyed when in fact they mounted the wrong volume.
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


class KeyProvider(Protocol):
    """Where content keys live.

    Separated from `ContentVault` because "what does erasure mean" and "who
    holds the key" are different questions with different answers per
    deployment, and the vault was quietly answering both.
    """

    supports_destroy: bool
    """Whether destroying a key here actually destroys it.

    False for a provider that can only *stop handing out* a key — a KMS the
    store cannot delete from, for instance. `erase_content` reports this rather
    than letting a caller believe an erasure reached further than it did, which
    for a subject-access request is the difference between a true answer and a
    false one.
    """

    def get(self, memory_id: str) -> bytes | None: ...

    def create(self, memory_id: str) -> bytes: ...

    def destroy(self, memory_id: str) -> bool: ...


class SqliteKeyProvider:
    """Keys in their own table in the store's own file. The default.

    Honest about what it is: the weakest defensible arrangement, because the
    keys sit beside the ciphertext. It makes erasure possible and does nothing
    against someone holding the file. Chosen as the default anyway because it
    needs no configuration and a store with no key management at all would make
    erasure cosmetic — see the bug that produced `_seal_content`.
    """

    supports_destroy = True

    def __init__(self, conn: sqlite3.Connection, now_ms: Callable[[], int]) -> None:
        self._conn = conn
        self._now_ms = now_ms

    def get(self, memory_id: str) -> bytes | None:
        row = self._conn.execute(
            "SELECT key_material, erased_ms FROM content_keys WHERE memory_id = ?",
            (memory_id,),
        ).fetchone()
        if row is None or row["erased_ms"] is not None or row["key_material"] is None:
            return None
        return bytes(row["key_material"])

    def create(self, memory_id: str) -> bytes:
        """Upsert the material onto the vault's audit row.

        An upsert rather than an insert because the vault owns that row — it is
        the erasure record and exists whether or not the key material is in
        this file — and this provider happens to keep the material in the same
        row's `key_material` column. Two inserts for one id was the first
        version of this split and it failed on the UNIQUE constraint
        immediately.
        """
        material = secrets.token_bytes(32)
        self._conn.execute(
            "INSERT INTO content_keys (memory_id, key_material, created_ms) "
            "VALUES (?, ?, ?) "
            "ON CONFLICT(memory_id) DO UPDATE SET key_material = excluded.key_material",
            (memory_id, material, self._now_ms()),
        )
        return material

    def destroy(self, memory_id: str) -> bool:
        cursor = self._conn.execute(
            "UPDATE content_keys SET key_material = NULL "
            "WHERE memory_id = ? AND key_material IS NOT NULL",
            (memory_id,),
        )
        return cursor.rowcount > 0


class DirectoryKeyProvider:
    """Keys as files in a directory outside the database.

    The cheapest arrangement that is not "keys beside the ciphertext": point it
    at a directory with its own ownership and mode, on a different volume or
    under different credentials from the store, and a copy of the `.db` file is
    no longer sufficient to read content.

    Destroying a key unlinks its file. That is as real as the filesystem makes
    it — on a copy-on-write filesystem, a snapshotted volume or an SSD without
    TRIM, the bytes may survive the unlink, which is a property of the storage
    and not something this class can promise away.
    """

    supports_destroy = True

    def __init__(self, directory: str | Path) -> None:
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)

    def _path(self, memory_id: str) -> Path:
        # The id is a ULID from this process, but it arrives as a string and a
        # separator in it would write outside the directory.
        if not memory_id.isalnum():
            raise ValueError(f"refusing a non-alphanumeric key id: {memory_id!r}")
        return self.directory / f"{memory_id}.key"

    def get(self, memory_id: str) -> bytes | None:
        path = self._path(memory_id)
        if not path.exists():
            return None
        material = path.read_bytes()
        return material or None

    def create(self, memory_id: str) -> bytes:
        material = secrets.token_bytes(32)
        path = self._path(memory_id)
        # Written then moved, so a crash cannot leave a half-written key that
        # would decrypt to nothing while looking present.
        temporary = path.with_suffix(".key.tmp")
        temporary.write_bytes(material)
        temporary.replace(path)
        return material

    def destroy(self, memory_id: str) -> bool:
        path = self._path(memory_id)
        if not path.exists():
            return False
        path.unlink()
        return True


class CallbackKeyProvider:
    """Keys from a callable: a KMS, a secrets manager, an HSM wrapper.

    `destroy` is optional. A provider that cannot delete passes nothing and
    declares `supports_destroy = False`, and the erasure record then says the
    key was not destroyed here. A store that reported a successful erasure it
    could not perform would be worse than one that cannot erase at all.
    """

    def __init__(
        self,
        fetch: Callable[[str], bytes | None],
        create: Callable[[str], bytes],
        destroy: Callable[[str], bool] | None = None,
    ) -> None:
        self._fetch = fetch
        self._create = create
        self._destroy = destroy
        self.supports_destroy = destroy is not None

    def get(self, memory_id: str) -> bytes | None:
        return self._fetch(memory_id)

    def create(self, memory_id: str) -> bytes:
        return self._create(memory_id)

    def destroy(self, memory_id: str) -> bool:
        return self._destroy(memory_id) if self._destroy is not None else False


class ContentVault:
    """The *record* of which content is erased, and when, and why.

    Key custody is delegated to a `KeyProvider`, because where keys live is a
    deployment choice while the erasure record is not: the `content_keys` table
    always holds the audit row — created, erased, reason — even when the key
    material itself is in a directory or a KMS and was never in this file.

    Keeping the row after erasure is deliberate. A deleted row would make an
    erased memory indistinguishable from one that never had a key, and
    "we were asked and there was nothing to erase" is a different audit answer
    from silence.
    """

    def __init__(
        self,
        conn: sqlite3.Connection,
        keys: "KeyProvider | None" = None,
        now_ms: Callable[[], int] | None = None,
    ) -> None:
        self._conn = conn
        # NOT wrapped in `transaction()`: `executescript` issues its own
        # COMMIT before running, which would end ours and leave the
        # context manager committing a transaction that no longer exists.
        # Safe unwrapped because every statement is `IF NOT EXISTS` and,
        # with `isolation_level=None`, each autocommits.
        self._conn.executescript(_SCHEMA)
        clock = now_ms or (lambda: 0)
        self.keys: KeyProvider = keys or SqliteKeyProvider(conn, clock)

    @property
    def supports_destroy(self) -> bool:
        return bool(getattr(self.keys, "supports_destroy", True))

    def key_for(self, memory_id: str, now_ms: int) -> bytes | None:
        """The memory's content key, minting one if absent.

        Returns None when the key has been destroyed — the caller must then
        treat the content as gone rather than falling back to plaintext.

        The erasure *row* is consulted first and is authoritative over the
        provider. An external provider that still returns material for an
        erased memory — a KMS that could not delete, a restored key directory —
        must not resurrect readable content behind the audit record that says
        it is gone.
        """
        row = self._conn.execute(
            "SELECT erased_ms FROM content_keys WHERE memory_id = ?",
            (memory_id,),
        ).fetchone()
        if row is not None:
            if row["erased_ms"] is not None:
                return None
            existing = self.keys.get(memory_id)
            if existing is not None:
                return existing
            # A row with no retrievable key: the provider lost it, or a store
            # was copied without its key directory. Not erasure, and not
            # something to paper over by minting a fresh key, which would make
            # existing ciphertext permanently undecryptable *and* look fine.
            raise KeyUnavailable(
                f"{memory_id} has a content key recorded but the provider "
                f"({type(self.keys).__name__}) does not have it. The key store "
                "is missing or not the one this database was written with."
            )
        # The audit row first, then the material. The row is this class's
        # responsibility and exists even when the key never touches this file;
        # the provider fills in `key_material` only if that is where it keeps
        # it. Ordered this way so a provider failure leaves no audit row
        # claiming a key was created.
        self._conn.execute(
            "INSERT INTO content_keys (memory_id, key_material, created_ms) "
            "VALUES (?, NULL, ?) ON CONFLICT(memory_id) DO NOTHING",
            (memory_id, now_ms),
        )
        return self.keys.create(memory_id)

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
        # The provider first, then the record. If destroying the key fails, the
        # record must not claim it succeeded — so the exception propagates and
        # the caller's transaction rolls back rather than leaving an audit row
        # asserting an erasure that did not happen.
        destroyed = self.keys.destroy(memory_id)
        self._conn.execute(
            "UPDATE content_keys SET key_material = NULL, erased_ms = ?, reason = ? "
            "WHERE memory_id = ?",
            (now_ms, reason if destroyed else f"{reason} [key not destroyed by provider]",
             memory_id),
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


def seal(content: str, key: bytes, aad: bytes) -> str:
    """Encrypt content for storage in the log, authenticated.

    Delegates to `cipher.default_suite()`: AES-256-GCM when `cryptography` is
    installed, otherwise HMAC-CTR encrypt-then-MAC. `aad` binds the ciphertext
    to a store, memory and version, so an authentic ciphertext cannot be moved
    somewhere it does not belong — see `cipher.associated_data`.
    """
    return default_suite().seal(content.encode("utf-8"), key, aad)


def unseal(sealed: str, key: bytes | None, aad: bytes) -> str:
    """Decrypt, or return the marker when the key is gone.

    Raises `IntegrityError` when a ciphertext fails authentication. It does not
    return a marker for that case, and the distinction is the whole point: a
    missing key is an erasure that was recorded and is expected, while a failed
    tag means someone changed bytes they should not have. Collapsing the two
    would file a tamper under "working as intended".
    """
    if not is_sealed(sealed):
        return sealed  # written before encryption was enabled
    if key is None:
        return ERASED_MARKER
    plaintext = suite_for(sealed).unseal(sealed, key, aad)
    try:
        return plaintext.decode("utf-8")
    except UnicodeDecodeError as exc:
        # For v2/v3 the tag has already verified, so this is a genuine encoding
        # fault. For legacy v1 there is no tag at all, and a failed decode is
        # the *only* signal available that the key is wrong or the bytes were
        # edited — which is exactly why v1 was replaced. Either way it is an
        # integrity failure and not something to hand back as content: the old
        # code decoded with errors="replace" and let mojibake travel into an
        # agent's context as if it were a remembered fact.
        raise IntegrityError(
            f"decrypted content is not valid UTF-8 ({exc}). For legacy enc:v1 "
            "this usually means the wrong key or edited bytes; v1 has no "
            "authentication tag, so nothing else can tell you."
        ) from None
