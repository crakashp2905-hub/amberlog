"""Authenticated content encryption: tamper, binding, key loss, and version skew.

The scheme this replaces (`enc:v1`) was an HMAC-SHA256 counter-mode keystream
with no authentication tag, which makes a ciphertext malleable: XOR a chosen
delta into it and the plaintext becomes whatever the attacker picked. Its
docstring justified that by saying "the append-only log and the event digests
provide [integrity]" — and there are no event digests. The log has `seq`,
`event_id`, `ts`, `type`, `agent_id`, `episode_id`, `schema_version` and
`payload`, with nothing chaining or signing them.

So these tests exist in two halves. The first is the ordinary contract. The
second is the set of attacks the old scheme could not even detect, each run
against **both** suites, because which one is active depends on whether
`cryptography` happens to be installed and a guarantee that holds only on the
maintainer's laptop is not a guarantee.
"""

from __future__ import annotations

import json
import sqlite3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from amberlog import Amberlog, PolicyViolation
from amberlog.governance.cipher import (
    ETM_PREFIX,
    _keystream,
    LEGACY_PREFIX,
    AesGcm,
    EncryptThenMac,
    IntegrityError,
    LegacyKeystream,
    aead_available,
    associated_data,
    default_suite,
    envelope_version,
    is_sealed,
    suite_for,
)
from amberlog.governance.erasure import (
    ERASED_MARKER,
    CallbackKeyProvider,
    ContentVault,
    DirectoryKeyProvider,
    KeyUnavailable,
)


def suites() -> list[tuple[str, object]]:
    """Every suite available here, so a test covers both code paths.

    `cryptography` is an optional dependency, so AES-GCM is present on some
    hosts and not others. Skipping it silently would mean the AEAD path is
    tested only where someone happened to install the library.
    """
    found: list[tuple[str, object]] = [("v2 encrypt-then-MAC", EncryptThenMac())]
    if aead_available():
        found.append(("v3 AES-256-GCM", AesGcm()))
    return found


KEY = bytes(range(32))
AAD = associated_data("st_one", "01MEMORY", 1)


class TheContract(unittest.TestCase):
    def test_a_round_trip_returns_the_plaintext(self) -> None:
        for label, suite in suites():
            with self.subTest(label):
                envelope = suite.seal(b"valve 7 is upstream", KEY, AAD)
                self.assertEqual(suite.unseal(envelope, KEY, AAD), b"valve 7 is upstream")

    def test_the_envelope_hides_the_plaintext(self) -> None:
        for label, suite in suites():
            with self.subTest(label):
                envelope = suite.seal(b"deploy with AKIAIOSFODNN7EXAMPLE", KEY, AAD)
                self.assertTrue(is_sealed(envelope))
                self.assertNotIn("AKIA", envelope)
                self.assertNotIn("deploy", envelope)

    def test_two_seals_of_one_plaintext_differ(self) -> None:
        """A fresh nonce each time. Equal ciphertexts would leak that two
        memories say the same thing, which for a small corpus of short facts is
        most of the content."""
        for label, suite in suites():
            with self.subTest(label):
                first = suite.seal(b"same text", KEY, AAD)
                second = suite.seal(b"same text", KEY, AAD)
                self.assertNotEqual(first, second)

    def test_the_envelope_version_is_readable_without_the_key(self) -> None:
        for label, suite in suites():
            with self.subTest(label):
                envelope = suite.seal(b"x", KEY, AAD)
                self.assertEqual(envelope_version(envelope), suite.prefix.split(":")[1])
                self.assertIs(type(suite_for(envelope)), type(suite))

    def test_unicode_survives(self) -> None:
        for label, suite in suites():
            with self.subTest(label):
                text = "válvula 7 · 3.5 bar · ✓".encode("utf-8")
                self.assertEqual(suite.unseal(suite.seal(text, KEY, AAD), KEY, AAD), text)

    def test_empty_content_round_trips(self) -> None:
        for label, suite in suites():
            with self.subTest(label):
                self.assertEqual(suite.unseal(suite.seal(b"", KEY, AAD), KEY, AAD), b"")


