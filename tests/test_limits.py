"""Store-level resource limits: payload, per-agent write quota, per-peer federation budget."""

from __future__ import annotations

import unittest

from memory_fabric import MemoryFabric
from memory_fabric.federation import offer
from memory_fabric.governance.firewall import (Firewall, rule_capabilities_must_be_granted,
                                               rule_must_be_active, rule_restricted_stays_private)
from memory_fabric.limits import LimitExceeded, Limits
from memory_fabric.model import Scope


class Clock:
    def __init__(self) -> None:
        self.t = 10_000

    def __call__(self) -> int:
        return self.t


class StoreLimits(unittest.TestCase):
    def test_an_oversized_payload_is_refused(self) -> None:
        f = MemoryFabric(":memory:", limits=Limits(max_content_bytes=100))
        self.addCleanup(f.close)
        with self.assertRaises(LimitExceeded) as caught:
            f.remember("a", "x" * 101)
        self.assertEqual(caught.exception.code, "payload_too_large")
        self.assertEqual(len(f.state.memories), 0)

    def test_the_write_quota_is_per_agent_and_recovers(self) -> None:
        clock = Clock()
        f = MemoryFabric(":memory:", clock=clock,
                         limits=Limits(writes_per_window=3, window_ms=1_000))
        self.addCleanup(f.close)
        for i in range(3):
            f.remember("loop", f"note {i}")
        with self.assertRaises(LimitExceeded) as caught:
            f.remember("loop", "note 3")
        self.assertEqual(caught.exception.code, "write_quota_exhausted")
        f.remember("other", "unaffected")
        clock.t += 1_000
        f.remember("loop", "note 4")

    def test_a_peer_cannot_flood_a_recipient(self) -> None:
        rules = (rule_restricted_stays_private, rule_must_be_active,
                 rule_capabilities_must_be_granted)
        origin = MemoryFabric(":memory:", auto_activate=True, firewall=Firewall(rules=rules))
        target = MemoryFabric(":memory:", firewall=Firewall(rules=rules),
                              limits=Limits(imports_per_window=2))
        self.addCleanup(origin.close)
        self.addCleanup(target.close)
        ids = [origin.remember("a", f"distinct fact number {i} about pump {i}", scope="team")
               for i in range(3)]
        for m in ids:
            origin.share(m, Scope.FEDERATED, actor="op")
        offer(origin, ids[0], target, recipient_agent="x")
        offer(origin, ids[1], target, recipient_agent="x")
        with self.assertRaises(LimitExceeded) as caught:
            offer(origin, ids[2], target, recipient_agent="x")
        self.assertEqual(caught.exception.code, "federation_budget_exhausted")
        target.remember("local", "a local write still works")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
