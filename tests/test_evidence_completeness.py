import unittest

from amberlog import Amberlog
from amberlog.evidence_completeness import classify, exhaustive


class CompletenessTests(unittest.TestCase):
    def setUp(self):
        self.f = Amberlog(":memory:", recognise_copies=False)
        self.addCleanup(self.f.close)

    def remember(self, fields=None, **kw):
        return self.f.remember("writer", "kind=sensor; status=open.",
                               structured=fields, auto_activate=True, scope="team", **kw)

    def run_query(self, evaluator=lambda m, q: True, budget=10, **kw):
        return exhaustive(self.f, "reader", {"kind": "sensor", "status": "open"},
                          query="sensor open", evaluate=evaluator, evaluator_id="fixture/1",
                          max_reads=budget, **kw)

    def test_three_valued_partition_and_positive_certificate(self):
        matched = self.remember({"kind": "sensor", "status": "open"})
        nonmatch = self.remember({"kind": "door"})
        unknown = self.remember({"kind": "sensor"})
        c = classify(self.f, "reader", {"kind": "sensor", "status": "open"})
        self.assertEqual(c.matches, [matched])
        self.assertEqual(c.nonmatches, [nonmatch])
        self.assertEqual(c.unknown, [unknown])
        self.assertFalse(c.complete)
        resolved = self.run_query()
        self.assertTrue(resolved.complete)
        self.assertEqual(set(resolved.ids), {matched, unknown})
        self.assertEqual(resolved.reads, 1)
        self.assertEqual(resolved.certificate()["typed_nonmatches"], 1)

    def test_budget_ambiguity_and_nonmatch_not_vacuous(self):
        self.remember()
        self.assertFalse(self.run_query(budget=0).complete)
        self.assertFalse(self.run_query(lambda m, q: None).complete)
        result = self.run_query(lambda m, q: False)
        self.assertTrue(result.complete)
        self.assertEqual(result.ids, [])
        self.assertEqual(len(result.fallback_nonmatches), 1)
        with self.assertRaises(ValueError):
            self.run_query(lambda m, q: "yes")

    def test_callback_never_receives_foreign_private_candidate_withdrawn_or_erased(self):
        foreign = self.remember(tenant_id="foreign")
        private = self.f.remember("other", "private datum", auto_activate=True, scope="private")
        candidate = self.f.remember("writer", "unreviewed datum", auto_activate=False, scope="team")
        withdrawn = self.remember()
        self.f.quarantine(withdrawn, reason="wrong", actor="reviewer")
        erased = self.remember({"kind": "sensor", "status": "open"})
        self.f.erase_content(erased, reason="erase fixture")
        allowed = self.remember()
        seen = []
        result = self.run_query(lambda m, q: seen.append(m.id) or True,
                                within=[foreign, private, candidate, withdrawn, erased, allowed])
        self.assertEqual(seen, [allowed])
        self.assertEqual(result.ids, [allowed])
        self.assertEqual(result.considered, 1)

    def test_mutation_invalidates_certificate_and_rechecks_each_read(self):
        first, second = self.remember(), self.remember()
        seen = []

        def revoke(m, q):
            seen.append(m.id)
            for mid in (first, second):
                self.f.quarantine(mid, reason="revoke mid-evaluation", actor="reviewer")
            return True

        result = self.run_query(revoke)
        self.assertEqual(len(seen), 1)
        self.assertFalse(result.complete)
        self.assertTrue(result.changed)
        self.assertEqual(result.ids, [])

    def test_derived_withdrawal_cannot_be_returned_on_requery(self):
        source = self.remember()
        child = self.f.derive("writer", "kind=sensor; status=open.", parents=[source], scope="team")
        self.f.validate(child, actor="reviewer")
        self.f.quarantine(source, reason="retracted", actor="reviewer")
        self.assertEqual(self.run_query().ids, [])
