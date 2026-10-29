"""Federation: offers recorded, retractions requested, received and forwarded, and hostile-source notices.

A service mixin of `Amberlog`, built on `FabricCore`. Methods moved here
verbatim from `fabric.py`.
"""

from __future__ import annotations

__stability__ = "stable"



from typing import TYPE_CHECKING, Sequence, cast

if TYPE_CHECKING:
    from ..fabric import Amberlog  # noqa: F401
    from ..protocol import SourceNotice  # pragma: no cover

from .. import events as ev
import hashlib

from ..outbox import now_ms as _now_ms
from ..protocol import (
    MAX_HOPS,
    Acknowledgement,
    PropagationState,
    RejectionCode,
    Retraction,
    new_retraction_id,
)
from ..model import (
    LifecycleState,
    ProvenanceMethod,
    WithdrawalBasis,
)


from .core import FabricCore
from .common import PolicyViolation, iso_timestamp, _fresh


class FederationMixin(FabricCore):

    # --- durable retraction protocol -------------------------------------

    @_fresh
    def request_retraction(
        self,
        memory_id: str,
        reason: str,
        recipients: Sequence[str],
        actor: str = "operator",
        basis: str | WithdrawalBasis | None = None,
    ) -> Retraction:
        """Quarantine locally **and** durably record that the retraction is owed
        to each recipient — in one transaction.

        This is what `propagate_retraction` could not do. That function
        committed the local quarantine and then looped over live target objects
        in the same call, so a crash in between lost the dispatch with no record
        that it was owed. Here the `RetractionRequested` event and the outbox
        rows commit together, so a crash leaves the intent recorded and a
        dispatcher picks it up (invariant 3).

        Returns the `Retraction` for dispatch. It names an **exact version**:
        matching on the memory id alone would withdraw an import of v3 on a
        retraction of v1.
        """
        memory = self._require(memory_id)
        retraction = Retraction(
            retraction_id=new_retraction_id(),
            origin_store_id=self.store_id,
            origin_memory_id=memory_id,
            origin_memory_version=memory.version,
            origin_sequence=self.state.origin_sequence + 1,
            reason_code=(
                basis.value if isinstance(basis, WithdrawalBasis) else basis
            ) or WithdrawalBasis.UNSTATED.value,
            requested_by=actor,
            issued_at=iso_timestamp(self.now()),
        )

        with self._transaction():
            self.quarantine(memory_id, reason=reason, actor=actor, basis=basis)
            self._emit(
                ev.retraction_requested(
                    ts=self.now(),
                    retraction_id=retraction.retraction_id,
                    origin_store_id=retraction.origin_store_id,
                    origin_memory_id=retraction.origin_memory_id,
                    origin_memory_version=retraction.origin_memory_version,
                    origin_sequence=retraction.origin_sequence,
                    reason_code=retraction.reason_code,
                    recipients=list(recipients),
                    requested_by=actor,
                )
            )
            self.outbox.enqueue(retraction, recipients, _now_ms())
        return retraction

    @_fresh
    def discredit_source(self, author: str, actor: str, signal: str = "hostile",
                         reason_code: str = "injection_screen") -> "SourceNotice":
        """Record that a local source was caught being hostile; return the notice for peers.

        Idempotent per (author, signal). The notice goes to the stores that
        hold this author's shared memories (`notice_recipients`), and the
        background manager sends it (`manager.py`).
        """
        from ..protocol import SOURCE_SIGNALS, SourceNotice

        if signal not in SOURCE_SIGNALS:
            raise PolicyViolation(f"signal must be one of {SOURCE_SIGNALS}")
        notice_id = "sn_" + hashlib.sha256(
            f"{self.store_id}/{author}/{signal}".encode()).hexdigest()[:26]
        if not any(e.payload.get("notice_id") == notice_id
                   for e in self.log.read_types([ev.EventType.SOURCE_DISCREDITED])):
            self._emit(ev.source_discredited(ts=self.now(), author_ref=author, signal=signal,
                                             origin_store_id=self.store_id,
                                             notice_id=notice_id, reason_code=reason_code,
                                             actor=actor))
        return SourceNotice(notice_id=notice_id, origin_store_id=self.store_id, author=author,
                            signal=signal, reason_code=reason_code,
                            issued_at=iso_timestamp(self.now()))

    @_fresh
    def notice_recipients(self, author: str) -> list[str]:
        """Stores holding a memory this author wrote here and shared."""
        out: set[str] = set()
        for memory_id, recipients in self.state.shared_to.items():
            memory = self.state.memories.get(memory_id)
            if memory is not None and memory.provenance.created_by == author:
                out.update(recipients)
        return sorted(out)

    @_fresh
    def receive_notice(self, notice: "SourceNotice", sender_authorised: bool = True) -> bool:
        """Record a peer's signed notice. Idempotent. Returns whether it was accepted."""
        author_ref = f"{notice.origin_store_id}/{notice.author}"
        seen = any(e.payload.get("notice_id") == notice.notice_id
                   and e.payload.get("authorised")
                   for e in self.log.read_types([ev.EventType.SOURCE_DISCREDITED]))
        if seen:
            return True
        self._emit(ev.source_discredited(ts=self.now(), author_ref=author_ref,
                                         signal=notice.signal,
                                         origin_store_id=notice.origin_store_id,
                                         notice_id=notice.notice_id,
                                         reason_code=notice.reason_code,
                                         actor=notice.origin_store_id,
                                         authorised=sender_authorised))
        return sender_authorised

    @_fresh
    def supersede_copies(self, memory_id: str, actor: str) -> list[Retraction]:
        """Owe every store holding an older version's copy a retraction of that version.

        A revision changed nothing in the stores that held a copy: only
        retractions travel, and offering the new version left the old import
        active beside it (found by G4; research direction S1). This is the
        correction half: for each store that was sent an older version, a
        retraction of **that version only** -- `contradicted`, with
        `evidence_reference` naming the version that replaced it -- through the
        same outbox, transport and dispatcher as any retraction. The origin's
        own current version is not withdrawn. A recipient withdraws exactly the
        copy of that version (supersession is per memory and version, F11), and
        its conclusions built on that copy are re-checked like any retraction's.

        Offering the current version is the host's step, as every share is
        (`federation.offer`). Idempotent: a (version, store) already owed is not
        owed twice. Returns the retractions, one per superseded version.
        """
        memory = self._require(memory_id)
        held: dict[str, set[int]] = {}
        for event in self.log.read_types([ev.EventType.MEMORY_SHARED]):
            if event.payload.get("memory_id") == memory_id:
                held.setdefault(event.payload["recipient_store_id"], set()).add(
                    int(event.payload.get("version", 1)))
        already = {
            (int(e.payload.get("origin_memory_version", 0)), recipient)
            for e in self.log.read_types([ev.EventType.RETRACTION_REQUESTED])
            if e.payload.get("origin_memory_id") == memory_id
            for recipient in e.payload.get("recipients") or ()
        }
        owed: dict[int, list[str]] = {}
        for recipient, versions in sorted(held.items()):
            for version in sorted(versions):
                if version < memory.version and (version, recipient) not in already:
                    owed.setdefault(version, []).append(recipient)
        out: list[Retraction] = []
        with self._transaction():
            for version, recipients in sorted(owed.items()):
                retraction = Retraction(
                    retraction_id=new_retraction_id(),
                    origin_store_id=self.store_id,
                    origin_memory_id=memory_id,
                    origin_memory_version=version,
                    origin_sequence=self.state.origin_sequence + 1,
                    reason_code=WithdrawalBasis.CONTRADICTED.value,
                    requested_by=actor,
                    issued_at=iso_timestamp(self.now()),
                    evidence_reference=f"superseded by version {memory.version}",
                )
                self._emit(ev.retraction_requested(
                    ts=self.now(), retraction_id=retraction.retraction_id,
                    origin_store_id=retraction.origin_store_id,
                    origin_memory_id=memory_id, origin_memory_version=version,
                    origin_sequence=retraction.origin_sequence,
                    reason_code=retraction.reason_code, recipients=recipients,
                    requested_by=actor))
                self.outbox.enqueue(retraction, recipients, _now_ms())
                out.append(retraction)
        return out

    @_fresh
    def record_share(
        self,
        memory_id: str,
        recipient_store_id: str,
        imported_memory_id: str,
        actor: str = "federation",
    ) -> None:
        """Record that `memory_id` left this store for `recipient_store_id`.

        The forwarding table a transitive retraction walks. `federation.offer`
        calls this on every accepted offer, so a store that re-shares an import
        knows who else now holds it.

        Not derivable after the fact: the recipient's copy is a new memory in
        the recipient's log with its own id, and nothing in the sender's log
        mentioned it until this event existed. Phase B worked without it only
        because its recipients never re-shared, which made the origin exactly
        one hop from every copy in the federation.
        """
        memory = self._require(memory_id)
        self._emit(
            ev.memory_shared(
                ts=self.now(),
                memory_id=memory_id,
                version=memory.version,
                recipient_store_id=recipient_store_id,
                imported_memory_id=imported_memory_id,
                actor=actor,
            )
        )

    @_fresh
    def shared_with(self, memory_id: str) -> dict[str, str]:
        """Which stores hold a copy of this memory, and what they call it."""
        return dict(self.state.shared_to.get(memory_id, {}))

    @_fresh
    def receive_retraction(
        self, retraction: Retraction, sender_authorised: bool = True
    ) -> Acknowledgement:
        """Apply a retraction arriving from another store, idempotently.

        The order is the one docs/PROTOCOL.md §5 specifies, and the ordering
        matters: deduplication comes before the version check so a replay gets
        the *first* outcome rather than a fresh verdict.

        Returns an acknowledgement of **committed** state only. `persisted`
        after the commit, `enforced` once the projections no longer expose the
        version. Acknowledging on receipt would be the most damaging lie
        available here.
        """
        at = iso_timestamp(self.now())

        def ack(state: PropagationState, detail: str = "", code: str | None = None):
            return Acknowledgement(
                retraction_id=retraction.retraction_id,
                recipient_store_id=self.store_id,
                state=state,
                at=at,
                # Per origin, not the log head. The head told every origin how
                # much this store did between two of its retractions, which is
                # none of its business (security review F13, measured by S5).
                # A count of this origin's applied retractions still regresses
                # when the store is restored from an older backup, which is
                # what the field is for.
                state_revision=self.outbox.inbox_count(retraction.origin_store_id),
                origin_sequence_seen=self.outbox.cursor_for(retraction.origin_store_id),
                detail=detail,
                rejection_code=code,
            )

        if not sender_authorised:
            self._emit(
                ev.retraction_rejected(
                    ts=self.now(),
                    retraction_id=retraction.retraction_id,
                    origin_store_id=retraction.origin_store_id,
                    rejection_code=RejectionCode.UNAUTHORIZED.value,
                    detail="sender not authorised for this destination",
                    actor=self.store_id,
                )
            )
            return ack(
                PropagationState.REJECTED,
                "sender not authorised",
                RejectionCode.UNAUTHORIZED.value,
            )

        # 4. Deduplicate on event identity, before anything else can change.
        previous = self.outbox.seen(retraction)
        if previous is not None:
            outcome, detail = previous
            state = {
                "applied": PropagationState.ENFORCED,
                "superseded": PropagationState.SUPERSEDED,
                "unknown_memory": PropagationState.REJECTED,
            }.get(outcome, PropagationState.REJECTED)
            return ack(state, f"duplicate: {outcome}")

        # 5. Supersession, per origin memory. It used to compare against one
        #    cursor per *origin store*, so a retraction delayed by an outage
        #    was discarded as "superseded" once a later retraction of a
        #    *different* memory had arrived first -- and the withdrawn memory
        #    stayed active here while the origin recorded the delivery as
        #    settled (docs/SECURITY_REVIEW.md F11). Stale means: a retraction of
        #    this same memory *and version* with a higher origin sequence was
        #    already applied. Version too, because a correction withdraws copies
        #    version by version, and a retraction of the v2 copy arriving before
        #    the one for the v1 copy must not discard it.
        cursor = self._latest_applied_sequence(retraction.origin_store_id,
                                               retraction.origin_memory_id,
                                               retraction.origin_memory_version)
        if cursor is not None and retraction.origin_sequence < cursor:
            with self._transaction():
                self.outbox.record_inbox(
                    retraction, "superseded", f"below cursor {cursor}", _now_ms()
                )
                self._emit(
                    ev.retraction_rejected(
                        ts=self.now(),
                        retraction_id=retraction.retraction_id,
                        origin_store_id=retraction.origin_store_id,
                        rejection_code=RejectionCode.VERSION_SUPERSEDED.value,
                        detail=f"origin_sequence {retraction.origin_sequence} below cursor {cursor}",
                        actor=self.store_id,
                    )
                )
            return ack(
                PropagationState.SUPERSEDED,
                f"below cursor {cursor}",
                RejectionCode.VERSION_SUPERSEDED.value,
            )

        targets = self._imports_of(retraction)
        if not targets:
            with self._transaction():
                self.outbox.record_inbox(retraction, "unknown_memory", "no import held", _now_ms())
                self.outbox.advance_cursor(
                    retraction.origin_store_id, retraction.origin_sequence
                )
            return ack(
                PropagationState.REJECTED,
                "no import of that memory version held here",
                RejectionCode.UNKNOWN_MEMORY.value,
            )

        # 6. Persist the event, the inbox record and the lifecycle change in one
        #    transaction. A crash between them is the window invariant 6 covers.
        with self._transaction():
            for local_id in targets:
                if self.get(local_id).lifecycle_state is not LifecycleState.QUARANTINED:
                    self.quarantine(
                        local_id,
                        reason=f"retracted at origin ({retraction.reason_code})",
                        actor=self.store_id,
                        basis=WithdrawalBasis.RETRACTED_AT_ORIGIN,
                    )
                self._emit(
                    ev.retraction_applied(
                        ts=self.now(),
                        retraction_id=retraction.retraction_id,
                        origin_store_id=retraction.origin_store_id,
                        origin_memory_id=retraction.origin_memory_id,
                        origin_memory_version=retraction.origin_memory_version,
                        local_memory_id=local_id,
                        actor=self.store_id,
                    )
                )
            forwarded = self._forward_retraction(retraction, targets)
            self.outbox.record_inbox(
                retraction, "applied", f"{len(targets)} memory/ies", _now_ms()
            )
            self.outbox.advance_cursor(
                retraction.origin_store_id, retraction.origin_sequence
            )

        # 7. Projections already reflect it: `quarantine` emitted through the
        #    same projection fold, and `_eligible_ids` reads lifecycle state, so
        #    the version is no longer exposed. Hence `enforced`, not `persisted`.
        # No counts: how many copies this store held and how many peers it
        # re-shared to are its own sharing graph, and went to every origin
        # (F13). Both stay in this store's log.
        del forwarded
        return ack(PropagationState.ENFORCED, "withdrawn")

    def _latest_applied_sequence(self, origin_store_id: str, origin_memory_id: str,
                                 origin_memory_version: int) -> int | None:
        """The highest origin sequence of a retraction of this memory version applied here."""
        applied = {
            e.payload["retraction_id"]
            for e in self.log.read_types([ev.EventType.RETRACTION_APPLIED])
            if e.payload.get("origin_store_id") == origin_store_id
            and e.payload.get("origin_memory_id") == origin_memory_id
            and int(e.payload.get("origin_memory_version", 0)) == int(origin_memory_version)
        }
        return self.outbox.max_inbox_sequence(origin_store_id, applied) if applied else None

    def _forward_retraction(
        self, retraction: Retraction, targets: Sequence[str]
    ) -> int:
        """Owe the same retraction onward to everyone this store re-shared to.

        **Called inside the caller's transaction**, so the onward intent commits
        with the local withdrawal. A store that applied a retraction and then
        crashed before recording what it owed would leave copies downstream that
        nothing was tracking — the same gap `request_retraction` closed at the
        origin, one hop out.

        Three things keep this terminating, and each is load-bearing:

        * the campaign identity `(origin_store_id, retraction_id)` is preserved,
          so a recipient recognises a copy it has already handled;
        * the *target* is retargeted per hop, so the inbox deduplicates per copy
          rather than per campaign, and a finite federation holds finitely many
          copies;
        * `MAX_HOPS` is a backstop, not the defence. Reaching it is a bug, so it
          records a rejection rather than failing quietly.
        """
        if retraction.hop >= MAX_HOPS:
            self._emit(
                ev.retraction_rejected(
                    ts=self.now(),
                    retraction_id=retraction.retraction_id,
                    origin_store_id=retraction.origin_store_id,
                    rejection_code=RejectionCode.HOP_LIMIT.value,
                    detail=f"hop limit {MAX_HOPS} reached; not forwarding further",
                    actor=self.store_id,
                )
            )
            return 0

        count = 0
        for local_id in targets:
            recipients = [
                store
                for store in self.state.shared_to.get(local_id, {})
                # Never back to the store that just told us. Not a correctness
                # requirement — dedup would absorb it — but one pointless round
                # trip per hop, per peer, is worth not making.
                if store != (retraction.forwarded_by or retraction.origin_store_id)
            ]
            if not recipients:
                continue
            onward = retraction.forward(
                from_store_id=self.store_id,
                local_memory_id=local_id,
                local_version=self.get(local_id).version,
            )
            self._emit(
                ev.retraction_requested(
                    ts=self.now(),
                    retraction_id=onward.retraction_id,
                    origin_store_id=onward.origin_store_id,
                    origin_memory_id=onward.origin_memory_id,
                    origin_memory_version=onward.origin_memory_version,
                    origin_sequence=onward.origin_sequence,
                    reason_code=onward.reason_code,
                    recipients=recipients,
                    requested_by=self.store_id,
                )
            )
            count += self.outbox.enqueue(onward, recipients, _now_ms())
        return count

    @_fresh
    def retractions_since(self, sequence: int) -> list[Retraction]:
        """Every retraction this store has issued above `sequence`.

        What an origin replays when a recipient reconnects and says where it got
        to. Read from the event log rather than from a cache, because the log is
        the source of truth and a cache would be one more thing that can be
        stale after a restore.
        """
        out: list[Retraction] = []
        for event in self.log.read():
            if event.type != ev.EventType.RETRACTION_REQUESTED:
                continue
            payload = event.payload
            if int(payload.get("origin_sequence", 0)) <= sequence:
                continue
            out.append(
                Retraction(
                    retraction_id=payload["retraction_id"],
                    origin_store_id=payload["origin_store_id"],
                    origin_memory_id=payload["origin_memory_id"],
                    origin_memory_version=int(payload["origin_memory_version"]),
                    origin_sequence=int(payload["origin_sequence"]),
                    reason_code=payload["reason_code"],
                    requested_by=payload["requested_by"],
                    issued_at=iso_timestamp(event.ts),
                    evidence_digest=payload.get("evidence_digest"),
                )
            )
        out.sort(key=lambda r: r.origin_sequence)
        return out

    def _imports_of(self, retraction: Retraction) -> list[str]:
        """Local memories imported from the retraction's **target** version.

        Matching on store and id was the old behaviour; adding the version is
        what stops a retraction of v1 withdrawing an import of v3.

        The target is the *hop's* target, which for a direct retraction is the
        origin and for a forwarded one is the store that passed it on. A store
        two hops from the origin never imported from the origin, so matching on
        the origin fields would find nothing and the retraction would stop one
        hop short — silently, with an acknowledgement saying "no import held".
        """
        from ..federation import imported_from

        found: list[str] = []
        for memory_id in self.state.memories:
            # Provenance method, not just the origin record. A memory *derived*
            # locally from an import inherits the parent's context, origin key
            # included, so it looks like a second copy of the imported memory.
            # Without this check a recipient's own conclusions were quarantined
            # outright instead of having their support recomputed — which is
            # exactly the "withdrawing unrelated useful knowledge" failure the
            # project exists to prevent. `descendants_of` carries the same
            # guard for the same reason; the deterministic fault matrix caught
            # this one (scenario `derived_conclusion_at_recipient`).
            if self.state.memories[memory_id].provenance.method is not ProvenanceMethod.IMPORTED:
                continue
            origin = imported_from(cast("Amberlog", self), memory_id)
            if origin is None:
                continue
            if origin.get("store") != retraction.applies_to_store:
                continue
            if origin.get("memory_id") != retraction.applies_to_memory:
                continue
            version = origin.get("version")
            if version is not None and int(version) != retraction.applies_to_version:
                continue
            found.append(memory_id)
        return found
