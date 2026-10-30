"""Strict freshness: leases, partitions, delayed revocation, forged and replayed leases."""

from __future__ import annotations

import os
import tempfile
import unittest

from memory_fabric import MemoryFabric
from memory_fabric.actions import EVIDENCE_NOT_FRESH, ActionGate, ActionPolicy, ToolRule
from memory_fabric.federation import offer
from memory_fabric.governance.firewall import (Firewall, rule_capabilities_must_be_granted,
                                               rule_must_be_active, rule_restricted_stays_private)
from memory_fabric.freshness import (BAD_SIGNATURE, EXPIRED, FRESH, LOCAL, NO_LEASE,
                                     UNKNOWN_KEY, VERSION_MISMATCH, WITHDRAWN, FreshnessLease,
                                     LeaseBook, freshness_of, issue_lease)

KEY, OLD_KEY, ROGUE = b"k" * 32, b"o" * 32, b"r" * 32


def permissive() -> Firewall:
    """Sharing without value evidence, as the federation tests do."""
    return Firewall(rules=[rule_must_be_active, rule_restricted_stays_private,
                           rule_capabilities_must_be_granted])


class Clock:
    def __init__(self) -> None:
        self.t = 1_000_000

    def __call__(self) -> int:
        self.t += 1
        return self.t


