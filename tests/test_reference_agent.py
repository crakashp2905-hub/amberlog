"""The reference agent runs its whole loop, and the gate refuses its poisoned evidence."""

from __future__ import annotations

import contextlib
import io
import unittest

from examples import reference_agent


class ReferenceAgentRuns(unittest.TestCase):
    def test_the_loop_verifies_one_task_and_refuses_the_poisoned_one(self) -> None:
        with contextlib.redirect_stdout(io.StringIO()):
            p1, p2 = reference_agent.main()
        self.assertEqual((p1.outcome, p1.decided), ("verified", 30))
        self.assertEqual(p2.outcome, "refused")
        self.assertIn("authority_insufficient", p2.reasons)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
