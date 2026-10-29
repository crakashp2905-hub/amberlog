"""Phase 6 — crypto-erasure, and the content/audit split.

Invariant 12: *append-only audit history does not justify retaining sensitive
content indefinitely.* The two halves are in genuine tension. The event log is
append-only and enforced by database triggers, and a log you can edit to remove
embarrassing entries is not an audit trail — but "it is in an immutable log" is
not an answer to a subject asking for erasure, or to a leaked credential.

The resolution: encrypt the content per memory, keep the key outside the log,
destroy the key. Events stay byte-identical, every projection still replays,
lineage and the propagation record are untouched, and the text is unrecoverable.

What survives is deliberately everything *about* the memory. An auditor can
still answer "was this handled correctly?" about a memory nobody can read.
Erasure removes the content, not the accountability.
"""

from __future__ import annotations

import json
import sqlite3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from amberlog import LifecycleState, Amberlog, WithdrawalBasis
from amberlog.governance.cipher import (
    IntegrityError,
    associated_data,
)
from amberlog.governance.erasure import (
    ERASED_MARKER,
    ContentVault,
    is_sealed,
    seal,
    unseal,
)


class TestTheVault(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.addCleanup(self.conn.close)
        self.vault = ContentVault(self.conn)
        # A ciphertext is now bound to a store, memory and version, so the
        # direct-cipher tests have to say which.
        self.aad = associated_data("st_test", "m1", 1)

    def test_a_key_is_minted_once_and_reused(self) -> None:
        first = self.vault.key_for("m1", 1000)
        self.assertEqual(self.vault.key_for("m1", 2000), first)

    def test_sealing_hides_the_plaintext(self) -> None:
        key = self.vault.key_for("m1", 1000)
        sealed = seal("deploy with AKIAIOSFODNN7EXAMPLE", key, self.aad)
        self.assertTrue(is_sealed(sealed))
        self.assertNotIn("AKIA", sealed)
        self.assertNotIn("deploy", sealed)
        self.assertEqual(
            unseal(sealed, key, self.aad), "deploy with AKIAIOSFODNN7EXAMPLE"
        )

    def test_the_wrong_key_does_not_return_the_plaintext(self) -> None:
        sealed = seal("secret text", self.vault.key_for("m1", 1000), self.aad)
        other = self.vault.key_for("m2", 1000)
        # Now a refusal rather than garbage: the wrong key fails the tag, and a
        # failed tag is an exception. The old scheme had no tag, so this test
        # could only assert "not the plaintext" — which was also true of
        # mojibake that flowed on into a Memory.content.
        with self.assertRaises(IntegrityError):
            unseal(sealed, other, self.aad)

    def test_erasure_destroys_the_key_irreversibly(self) -> None:
        key = self.vault.key_for("m1", 1000)
        sealed = seal("sensitive", key, self.aad)
        self.assertTrue(self.vault.erase("m1", "subject request", 2000))
        self.assertIsNone(self.vault.key_for("m1", 3000))
        self.assertEqual(
            unseal(sealed, self.vault.key_for("m1", 3000), self.aad), ERASED_MARKER
        )

    def test_erasing_twice_is_not_an_error_and_not_a_second_erasure(self) -> None:
        self.vault.key_for("m1", 1000)
        self.assertTrue(self.vault.erase("m1", "first", 2000))
        self.assertFalse(self.vault.erase("m1", "again", 3000))

    def test_the_fact_of_erasure_survives(self) -> None:
        """A deleted row would make an erased memory indistinguishable from one
        that never had a key."""
        self.vault.key_for("m1", 1000)
        self.vault.erase("m1", "subject request", 2000)
        status = self.vault.status("m1")
        self.assertTrue(status.erased)
        self.assertEqual(status.reason, "subject request")
        self.assertEqual(status.erased_ms, 2000)

    def test_erasing_something_that_was_never_sealed_is_recorded(self) -> None:
        """"We were asked and there was nothing to erase" is a different audit
        answer from silence."""
        self.assertFalse(self.vault.erase("never-existed", "request", 1000))
        self.assertTrue(self.vault.status("never-existed").erased)

    def test_unsealing_unencrypted_text_passes_it_through(self) -> None:
        """What keeps a log written before encryption existed replayable."""
        self.assertEqual(
            unseal("plain old content", b"any-key", self.aad), "plain old content"
        )
        self.assertFalse(is_sealed("plain old content"))

    def test_the_marker_is_distinct_from_empty(self) -> None:
        """"Erased" and "was always blank" must stay different facts."""
        self.assertTrue(ERASED_MARKER)
        self.assertNotEqual(ERASED_MARKER, "")


class ErasureCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = str(Path(self.tmp.name) / "store.db")
        self.fabric = Amberlog(self.path)
        self.addCleanup(self._close)
        self.secret = "Jane Doe lives at 14 Elm Road, Bristol."
        self.memory_id = self.fabric.remember("ag_a", self.secret)
        self.fabric.validate(self.memory_id, actor="supervisor")

    def _close(self) -> None:
        try:
            self.fabric.close()
        except Exception:
            pass

    def raw_log(self) -> str:
        return json.dumps([list(e.payload.items()) for e in self.fabric.log.read()], default=str)


class TestContentNeverReachesTheLogInPlaintext(ErasureCase):
    def test_the_log_holds_ciphertext(self) -> None:
        self.assertNotIn("Jane Doe", self.raw_log())
        self.assertNotIn("Elm Road", self.raw_log())

    def test_reads_still_see_plaintext(self) -> None:
        """The projection unseals as it folds, so the thirty call sites that read
        `.content` need no change."""
        self.assertEqual(self.fabric.get(self.memory_id).content, self.secret)

    def test_retrieval_still_works(self) -> None:
        hits = self.fabric.retrieve("ag_a", "Elm Road Bristol", k=5)
        self.assertIn(self.memory_id, [m.id for m in hits.exposed])

    def test_a_revision_is_sealed_too(self) -> None:
        self.fabric.revise(
            self.memory_id, "Jane Doe lives at 9 Oak Lane, Bath.",
            agent_id="ag_a", reason="moved",
        )
        self.assertNotIn("Oak Lane", self.raw_log())
        self.assertIn("Oak Lane", self.fabric.get(self.memory_id).content)

    def test_encryption_can_be_turned_off(self) -> None:
        """A deployment that wants the log readable by other tools may choose
        plaintext — and then erasure is not available, which the docs say."""
        plain = Amberlog(":memory:", encrypt_content=False)
        self.addCleanup(plain.close)
        memory_id = plain.remember("ag_a", "readable in the log")
        raw = json.dumps(
            [list(e.payload.items()) for e in plain.log.read()], default=str
        )
        self.assertIn("readable in the log", raw)


class TestErasureThroughTheFabric(ErasureCase):
    def test_the_content_becomes_unrecoverable(self) -> None:
        self.assertTrue(
            self.fabric.erase_content(self.memory_id, reason="subject request", actor="dpo")
        )
        self.assertEqual(self.fabric.get(self.memory_id).content, ERASED_MARKER)
        self.assertNotIn("Jane Doe", self.raw_log())

    def test_erasure_survives_a_replay(self) -> None:
        self.fabric.erase_content(self.memory_id, reason="request", actor="dpo")
        self.fabric.rebuild()
        self.assertEqual(self.fabric.get(self.memory_id).content, ERASED_MARKER)

    def test_erasure_survives_a_restart(self) -> None:
        self.fabric.erase_content(self.memory_id, reason="request", actor="dpo")
        self.fabric.close()
        reopened = Amberlog(self.path)
        self.addCleanup(reopened.close)
        self.assertEqual(reopened.get(self.memory_id).content, ERASED_MARKER)

    def test_the_memory_is_no_longer_searchable(self) -> None:
        """The index holds the plaintext too, so leaving it would surface the
        content the caller just erased."""
        self.fabric.erase_content(self.memory_id, reason="request", actor="dpo")
        hits = self.fabric.retrieve("ag_a", "Elm Road Bristol", k=5)
        self.assertNotIn(self.memory_id, [m.id for m in hits.exposed])

    def test_history_is_not_rewritten(self) -> None:
        before = len(self.fabric.log)
        self.fabric.erase_content(self.memory_id, reason="request", actor="dpo")
        self.assertGreater(len(self.fabric.log), before, "erasure is an appended event")

    def test_the_append_only_guarantee_still_holds(self) -> None:
        self.fabric.erase_content(self.memory_id, reason="request", actor="dpo")
        with self.assertRaises(sqlite3.IntegrityError):
            self.fabric.log._conn.execute(
                "UPDATE events SET payload = '{}' WHERE seq = 1"
            )


class TestAccountabilitySurvivesErasure(ErasureCase):
    """The content goes; everything *about* the memory stays."""

    def test_provenance_and_lineage_are_intact(self) -> None:
        child = self.fabric.derive(
            "ag_b", "Deliveries for Jane go to the Elm Road gate.",
            parents=[self.memory_id],
        )
        self.fabric.validate(child, actor="supervisor")
        self.fabric.erase_content(self.memory_id, reason="request", actor="dpo")

        self.assertEqual(
            self.fabric.get(self.memory_id).provenance.created_by, "ag_a"
        )
        descendants = [n.memory_id for n in self.fabric.lineage_graph.descendants(self.memory_id)]
        self.assertIn(child, descendants)

    def test_the_audit_trail_records_who_erased_and_why(self) -> None:
        self.fabric.erase_content(
            self.memory_id, reason="GDPR art. 17 request #4417", actor="dpo"
        )
        erased = [e for e in self.fabric.log.read() if e.type == "ContentErased"]
        self.assertEqual(len(erased), 1)
        self.assertEqual(erased[0].agent_id, "dpo")
        self.assertIn("4417", erased[0].payload["reason"])
        self.assertTrue(erased[0].payload["had_content"])

    def test_the_erasure_event_does_not_contain_the_content(self) -> None:
        self.fabric.erase_content(self.memory_id, reason="request", actor="dpo")
        erased = [e for e in self.fabric.log.read() if e.type == "ContentErased"]
        self.assertNotIn("Jane Doe", json.dumps(erased[0].payload))

    def test_a_retraction_before_erasure_is_still_on_the_record(self) -> None:
        """An auditor can still answer "was this handled correctly?" about a
        memory nobody can read."""
        self.fabric.quarantine(
            self.memory_id, reason="should never have been stored", actor="dpo",
            basis=WithdrawalBasis.SENSITIVE_DATA,
        )
        self.fabric.erase_content(self.memory_id, reason="request", actor="dpo")

        self.assertEqual(
            self.fabric.get(self.memory_id).lifecycle_state, LifecycleState.QUARANTINED
        )
        self.assertEqual(
            self.fabric.state.withdrawal_basis[self.memory_id],
            WithdrawalBasis.SENSITIVE_DATA.value,
        )
        trail = [e.type for e in self.fabric.audit_trail(self.memory_id)]
        self.assertIn("LifecycleChanged", trail)

    def test_the_erasure_status_is_queryable(self) -> None:
        self.fabric.erase_content(self.memory_id, reason="request #9", actor="dpo")
        status = self.fabric.erasure_status(self.memory_id)
        self.assertTrue(status.erased)
        self.assertEqual(status.reason, "request #9")

    def test_a_backup_taken_after_erasure_cannot_recover_the_content(self) -> None:
        """The key is destroyed in the same file the backup copies, so a
        restored backup is erased too — which is the right behaviour and worth
        pinning, because the opposite would make erasure defeatable by holding
        an old copy."""
        from amberlog.cli import main

        self.fabric.erase_content(self.memory_id, reason="request", actor="dpo")
        target = str(Path(self.tmp.name) / "copy.db")
        self.assertEqual(main(["--db", self.path, "backup", target]), 0)
        restored = Amberlog(target)
        self.addCleanup(restored.close)
        self.assertEqual(restored.get(self.memory_id).content, ERASED_MARKER)


class TestBackupTakenBeforeErasure(ErasureCase):
    def test_an_older_backup_still_holds_the_content(self) -> None:
        """Stated rather than hidden: crypto-erasure cannot reach a copy made
        before the key was destroyed. Retention of backups is an operational
        control, and DEPLOYMENT.md says so.
        """
        from amberlog.cli import main

        target = str(Path(self.tmp.name) / "before.db")
        self.assertEqual(main(["--db", self.path, "backup", target]), 0)
        self.fabric.erase_content(self.memory_id, reason="request", actor="dpo")

        older = Amberlog(target)
        self.addCleanup(older.close)
        self.assertEqual(older.get(self.memory_id).content, self.secret)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()


class TestEraseFromTheCommandLine(unittest.TestCase):
    """An operator handling an erasure request needs a command, not a script."""

    def test_erase_then_report(self) -> None:
        import json
        import os
        import tempfile

        from amberlog.cli import main

        with tempfile.TemporaryDirectory() as tmp:
            db = os.path.join(tmp, "s.db")
            fabric = Amberlog(db)
            mid = fabric.remember("ag", "the customer lives at 4 Elm Road")
            fabric.close()

            import contextlib
            import io
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = main(["--db", db, "--json", "erase", mid,
                             "--reason", "ticket SAR-17", "--actor", "dpo"])
            self.assertEqual(code, 0)
            scope = json.loads(out.getvalue())
            self.assertTrue(scope["erased"])
            self.assertTrue(all(scope["reached"].values()))

            reopened = Amberlog(db)
            try:
                self.assertNotIn("Elm Road", reopened.get(mid).content)
                self.assertEqual(reopened.erasure_status(mid).reason, "ticket SAR-17")
            finally:
                reopened.close()
