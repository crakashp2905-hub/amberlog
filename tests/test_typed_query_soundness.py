"""Independent known-answer fixtures for N01–N05, including positive completeness."""
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from amberlog import Amberlog
from amberlog import typed_query as query


class QuerySoundness(unittest.TestCase):
    def test_join_uses_identical_scope_for_both_sides_of_one_shot_iterable(self):
        left = self.record({"side": "left", "key": "A"})
        right = self.record({"side": "right", "key": "A"})
        self.assertEqual(query.join(self.f, "reader", {"side": "left"}, {"side": "right"},
                                    on=("key", "key"), within=iter([left, right])),
                         ([(left, right)], True))

    def test_explicit_null_and_missing_aggregate_fixtures(self):
        self.record({"kind": "sensor", "value": None})
        self.assertEqual(query.distinct(self.f, "reader", "value"), ([None], True))
        self.assertTrue(query.group_by(self.f, "reader", "value")[1])
        self.record({"kind": "sensor", "value": {"unexpected": "object"}})
        self.assertFalse(query.distinct(self.f, "reader", "value")[1])
        self.assertFalse(query.join(self.f, "reader", {"kind": "sensor"},
                                    {"kind": "sensor"}, on=("value", "value"))[1])

    def test_private_candidate_and_contested_records_do_not_change_certificate(self):
        baseline = query.select(self.f, "reader", {}).certificate()
        self.f.remember("other", "Private inventory.", structured={"key": "A"},
                        scope="private", auto_activate=True)
        self.f.remember("other", "Candidate inventory.", structured={"key": "B"},
                        scope="team", auto_activate=False)
        parent = self.record({"key": "C"})
        child = self.f.derive("writer", "Derived inventory.", parents=[parent], scope="team")
        self.f.validate(child, actor="reviewer")
        self.f.quarantine(parent, reason="withdrawn", actor="reviewer")
        self.assertEqual(query.select(self.f, "reader", {}).certificate(), baseline)

    def test_replay_preserves_erasure_and_tenant_exclusions(self):
        with TemporaryDirectory() as directory:
            path = str(Path(directory) / "query.db")
            f = Amberlog(path)
            visible = f.remember("writer", "Visible inventory.", structured={"kind": "sensor"},
                                 scope="team", auto_activate=True)
            f.remember("writer", "Foreign inventory.", structured={"kind": "sensor"},
                       scope="team", auto_activate=True, tenant_id="foreign")
            erased = f.remember("writer", "Erase inventory.", structured={"kind": "sensor"},
                                scope="team", auto_activate=True)
            f.erase_content(erased, reason="fixture erasure")
            before = query.select(f, "reader", {"kind": "sensor"}).certificate()
            f.close()
            reopened = Amberlog(path)
            try:
                self.assertEqual(query.select(reopened, "reader", {"kind": "sensor"}).ids, [visible])
                self.assertEqual(query.select(reopened, "reader", {"kind": "sensor"}).certificate(), before)
            finally:
                reopened.close()

    def setUp(self):
        self.f = Amberlog(":memory:", recognise_copies=False)
        self.addCleanup(self.f.close)

    def record(self, fields, **kw):
        return self.f.remember("writer", "Inventory record.", structured=fields,
                               scope="team", auto_activate=True, **kw)

    def test_missing_join_key_is_unknown_not_complete_empty_join(self):
        self.record({"side": "left"})
        self.record({"side": "right", "key": "A"})
        self.assertEqual(query.join(self.f, "reader", {"side": "left"}, {"side": "right"},
                                    on=("key", "key")), ([], False))

    def test_known_join_and_explicit_null_keys(self):
        left = self.record({"side": "left", "key": 1})
        right = self.record({"side": "right", "key": 1.0})
        self.record({"side": "right", "key": "1"})
        self.record({"side": "right", "key": True})
        self.record({"side": "right", "key": None})
        pairs, complete = query.join(self.f, "reader", {"side": "left"}, {"side": "right"},
                                     on=("key", "key"))
        self.assertEqual(pairs, [(left, right)])
        self.assertTrue(complete)

    def test_aggregates_preserve_filter_and_missing_key_uncertainty(self):
        first = self.record({"kind": "sensor", "value": 3})
        missing = self.record({"kind": "sensor"})
        self.record({"kind": "door", "value": 5})
        self.assertEqual(query.distinct(self.f, "reader", "value", {"kind": "sensor"}), ([3], False))
        grouped, complete = query.group_by(self.f, "reader", "value", {"kind": "sensor"})
        self.assertEqual(grouped, {"3": [first]})
        self.assertFalse(complete)
        # Existing aggregate implementations overwrote a predicate on the key.
        self.assertEqual(query.distinct(self.f, "reader", "value", {"value": {"$gt": 4}}), ([5], False))
        self.assertIn(missing, query.select(self.f, "reader", {"kind": "sensor", "value": 3}).unknown)

    def test_missing_null_malformed_and_nested_fields(self):
        null = self.record({"a": {"value": None}})
        valid = self.record({"a": {"value": 4}})
        malformed = self.record({"a": {"value": "four"}})
        self.assertEqual(query.count(self.f, "reader", {"a.value": None}), (1, True))
        result = query.select(self.f, "reader", {"a.value": {"$gte": 3}})
        self.assertEqual(result.ids, [valid])
        self.assertEqual(set(result.unknown), {null, malformed})
        self.assertFalse(result.complete)

    def test_erased_foreign_and_withdrawn_counts_are_not_observable(self):
        self.record({"kind": "sensor"}, tenant_id="other")
        withdrawn = self.record({"kind": "sensor"})
        self.f.quarantine(withdrawn, reason="fixture correction", actor="reviewer")
        erased = self.record({"kind": "sensor"})
        self.f.erase_content(erased, reason="fixture erasure")
        result = query.select(self.f, "reader", {"kind": "sensor"})
        self.assertEqual((result.ids, result.considered, result.complete), ([], 0, True))
