"""The lifecycle center finds what it says it finds, and writes nothing."""

from __future__ import annotations

import unittest

from amberlog import Amberlog
from amberlog.governance.firewall import Firewall
from amberlog.lifecycle import DAY_MS, center
from amberlog.model import Scope

T0 = 1_800_000_000_000


class Clocked(unittest.TestCase):
    def setUp(self) -> None:
        self.now = [T0]
        self.fabric = Amberlog(":memory:", auto_activate=True, clock=lambda: self.now[0])
        self.addCleanup(self.fabric.close)

    def at(self, days: float) -> None:
        self.now[0] = T0 + int(days * DAY_MS)

    def ids(self, items: list) -> list[str]:
        return [i["memory_id"] for i in items]


class Finders(Clocked):
    def test_stale_means_nobody_was_shown_it(self) -> None:
        idle = self.fabric.remember("ana", "pump 3 needs a new seal kit", scope="team")
        used = self.fabric.remember("ana", "valve 7 sticks below freezing", scope="team")
        self.at(95)
        self.fabric.retrieve("ben", "valve 7 sticks")
        self.at(100)
        stale = self.ids(center(self.fabric, stale_days=30, now_ms=self.now[0])["stale"])
        self.assertIn(idle, stale)
        self.assertNotIn(used, stale)

    def test_a_candidate_waiting_past_the_policy_is_listed(self) -> None:
        mid = self.fabric.remember("ana", "unreviewed claim", auto_activate=False)
        self.at(3)
        self.assertEqual(center(self.fabric, now_ms=self.now[0])["waiting_for_review"], [])
        self.at(20)
        self.assertEqual(self.ids(center(self.fabric, now_ms=self.now[0])["waiting_for_review"]), [mid])

    def test_a_readable_secret_is_listed_until_erased(self) -> None:
        mid = self.fabric.remember("ana", "deploy key " + "AKIA" + "QWER" * 4)
        data = center(self.fabric)
        self.assertEqual(self.ids(data["sensitive"]["readable_secrets"]), [mid])
        self.fabric.erase_content(mid, reason="leaked credential", actor="dpo")
        data = center(self.fabric)
        self.assertEqual(data["sensitive"]["readable_secrets"], [])
        self.assertEqual([(e["memory_id"], e["actor"]) for e in data["deletions"]["erased"]],
                         [(mid, "dpo")])

    def test_screens_that_improved_catch_what_they_missed(self) -> None:
        class Blind:
            def scan(self, content: str) -> list:
                return []

        self.fabric.firewall = Firewall(detector=Blind())
        mid = self.fabric.remember("ana", "deploy key " + "AKIA" + "QWER" * 4)
        self.assertEqual(center(self.fabric)["sensitive"]["flagged_by_current_screens"], [])
        self.fabric.firewall = Firewall()
        flagged = center(self.fabric)["sensitive"]["flagged_by_current_screens"]
        self.assertEqual(self.ids(flagged), [mid])

    def test_it_writes_nothing(self) -> None:
        self.fabric.remember("ana", "pump 3 needs a new seal kit")
        before = self.fabric.log.head_seq
        center(self.fabric)
        self.assertEqual(self.fabric.log.head_seq, before)


class Propagation(unittest.TestCase):
    def test_outstanding_until_the_store_confirms(self) -> None:
        from amberlog.correction import apply
        from amberlog.dispatcher import Dispatcher
        from amberlog.federation import offer
        from amberlog.governance.firewall import (rule_capabilities_must_be_granted,
                                                       rule_must_be_active,
                                                       rule_restricted_stays_private)
        from amberlog.transport import InProcessTransport, Peer, PeerRegistry

        permissive = Firewall(rules=(rule_restricted_stays_private, rule_must_be_active,
                                     rule_capabilities_must_be_granted))
        origin = Amberlog(":memory:", firewall=permissive, auto_activate=True)
        recipient = Amberlog(":memory:", firewall=permissive)
        self.addCleanup(origin.close)
        self.addCleanup(recipient.close)
        mid = origin.remember("ana", "tug tyre pressure is 3.5 bar")
        origin.share(mid, Scope.FEDERATED, actor="op")
        offer(origin, mid, recipient, recipient_agent="ben")
        apply(origin, mid, reason="bulletin", actor="carol")
        row = center(origin)["deletions"]["propagation"][0]
        self.assertEqual(row["outstanding"], [recipient.store_id])
        registry = PeerRegistry({origin.store_id: Peer(origin.store_id, "x", b"k")})
        Dispatcher(origin, InProcessTransport({recipient.store_id: recipient},
                                              registry=registry)).run_once()
        row = center(origin)["deletions"]["propagation"][0]
        self.assertEqual((row["confirmed"], row["outstanding"]), ([recipient.store_id], []))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
