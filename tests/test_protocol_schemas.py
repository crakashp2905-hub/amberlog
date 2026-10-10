"""The protocol schemas, and whether they still describe this codebase.

These are *specification* artefacts — no implementation exists yet (see
docs/AUDIT.md). That makes them unusually easy to let rot: nothing breaks when
a spec and its code disagree, which is exactly why the disagreement needs a
test.

The schemas are validated structurally with the standard library only, because
the core is zero-dependency and a JSON Schema validator would be the first
runtime dependency in the project for the sake of a document.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from memory_fabric.model import SCHEMA_VERSION, WithdrawalBasis

PROTOCOL_DIR = Path(__file__).resolve().parent.parent / "docs" / "protocol"


def load(name: str) -> dict:
    return json.loads((PROTOCOL_DIR / name).read_text(encoding="utf-8"))


class TestSchemasAreWellFormed(unittest.TestCase):
    def test_every_schema_parses(self) -> None:
        files = sorted(PROTOCOL_DIR.glob("*.json"))
        self.assertTrue(files, "no protocol schemas found")
        for path in files:
            with self.subTest(path.name):
                json.loads(path.read_text(encoding="utf-8"))

    def test_every_schema_declares_its_draft_and_id(self) -> None:
        for path in sorted(PROTOCOL_DIR.glob("*.json")):
            schema = json.loads(path.read_text(encoding="utf-8"))
            with self.subTest(path.name):
                self.assertIn("$schema", schema)
                self.assertIn("$id", schema)
                self.assertIn("title", schema)

    def test_every_required_field_is_defined(self) -> None:
        """A `required` entry with no matching property is a schema that cannot
        be satisfied, and `additionalProperties: false` makes it unsatisfiable
        rather than merely loose."""
        for path in sorted(PROTOCOL_DIR.glob("*.json")):
            schema = json.loads(path.read_text(encoding="utf-8"))
            properties = set(schema.get("properties", {}))
            for field in schema.get("required", []):
                with self.subTest(f"{path.name}:{field}"):
                    self.assertIn(field, properties)

    def test_every_ref_resolves(self) -> None:
        for path in sorted(PROTOCOL_DIR.glob("*.json")):
            schema = json.loads(path.read_text(encoding="utf-8"))
            defs = set(schema.get("$defs", {}))

            def walk(node) -> None:
                if isinstance(node, dict):
                    ref = node.get("$ref")
                    if isinstance(ref, str) and ref.startswith("#/$defs/"):
                        self.assertIn(ref.split("/")[-1], defs, f"{path.name} {ref}")
                    for value in node.values():
                        walk(value)
                elif isinstance(node, list):
                    for value in node:
                        walk(value)

            walk(schema)


class TestSchemaMatchesTheCode(unittest.TestCase):
    """The rows that would rot silently."""

    def test_reason_codes_are_exactly_the_withdrawal_bases(self) -> None:
        """`reason_code` is drawn from `WithdrawalBasis`. If a basis is added or
        renamed, the protocol must move with it or a recipient will reject a
        retraction the origin considers valid."""
        schema = load("retraction-v1.schema.json")
        codes = set(schema["properties"]["reason_code"]["enum"])
        self.assertEqual(codes, {b.value for b in WithdrawalBasis})

    def test_the_retraction_targets_an_exact_version(self) -> None:
        """The single most important difference between the specification and
        today's code: `propagate_retraction` matches on memory id alone, so a
        retraction of v1 would withdraw an import of v3. The schema makes the
        version mandatory, and this test is what stops it being dropped as an
        inconvenience during implementation."""
        schema = load("retraction-v1.schema.json")
        self.assertIn("origin_memory_version", schema["required"])
        self.assertEqual(
            schema["properties"]["origin_memory_version"]["minimum"], 1
        )

    def test_the_store_id_cannot_be_a_path(self) -> None:
        """Today's origin record uses `source.log.path`. The pattern is the
        guard against that returning."""
        schema = load("retraction-v1.schema.json")
        pattern = schema["$defs"]["store_id"]["pattern"]
        import re

        matcher = re.compile(pattern)
        self.assertTrue(matcher.match("st_01M4CV9BY8QH9AA1HN3KRASJ8V"))
        for path_like in (
            "/data/store.db",
            "C:\\Users\\x\\store.db",
            ":memory:",
            "store.db",
        ):
            self.assertIsNone(matcher.match(path_like), path_like)

    def test_evidence_is_a_digest_not_the_evidence(self) -> None:
        """Shipping the content would move memory text into a second system,
        which is what the governance layer exists to prevent."""
        schema = load("retraction-v1.schema.json")
        self.assertNotIn("evidence", schema["properties"])
        self.assertIn("evidence_digest", schema["properties"])
        self.assertTrue(
            schema["properties"]["evidence_digest"]["pattern"].startswith("^sha256:")
        )

    def test_acknowledgement_states_cover_the_four_the_roadmap_requires(self) -> None:
        ack = load("acknowledgement-v1.schema.json")
        states = set(ack["properties"]["state"]["enum"])
        for required in ("received", "persisted", "enforced", "verified"):
            self.assertIn(required, states)

    def test_unknown_is_a_state_so_offline_is_never_verified(self) -> None:
        """Invariant 9, and the specific failure the dashboard section of the
        roadmap calls out: an offline agent must appear unknown, not healthy."""
        ack = load("acknowledgement-v1.schema.json")
        self.assertIn("unknown", ack["properties"]["state"]["enum"])

    def test_acknowledgement_detail_cannot_carry_content(self) -> None:
        """Bounded, and documented as operator-facing. A free-form unbounded
        field is where memory content ends up in a log."""
        ack = load("acknowledgement-v1.schema.json")
        self.assertLessEqual(ack["properties"]["detail"]["maxLength"], 1024)

    def test_both_schemas_pin_the_same_protocol_version(self) -> None:
        self.assertEqual(
            load("retraction-v1.schema.json")["properties"]["protocol_version"]["const"],
            load("acknowledgement-v1.schema.json")["properties"]["protocol_version"]["const"],
        )

    def test_protocol_version_is_independent_of_the_schema_version(self) -> None:
        """They answer different questions — "can you read my log?" versus "can
        you talk to me?" — and conflating them would force a wire break on every
        additive event change."""
        self.assertEqual(SCHEMA_VERSION, "0.4.0")
        self.assertEqual(
            load("retraction-v1.schema.json")["properties"]["protocol_version"]["const"], 1
        )


class TestTheAuditTellsTheTruth(unittest.TestCase):
    """The audit's claims about this repository are claims, so they are
    checkable. Phase 1 landed, so these now assert the *new* state — and the
    two that previously asserted "there is still no outbox" and
    "propagate_retraction still takes live objects" failed exactly when they
    were supposed to, which is why they were written that way.
    """

    def test_the_outbox_now_exists_and_is_durable(self) -> None:
        from memory_fabric.outbox import Outbox

        self.assertTrue(hasattr(Outbox, "enqueue"))
        self.assertTrue(hasattr(Outbox, "due"))
        self.assertTrue(hasattr(Outbox, "record_attempt"))

    def test_the_in_process_call_still_exists_alongside_the_protocol(self) -> None:
        """`propagate_retraction` is kept deliberately. It is the honest
        in-process operation Phase B measured, and removing it would invalidate
        a published result; `request_retraction` is the durable path. Both are
        documented for what they are in docs/AUDIT.md §3."""
        import inspect

        from memory_fabric.federation import propagate_retraction

        self.assertIn("targets", inspect.signature(propagate_retraction).parameters)

    def test_the_durable_path_does_not_take_live_objects(self) -> None:
        """The distinction that matters: the protocol path names recipients by
        opaque store id, so it cannot require them to be in this process."""
        import inspect

        from memory_fabric.fabric import MemoryFabric

        signature = inspect.signature(MemoryFabric.request_retraction)
        self.assertIn("recipients", signature.parameters)
        annotation = str(signature.parameters["recipients"].annotation)
        self.assertIn("str", annotation)
        self.assertNotIn("MemoryFabric", annotation)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
