"""Content encryption and crypto-erasure: sealing, unsealing, the associated data, and erasure's scope and status.

A service mixin of `MemoryFabric`, built on `FabricCore`. Methods moved here
verbatim from `fabric.py`.
"""

from __future__ import annotations

__stability__ = "stable"



from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from ..fabric import MemoryFabric  # noqa: F401
    pass

from .. import events as ev

from ..governance.cipher import associated_data, is_sealed
from ..governance.erasure import (
    ERASED_MARKER,
    seal,
    unseal,
)
from ..outbox import now_ms as _now_ms


from .core import FabricCore
from .common import PolicyViolation, _fresh


class SealingMixin(FabricCore):

    def _unseal_content(self, content: str, memory_id: str, version: int = 1) -> str:
        """Decrypt on the way out of the log, or report erasure.

        Text written before encryption existed passes through untouched, which
        is what keeps a 0.2.0 log replayable.

        A failed authentication raises rather than returning anything. The
        previous cipher could not fail — it had no tag — and decoded with
        `errors="replace"`, so tampered bytes became mojibake inside a
        `Memory.content` and travelled into an agent's context as if they were
        remembered facts.
        """
        if not is_sealed(content):
            return content
        return unseal(
            content,
            self.vault.key_for(memory_id, self.now()),
            self._content_aad(memory_id, version),
        )

    def _seal_content(self, content: str, memory_id: str, version: int = 1) -> str:
        """Encrypt on the way into the log, when the store is configured to.

        Without this, `erase_content` destroys a key that was never used and the
        plaintext stays in the event log — which would make erasure cosmetic
        rather than real. Found by actually erasing something and reading the
        log back.
        """
        if not self.encrypt_content:
            return content
        key = self.vault.key_for(memory_id, self.now())
        if key is None:
            # The key was destroyed. Falling back to plaintext here would store
            # readable content for a memory whose content was erased — and
            # unsealed, so a later erasure could not reach it either. Refuse.
            raise PolicyViolation(
                f"{memory_id} has been content-erased; its content cannot be "
                "written again. Record new information as a new memory."
            )
        return seal(content, key, self._content_aad(memory_id, version))

    def _content_aad(self, memory_id: str, version: int) -> bytes:
        """The associated data a content ciphertext is bound to.

        Raises rather than substituting a placeholder when the store has no
        identity: sealing under `""` and later unsealing under a real id would
        fail authentication on every read, and the failure would look like
        tampering instead of like the configuration error it is.
        """
        store_id = self._sealing_store_id or self.state.store_id
        if store_id is None:
            raise PolicyViolation(
                "cannot seal or unseal content before this store has an "
                "identity; the StoreIdentified event is missing from the log"
            )
        return associated_data(store_id, memory_id, version)

    @_fresh
    def erase_content(
        self, memory_id: str, reason: str, actor: str = "operator"
    ) -> bool:
        """Destroy a memory's content key: crypto-erasure.

        Invariant 12. The event log is append-only and rewriting it to delete a
        memory's text would destroy the property everything else rests on — and
        a log you can edit to remove embarrassing entries is not an audit trail.
        But "it is in an immutable log" is not an answer to a subject asking for
        erasure, or to a leaked credential.

        So the content is encrypted per memory and the *key* is destroyed. Every
        event stays exactly as it was, every projection still replays, lineage
        and the propagation record are untouched, and the text is unrecoverable.

        Irreversible. Returns False when there was nothing to erase, which is
        recorded too: "we were asked and there was no content" is a different
        audit answer from silence.
        """
        self._require(memory_id)
        with self._transaction():
            had_content = self.vault.erase(memory_id, reason, _now_ms())
            self._emit(
                ev.content_erased(
                    ts=self.now(),
                    memory_id=memory_id,
                    reason=reason,
                    actor=actor,
                    had_content=had_content,
                )
            )
        # The index holds the plaintext too, so drop it or a search would still
        # surface the content the caller just erased. The copy index as well:
        # `_unindex` leaves it alone, so that withdrawn documents stay
        # recognisable, but its term set is derived from the erased text.
        self._unindex(memory_id)
        self.copy_index.remove(memory_id)
        # A summary written from this memory holds some of its text: erased too
        # (decay.py). Recursion ends, since a summary is never a summary's source.
        from ..decay import erase_summaries_of

        erase_summaries_of(cast("MemoryFabric", self), memory_id, actor)
        return had_content

    @_fresh
    def erasure_scope(self, memory_id: str) -> dict[str, Any]:
        """What an erasure reached, and what it provably did not.

        A subject-access request needs a truthful answer, and "the content is
        erased" is only true of the places this store controls. The honest
        answer has three parts, and the third is the one usually left out.

        **Reached**, and verified rather than asserted: the content key is
        destroyed, the event-log payload is ciphertext nobody can open, the
        search indexes no longer hold the terms, and the projection returns the
        marker.

        **Deliberately kept**: provenance, lineage, the retraction basis, the
        propagation record and the whole audit trail. An auditor can still
        answer "was this handled correctly?" about a memory nobody can read —
        that is the point rather than a shortfall.

        **Outside this store's reach**, and reported as unknown rather than
        guessed: backups taken before the key was destroyed still hold the
        ciphertext *and* the key; anything exported, logged, or sent to a model
        provider left before erasure existed; a federated copy at another store
        has its own key and must be erased there. `doctor` cannot see any of
        these, so neither can this.
        """
        memory = self._require(memory_id)
        record = self.vault.status(memory_id)
        sealed = is_sealed(
            next(
                (
                    (event.payload.get("memory") or {}).get("content", "")
                    for event in reversed(list(self.log.read()))
                    if event.type
                    in (
                        ev.EventType.MEMORY_CREATED,
                        ev.EventType.MEMORY_VERSIONED,
                    )
                    and (event.payload.get("memory") or {}).get("id") == memory_id
                ),
                "",
            )
        )
        shared = self.shared_with(memory_id)
        return {
            "memory_id": memory_id,
            "erased": record.erased,
            "reason": record.reason,
            "erased_at": record.erased_ms,
            "reached": {
                "content_key_destroyed": record.erased,
                "log_payload_is_ciphertext": sealed,
                "content_reads_as_marker": memory.content == ERASED_MARKER,
                "removed_from_vector_index": memory_id not in self.index._vectors,
                "removed_from_lexical_index": memory_id not in self.lexical._terms,
            },
            "kept_deliberately": [
                "provenance and the creating agent",
                "derivation lineage in both directions",
                "lifecycle history and the withdrawal basis",
                "the propagation record and every acknowledgement",
                "the erasure event itself, with its reason and time",
            ],
            "outside_this_store": {
                "backups_taken_before_erasure": "unknown — they hold both the "
                "ciphertext and the key; retention is an operational control",
                "exports_logs_and_model_traces": "unknown — anything that left "
                "this store is beyond crypto-erasure",
                "federated_copies": sorted(shared) or "none recorded",
                "federated_copies_note": "each recipient holds its own key and "
                "must erase independently; a retraction withdraws a copy from "
                "use but does not destroy its content",
            },
            "key_custody": type(self.vault.keys).__name__,
            "provider_can_destroy": self.vault.supports_destroy,
        }

    @_fresh
    def erasure_status(self, memory_id: str):
        return self.vault.status(memory_id)
