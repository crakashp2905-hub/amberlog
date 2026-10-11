"""Old and new stores talking to each other, and old code meeting a new store.

Four schema versions have shipped (0.2.0 → 0.7.0) and one protocol version, so
"does a 0.3.0 peer still work?" is a real question with a real answer, and the
answer should be written down rather than assumed from the fact that nothing
broke on a developer's machine.

Two directions, and they are **not** symmetric:

* **Older store, newer code** — must work. A store is data a customer already has, and refusing to open it is refusing their history. Every field added since 0.2.0 is nullable with a defined absent-meaning, and these tests check each one.
* **Newer store, older code** — must *fail safely*, and cannot be made to work. 0.5.0 code pointed at a 0.7.0 store does not know `enc:v2`, so `is_sealed` returns False and the envelope is handed back as content. That is a one-way door and the honest response is to say so, not to pretend compatibility.

The protocol is the third case: a retraction crossing between stores of
different versions. Hop 0 is byte-identical across 0.3.0–0.7.0 by design, and
that is checked here rather than claimed in a docstring.
"""

from __future__ import annotations

import json
import sqlite3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from memory_fabric import LifecycleState, MemoryFabric
from memory_fabric.federation import offer
from memory_fabric.governance.cipher import ETM_PREFIX, LEGACY_PREFIX
from memory_fabric.governance.firewall import (
    Firewall,
    rule_capabilities_must_be_granted,
    rule_must_be_active,
    rule_restricted_stays_private,
)
from memory_fabric.identity import DEFAULT_TENANT
from memory_fabric.model import SCHEMA_VERSION, Memory
from memory_fabric.protocol import PROTOCOL_VERSION, PropagationState, Retraction


def permissive() -> Firewall:
    return Firewall(
        rules=[
            rule_must_be_active,
            rule_restricted_stays_private,
            rule_capabilities_must_be_granted,
        ]
    )


class EveryAddedFieldHasAnAbsentMeaning(unittest.TestCase):
    """A memory written by an older version must replay with defined values.

    One test per field added since 0.2.0, because "it still loads" is not the
    claim — the claim is that the *absent* value is the one that preserves the
    old behaviour.
    """

    BASE = {
        "id": "01OLD",
        "version": 1,
        "type": "semantic",
        "content": "valve 7 is upstream of the pump",
        "provenance": {"created_by": "ag", "method": "observed"},
    }

    def test_a_0_2_0_memory_loads(self) -> None:
        memory = Memory.from_json(dict(self.BASE))
        self.assertEqual(memory.id, "01OLD")
        self.assertEqual(memory.content, "valve 7 is upstream of the pump")

    def test_tenant_defaults_to_the_single_tenant(self) -> None:
        """Absent means `tn_default`, not None: a nullable boundary is one
        every comparison has to remember to handle."""
        self.assertEqual(Memory.from_json(dict(self.BASE)).tenant_id, DEFAULT_TENANT)

    def test_validity_defaults_to_open_ended(self) -> None:
        """Absent means "applies always", not "never valid" — so a pre-0.7.0
        memory answers every temporal query exactly as it did."""
        memory = Memory.from_json(dict(self.BASE))
        self.assertIsNone(memory.valid_from)
        self.assertIsNone(memory.valid_to)
        self.assertTrue(memory.applies_at(0))
        self.assertTrue(memory.applies_at(10**12))
        self.assertTrue(memory.is_open_ended)

    def test_lifecycle_defaults_to_candidate(self) -> None:
        """The conservative end: an unlabelled memory is not exposed."""
        self.assertIs(
            Memory.from_json(dict(self.BASE)).lifecycle_state,
            LifecycleState.CANDIDATE,
        )

    def test_the_schema_version_travels_with_the_record(self) -> None:
        memory = Memory.from_json({**self.BASE, "schema_version": "0.2.0"})
        self.assertEqual(memory.schema_version, "0.2.0")


