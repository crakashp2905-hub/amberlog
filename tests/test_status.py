"""The four status labels: each one true only when its own fact holds.

Mostly negative cases, because the failure that matters is a label that
claims more than the log shows: "reviewed" for something auto-activated or
revised since, "policy-checked" for something a screen quarantined,
"verified in destination" before every owed store has confirmed.
"""

from __future__ import annotations

import unittest

from memory_fabric import MemoryFabric, WithdrawalBasis
from memory_fabric.status import labels, labels_for


def by_key(fabric: MemoryFabric, memory_id: str) -> dict:
    return {label.key: label for label in labels(fabric, memory_id)}


class Labels(unittest.TestCase):
    def setUp(self) -> None:
        self.fabric = MemoryFabric(":memory:")
        self.addCleanup(self.fabric.close)

    def test_every_label_says_what_it_does_not_establish(self) -> None:
        mid = self.fabric.remember("a", "valve 7 sticks when cold")
        for label in labels(self.fabric, mid):
            with self.subTest(label=label.key):
                self.assertTrue(label.means and label.does_not_mean and label.detail)

    def test_source_recorded_names_the_author(self) -> None:
        mid = self.fabric.remember("agent-7", "valve 7 sticks when cold")
        label = by_key(self.fabric, mid)["source_recorded"]
        self.assertTrue(label.established)
        self.assertIn("agent-7", label.detail)

    def test_a_candidate_is_not_reviewed(self) -> None:
        mid = self.fabric.remember("a", "valve 7 sticks when cold")
        self.assertFalse(by_key(self.fabric, mid)["reviewed"].established)

    def test_validation_by_a_person_is_review(self) -> None:
        mid = self.fabric.remember("a", "valve 7 sticks when cold")
        self.fabric.validate(mid, actor="alice")
        label = by_key(self.fabric, mid)["reviewed"]
        self.assertTrue(label.established)
        self.assertIn("alice", label.detail)

    def test_auto_activation_is_not_review(self) -> None:
        mid = self.fabric.remember("a", "valve 7 sticks when cold", auto_activate=True)
        label = by_key(self.fabric, mid)["reviewed"]
        self.assertFalse(label.established)
        self.assertIn("without review", label.detail)

    def test_trusted_local_is_not_review(self) -> None:
        mid = self.fabric.remember("a", "valve 7 sticks when cold", auto_activate=True,
                                   context={"activation": "trusted-local"})
        self.assertFalse(by_key(self.fabric, mid)["reviewed"].established)

    def test_a_revision_needs_its_own_review(self) -> None:
        mid = self.fabric.remember("a", "valve 7 sticks when cold")
        self.fabric.validate(mid, actor="alice")
        self.fabric.revise(mid, "valve 7 sticks below 4 C", agent_id="a", reason="sharper")
        label = by_key(self.fabric, mid)["reviewed"]
        self.assertFalse(label.established)
        self.fabric.validate(mid, actor="bob")
        self.assertTrue(by_key(self.fabric, mid)["reviewed"].established)

    def test_a_screen_quarantine_fails_the_policy_check(self) -> None:
        key = "AKIA" + "QWER" * 4  # assembled so the repository's own scan does not flag it
        mid = self.fabric.remember("a", f"deploy with key {key}")
        self.assertFalse(by_key(self.fabric, mid)["policy_checked"].established)

    def test_a_clean_write_passes_the_policy_check(self) -> None:
        mid = self.fabric.remember("a", "valve 7 sticks when cold")
        label = by_key(self.fabric, mid)["policy_checked"]
        self.assertTrue(label.established)
        self.assertIn("known patterns", label.does_not_mean)

    def test_nothing_to_verify_without_a_destination(self) -> None:
        mid = self.fabric.remember("a", "valve 7 sticks when cold")
        self.assertIsNone(by_key(self.fabric, mid)["verified_in_destination"].established)

    def test_labels_for_many_matches_one_at_a_time(self) -> None:
        ids = [self.fabric.remember("a", f"fact {i} about pump {i}") for i in range(5)]
        self.fabric.validate(ids[0], actor="alice")
        many = labels_for(self.fabric, ids)
        for mid in ids:
            self.assertEqual(many[mid], labels(self.fabric, mid))


class VerifiedInDestination(unittest.TestCase):
    def test_it_holds_only_after_the_recipient_reports_enforcement(self) -> None:
        from memory_fabric.dispatcher import Dispatcher
        from memory_fabric.federation import offer
        from memory_fabric.governance.firewall import (Firewall, rule_capabilities_must_be_granted,
                                                       rule_must_be_active,
                                                       rule_restricted_stays_private)
        from memory_fabric.transport import InProcessTransport, Peer, PeerRegistry

        permissive = Firewall(rules=(rule_restricted_stays_private, rule_must_be_active,
                                     rule_capabilities_must_be_granted))
        origin = MemoryFabric(":memory:", firewall=permissive)
        recipient = MemoryFabric(":memory:", firewall=permissive)
        self.addCleanup(origin.close)
        self.addCleanup(recipient.close)
        source = origin.remember("ag_n", "Tug tyre pressure is 3.5 bar in winter.")
        origin.validate(source, actor="supervisor")
        offer(origin, source, recipient, recipient_agent="ag_s")
        origin.request_retraction(source, reason="bulletin: 2.8 bar",
                                  recipients=[recipient.store_id], actor="ag_n",
                                  basis=WithdrawalBasis.CONTRADICTED)
        before = by_key(origin, source)["verified_in_destination"]
        self.assertFalse(before.established, "owed but not yet delivered")
        registry = PeerRegistry({origin.store_id: Peer(origin.store_id, "x", b"k")})
        Dispatcher(origin, InProcessTransport({recipient.store_id: recipient},
                                              registry=registry)).run_once()
        after = by_key(origin, source)["verified_in_destination"]
        self.assertTrue(after.established)
        self.assertIn("self-reported", after.detail)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
