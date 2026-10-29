import json
import unittest

from amberlog import Amberlog
from amberlog.compaction import compact_session
from amberlog.lossless_compaction import encode_records, decode_records, dictionary_summary


class LosslessCompaction(unittest.TestCase):
    def test_summarizer_cannot_commit_stale_source_text_after_revocation(self):
        from amberlog.compaction import CompactionRefused
        f = Amberlog(":memory:")
        self.addCleanup(f.close)
        episode = f.start_episode("writer", "revoked inspection")
        mid = f.remember("writer", "Unit P1 limit is 10 bar.", scope="team", auto_activate=True,
                         source_episodes=[episode.id])

        def revoke(memories, disputes):
            f.quarantine(mid, reason="revoked during summarization", actor="reviewer")
            return " ".join(m.content for m in memories)

        with self.assertRaises(CompactionRefused):
            compact_session(f, episode.id, "writer", summarise=revoke)
        self.assertFalse(any("compaction_of" in m.context for m in f.state.memories.values()))

    def test_summary_cannot_widen_private_visibility(self):
        from amberlog.compaction import CompactionRefused
        f = Amberlog(":memory:")
        self.addCleanup(f.close)
        episode = f.start_episode("writer", "private inspection")
        f.remember("writer", "Unit P1 limit is 10 bar.", scope="private", auto_activate=True,
                   source_episodes=[episode.id])
        with self.assertRaises(CompactionRefused):
            compact_session(f, episode.id, "writer", scope="team")

    def test_foreign_episode_records_do_not_enter_inputs_or_omission_counts(self):
        f = Amberlog(":memory:")
        self.addCleanup(f.close)
        episode = f.start_episode("writer", "mixed inspection")
        own = f.remember("writer", "Unit P1 limit is 10 bar.", scope="team", auto_activate=True,
                         source_episodes=[episode.id])
        f.remember("foreign", "Foreign limit is 99 bar.", scope="team", auto_activate=True,
                   source_episodes=[episode.id], tenant_id="foreign")
        report = compact_session(f, episode.id, "writer")
        self.assertEqual(report.inputs, [own])
        self.assertEqual(report.left_out, {})

    def texts(self):
        return [f"Unit P{i} limit is {i + 3} bar. It must not be restarted before independent verification."
                for i in range(12)]

    def test_exact_roundtrip_and_measured_byte_savings_on_repetitive_fixture(self):
        source = self.texts()
        payload = encode_records(source)
        self.assertEqual(decode_records(payload), source)
        self.assertLess(len(payload.encode()), len(" ".join(source).encode()))
        # Prefix-like numeric values must remain directly visible to the
        # existing compaction fact guard, not split into dictionary fragments.
        from amberlog.conflicts import claim
        edge = [f"Unit P{i} limit is {value} bar. It must not be restarted before verification."
                for i, value in enumerate([5, 50, 51, 6, 60, 61] * 3)]
        packed = encode_records(edge)
        self.assertEqual(decode_records(packed), edge)
        self.assertTrue(set().union(*(claim(t)[2] for t in edge)) <= claim(packed)[2])

    def test_unicode_whitespace_negation_and_literal_reference_markers_survive(self):
        source = ["Café\r\n must not open at 1.25 bar", "~A~ is a literal marker."]
        self.assertEqual(decode_records(encode_records(source)), source)

    def test_malformed_references_and_oversized_expansion_are_refused(self):
        with self.assertRaises(ValueError):
            decode_records(json.dumps({"dictionary": {"A": "value"}, "records": ["~B~"]}))
        with self.assertRaises(ValueError):
            decode_records(json.dumps({"dictionary": {"A": "x" * 50000}, "records": ["~A~" * 10]}))

    def test_summary_erasure_reaches_compaction_payload(self):
        f = Amberlog(":memory:", recognise_copies=False)
        self.addCleanup(f.close)
        episode = f.start_episode("writer", "repeated inspection")
        ids = [f.remember("writer", t, source_episodes=[episode.id], auto_activate=True, scope="team")
               for t in self.texts()]
        report = compact_session(f, episode.id, "writer", summarise=dictionary_summary)
        self.assertEqual(set(report.inputs), set(ids))
        f.erase_content(ids[0], reason="fixture erasure")
        self.assertIn(report.summary_id, f.state.erased)

    def test_compaction_cannot_launder_another_agents_private_source(self):
        f = Amberlog(":memory:")
        self.addCleanup(f.close)
        episode = f.start_episode("owner", "private inspection")
        f.remember("owner", "Private limit is 11 bar.", source_episodes=[episode.id],
                   auto_activate=True, scope="private")
        from amberlog.compaction import CompactionRefused
        with self.assertRaises(CompactionRefused):
            compact_session(f, episode.id, "other", summarise=dictionary_summary)