class AnOlderStoreOpensOnNewerCode(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "legacy.db"

    def _write_legacy(self, schema: str, strip: tuple[str, ...] = ()) -> str:
        """Build a store, then rewrite its events to look like `schema`."""
        fabric = MemoryFabric(
            self.path, firewall=permissive(), auto_activate=True,
            encrypt_content=False,
        )
        try:
            memory_id = fabric.remember(
                agent_id="ag", content="valve 7 is upstream of the pump"
            )
        finally:
            fabric.close()

        conn = sqlite3.connect(self.path)
        try:
            with conn:
                conn.execute("DROP TRIGGER events_no_update")
                conn.execute("DROP TRIGGER integrity_chain_no_delete")
                # The chain covered the original events; rewriting them makes
                # it diverge, which is correct and not what this test is about.
                conn.execute("DELETE FROM integrity_chain")
                for seq, payload in conn.execute(
                    "SELECT seq, payload FROM events"
                ).fetchall():
                    document = json.loads(payload)
                    memory = document.get("memory")
                    if isinstance(memory, dict):
                        for field in strip:
                            memory.pop(field, None)
                        memory["schema_version"] = schema
                    conn.execute(
                        "UPDATE events SET payload = ?, schema_version = ? WHERE seq = ?",
                        (json.dumps(document), schema, seq),
                    )
        finally:
            conn.close()
        return memory_id

    def test_a_0_2_0_store_replays(self) -> None:
        memory_id = self._write_legacy(
            "0.2.0",
            strip=("tenant_id", "valid_from", "valid_to", "capabilities"),
        )
        fabric = MemoryFabric(self.path, firewall=permissive(), auto_activate=True)
        self.addCleanup(fabric.close)
        memory = fabric.get(memory_id)
        self.assertEqual(memory.content, "valve 7 is upstream of the pump")
        self.assertEqual(memory.tenant_id, DEFAULT_TENANT)
        self.assertTrue(memory.applies_at(0))

    def test_an_older_store_is_retrievable_including_with_the_new_filters(self) -> None:
        """The new mechanisms must not quietly exclude old data.

        `as_of` on a store whose memories have no validity window is the case
        that would silently return nothing if absent had meant "never valid".
        """
        self._write_legacy("0.3.0", strip=("tenant_id", "valid_from", "valid_to"))
        fabric = MemoryFabric(self.path, firewall=permissive(), auto_activate=True)
        self.addCleanup(fabric.close)
        for label, kwargs in (
            ("plain", {}),
            ("as_of", {"as_of": 1_700_000_000}),
            ("roots", {"group_by_source_root": True}),
            ("lineage", {"expand_lineage": 2}),
        ):
            with self.subTest(label):
                result = fabric.retrieve(agent_id="ag", query="valve 7 pump", k=3, **kwargs)
                self.assertEqual(len(result.exposed), 1, label)

    def test_doctor_reports_an_older_store_as_sound(self) -> None:
        from io import StringIO
        from unittest.mock import patch

        from memory_fabric.cli import main

        self._write_legacy("0.3.0", strip=("tenant_id", "valid_from", "valid_to"))
        buffer = StringIO()
        with patch("sys.stdout", buffer):
            code = main(["--json", "--db", str(self.path), "doctor"])
        report = json.loads(buffer.getvalue())
        self.assertTrue(report["sound"], report["findings"])
        # The chain was cleared with the rewrite, so it should say so rather
        # than claiming verification it cannot perform.
        chain = next(f for f in report["findings"] if f["name"] == "event chain")
        self.assertEqual(chain["status"], "warn")
        self.assertIn("nothing about this log", chain["detail"])
        self.assertIn(code, (0, 1))

    def test_a_newer_schema_is_refused_rather_than_half_read(self) -> None:
        """The other direction. Events this code does not understand are
        skipped for forward compatibility, which is right and is exactly why
        it must be reported rather than silently tolerated."""
        from io import StringIO
        from unittest.mock import patch

        from memory_fabric.cli import main

        self._write_legacy("99.0.0")
        buffer = StringIO()
        with patch("sys.stdout", buffer):
            code = main(["--json", "--db", str(self.path), "doctor"])
        report = json.loads(buffer.getvalue())
        self.assertEqual(code, 5)
        schema = next(f for f in report["findings"] if f["name"] == "schema version")
        self.assertEqual(schema["status"], "fail")


class CiphertextGenerationsCoexist(unittest.TestCase):
    def test_a_store_can_hold_v1_v2_and_plaintext_at_once(self) -> None:
        """Three generations in one log, all readable.

        A store is not re-encrypted on upgrade — rewriting the log is the one
        thing this design forbids — so mixed envelopes are the normal state of
        any store that has been through a version change.
        """
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "mixed.db"
            plain = MemoryFabric(path, auto_activate=True, encrypt_content=False)
            try:
                plaintext_id = plain.remember(agent_id="ag", content="written in the clear")
            finally:
                plain.close()

            sealed = MemoryFabric(path, auto_activate=True, encrypt_content=True)
            try:
                sealed_id = sealed.remember(agent_id="ag", content="written sealed")
                self.assertEqual(sealed.get(plaintext_id).content, "written in the clear")
                self.assertEqual(sealed.get(sealed_id).content, "written sealed")
            finally:
                sealed.close()

            reopened = MemoryFabric(path, auto_activate=True, encrypt_content=True)
            try:
                self.assertEqual(reopened.get(plaintext_id).content, "written in the clear")
                self.assertEqual(reopened.get(sealed_id).content, "written sealed")
            finally:
                reopened.close()

    def test_a_legacy_envelope_is_still_recognised(self) -> None:
        from memory_fabric.governance.cipher import is_sealed

        self.assertTrue(is_sealed(LEGACY_PREFIX + "00:00"))
        self.assertTrue(is_sealed(ETM_PREFIX + "00:00:00"))
        self.assertFalse(is_sealed("plain content"))


class TheProtocolIsStableAcrossVersions(unittest.TestCase):
    """Hop 0 must look the same to a 0.3.0 peer as to a 0.7.0 one."""

    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def _pair(self):
        origin = MemoryFabric(self.dir / "a.db", firewall=permissive(), auto_activate=True)
        recipient = MemoryFabric(self.dir / "b.db", firewall=permissive(), auto_activate=True)
        self.addCleanup(origin.close)
        self.addCleanup(recipient.close)
        return origin, recipient

    def test_a_hop_zero_retraction_carries_no_new_fields(self) -> None:
        """Byte-compatibility with a 0.3.0 peer, checked rather than claimed.

        The transitive-forwarding fields are optional and default to the origin
        values, so a direct retraction serialises exactly as it did before they
        existed — which is what lets a 0.7.0 origin talk to a 0.3.0 recipient.
        """
        origin, _ = self._pair()
        memory_id = origin.remember(agent_id="ag", content="valve 7 is upstream")
        retraction = origin.request_retraction(
            memory_id, reason="contradicted", recipients=["st_peer"],
            basis="contradicted",
        )
        payload = retraction.to_json()
        for new_field in (
            "target_store_id", "target_memory_id", "target_memory_version",
            "forwarded_by", "hop",
        ):
            with self.subTest(new_field):
                self.assertNotIn(new_field, payload)
        self.assertEqual(payload["protocol_version"], PROTOCOL_VERSION)

    def test_a_retraction_without_the_new_fields_still_applies(self) -> None:
        """A 0.3.0 peer's wire format, parsed by this code."""
        origin, recipient = self._pair()
        memory_id = origin.remember(agent_id="ag", content="valve 7 is upstream")
        imported = offer(origin, memory_id, recipient, "ag-b", activate=True)
        self.assertTrue(imported.accepted, imported.reasons)
        retraction = origin.request_retraction(
            memory_id, reason="contradicted", recipients=[recipient.store_id],
            basis="contradicted",
        )

        # Round-trip through the minimal 0.3.0 field set.
        legacy_payload = {
            key: value
            for key, value in retraction.to_json().items()
            if key
            in {
                "retraction_id", "origin_store_id", "origin_memory_id",
                "origin_memory_version", "origin_sequence", "reason_code",
                "requested_by", "issued_at", "protocol_version",
            }
        }
        rebuilt = Retraction.from_json(legacy_payload)
        self.assertEqual(rebuilt.hop, 0)
        self.assertEqual(rebuilt.applies_to_store, retraction.origin_store_id)

        ack = recipient.receive_retraction(rebuilt)
        self.assertIs(ack.state, PropagationState.ENFORCED)
        self.assertIs(
            recipient.get(imported.imported_memory_id).lifecycle_state,
            LifecycleState.QUARANTINED,
        )

    def test_an_unsupported_protocol_version_is_refused(self) -> None:
        from memory_fabric.protocol import ProtocolError

        origin, _ = self._pair()
        memory_id = origin.remember(agent_id="ag", content="valve 7 is upstream")
        retraction = origin.request_retraction(
            memory_id, reason="contradicted", recipients=["st_peer"],
        )
        payload = {**retraction.to_json(), "protocol_version": 99}
        with self.assertRaises(ProtocolError):
            Retraction.from_json(payload)

    def test_the_schema_version_is_not_the_protocol_version(self) -> None:
        """They move independently, and conflating them would force a protocol
        bump on every storage change."""
        self.assertNotEqual(str(PROTOCOL_VERSION), SCHEMA_VERSION)
        self.assertEqual(PROTOCOL_VERSION, 1)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
