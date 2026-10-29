"""S5: a correction receipt proves enforcement, reveals nothing else, and binds at audit."""

from __future__ import annotations

import unittest

from amberlog import Amberlog
from amberlog.federation import offer
from amberlog.governance.firewall import (Firewall, rule_capabilities_must_be_granted,
                                               rule_must_be_active, rule_restricted_stays_private)
from amberlog.model import Scope
from amberlog.receipts import (CorrectionReceipt, ReceiptError, audit, authentic, issue)

PEER = b"peer-key-shared-with-origin"
BINDING = b"recipient-only-binding-key"


def store() -> Amberlog:
    return Amberlog(":memory:", auto_activate=True, firewall=Firewall(rules=(
        rule_restricted_stays_private, rule_must_be_active, rule_capabilities_must_be_granted)))


class Receipts(unittest.TestCase):
    def setUp(self) -> None:
        self.origin, self.recipient = store(), store()
        self.addCleanup(self.origin.close)
        self.addCleanup(self.recipient.close)
        self.mid = self.origin.remember("ana", "valve A runs at 4 bar", scope="team")
        self.origin.share(self.mid, Scope.FEDERATED, actor="op")
        self.copy = offer(self.origin, self.mid, self.recipient, recipient_agent="x",
                          activate=True).imported_memory_id
        self.retraction = self.origin.request_retraction(
            self.mid, reason="wrong", recipients=[self.recipient.store_id], actor="op")
        self.ack = self.recipient.receive_retraction(self.retraction)

    def receipt(self) -> CorrectionReceipt:
        return issue(self.recipient, self.retraction.retraction_id, binding_key=BINDING,
                     peer_key=PEER)

    def test_it_is_authentic_and_holds_up_at_audit(self) -> None:
        receipt = self.receipt()
        self.assertTrue(authentic(receipt, PEER))
        self.assertFalse(authentic(receipt, b"someone else"))
        result = audit(self.recipient, receipt, BINDING)
        self.assertTrue(result.ok, result.reasons)

    def test_it_says_nothing_the_acknowledgement_does(self) -> None:
        receipt = self.receipt().to_json()
        self.assertIn("withdrawn", self.ack.detail)  # the leak this replaces
        self.assertEqual(set(receipt), {"version", "retraction_id", "origin_store_id",
                                        "recipient_store_id", "state", "commitment", "tag"})
        self.assertNotIn(self.copy, str(receipt))

    def test_a_forged_commitment_fails_audit(self) -> None:
        receipt = self.receipt()
        forged = CorrectionReceipt(**{**receipt.__dict__, "commitment": "0" * 64})
        self.assertFalse(audit(self.recipient, forged, BINDING).ok)

    def test_a_recipient_that_never_applied_it_cannot_issue_or_pass(self) -> None:
        other = store()
        self.addCleanup(other.close)
        with self.assertRaises(ReceiptError):
            issue(other, self.retraction.retraction_id, binding_key=BINDING, peer_key=PEER)
        claimed = CorrectionReceipt(**{**self.receipt().__dict__,
                                       "recipient_store_id": other.store_id})
        self.assertFalse(audit(other, claimed, BINDING).ok)

    def test_re_activating_the_copy_afterwards_is_reported(self) -> None:
        receipt = self.receipt()
        self.recipient.release(self.copy, actor="op")
        if self.recipient.get(self.copy).lifecycle_state.value != "active":
            self.recipient.validate(self.copy, actor="op")
        result = audit(self.recipient, receipt, BINDING)
        self.assertTrue(result.ok, "it was enforced at the receipt's log point")
        self.assertEqual(result.reactivated_since, [self.copy])
        with self.assertRaises(ReceiptError):
            self.receipt()

    def test_receipts_are_the_same_size_whatever_the_recipient_did(self) -> None:
        small = self.receipt()
        for i in range(30):
            self.recipient.remember("busy", f"unrelated note {i}", scope="team")
        mid2 = self.origin.remember("ana", "valve B runs at 6 bar", scope="team")
        self.origin.share(mid2, Scope.FEDERATED, actor="op")
        offer(self.origin, mid2, self.recipient, recipient_agent="x", activate=True)
        offer(self.origin, mid2, self.recipient, recipient_agent="y", activate=True)
        second = self.origin.request_retraction(mid2, reason="wrong",
                                                recipients=[self.recipient.store_id], actor="op")
        self.recipient.receive_retraction(second)
        big = issue(self.recipient, second.retraction_id, binding_key=BINDING, peer_key=PEER)
        self.assertEqual(len(str(small.to_json())), len(str(big.to_json())))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
