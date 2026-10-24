"""Signed action receipts: verifiable by anyone with the public key."""

from __future__ import annotations

import base64
import copy
import json
import os
import tempfile
import unittest
from io import StringIO
from unittest import mock

try:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: F401
    HAVE_CRYPTO = True
except Exception:  # noqa: BLE001
    HAVE_CRYPTO = False

from memory_fabric import MemoryFabric
from memory_fabric.actions import ActionGate, ActionPolicy, ActionRequest, ToolRule
from memory_fabric.cli import main


@unittest.skipUnless(HAVE_CRYPTO, "cryptography not installed")
class ActionReceipts(unittest.TestCase):
    def setUp(self) -> None:
        from memory_fabric.action_receipt import generate_key

        self.f = MemoryFabric(auto_activate=True)
        self.addCleanup(self.f.close)
        self.gauge = self.f.remember("ag_field", "Valve V-7 pressure reads 4 bar.", scope="team")
        self.f.validate(self.gauge, actor="supervisor")
        self.private, self.public = generate_key()
        self.gate = ActionGate(self.f, ActionPolicy(tools={"open_valve": ToolRule("open_valve")},
                                                    grants={"ag_ops": frozenset({"open_valve"})}))
        self.request = ActionRequest("valve V-7", {"position": "open", "operator": "night shift"})

    def receipt(self):
        from memory_fabric.action_receipt import issue

        cert = self.f.certify("open-valve-7", [self.gauge], "ag_ops")
        decision = self.gate.authorize("open_valve", "ag_ops", cert, request=self.request)
        return issue(self.f, decision, self.private, certificate=cert, request=self.request)

    def test_a_receipt_verifies_with_the_public_key_alone(self) -> None:
        from memory_fabric.action_receipt import verify_receipt

        doc = self.receipt()
        verify_receipt(json.loads(json.dumps(doc)), self.public)
        self.assertTrue(doc["decision"]["allowed"])
        self.assertEqual(doc["evidence"][0]["memory_id"], self.gauge)

    def test_it_carries_hashes_never_content_or_parameters(self) -> None:
        text = json.dumps(self.receipt())
        self.assertNotIn("4 bar", text)
        self.assertNotIn("night shift", text)

    def test_any_alteration_is_detected(self) -> None:
        from memory_fabric.action_receipt import ReceiptInvalid, verify_receipt

        doc = self.receipt()
        for path in (("decision", "allowed"), ("action", "tool"), ("log", "seq")):
            forged = copy.deepcopy(doc)
            node = forged
            for key in path[:-1]:
                node = node[key]
            node[path[-1]] = {"allowed": False, "tool": "drain_tank", "seq": 1}[path[-1]]
            with self.assertRaises(ReceiptInvalid, msg=path):
                verify_receipt(forged, self.public)

    def test_a_different_trusted_key_is_refused(self) -> None:
        from memory_fabric.action_receipt import ReceiptInvalid, generate_key, verify_receipt

        _, other = generate_key()
        with self.assertRaises(ReceiptInvalid):
            verify_receipt(self.receipt(), other)

    def test_a_refusal_is_receipted_too(self) -> None:
        from memory_fabric.action_receipt import issue, verify_receipt

        cert = self.f.certify("open-valve-7", [self.gauge], "ag_ops")
        self.f.quarantine(self.gauge, reason="miscalibrated", basis="contradicted")
        decision = self.gate.authorize("open_valve", "ag_ops", cert)
        doc = issue(self.f, decision, self.private, certificate=cert)
        verify_receipt(doc, self.public)
        self.assertFalse(doc["decision"]["allowed"])
        self.assertEqual(doc["evidence"][0]["lifecycle_state"], "quarantined")

    def test_against_the_store(self) -> None:
        from memory_fabric.action_receipt import verify_against_store

        doc = self.receipt()
        self.assertEqual(verify_against_store(doc, self.f), [])
        other = MemoryFabric()
        self.addCleanup(other.close)
        self.assertTrue(verify_against_store(doc, other))

    def test_cli_verifies_without_a_store(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = os.path.join(tmp.name, "r.json")
        doc = self.receipt()
        with open(path, "w") as fh:
            json.dump(doc, fh)
        key = base64.b64encode(self.public).decode()
        with mock.patch("sys.stdout", StringIO()) as out:
            self.assertEqual(main(["receipt-verify", path, "--public-key", key]), 0)
        self.assertIn("ALLOWED", out.getvalue())
        doc["decision"]["allowed"] = False
        with open(path, "w") as fh:
            json.dump(doc, fh)
        with mock.patch("sys.stdout", StringIO()):
            self.assertEqual(main(["receipt-verify", path, "--public-key", key]), 5)


if __name__ == "__main__":
    unittest.main()
