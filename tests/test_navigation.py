"""Browsing by topic: only what the reader may see, and opening a topic is a logged retrieval."""

from __future__ import annotations

import unittest

from amberlog import Amberlog
from amberlog.adapters.mcp import McpServer
from amberlog.events import EventType
from amberlog.navigation import members, navigate, open_topic, topics
from amberlog.sdk import AgentClient


class Navigation(unittest.TestCase):
    def setUp(self) -> None:
        self.f = Amberlog(":memory:", auto_activate=True)
        self.addCleanup(self.f.close)
        for text in ("Pump P-14 relief valve opens at 12 bar.", "Pump P-14 relief valve was replaced in May.",
                     "Pump P-14 relief valve has a new gasket.", "Pump P-14 relief valve leaks at the flange.",
                     "Chiller C-2 setpoint is 7 C for the server room.", "Chiller C-2 alarms page the night shift."):
            self.f.remember("ana", text, scope="team")
        self.private = self.f.remember("ben", "The spare locker key is in drawer three.", scope="private")

    def test_topics_name_what_is_there_with_counts(self) -> None:
        top = {t["label"].split(" · ")[0]: t["size"] for t in topics(self.f, "ana")}
        self.assertEqual(top.get("Pump") or top.get("Relief") or top.get("Valve"), 4)
        self.assertEqual(top.get("Chiller"), 2)

    def test_a_private_memory_lends_nothing_to_another_reader(self) -> None:
        self.assertNotIn(self.private, members(self.f, "ana"))
        self.assertIn(self.private, members(self.f, "ben"))

    def test_opening_a_topic_is_a_logged_retrieval_inside_it(self) -> None:
        path = next(t["path"] for t in topics(self.f, "ana") if t["size"] == 4)
        before = len(list(self.f.log.read_types([EventType.EXPOSURE_DECIDED])))
        result = open_topic(self.f, "ana", path, query="gasket")
        self.assertEqual(result.exposed[0].content, "Pump P-14 relief valve has a new gasket.")
        self.assertTrue(all("Chiller" not in m.content for m in result.exposed))
        after = len(list(self.f.log.read_types([EventType.EXPOSURE_DECIDED])))
        self.assertGreater(after, before, "exposures are decided and logged")

    def test_withdrawn_memories_leave_the_tree(self) -> None:
        gone = self.f.remember("ana", "Chiller C-2 runs a night defrost cycle.", scope="team")
        self.assertIn(gone, members(self.f, "ana"))
        self.f.quarantine(gone, reason="wrong", actor="op")
        self.assertNotIn(gone, members(self.f, "ana"))

    def test_navigate_ranks_inside_the_best_topic(self) -> None:
        ids = navigate(self.f, "ana", "what is the chiller setpoint", k=3)
        self.assertTrue(ids)
        self.assertIn("setpoint", self.f.get(ids[0]).content)


class McpBrowse(unittest.TestCase):
    def test_browse_then_open_over_mcp(self) -> None:
        f = Amberlog(":memory:", auto_activate=True)
        self.addCleanup(f.close)
        for i in range(4):
            f.remember("ana", f"Pump P-14 relief valve inspection {i} passed.", scope="team")
        server = McpServer(AgentClient(f, "ana"), f, extended=True)
        listed = server._call("browse_topics", {})
        path = listed["structuredContent"]["topics"][0]["path"] if "structuredContent" in listed else None
        self.assertIsNotNone(path, listed)
        opened = server._call("open_topic", {"path": path, "k": 2})
        self.assertEqual(len(opened["structuredContent"]["memories"]), 2)
        bad = server._call("open_topic", {"path": "valve"})
        self.assertTrue(bad.get("isError"))

    def test_browsing_is_opt_in_so_the_default_surface_stays_narrow(self) -> None:
        f = Amberlog(":memory:")
        self.addCleanup(f.close)
        self.assertTrue(McpServer(AgentClient(f, "ana"), f)._call("browse_topics", {}).get("isError"))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
