"""Phase 1 — the durable retraction protocol.

The roadmap's exit gate: committed retractions survive the defined crash
matrix; duplicate delivery has one semantic effect; acknowledgements never
overstate persistence or enforcement; conflicts are deterministic and auditable.

These are the three invariants the Phase 0 audit found *unimplementable* —
crash-safe retraction intent (3), acknowledgement states (5), and causal
ordering (7) — so this file is the first place they can be tested at all.

A crash is simulated the way it actually happens: the process stops between two
operations and a *new* `MemoryFabric` opens the same file. Nothing is mocked,
because the thing under test is whether the durable state is enough to recover.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from memory_fabric import LifecycleState, MemoryFabric, WithdrawalBasis
from memory_fabric.federation import offer
from memory_fabric.governance.firewall import (
    Firewall,
    rule_capabilities_must_be_granted,
    rule_must_be_active,
    rule_restricted_stays_private,
)
from memory_fabric.outbox import MAX_ATTEMPTS, now_ms
from memory_fabric.protocol import (
    Acknowledgement,
    PropagationState,
    ProtocolError,
    RejectionCode,
    Retraction,
    can_transition,
    evidence_digest,
    new_retraction_id,
    new_store_id,
)


def permissive() -> Firewall:
    return Firewall(
        rules=(
            rule_restricted_stays_private,
            rule_must_be_active,
            rule_capabilities_must_be_granted,
        )
    )


class ProtocolCase(unittest.TestCase):
    """An origin and a recipient, each a real store on disk, plus one import."""

    def setUp(self) -> None:
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.origin_path = str(Path(self.tmp.name) / "origin.db")
        self.recipient_path = str(Path(self.tmp.name) / "recipient.db")

        self.origin = MemoryFabric(self.origin_path, firewall=permissive())
        self.recipient = MemoryFabric(self.recipient_path, firewall=permissive())
        self.addCleanup(self._close)

        self.memory_id = self.origin.remember("ag_north", "E01 at coastal: swap the cable.")
        self.origin.validate(self.memory_id, actor="supervisor")
        result = offer(
            self.origin, self.memory_id, self.recipient, recipient_agent="ag_south"
        )
        self.assertTrue(result.accepted)
        self.imported_id = result.imported_memory_id
        self.recipient.validate(self.imported_id, actor="ag_south")

    def _close(self) -> None:
        for store in (self.origin, self.recipient):
            try:
                store.close()
            except Exception:
                pass

    def reopen_recipient(self) -> MemoryFabric:
        """Simulate a crash and restart of the recipient process."""
        self.recipient.close()
        self.recipient = MemoryFabric(self.recipient_path, firewall=permissive())
        return self.recipient


class TestStoreIdentity(ProtocolCase):
    def test_identity_is_opaque_and_not_a_path(self) -> None:
        for store in (self.origin, self.recipient):
            self.assertRegex(store.store_id, r"^st_[0-9A-HJKMNP-TV-Z]{26}$")
            self.assertNotIn("/", store.store_id)
            self.assertNotIn("\\", store.store_id)

    def test_two_stores_have_different_identities(self) -> None:
        """`log.path` gave every `:memory:` store the same identity, and two
        containers each holding `./store.db` were indistinguishable."""
        self.assertNotEqual(self.origin.store_id, self.recipient.store_id)

    def test_identity_survives_restart(self) -> None:
        before = self.recipient.store_id
        self.assertEqual(self.reopen_recipient().store_id, before)

    def test_an_import_records_the_origin_identity_and_version(self) -> None:
        from memory_fabric.federation import imported_from

        origin = imported_from(self.recipient, self.imported_id)
        self.assertEqual(origin["store"], self.origin.store_id)
        self.assertEqual(origin["version"], 1)


class TestDurability(ProtocolCase):
    """Invariant 3: a committed retraction cannot disappear because a process
    crashes before dispatch."""

    def test_the_intent_survives_a_crash_before_dispatch(self) -> None:
        retraction = self.origin.request_retraction(
            self.memory_id, reason="root cause was elsewhere",
            recipients=[self.recipient.store_id], actor="ag_north",
            basis=WithdrawalBasis.CONTRADICTED,
        )
        # Crash: nothing was ever dispatched.
        self.origin.close()
        reopened = MemoryFabric(self.origin_path, firewall=permissive())
        self.addCleanup(reopened.close)

        pending = reopened.outbox.pending()
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0].retraction_id, retraction.retraction_id)
        self.assertEqual(pending[0].recipient, self.recipient.store_id)
        self.assertEqual(pending[0].state, PropagationState.QUEUED)

    def test_the_local_quarantine_and_the_intent_commit_together(self) -> None:
        self.origin.request_retraction(
            self.memory_id, reason="r", recipients=[self.recipient.store_id],
            actor="ag_north", basis=WithdrawalBasis.CONTRADICTED,
        )
        self.origin.close()
        reopened = MemoryFabric(self.origin_path, firewall=permissive())
        self.addCleanup(reopened.close)
        self.assertEqual(
            reopened.get(self.memory_id).lifecycle_state, LifecycleState.QUARANTINED
        )
        self.assertEqual(len(reopened.outbox.pending()), 1)

    def test_a_retraction_names_an_exact_version(self) -> None:
        """Matching on the memory id alone would withdraw an import of v3 on a
        retraction of v1."""
        retraction = self.origin.request_retraction(
            self.memory_id, reason="r", recipients=[self.recipient.store_id],
            actor="ag_north",
        )
        self.assertEqual(retraction.origin_memory_version, 1)
        self.assertEqual(retraction.origin_store_id, self.origin.store_id)


class TestIdempotency(ProtocolCase):
    """Invariant 4, properly this time: deduplication by event identity rather
    than convergence on state."""

    def _retraction(self) -> Retraction:
        return self.origin.request_retraction(
            self.memory_id, reason="r", recipients=[self.recipient.store_id],
            actor="ag_north", basis=WithdrawalBasis.CONTRADICTED,
        )

    def test_one_event_delivered_a_hundred_times_has_one_effect(self) -> None:
        """Straight from the roadmap's test list."""
        retraction = self._retraction()
        acks = [self.recipient.receive_retraction(retraction) for _ in range(100)]

        self.assertTrue(all(a.state == PropagationState.ENFORCED for a in acks))
        self.assertTrue(all("duplicate" in a.detail for a in acks[1:]))

        applied = [
            e for e in self.recipient.log.read()
            if e.type == "RetractionApplied"
        ]
        self.assertEqual(len(applied), 1, "applied more than once")

    def test_a_replay_returns_the_first_outcome_not_a_fresh_verdict(self) -> None:
        retraction = self._retraction()
        first = self.recipient.receive_retraction(retraction)
        # Release it locally, so a *re-application* would be visible.
        self.recipient.release(self.imported_id, actor="reviewer")
        second = self.recipient.receive_retraction(retraction)

        self.assertEqual(second.state, first.state)
        self.assertEqual(
            self.recipient.get(self.imported_id).lifecycle_state,
            LifecycleState.CANDIDATE,
            "a replay re-applied the retraction instead of returning the first outcome",
        )

    def test_a_distinct_second_retraction_is_not_a_duplicate(self) -> None:
        """The thing state convergence cannot do: tell a replay from a genuinely
        new second retraction of the same memory."""
        first = self._retraction()
        self.recipient.receive_retraction(first)
        self.recipient.release(self.imported_id, actor="reviewer")
        self.recipient.validate(self.imported_id, actor="ag_south")

        second = Retraction(
            retraction_id=new_retraction_id(),
            origin_store_id=self.origin.store_id,
            origin_memory_id=self.memory_id,
            origin_memory_version=1,
            origin_sequence=first.origin_sequence + 1,
            reason_code=WithdrawalBasis.CONTRADICTED.value,
            requested_by="ag_north",
            issued_at=first.issued_at,
        )
        ack = self.recipient.receive_retraction(second)
        self.assertEqual(ack.state, PropagationState.ENFORCED)
        self.assertNotIn("duplicate", ack.detail)
        self.assertEqual(
            self.recipient.get(self.imported_id).lifecycle_state,
            LifecycleState.QUARANTINED,
        )

    def test_enqueuing_the_same_pair_twice_creates_one_delivery(self) -> None:
        retraction = self._retraction()
        self.assertEqual(
            self.origin.outbox.enqueue(
                retraction, [self.recipient.store_id], now_ms()
            ),
            0,
        )
        self.assertEqual(len(self.origin.outbox.pending()), 1)