class Tamper(unittest.TestCase):
    """What the old scheme could not detect."""

    def test_flipping_a_ciphertext_bit_is_detected(self) -> None:
        """The whole reason for the change.

        Under `enc:v1` this attack *worked*: the plaintext changed to whatever
        the attacker chose and nothing anywhere noticed.
        """
        for label, suite in suites():
            with self.subTest(label):
                envelope = suite.seal(b"pressure is 3.5 bar", KEY, AAD)
                parts = envelope.split(":")
                body = bytearray(bytes.fromhex(parts[3]))
                body[0] ^= 0x01
                parts[3] = body.hex()
                with self.assertRaises(IntegrityError):
                    suite.unseal(":".join(parts), KEY, AAD)

    def test_the_old_scheme_really_was_malleable(self) -> None:
        """Pinned so the motivation is not just an assertion in a docstring.

        A chosen-plaintext rewrite of a v1 ciphertext, decrypting cleanly to
        text the attacker picked. This is what shipped.
        """
        legacy = LegacyKeystream()
        original = b"pressure is 3.5 bar"
        forged_text = b"pressure is 9.9 bar"
        # v1 cannot be written any more, so build the envelope by hand.
        from amberlog.governance.cipher import _keystream

        nonce = bytes(range(16))
        stream = _keystream(KEY, nonce, len(original))
        ciphertext = bytes(a ^ b for a, b in zip(original, stream))
        delta = bytes(a ^ b for a, b in zip(original, forged_text))
        tampered = bytes(a ^ b for a, b in zip(ciphertext, delta))
        envelope = f"{LEGACY_PREFIX}{nonce.hex()}:{tampered.hex()}"

        # No key, no tag, no detection: the attacker chose the plaintext.
        self.assertEqual(legacy.unseal(envelope, KEY, AAD), forged_text)

    def test_v1_can_no_longer_be_written(self) -> None:
        with self.assertRaises(IntegrityError):
            LegacyKeystream().seal(b"x", KEY, AAD)

    def test_truncating_the_ciphertext_is_detected(self) -> None:
        for label, suite in suites():
            with self.subTest(label):
                parts = suite.seal(b"pressure is 3.5 bar", KEY, AAD).split(":")
                parts[3] = parts[3][:-4]
                with self.assertRaises(IntegrityError):
                    suite.unseal(":".join(parts), KEY, AAD)

    def test_replacing_the_nonce_is_detected(self) -> None:
        for label, suite in suites():
            with self.subTest(label):
                parts = suite.seal(b"pressure is 3.5 bar", KEY, AAD).split(":")
                parts[2] = ("00" * (len(parts[2]) // 2))
                with self.assertRaises(IntegrityError):
                    suite.unseal(":".join(parts), KEY, AAD)

    def test_a_stripped_tag_is_detected(self) -> None:
        """Downgrading v2 to something tagless must not read as v1."""
        suite = EncryptThenMac()
        parts = suite.seal(b"pressure is 3.5 bar", KEY, AAD).split(":")
        without_tag = ":".join(parts[:4])
        with self.assertRaises(IntegrityError):
            suite.unseal(without_tag, KEY, AAD)

    def test_the_wrong_key_is_detected(self) -> None:
        for label, suite in suites():
            with self.subTest(label):
                envelope = suite.seal(b"pressure is 3.5 bar", KEY, AAD)
                with self.assertRaises(IntegrityError):
                    suite.unseal(envelope, bytes(32), AAD)

    def test_a_garbage_envelope_raises_rather_than_returning(self) -> None:
        for label, suite in suites():
            with self.subTest(label):
                for broken in (f"{suite.prefix}zz", f"{suite.prefix}aa:bb", suite.prefix):
                    with self.assertRaises(IntegrityError):
                        suite.unseal(broken, KEY, AAD)

    def test_an_unknown_envelope_version_raises(self) -> None:
        with self.assertRaises(IntegrityError):
            suite_for("enc:v99:aa:bb")


class Binding(unittest.TestCase):
    """A tag proves the bytes were not edited. The AAD proves they belong here."""

    def test_content_cannot_be_moved_between_memories(self) -> None:
        for label, suite in suites():
            with self.subTest(label):
                envelope = suite.seal(b"pressure is 3.5 bar", KEY, AAD)
                other = associated_data("st_one", "01OTHER", 1)
                with self.assertRaises(IntegrityError):
                    suite.unseal(envelope, KEY, other)

    def test_content_cannot_be_rolled_back_to_an_older_version(self) -> None:
        """The attack the version binding exists for.

        Paste v1's ciphertext over v3's and, with only a tag, both verify: the
        bytes are authentic and the memory has silently reverted to what it
        said before it was corrected. That is the failure the whole retraction
        machinery exists to prevent, reached by editing one column.
        """
        for label, suite in suites():
            with self.subTest(label):
                old_version = suite.seal(b"pressure is 3.5 bar", KEY, AAD)
                current = associated_data("st_one", "01MEMORY", 3)
                with self.assertRaises(IntegrityError):
                    suite.unseal(old_version, KEY, current)

    def test_content_cannot_be_moved_between_stores(self) -> None:
        for label, suite in suites():
            with self.subTest(label):
                envelope = suite.seal(b"pressure is 3.5 bar", KEY, AAD)
                elsewhere = associated_data("st_two", "01MEMORY", 1)
                with self.assertRaises(IntegrityError):
                    suite.unseal(envelope, KEY, elsewhere)


class EndToEndThroughTheFabric(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.path = Path(self._tmp.name) / "store.db"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_new_content_is_sealed_with_an_authenticated_suite(self) -> None:
        fabric = Amberlog(self.path)
        try:
            fabric.remember(agent_id="a", content="valve 7 is upstream of the pump")
            rows = [
                row[0]
                for row in fabric.log._conn.execute(
                    "SELECT payload FROM events WHERE type = 'MemoryCreated'"
                )
            ]
            self.assertTrue(rows)
            for payload in rows:
                self.assertNotIn("valve 7", payload)
                self.assertNotIn(LEGACY_PREFIX, payload)
                self.assertIn(default_suite().prefix, payload)
        finally:
            fabric.close()

    def test_tampering_with_stored_content_is_detected_on_replay(self) -> None:
        """The realistic path: file access, drop the trigger, edit, restore it.

        `doctor` reports a missing trigger, but an attacker who puts it back
        leaves nothing for the log itself to notice — so the detection has to
        come from the ciphertext.
        """
        fabric = Amberlog(self.path)
        try:
            fabric.remember(agent_id="a", content="pressure is 3.5 bar")
        finally:
            fabric.close()

        conn = sqlite3.connect(self.path)
        try:
            with conn:
                conn.execute("DROP TRIGGER events_no_update")
                seq, payload = conn.execute(
                    "SELECT seq, payload FROM events WHERE type = 'MemoryCreated'"
                ).fetchone()
                # Parsed rather than sliced: the envelope sits inside a JSON
                # document and string surgery on it breaks whenever the suite
                # changes shape.
                document = json.loads(payload)
                envelope = document["memory"]["content"]
                parts = envelope.split(":")
                body = bytearray(bytes.fromhex(parts[3]))
                body[0] ^= 0x01
                parts[3] = body.hex()
                document["memory"]["content"] = ":".join(parts)
                conn.execute(
                    "UPDATE events SET payload = ? WHERE seq = ?",
                    (json.dumps(document), seq),
                )
                conn.execute(
                    "CREATE TRIGGER events_no_update BEFORE UPDATE ON events "
                    "BEGIN SELECT RAISE(ABORT, 'append-only'); END"
                )
        finally:
            conn.close()

        with self.assertRaises(IntegrityError):
            Amberlog(self.path)

    def test_erasure_still_reads_as_erasure_not_as_tampering(self) -> None:
        """The distinction the marker exists for.

        A missing key is a recorded, expected erasure. A failed tag is someone
        changing bytes. Collapsing them would file a tamper under "working as
        intended" — or tell an operator their data was deliberately destroyed
        when they had in fact mounted the wrong key volume.
        """
        fabric = Amberlog(self.path)
        try:
            memory_id = fabric.remember(agent_id="a", content="pressure is 3.5 bar")
            fabric.erase_content(memory_id, reason="subject request", actor="dpo")
            self.assertEqual(fabric.get(memory_id).content, ERASED_MARKER)
        finally:
            fabric.close()

        reopened = Amberlog(self.path)
        try:
            self.assertEqual(reopened.get(memory_id).content, ERASED_MARKER)
        finally:
            reopened.close()


class TheErasureScopeIsHonest(unittest.TestCase):
    """A subject-access request needs a truthful answer, and "the content is
    erased" is only true of what this store controls."""

    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.fabric = Amberlog(
            Path(self._tmp.name) / "store.db", auto_activate=True
        )
        self.addCleanup(self.fabric.close)
        self.memory_id = self.fabric.remember(
            agent_id="ag", content="the keypad code is PLUTO-4417"
        )

    def test_it_reports_every_place_the_erasure_reached(self) -> None:
        self.fabric.erase_content(
            self.memory_id, reason="subject request", actor="dpo"
        )
        scope = self.fabric.erasure_scope(self.memory_id)
        self.assertTrue(scope["erased"])
        for claim, reached in scope["reached"].items():
            with self.subTest(claim):
                self.assertTrue(reached, claim)

    def test_the_claims_are_verified_not_asserted(self) -> None:
        """Before erasure every one must be False, or the report is a constant
        dressed up as a check."""
        scope = self.fabric.erasure_scope(self.memory_id)
        self.assertFalse(scope["erased"])
        self.assertFalse(scope["reached"]["content_key_destroyed"])
        self.assertFalse(scope["reached"]["content_reads_as_marker"])
        self.assertFalse(scope["reached"]["removed_from_vector_index"])
        self.assertFalse(scope["reached"]["removed_from_lexical_index"])

    def test_the_search_indexes_really_are_purged(self) -> None:
        """Content left in an index is still matchable, which would make the
        erasure cosmetic in exactly the place a subject would notice."""
        before = self.fabric.retrieve(agent_id="ag", query="keypad code PLUTO")
        self.assertEqual(len(before.exposed), 1)
        self.fabric.erase_content(self.memory_id, reason="request", actor="dpo")
        after = self.fabric.retrieve(agent_id="ag", query="keypad code PLUTO")
        self.assertEqual(after.exposed, [])
        self.assertNotIn(self.memory_id, self.fabric.lexical._terms)
        self.assertNotIn(self.memory_id, self.fabric.index)

    def test_what_is_outside_the_store_is_unknown_rather_than_claimed(self) -> None:
        """The part usually left out. A store cannot see its own backups,
        exports or model traces, so it must not imply it has."""
        self.fabric.erase_content(self.memory_id, reason="request", actor="dpo")
        outside = self.fabric.erasure_scope(self.memory_id)["outside_this_store"]
        self.assertIn("unknown", outside["backups_taken_before_erasure"])
        self.assertIn("unknown", outside["exports_logs_and_model_traces"])

    def test_a_federated_copy_is_named(self) -> None:
        """A recipient holds its own key. A retraction withdraws the copy from
        use; it does not destroy the content."""
        from amberlog.federation import offer
        from amberlog.governance.firewall import (
            Firewall,
            rule_capabilities_must_be_granted,
            rule_must_be_active,
            rule_restricted_stays_private,
        )

        permissive = Firewall(
            rules=[
                rule_must_be_active,
                rule_restricted_stays_private,
                rule_capabilities_must_be_granted,
            ]
        )
        self.fabric.firewall = permissive
        other = Amberlog(
            Path(self._tmp.name) / "other.db", auto_activate=True,
            firewall=permissive,
        )
        self.addCleanup(other.close)
        result = offer(self.fabric, self.memory_id, other, "ag-b", activate=True)
        self.assertTrue(result.accepted, result.reasons)

        self.fabric.erase_content(self.memory_id, reason="request", actor="dpo")
        scope = self.fabric.erasure_scope(self.memory_id)
        self.assertIn(other.store_id, scope["outside_this_store"]["federated_copies"])
        # And the recipient's copy really is still readable, which is why it is
        # reported rather than assumed handled.
        self.assertIn("PLUTO", other.get(result.imported_memory_id).content)

    def test_the_audit_trail_is_listed_as_deliberately_kept(self) -> None:
        self.fabric.erase_content(self.memory_id, reason="request", actor="dpo")
        scope = self.fabric.erasure_scope(self.memory_id)
        self.assertTrue(scope["kept_deliberately"])
        # And it is true: the provenance survives a store reopen.
        self.assertEqual(
            self.fabric.get(self.memory_id).provenance.created_by, "ag"
        )


class KeyCustody(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        # Registered rather than torn down, so it runs *after* the connection
        # and fabric cleanups below it. `tearDown` runs before them, and on
        # Windows an open SQLite handle keeps the file locked and the directory
        # removal fails as a test error.
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def test_keys_can_live_outside_the_database(self) -> None:
        """The arrangement that makes a stolen `.db` file insufficient."""
        keys = self.dir / "keys"
        fabric = Amberlog(
            self.dir / "store.db", key_provider=DirectoryKeyProvider(keys)
        )
        try:
            fabric.remember(agent_id="a", content="valve 7 is upstream of the pump")
            self.assertTrue(list(keys.glob("*.key")))
            # And nothing in the database holds the material.
            material = [
                row[0]
                for row in fabric.log._conn.execute(
                    "SELECT key_material FROM content_keys"
                )
            ]
            self.assertTrue(material)
            self.assertTrue(all(m is None for m in material))
        finally:
            fabric.close()

    def test_a_lost_key_store_is_an_error_not_an_erasure(self) -> None:
        """Mounting the wrong volume must not report destroyed data.

        Returning the erased marker here would tell an operator the content was
        deliberately erased, which is the one answer that stops them looking
        for the key directory they forgot to mount.
        """
        keys = self.dir / "keys"
        store = self.dir / "store.db"
        fabric = Amberlog(store, key_provider=DirectoryKeyProvider(keys))
        try:
            fabric.remember(agent_id="a", content="pressure is 3.5 bar")
        finally:
            fabric.close()

        for key_file in keys.glob("*.key"):
            key_file.unlink()

        # The store will not even open, which is the right severity: every
        # sealed memory in it is unreadable, and continuing would mean serving
        # a store whose content is silently gone.
        with self.assertRaises(KeyUnavailable):
            Amberlog(store, key_provider=DirectoryKeyProvider(keys))

    def test_a_provider_that_cannot_destroy_says_so(self) -> None:
        """A store reporting an erasure it could not perform is worse than one
        that cannot erase at all — for a subject-access request it is the
        difference between a true answer and a false one."""
        held: dict[str, bytes] = {}
        provider = CallbackKeyProvider(
            fetch=held.get,
            create=lambda mid: held.setdefault(mid, bytes(range(32))),
        )
        self.assertFalse(provider.supports_destroy)

        conn = sqlite3.connect(self.dir / "v.db")
        conn.row_factory = sqlite3.Row
        self.addCleanup(conn.close)
        vault = ContentVault(conn, keys=provider, now_ms=lambda: 1)
        self.assertFalse(vault.supports_destroy)
        vault.key_for("m1", 1000)
        with conn:
            vault.erase("m1", "subject request", 2000)
        # The erasure is recorded, and records that the key outlived it.
        status = vault.status("m1")
        self.assertTrue(status.erased)
        self.assertIn("not destroyed", status.reason)

    def test_the_directory_provider_refuses_a_traversing_id(self) -> None:
        provider = DirectoryKeyProvider(self.dir / "keys")
        for bad in ("../escape", "a/b", "..", "a.b"):
            with self.subTest(bad):
                with self.assertRaises(ValueError):
                    provider.get(bad)

    def test_an_erased_memory_is_not_resurrected_by_a_restored_key(self) -> None:
        """The erasure record beats the provider.

        A KMS that could not delete, or a key directory restored from backup,
        must not make content readable again behind an audit record saying it
        is gone.
        """
        held: dict[str, bytes] = {}
        provider = CallbackKeyProvider(
            fetch=held.get,
            create=lambda mid: held.setdefault(mid, bytes(range(32))),
            destroy=lambda mid: True,  # claims success, keeps the material
        )
        conn = sqlite3.connect(self.dir / "v.db")
        conn.row_factory = sqlite3.Row
        self.addCleanup(conn.close)
        vault = ContentVault(conn, keys=provider, now_ms=lambda: 1)
        vault.key_for("m1", 1000)
        with conn:
            vault.erase("m1", "subject request", 2000)
        self.assertIn("m1", held, "the provider still holds the material")
        self.assertIsNone(vault.key_for("m1", 3000))


class TheDoctorReportsTheCipher(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "store.db"

    def _report(self) -> dict:
        import json as _json
        from io import StringIO
        from unittest.mock import patch

        from amberlog.cli import main

        buffer = StringIO()
        with patch("sys.stdout", buffer):
            main(["--json", "--db", str(self.path), "doctor"])
        return _json.loads(buffer.getvalue())

    def _finding(self, report: dict) -> dict:
        for finding in report["findings"]:
            if finding["name"] == "content cipher":
                return finding
        raise AssertionError("no content cipher check")

    def assertHealthyCipher(self, finding) -> None:
        """`ok` where AES-GCM works or is simply not installed. On a host
        where `cryptography` is installed but broken, the right answer is a
        warning naming why, which `BrokenCryptography` pins on every host."""
        from amberlog.governance.cipher import aead_status

        available, reason = aead_status()
        if available or reason == "not installed":
            self.assertEqual(finding["status"], "ok")
        else:
            self.assertEqual(finding["status"], "warn")
            self.assertIn("broken", finding["detail"])

    def test_an_authenticated_store_reports_ok(self) -> None:
        fabric = Amberlog(self.path)
        try:
            fabric.remember(agent_id="a", content="valve 7 is upstream")
        finally:
            fabric.close()
        finding = self._finding(self._report())
        self.assertHealthyCipher(finding)
        if finding["status"] == "ok":
            self.assertIn("authenticated", finding["detail"])

    def test_legacy_ciphertext_is_reported_as_a_warning(self) -> None:
        """It only goes down: v1 is never written again, and a revision
        re-seals. There is deliberately no bulk migration, because rewriting
        the log is the one thing this design forbids."""
        fabric = Amberlog(self.path)
        try:
            fabric.remember(agent_id="a", content="valve 7 is upstream")
        finally:
            fabric.close()

        conn = sqlite3.connect(self.path)
        try:
            with conn:
                conn.execute("DROP TRIGGER events_no_update")
                seq, payload = conn.execute(
                    "SELECT seq, payload FROM events WHERE type = 'MemoryCreated'"
                ).fetchone()
                document = json.loads(payload)
                # A *real* v1 ciphertext under this memory's own key, so the
                # store still opens and the check has something true to count.
                # A placeholder blob decrypts to non-UTF-8 and the store
                # refuses to open at all — which is correct behaviour, and not
                # what this test is about.
                memory_id = document["memory"]["id"]
                conn2 = sqlite3.connect(self.path)
                try:
                    conn2.row_factory = sqlite3.Row
                    key = bytes(
                        conn2.execute(
                            "SELECT key_material FROM content_keys WHERE memory_id = ?",
                            (memory_id,),
                        ).fetchone()["key_material"]
                    )
                finally:
                    conn2.close()
                nonce = bytes(range(16))
                text = b"valve 7 is upstream"
                stream = _keystream(key, nonce, len(text))
                blob = bytes(a ^ b for a, b in zip(text, stream))
                document["memory"]["content"] = (
                    f"{LEGACY_PREFIX}{nonce.hex()}:{blob.hex()}"
                )
                conn.execute(
                    "UPDATE events SET payload = ? WHERE seq = ?",
                    (json.dumps(document), seq),
                )
        finally:
            conn.close()

        finding = self._finding(self._report())
        self.assertEqual(finding["status"], "warn")
        self.assertIn("enc:v1", finding["detail"])

    def test_an_unencrypted_store_is_reported_as_a_warning(self) -> None:
        """Erasing a key that was never used is cosmetic — the bug that
        produced `_seal_content` in the first place."""
        fabric = Amberlog(self.path, encrypt_content=False)
        try:
            fabric.remember(agent_id="a", content="valve 7 is upstream")
        finally:
            fabric.close()
        # Re-opened the same way, or the check cannot know encryption is off.
        import json as _json
        from io import StringIO
        from unittest.mock import patch

        from amberlog import cli

        original = cli.Amberlog
        buffer = StringIO()
        try:
            cli.Amberlog = lambda *a, **k: original(
                *a, **{**k, "encrypt_content": False}
            )
            with patch("sys.stdout", buffer):
                cli.main(["--json", "--db", str(self.path), "doctor"])
        finally:
            cli.Amberlog = original
        finding = self._finding(_json.loads(buffer.getvalue()))
        self.assertEqual(finding["status"], "warn")
        self.assertIn("plaintext", finding["detail"])

    def test_external_key_custody_is_reported(self) -> None:
        """And the CLI needs `--keys` to open such a store at all.

        Writing this test is what surfaced that gap: the tooling had no way to
        point at an external key store, so the one arrangement that protects
        against a stolen database file was unusable from the command line.
        """
        import json as _json
        from io import StringIO
        from unittest.mock import patch

        from amberlog.cli import main

        keys = Path(self._tmp.name) / "keys"
        fabric = Amberlog(self.path, key_provider=DirectoryKeyProvider(keys))
        try:
            fabric.remember(agent_id="a", content="valve 7 is upstream")
        finally:
            fabric.close()

        # Without --keys: refused, with the remedy named.
        errors = StringIO()
        with patch("sys.stderr", errors):
            self.assertEqual(main(["--db", str(self.path), "doctor"]), 2)
        self.assertIn("--keys", errors.getvalue())

        # With --keys: opens, and reports custody as external.
        buffer = StringIO()
        with patch("sys.stdout", buffer):
            main(["--json", "--db", str(self.path), "--keys", str(keys), "doctor"])
        finding = self._finding(_json.loads(buffer.getvalue()))
        self.assertHealthyCipher(finding)
        self.assertIn("externally", finding["detail"])
        self.assertIn("DirectoryKeyProvider", finding["detail"])


class _Panic(BaseException):
    """Stands in for `pyo3_runtime.PanicException`, which is not an Exception."""


class BrokenCryptography(unittest.TestCase):
    """A broken `cryptography` install must not take every write down.

    Seen for real: Debian's python3-cryptography imported under an interpreter
    with no `_cffi_backend` raises `pyo3_runtime.PanicException`, a
    `BaseException`, and that escaped `aead_available()` so every `remember`
    crashed while sealing.
    """

    def setUp(self) -> None:
        import builtins

        from amberlog.governance import cipher

        self.cipher = cipher
        self.real_import = builtins.__import__
        cipher._reset_aead_status()
        self.addCleanup(cipher._reset_aead_status)
        self.addCleanup(setattr, builtins, "__import__", self.real_import)

    def break_import(self, error: BaseException) -> None:
        import builtins

        real = self.real_import

        def fake(name, *args, **kwargs):
            if name.startswith("cryptography"):
                raise error
            return real(name, *args, **kwargs)

        builtins.__import__ = fake

    def test_a_panicking_import_falls_back_to_encrypt_then_mac_and_warns(self) -> None:
        self.break_import(_Panic("Python API call failed"))
        with self.assertWarns(RuntimeWarning) as caught:
            available, reason = self.cipher.aead_status()
        self.assertFalse(available)
        self.assertIn("broken", reason)
        self.assertIn("_Panic", reason)
        self.assertIn("cannot be used", str(caught.warning))
        self.assertIsInstance(self.cipher.default_suite(), EncryptThenMac)

    def test_writes_and_reads_still_work(self) -> None:
        self.break_import(_Panic("Python API call failed"))
        fabric = Amberlog()
        self.addCleanup(fabric.close)
        with self.assertWarns(RuntimeWarning):
            mid = fabric.remember("ag", "valve 7 is upstream")
        self.assertEqual(fabric.get(mid).content, "valve 7 is upstream")

    def test_existing_aes_gcm_content_is_refused_with_the_reason(self) -> None:
        self.break_import(_Panic("Python API call failed"))
        with self.assertWarns(RuntimeWarning):
            with self.assertRaises(IntegrityError) as caught:
                self.cipher.suite_for("enc:v3:00:00")
        self.assertIn("broken", str(caught.exception))

    def test_not_installed_is_the_quiet_default(self) -> None:
        missing = ModuleNotFoundError("No module named 'cryptography'")
        missing.name = "cryptography"
        self.break_import(missing)
        import warnings

        with warnings.catch_warnings():
            warnings.simplefilter("error")
            self.assertEqual(self.cipher.aead_status(), (False, "not installed"))

    def test_a_missing_dependency_of_cryptography_is_broken_not_absent(self) -> None:
        missing = ModuleNotFoundError("No module named '_cffi_backend'")
        missing.name = "_cffi_backend"
        self.break_import(missing)
        with self.assertWarns(RuntimeWarning):
            available, reason = self.cipher.aead_status()
        self.assertFalse(available)
        self.assertIn("_cffi_backend", reason)

    def test_an_interrupt_is_not_swallowed(self) -> None:
        self.break_import(KeyboardInterrupt())
        with self.assertRaises(KeyboardInterrupt):
            self.cipher.aead_status()

    def test_the_probe_runs_once(self) -> None:
        calls = []
        import builtins

        real = self.real_import

        def counting(name, *args, **kwargs):
            if name.startswith("cryptography"):
                calls.append(name)
                raise _Panic("again")
            return real(name, *args, **kwargs)

        builtins.__import__ = counting
        with self.assertWarns(RuntimeWarning):
            self.cipher.aead_available()
        self.cipher.aead_available()
        self.cipher.default_suite()
        self.assertEqual(len(calls), 1)

    def test_doctor_names_the_fallback(self) -> None:
        from amberlog import cli

        self.break_import(_Panic("Python API call failed"))
        fabric = Amberlog(encrypt_content=True)
        self.addCleanup(fabric.close)
        with self.assertWarns(RuntimeWarning):
            fabric.remember("ag", "valve 7 is upstream")
        finding = cli._check_content_cipher(fabric)
        self.assertEqual(finding.status, "warn")
        self.assertIn("broken", finding.detail)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
