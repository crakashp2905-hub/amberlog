"""A running fabric must see what other processes wrote to the same log.

Each `Amberlog` folds its own writes into an in-memory projection. Before
this was fixed, nothing folded anyone else's: an operator ran
`amberlog quarantine` from a terminal while an MCP server, an app or the
dashboard was running, and the running process went on recalling the withdrawn
memory until it restarted. A fresh process said `quarantined`; the live one
served it. That breaks the guarantee the project is built on -- a known-invalid
version is never served -- for exactly the deployment shape the MCP server and
the dashboard create. Found while setting up the live Claude-over-MCP run.

The other writer here is a real second process through the real CLI, because a
second `Amberlog` in this process would share nothing that matters less
than the thing under test.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest

from amberlog import LifecycleState, Amberlog
from amberlog.enforcement import RiskLevel
from amberlog.sdk import agent, operator

CONTENT = "E01 at coastal sites: swap the pilot cable before anything else."


def _cli(db: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "amberlog", "--db", db, *args],
        capture_output=True, text=True, timeout=60,
    )


class CrossProcessCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = os.path.join(self.tmp.name, "store.db")
        self.fabric = Amberlog(self.db)
        self.addCleanup(self.fabric.close)
        self.agent = agent(self.fabric, "ag_live")
        self.memory_id = self.agent.remember(CONTENT)
        operator(self.fabric, "op").validate(self.memory_id)

    def quarantine_elsewhere(self) -> None:
        result = _cli(self.db, "quarantine", self.memory_id,
                      "--reason", "wrong fault", "--basis", "contradicted")
        self.assertEqual(result.returncode, 0, result.stderr)


class TestARunningFabricSeesAnotherProcessesRetraction(CrossProcessCase):
    def test_recall_stops_returning_it(self) -> None:
        self.assertIn(self.memory_id,
                      [m.memory_id for m in self.agent.recall("pilot cable coastal")])
        self.quarantine_elsewhere()
        self.assertNotIn(self.memory_id,
                         [m.memory_id for m in self.agent.recall("pilot cable coastal")])

    def test_the_action_time_check_refuses_it(self) -> None:
        """The token was issued before the retraction; the re-check after it
        must refuse. This is the time-of-check/time-of-use defence working
        across a process boundary, not only within one."""
        usable = self.agent.recall("pilot cable coastal")[0]
        self.quarantine_elsewhere()
        decision = self.agent.verify(usable, risk=RiskLevel.HIGH)
        self.assertFalse(decision.usable)

    def test_lifecycle_reads_are_current(self) -> None:
        self.quarantine_elsewhere()
        self.assertIs(self.fabric.lifecycle_of(self.memory_id),
                      LifecycleState.QUARANTINED)

    def test_a_write_after_a_foreign_write_keeps_both(self) -> None:
        """Our next write lands after theirs in the log; the projection must
        hold both, in log order, not just our own."""
        self.quarantine_elsewhere()
        second = self.agent.remember("Reset the breaker before swapping a pump.")
        self.assertIs(self.fabric.lifecycle_of(self.memory_id),
                      LifecycleState.QUARANTINED)
        self.assertIn(second, self.fabric.state.memories)
        reopened = Amberlog(self.db)
        try:
            self.assertEqual(set(reopened.state.memories), set(self.fabric.state.memories))
        finally:
            reopened.close()

    def test_no_foreign_write_means_no_rebuild(self) -> None:
        """The catch-up must cost one indexed read when nothing changed, not a
        replay -- otherwise every recall rebuilds the store."""
        calls = []
        original = self.fabric._replay
        self.fabric._replay = lambda: (calls.append(1), original())[1]
        for _ in range(5):
            self.agent.recall("pilot cable coastal")
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