class TestOrdering(ProtocolCase):
    """Invariant 7: a delayed older correction cannot blindly invalidate a newer
    independently validated version."""

    def test_a_retraction_below_the_cursor_is_superseded_not_applied(self) -> None:
        newer = Retraction(
            retraction_id=new_retraction_id(),
            origin_store_id=self.origin.store_id,
            origin_memory_id=self.memory_id,
            origin_memory_version=1,
            origin_sequence=50,
            reason_code=WithdrawalBasis.CONTRADICTED.value,
            requested_by="ag_north",
            issued_at="2026-10-10T12:00:00Z",
        )
        self.assertEqual(
            self.recipient.receive_retraction(newer).state, PropagationState.ENFORCED
        )
        self.recipient.release(self.imported_id, actor="reviewer")
        self.recipient.validate(self.imported_id, actor="ag_south")

        stale = Retraction(
            retraction_id=new_retraction_id(),
            origin_store_id=self.origin.store_id,
            origin_memory_id=self.memory_id,
            origin_memory_version=1,
            origin_sequence=10,
            reason_code=WithdrawalBasis.CONTRADICTED.value,
            requested_by="ag_north",
            issued_at="2026-10-10T11:00:00Z",
        )
        ack = self.recipient.receive_retraction(stale)
        self.assertEqual(ack.state, PropagationState.SUPERSEDED)
        self.assertEqual(ack.rejection_code, RejectionCode.VERSION_SUPERSEDED.value)
        self.assertEqual(
            self.recipient.get(self.imported_id).lifecycle_state,
            LifecycleState.ACTIVE,
            "a stale retraction invalidated a newer validated version",
        )

    def test_a_refusal_is_auditable(self) -> None:
        """An unauthorised or superseded retraction that left no trace would be
        indistinguishable from one that never arrived."""
        stale = Retraction(
            retraction_id=new_retraction_id(),
            origin_store_id=self.origin.store_id,
            origin_memory_id=self.memory_id,
            origin_memory_version=1,
            origin_sequence=0,
            reason_code="contradicted",
            requested_by="ag_north",
            issued_at="2026-10-10T11:00:00Z",
        )
        self.recipient.outbox.advance_cursor(self.origin.store_id, 99)
        self.recipient.receive_retraction(stale)
        rejected = [
            e for e in self.recipient.log.read() if e.type == "RetractionRejected"
        ]
        self.assertEqual(len(rejected), 1)
        self.assertEqual(
            rejected[0].payload["rejection_code"],
            RejectionCode.VERSION_SUPERSEDED.value,
        )

    def test_the_cursor_never_rewinds(self) -> None:
        self.recipient.outbox.advance_cursor(self.origin.store_id, 40)
        self.recipient.outbox.advance_cursor(self.origin.store_id, 12)
        self.assertEqual(self.recipient.outbox.cursor_for(self.origin.store_id), 40)

    def test_a_retraction_for_another_version_is_not_applied(self) -> None:
        wrong_version = Retraction(
            retraction_id=new_retraction_id(),
            origin_store_id=self.origin.store_id,
            origin_memory_id=self.memory_id,
            origin_memory_version=3,
            origin_sequence=5,
            reason_code="contradicted",
            requested_by="ag_north",
            issued_at="2026-10-10T12:00:00Z",
        )
        ack = self.recipient.receive_retraction(wrong_version)
        self.assertEqual(ack.state, PropagationState.REJECTED)
        self.assertEqual(ack.rejection_code, RejectionCode.UNKNOWN_MEMORY.value)
        self.assertEqual(
            self.recipient.get(self.imported_id).lifecycle_state, LifecycleState.ACTIVE
        )


