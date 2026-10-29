"""Reach keeps permission, history and copies apart."""

from __future__ import annotations

import unittest

from amberlog import Amberlog
from amberlog.model import Scope
from amberlog.reach import reach


class Reach(unittest.TestCase):
    def setUp(self) -> None:
        self.fabric = Amberlog(":memory:", auto_activate=True)
        self.addCleanup(self.fabric.close)

    def test_private_is_the_writer_only(self) -> None:
        mid = self.fabric.remember("ana", "pump 3 needs a new seal")
        self.assertIn("only ana", reach(self.fabric, mid).may_read)

    def test_team_is_the_tenant(self) -> None:
        mid = self.fabric.remember("ana", "pump 3 needs a new seal", scope="team")
        self.assertIn("every agent in tenant", reach(self.fabric, mid).may_read)

    def test_a_memory_retrieval_refuses_is_readable_by_nobody(self) -> None:
        mid = self.fabric.remember("ana", "pump 3 needs a new seal", scope="team",
                                   auto_activate=False)
        r = reach(self.fabric, mid)
        self.assertFalse(r.readable_now)
        self.assertIn("candidate", r.why_not)

    def test_history_records_who_saw_it_and_who_was_refused(self) -> None:
        mid = self.fabric.remember("ana", "pump 3 needs a new seal")
        self.fabric.retrieve("ana", "pump 3 seal")
        self.fabric.retrieve("ana", "pump 3 seal")
        self.fabric.use(mid, "ben")
        r = reach(self.fabric, mid)
        self.assertEqual(r.seen_by, {"ana": 2})
        self.assertEqual(r.refused, {"ben": 1})

    def test_seeing_it_is_not_undone_by_withdrawing_it(self) -> None:
        mid = self.fabric.remember("ana", "pump 3 needs a new seal")
        self.fabric.retrieve("ana", "pump 3 seal")
        self.fabric.quarantine(mid, reason="wrong", actor="op")
        r = reach(self.fabric, mid)
        self.assertFalse(r.readable_now)
        self.assertEqual(r.seen_by, {"ana": 1})

    def test_other_stores_are_listed_with_the_copys_id(self) -> None:
        from amberlog.federation import offer
        from amberlog.governance.firewall import (Firewall, rule_capabilities_must_be_granted,
                                                       rule_must_be_active,
                                                       rule_restricted_stays_private)

        permissive = Firewall(rules=(rule_restricted_stays_private, rule_must_be_active,
                                     rule_capabilities_must_be_granted))
        origin = Amberlog(":memory:", firewall=permissive, auto_activate=True)
        recipient = Amberlog(":memory:", firewall=permissive)
        self.addCleanup(origin.close)
        self.addCleanup(recipient.close)
        mid = origin.remember("ana", "pump 3 needs a new seal")
        origin.share(mid, Scope.FEDERATED, actor="op")
        imported = offer(origin, mid, recipient, recipient_agent="ben")
        r = reach(origin, mid)
        self.assertEqual([s["store_id"] for s in r.stores], [recipient.store_id])
        self.assertEqual(r.stores[0]["imported_memory_id"], imported.imported_memory_id)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
