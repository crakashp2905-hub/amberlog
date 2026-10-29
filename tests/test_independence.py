"""Evidence independence from exposure (S2): a paraphrase of what you were shown is not a second source."""

from __future__ import annotations

import unittest

from amberlog import Amberlog
from amberlog.federation import offer
from amberlog.governance.firewall import (Firewall, rule_capabilities_must_be_granted,
                                               rule_must_be_active, rule_restricted_stays_private)
from amberlog.independence import Independence, global_ref, independent_sources
from amberlog.model import Scope


def store() -> Amberlog:
    return Amberlog(":memory:", auto_activate=True, firewall=Firewall(rules=(
        rule_restricted_stays_private, rule_must_be_active, rule_capabilities_must_be_granted)))


REPORT = "Pump P4 at the north site is leaking oil from its seal."
PARAPHRASE = "There is an oil leak at the north site: the seal on pump P4 has failed."
OWN = "North site walk-round: pump P4 seal weeping oil, about a cup an hour."


class InOneStore(unittest.TestCase):
    def setUp(self) -> None:
        self.f = store()
        self.addCleanup(self.f.close)
        self.a = self.f.remember("ana", REPORT, scope="team")

    def test_a_paraphrase_by_someone_shown_the_report_is_not_independent(self) -> None:
        shown = self.f.retrieve("ben", "pump P4 north site leak", k=3)
        self.assertIn(self.a, [m.id for m in shown.exposed])
        b = self.f.remember("ben", PARAPHRASE, scope="team")
        self.assertEqual(independent_sources(self.f, [self.a, b]), 1)
        self.assertIn(global_ref(self.f, self.a), Independence(self.f).informed_by(b))

    def test_the_same_words_from_someone_never_shown_it_are_independent(self) -> None:
        b = self.f.remember("cara", PARAPHRASE, scope="team")
        self.assertEqual(independent_sources(self.f, [self.a, b]), 2)

    def test_being_shown_it_afterwards_does_not_reach_back(self) -> None:
        b = self.f.remember("cara", OWN, scope="team")
        self.f.retrieve("cara", "pump P4 north site leak", k=3)
        self.assertEqual(independent_sources(self.f, [self.a, b]), 2)

    def test_a_summary_of_two_real_reports_does_not_merge_them(self) -> None:
        b = self.f.remember("cara", OWN, scope="team")
        self.f.retrieve("dev", "pump P4 north site seal oil", k=5, group_by_source_root=False)
        summary = self.f.remember("dev", "P4 north: seal leaking (two reports).", scope="team")
        self.assertEqual(independent_sources(self.f, [self.a, b, summary]), 2)

    def test_it_is_transitive(self) -> None:
        self.f.retrieve("ben", "pump P4 north site leak", k=3)
        b = self.f.remember("ben", PARAPHRASE, scope="team")
        # dev is shown only ben's paraphrase: ana's report is withdrawn first,
        # so retrieval cannot show it (independence does not look at lifecycle)
        self.f.quarantine(self.a, reason="test", actor="op")
        result = self.f.retrieve("dev", "oil leak seal failed", k=5, group_by_source_root=False)
        self.assertIn(b, [m.id for m in result.exposed])
        self.f.retrieve("dev", "nothing about pumps at all", k=1)
        seen = {r.memory_id for r in self.f.state.exposures if r.agent_id == "dev" and r.exposed}
        c = self.f.remember("dev", "P4's seal has gone at north; oil on the floor.", scope="team")
        self.assertNotIn(self.a, seen)
        self.assertTrue(Independence(self.f).dependent(self.a, c))
        self.assertEqual(independent_sources(self.f, [self.a, b, c]), 1)


class AcrossStores(unittest.TestCase):
    def test_laundering_through_a_second_store_is_still_one_source(self) -> None:
        s0, s1, s2 = store(), store(), store()
        for s in (s0, s1, s2):
            self.addCleanup(s.close)
        a = s0.remember("ana", REPORT, scope="team")
        s0.share(a, Scope.FEDERATED, actor="op")
        a_at_1 = offer(s0, a, s1, recipient_agent="ben", activate=True).imported_memory_id
        a_at_2 = offer(s0, a, s2, recipient_agent="x", activate=True).imported_memory_id
        s1.retrieve("ben", "pump P4 north site leak", k=3)
        p = s1.remember("ben", PARAPHRASE, scope="team")
        s1.share(p, Scope.FEDERATED, actor="op")
        p_at_2 = offer(s1, p, s2, recipient_agent="x", activate=True).imported_memory_id
        self.assertEqual(global_ref(s1, a_at_1), (s0.store_id, a))
        self.assertEqual(global_ref(s2, a_at_2), (s0.store_id, a))
        self.assertEqual(independent_sources(s2, [a_at_2, p_at_2]), 1)

    def test_an_independent_report_from_another_store_still_counts(self) -> None:
        s0, s1, s2 = store(), store(), store()
        for s in (s0, s1, s2):
            self.addCleanup(s.close)
        a = s0.remember("ana", REPORT, scope="team")
        s0.share(a, Scope.FEDERATED, actor="op")
        a_at_2 = offer(s0, a, s2, recipient_agent="x", activate=True).imported_memory_id
        own = s1.remember("ben", OWN, scope="team")
        s1.share(own, Scope.FEDERATED, actor="op")
        own_at_2 = offer(s1, own, s2, recipient_agent="x", activate=True).imported_memory_id
        self.assertEqual(independent_sources(s2, [a_at_2, own_at_2]), 2)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