class TestAcknowledgements(ProtocolCase):
    """Invariant 5, and the rule that keeps them honest."""

    def test_enforced_is_only_claimed_once_the_version_is_unexposed(self) -> None:
        retraction = self.origin.request_retraction(
            self.memory_id, reason="r", recipients=[self.recipient.store_id],
            actor="ag_north",
        )
        ack = self.recipient.receive_retraction(retraction)
        self.assertEqual(ack.state, PropagationState.ENFORCED)
        hits = self.recipient.retrieve("ag_south", "E01 coastal cable", k=5)
        self.assertNotIn(
            self.imported_id,
            [m.id for m in hits.exposed],
            "claimed enforced while still exposing the version",
        )

    def test_an_acknowledgement_carries_a_state_revision(self) -> None:
        """Lets an origin detect a recipient restored from a backup that has
        regressed."""
        retraction = self.origin.request_retraction(
            self.memory_id, reason="r", recipients=[self.recipient.store_id],
            actor="ag_north",
        )
        ack = self.recipient.receive_retraction(retraction)
        self.assertGreater(ack.state_revision, 0)
        self.assertFalse(ack.overstates_persistence)

    def test_a_claim_of_persistence_without_a_revision_is_flagged(self) -> None:
        bogus = Acknowledgement(
            retraction_id=new_retraction_id(),
            recipient_store_id=new_store_id(),
            state=PropagationState.ENFORCED,
            at="2026-10-10T12:00:00Z",
            state_revision=0,
        )
        self.assertTrue(bogus.overstates_persistence)

    def test_an_unauthorised_sender_is_rejected_and_recorded(self) -> None:
        retraction = self.origin.request_retraction(
            self.memory_id, reason="r", recipients=[self.recipient.store_id],
            actor="ag_north",
        )
        ack = self.recipient.receive_retraction(retraction, sender_authorised=False)
        self.assertEqual(ack.state, PropagationState.REJECTED)
        self.assertEqual(ack.rejection_code, RejectionCode.UNAUTHORIZED.value)
        self.assertEqual(
            self.recipient.get(self.imported_id).lifecycle_state,
            LifecycleState.ACTIVE,
            "applied a retraction from an unauthorised sender",
        )

    def test_an_offline_recipient_is_unknown_not_verified(self) -> None:
        retraction = self.origin.request_retraction(
            self.memory_id, reason="r", recipients=["st_" + "0" * 26], actor="ag_north",
        )
        state = self.origin.outbox.state_of(retraction.retraction_id, "st_" + "0" * 26)
        self.assertNotEqual(state, PropagationState.VERIFIED)
        self.assertIn(state, (PropagationState.QUEUED, PropagationState.UNKNOWN))

    def test_a_lost_acknowledgement_is_safe_to_retry(self) -> None:
        retraction = self.origin.request_retraction(
            self.memory_id, reason="r", recipients=[self.recipient.store_id],
            actor="ag_north",
        )
        first = self.recipient.receive_retraction(retraction)   # ack lost
        second = self.recipient.receive_retraction(retraction)  # origin retries
        self.assertEqual(first.state, second.state)


