"""The dashboard's story views: a fact's timeline, a store replay, if-wrong."""

from __future__ import annotations

import unittest

from amberlog import Amberlog
from amberlog.actions import ActionGate, ActionPolicy, ToolRule
from amberlog.observability.control import action_detail, action_rows, if_wrong, story, timeline


class StoryCase(unittest.TestCase):
    def setUp(self) -> None:
        f = Amberlog(":memory:", auto_activate=True)
        self.addCleanup(f.close)
        self.f = f
        self.mid = f.remember("ag_inspector", "Pump P-14 relief valve is set to 12 bar.",
                              scope="team")
        self.conclusion = f.derive("ag_planner", "Restore P-14 relief to 12 bar after seal work.",
                                   [self.mid])
        gate = ActionGate(f, ActionPolicy(tools={"set_relief": ToolRule("set_relief")},
                                          grants={"ag_ops": frozenset({"set_relief"})}))
        cert = f.certify("relief is 12 bar", [self.mid], "ag_ops")
        assert gate.authorize("set_relief", "ag_ops", cert).allowed
        f.retrieve("ag_planner", "P-14 relief valve", k=3)
        f.quarantine(self.mid, reason="vendor re-specified it", actor="ops",
                     basis="contradicted")
        assert not gate.authorize("set_relief", "ag_ops", cert).allowed

    def test_timeline_tells_the_life_of_a_fact(self):
        t = timeline(self.f, self.mid)
        kinds = [s["kind"] for s in t["steps"]]
        self.assertEqual(kinds[0], "created")
        for kind in ("action_allowed", "withdrawn", "action_blocked", "recalled"):
            self.assertIn(kind, kinds)
        withdrawn = next(s for s in t["steps"] if s["kind"] == "withdrawn")
        self.assertIn("ops withdrew it: vendor re-specified it", withdrawn["text"])
        self.assertIn("1 action(s) relied on it", t["headline"])
        self.assertIn("1 blocked", t["headline"])

    def test_story_replays_the_store_in_order(self):
        rows = story(self.f)
        seqs = [r["seq"] for r in rows]
        self.assertEqual(seqs, sorted(seqs))
        self.assertTrue(any(r["kind"] == "action_blocked" for r in rows))
        self.assertLessEqual(len(story(self.f, limit=2)), 2)

    def test_if_wrong_summarises_consequences(self):
        w = if_wrong(self.f, self.mid)
        self.assertIn(self.conclusion, w["descendants"])
        self.assertTrue(w["summary"].startswith("If this were wrong:"))

    def test_action_detail_explains_in_sentences(self):
        blocked = next(r for r in action_rows(self.f) if not r["allowed"])
        d = action_detail(self.f, blocked["seq"])
        allowed = next(r for r in action_rows(self.f) if r["allowed"])
        text = " ".join(action_detail(self.f, allowed["seq"])["explanation"])
        self.assertIn("was quarantined by ops", text)
        self.assertTrue(any("withdrawn" in x for x in d["explanation"]))



class TestSecretsStayMasked(unittest.TestCase):
    def test_story_and_timeline_mask_secret_values(self):
        f = Amberlog(":memory:", auto_activate=True)
        self.addCleanup(f.close)
        secret = "AKIAIOSFODNN7EXAMPLE"
        mid = f.remember("ag", f"To deploy, export AWS_ACCESS_KEY_ID={secret} and run make.",
                         scope="team")
        texts = [r["text"] for r in story(f)] + [timeline(f, mid)["headline"]]
        texts += [s["text"] for s in timeline(f, mid)["steps"]]
        self.assertTrue(texts)
        self.assertFalse(any(secret in t for t in texts))


if __name__ == "__main__":
    unittest.main()
