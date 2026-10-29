import unittest

from amberlog import Amberlog
from amberlog.history_query import query
from amberlog.incident import replay_until
from amberlog.events import EventType


class HistoricalReads(unittest.TestCase):
    def setUp(self):
        self.f = Amberlog(":memory:", recognise_copies=False)
        self.addCleanup(self.f.close)

    def remember(self, text="The limit is 10 bar.", **kw):
        return self.f.remember("writer", text, scope="team", auto_activate=True, **kw)

    def test_historical_revision_and_valid_time_match_replay(self):
        mid = self.remember(valid_from=100, valid_to=200)
        seq = self.f.log.head_seq
        expected = replay_until(self.f, seq).memories[mid]
        self.f.revise(mid, "The limit is 12 bar.", reason="new measurement", agent_id="writer")
        receipt = query(self.f, "reader", [mid], known_at=seq, valid_at=150)
        self.assertEqual(receipt.rows[0].version, expected.version)
        self.assertEqual(receipt.rows[0].content, "The limit is 10 bar.")
        self.assertTrue(receipt.rows[0].superseded)
        self.assertTrue(receipt.rows[0].archival_only)
        self.assertGreater(receipt.rows[0].recorded_seq, 0)
        self.assertLessEqual(receipt.rows[0].recorded_seq, seq)
        self.assertEqual(query(self.f, "reader", [mid], known_at=seq, valid_at=250).rows, [])
        exposure = list(self.f.log.read_types([EventType.EXPOSURE_DECIDED]))[-1]
        self.assertEqual(exposure.payload["propensity"], 1.0)

    def test_current_retraction_and_erasure_override_historical_visibility(self):
        revoked = self.remember()
        erased = self.remember("The spare limit is 9 bar.")
        seq = self.f.log.head_seq
        self.f.quarantine(revoked, reason="retracted", actor="reviewer")
        self.f.erase_content(erased, reason="erasure fixture")
        receipt = query(self.f, "reader", [revoked, erased, "missing"], known_at=seq)
        self.assertEqual(receipt.rows, [])

    def test_foreign_and_historical_private_content_is_not_disclosed(self):
        foreign = self.remember(tenant_id="other")
        private = self.f.remember("writer", "Private limit is 8 bar.", scope="private", auto_activate=True)
        seq = self.f.log.head_seq
        self.assertEqual(query(self.f, "reader", [foreign, private], known_at=seq).rows, [])
        self.assertEqual(len(query(self.f, "writer", [private], known_at=seq).rows), 1)

    def test_bounded_replay_refuses_without_exposing_a_partial_result(self):
        mid = self.remember()
        seq = self.f.log.head_seq
        with self.assertRaisesRegex(ValueError, "max_events"):
            query(self.f, "reader", [mid], known_at=seq, max_events=1)
        for bad in (-1, True, 1.5, seq + 100):
            with self.assertRaises(ValueError):
                query(self.f, "reader", [mid], known_at=bad)

    def test_old_certificate_cannot_authorize_a_historical_revision(self):
        mid = self.remember()
        certificate = self.f.certify("The limit is 10 bar.", [mid], "reader")
        seq = self.f.log.head_seq
        self.f.revise(mid, "The limit is 12 bar.", agent_id="writer", reason="correction")
        row = query(self.f, "reader", [mid], known_at=seq).rows[0]
        self.assertEqual(row.version, certificate.evidence[0].version)
        decision = self.f.verify_certificate(certificate, "reader")
        self.assertFalse(decision.ok)
        self.assertIn("evidence_version_moved", decision.reason_codes)

    def test_collection_permission_must_exist_both_then_and_now(self):
        mid = self.f.remember("owner", "Collection inventory.", scope="private", auto_activate=True)
        private_seq = self.f.log.head_seq
        self.f.collection_add("history", mid, actor="lead")
        self.f.collection_grant("history", "reader", ["read"], actor="lead")
        granted_seq = self.f.log.head_seq
        self.assertEqual(query(self.f, "reader", [mid], known_at=private_seq).rows, [])
        self.assertEqual(len(query(self.f, "reader", [mid], known_at=granted_seq).rows), 1)
        self.f.collection_revoke("history", "reader", actor="lead")
        self.assertEqual(query(self.f, "reader", [mid], known_at=granted_seq).rows, [])