class TestRecipientRestart(ProtocolCase):
    def test_enforcement_survives_a_restart(self) -> None:
        retraction = self.origin.request_retraction(
            self.memory_id, reason="r", recipients=[self.recipient.store_id],
            actor="ag_north",
        )
        self.recipient.receive_retraction(retraction)
        reopened = self.reopen_recipient()

        self.assertEqual(
            reopened.get(self.imported_id).lifecycle_state, LifecycleState.QUARANTINED
        )
        self.assertIsNotNone(reopened.outbox.seen(retraction))
        self.assertEqual(
            reopened.outbox.cursor_for(self.origin.store_id), retraction.origin_sequence
        )

    def test_a_duplicate_after_a_restart_is_still_deduplicated(self) -> None:
        retraction = self.origin.request_retraction(
            self.memory_id, reason="r", recipients=[self.recipient.store_id],
            actor="ag_north",
        )
        self.recipient.receive_retraction(retraction)
        reopened = self.reopen_recipient()
        ack = reopened.receive_retraction(retraction)
        self.assertIn("duplicate", ack.detail)
        applied = [e for e in reopened.log.read() if e.type == "RetractionApplied"]
        self.assertEqual(len(applied), 1)


class TestBackoffAndVisibility(ProtocolCase):
    def test_transient_failures_back_off_then_fail_visibly(self) -> None:
        retraction = self.origin.request_retraction(
            self.memory_id, reason="r", recipients=[self.recipient.store_id],
            actor="ag_north",
        )
        outbox = self.origin.outbox
        row = outbox.due(now_ms())[0]
        delays = []
        for _ in range(MAX_ATTEMPTS - 1):
            state = outbox.record_attempt(row, now_ms(), "connection refused")
            self.assertEqual(state, PropagationState.RETRYING)
            row = outbox._row(
                outbox._conn.execute(
                    "SELECT * FROM outbox WHERE id = ?", (row.id,)
                ).fetchone()
            )
            delays.append(row.next_attempt_ms)
        self.assertEqual(
            outbox.record_attempt(row, now_ms(), "connection refused"),
            PropagationState.FAILED,
        )
        self.assertEqual(sorted(delays), delays, "backoff did not increase")

    def test_a_permanent_failure_stays_visible(self) -> None:
        retraction = self.origin.request_retraction(
            self.memory_id, reason="r", recipients=[self.recipient.store_id],
            actor="ag_north",
        )
        outbox = self.origin.outbox
        outbox.advance(
            retraction.retraction_id, self.recipient.store_id,
            PropagationState.FAILED, now_ms(), "gave up",
        )
        self.assertEqual(
            outbox.state_of(retraction.retraction_id, self.recipient.store_id),
            PropagationState.FAILED,
        )
        self.assertEqual(outbox.pending(), [], "failed rows are terminal")
        row = outbox._conn.execute(
            "SELECT last_error FROM outbox WHERE retraction_id = ?",
            (retraction.retraction_id,),
        ).fetchone()
        self.assertEqual(row["last_error"], "gave up")


