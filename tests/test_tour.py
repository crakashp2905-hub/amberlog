"""`memory_fabric tour` tells the story and its claims hold."""

from __future__ import annotations

import io
import unittest

from memory_fabric.cli import main
from memory_fabric.tour import run


class TestTour(unittest.TestCase):
    def test_story_claims_are_what_happened(self):
        out = io.StringIO()
        r = run(out, pause=0, color=False)
        self.assertTrue(r["first_allowed"])
        self.assertFalse(r["second_allowed"])
        self.assertEqual(r["recall_after"], [])
        self.assertEqual(r["plan_state"], "contested")
        self.assertEqual(r["steps"][:4], ["created", "action_allowed", "withdrawn",
                                          "action_blocked"])
        text = out.getvalue()
        self.assertIn("withdrawn by shift-lead", text)
        self.assertNotIn("\033[", text)

    def test_cli_needs_no_store(self):
        import contextlib

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.assertEqual(main(["tour", "--fast"]), 0)
        self.assertIn("BLOCKED", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