class Federation(unittest.TestCase):
    def setUp(self) -> None:
        self.clock = Clock()
        self.origin = MemoryFabric(auto_activate=True, clock=self.clock, firewall=permissive())
        self.peer = MemoryFabric(auto_activate=True, clock=self.clock, firewall=permissive())
        self.addCleanup(self.origin.close)
        self.addCleanup(self.peer.close)
        self.src = self.origin.remember("ag_field", "Valve V-7 pressure reads 4 bar.", scope="federated")
        self.origin.validate(self.src, actor="supervisor")
        result = offer(self.origin, self.src, self.peer, "ag_ops", activate=True)
        self.assertTrue(result.accepted, result)
        self.imported = result.imported_memory_id
        self.book = LeaseBook({self.origin.store_id: {"k1": KEY}})
        self.gate = ActionGate(self.peer, ActionPolicy(
            tools={"open_valve": ToolRule("open_valve", require_fresh=True, min_authority="untrusted"),
                   "lenient": ToolRule("lenient", min_authority="untrusted")},
            grants={"ag_ops": frozenset({"open_valve", "lenient"})}), leases=self.book)

    def authorize(self, tool: str = "open_valve"):
        cert = self.peer.certify("open-7", [self.imported], "ag_ops")
        return self.gate.authorize(tool, "ag_ops", cert)

    def lease(self, ttl: float = 60.0, key: bytes = KEY, key_id: str = "k1") -> FreshnessLease:
        return issue_lease(self.origin, self.src, ttl, key, key_id)

    # --- the basic contract ---------------------------------------------------

    def test_no_lease_means_strict_refuses_and_lenient_allows(self) -> None:
        self.assertEqual(freshness_of(self.peer, self.imported, self.book), NO_LEASE)
        self.assertIn(EVIDENCE_NOT_FRESH, self.authorize().reason_codes)
        self.assertTrue(self.authorize("lenient").allowed)

    def test_a_valid_lease_allows(self) -> None:
        self.assertIsNone(self.book.accept(self.lease()))
        self.assertEqual(freshness_of(self.peer, self.imported, self.book), FRESH)
        self.assertTrue(self.authorize().allowed)

    def test_native_evidence_is_fresh_without_a_lease(self) -> None:
        native = self.peer.remember("ag_ops", "Valve V-9 pressure reads 2 bar.", scope="team")
        self.assertEqual(freshness_of(self.peer, native, self.book), LOCAL)

    # --- partition and delayed revocation -----------------------------------

    def test_partition_bounds_staleness_to_one_lease_lifetime(self) -> None:
        """Origin withdraws while partitioned: the importer acts until the lease expires, then stops."""
        self.book.accept(self.lease(ttl=10))
        self.origin.quarantine(self.src, reason="gauge miscalibrated", basis="contradicted")
        # No retraction reaches the peer (partition). Within the lease: allowed.
        self.assertTrue(self.authorize().allowed)
        self.clock.t += 11_000
        self.assertEqual(freshness_of(self.peer, self.imported, self.book), EXPIRED)
        self.assertIn(EVIDENCE_NOT_FRESH, self.authorize().reason_codes)

    def test_a_renewal_after_withdrawal_carries_the_withdrawal(self) -> None:
        """The retraction is delayed, but the next lease renewal already says withdrawn."""
        self.book.accept(self.lease())
        self.origin.quarantine(self.src, reason="wrong", basis="contradicted")
        self.book.accept(self.lease())
        self.assertEqual(freshness_of(self.peer, self.imported, self.book), WITHDRAWN)
        self.assertFalse(self.authorize().allowed)

    def test_a_replayed_old_lease_cannot_undo_a_withdrawal(self) -> None:
        old = self.lease()
        self.origin.quarantine(self.src, reason="wrong", basis="contradicted")
        self.book.accept(self.lease())
        self.book.accept(old)  # replay of the earlier "active" lease
        self.assertEqual(freshness_of(self.peer, self.imported, self.book), WITHDRAWN)

    # --- forged, rogue and mismatched leases --------------------------------

    def test_a_forged_lease_is_rejected(self) -> None:
        forged = self.lease(key=ROGUE)
        self.assertEqual(self.book.accept(forged), BAD_SIGNATURE)
        self.assertEqual(freshness_of(self.peer, self.imported, self.book), NO_LEASE)

    def test_a_compromised_peer_cannot_vouch_for_another_store(self) -> None:
        rogue = MemoryFabric(auto_activate=True, clock=self.clock)
        self.addCleanup(rogue.close)
        self.book.peer_keys[rogue.store_id] = {"k1": ROGUE}
        fake = FreshnessLease(rogue.store_id, self.src, 1, self.clock(), self.clock.t + 60_000)
        self.assertIsNone(self.book.accept(fake.signed(ROGUE)))
        # It verifies under the rogue's own key, but it is about the rogue's
        # store, not the origin's, so it says nothing about this import.
        self.assertEqual(freshness_of(self.peer, self.imported, self.book), NO_LEASE)

    def test_a_lease_for_another_version_does_not_count(self) -> None:
        self.origin.revise(self.src, "Valve V-7 pressure reads 5 bar.", "ag_field", reason="recal")
        self.book.accept(self.lease())
        self.assertEqual(freshness_of(self.peer, self.imported, self.book), VERSION_MISMATCH)

    def test_key_rotation_with_an_overlap_window(self) -> None:
        self.book.peer_keys[self.origin.store_id] = {"k2": KEY, "k1": OLD_KEY}
        self.assertIsNone(self.book.accept(self.lease(key=OLD_KEY, key_id="k1")))
        self.assertTrue(self.authorize().allowed)
        del self.book.peer_keys[self.origin.store_id]["k1"]  # overlap ends
        self.assertEqual(freshness_of(self.peer, self.imported, self.book), UNKNOWN_KEY)
        self.assertIsNone(self.book.accept(self.lease(key=KEY, key_id="k2")))
        self.assertEqual(freshness_of(self.peer, self.imported, self.book), FRESH)

    def test_tampering_with_a_held_lease_is_detected(self) -> None:
        good = self.lease()
        self.book.accept(good)
        from dataclasses import replace
        self.book._leases[(good.origin_store_id, good.memory_id)] = replace(
            good, expires_ms=good.expires_ms + 10**9)
        self.assertEqual(freshness_of(self.peer, self.imported, self.book), BAD_SIGNATURE)

    def test_saved_leases_are_re_verified_on_load(self) -> None:
        self.book.accept(self.lease())
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = os.path.join(tmp.name, "leases.json")
        self.book.save(path)
        fresh = LeaseBook({self.origin.store_id: {"k1": KEY}})
        self.assertEqual(fresh.load(path), 1)
        wrong_keys = LeaseBook({self.origin.store_id: {"k1": ROGUE}})
        self.assertEqual(wrong_keys.load(path), 0)

    def test_restart_without_leases_fails_safe(self) -> None:
        self.book.accept(self.lease())
        self.gate.leases = None  # a restart that did not load the book
        self.assertIn(EVIDENCE_NOT_FRESH, self.authorize().reason_codes)


if __name__ == "__main__":
    unittest.main()