class TestMalformedMessages(unittest.TestCase):
    """Roadmap: unknown schema versions and unauthorised messages."""

    def base(self) -> dict:
        return Retraction(
            retraction_id=new_retraction_id(),
            origin_store_id=new_store_id(),
            origin_memory_id="01M4CV9BY8QH9AA1HN3KRASJ8V",
            origin_memory_version=2,
            origin_sequence=3,
            reason_code="contradicted",
            requested_by="ag_x",
            issued_at="2026-10-10T12:00:00Z",
            evidence_digest=evidence_digest("why"),
        ).to_json()

    def test_a_path_is_not_a_store_identity(self) -> None:
        for path_like in ("/data/store.db", "C:\\s\\store.db", ":memory:", "store.db"):
            with self.subTest(path_like), self.assertRaises(ProtocolError) as ctx:
                Retraction.from_json({**self.base(), "origin_store_id": path_like})
            self.assertEqual(ctx.exception.code, RejectionCode.MALFORMED)

    def test_an_unsupported_protocol_version_is_rejected_by_code(self) -> None:
        with self.assertRaises(ProtocolError) as ctx:
            Retraction.from_json({**self.base(), "protocol_version": 99})
        self.assertEqual(
            ctx.exception.code, RejectionCode.PROTOCOL_VERSION_UNSUPPORTED
        )

    def test_missing_fields_are_named(self) -> None:
        payload = self.base()
        del payload["origin_memory_version"]
        with self.assertRaises(ProtocolError) as ctx:
            Retraction.from_json(payload)
        self.assertIn("origin_memory_version", ctx.exception.detail)

    def test_a_version_below_one_is_rejected(self) -> None:
        with self.assertRaises(ProtocolError):
            Retraction.from_json({**self.base(), "origin_memory_version": 0})

    def test_a_signature_proves_origin_not_truth(self) -> None:
        retraction = Retraction.from_json(self.base())
        signature = retraction.sign(b"shared-key")
        self.assertTrue(retraction.verify(signature, b"shared-key"))
        self.assertFalse(retraction.verify(signature, b"other-key"))
        tampered = Retraction.from_json({**self.base(), "reason_code": "unstated"})
        self.assertFalse(tampered.verify(signature, b"shared-key"))


class TestStateMachine(unittest.TestCase):
    def test_enforced_cannot_regress(self) -> None:
        self.assertFalse(
            can_transition(PropagationState.ENFORCED, PropagationState.PERSISTED)
        )

    def test_nothing_leaves_a_rejection(self) -> None:
        """A recipient that has refused has refused; an origin that retries gets
        the same refusal rather than a second chance at a different answer."""
        for target in PropagationState:
            self.assertFalse(can_transition(PropagationState.REJECTED, target))

    def test_persisted_and_enforced_are_distinct(self) -> None:
        self.assertNotEqual(PropagationState.PERSISTED, PropagationState.ENFORCED)
        self.assertTrue(
            can_transition(PropagationState.PERSISTED, PropagationState.ENFORCED)
        )

    def test_unknown_can_be_retried_out_of(self) -> None:
        """An offline recipient is `unknown`, and `unknown` is not terminal."""
        self.assertTrue(
            can_transition(PropagationState.UNKNOWN, PropagationState.QUEUED)
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
