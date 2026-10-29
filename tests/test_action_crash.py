"""A process that dies mid-action leaves an *uncertain* outcome, never an absent one.

The fence runs verification and the tool inside one transaction, so a crash
mid-tool rolls the transaction back. Before an attempt was recorded outside
it, the store then held no trace of the action, and the next call with the
same key ran the tool again as if it had never started: a possible double
side effect, treated as definitely absent.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from amberlog import Amberlog
from amberlog.actions import EXECUTED, REFUSED, ActionGate, ActionPolicy, ToolRule

ROOT = Path(__file__).resolve().parents[1]

CRASHER = textwrap.dedent("""
    import os, sys
    sys.path.insert(0, {root!r})
    from amberlog import Amberlog
    from amberlog.actions import ActionGate, ActionPolicy, ToolRule
    f = Amberlog({db!r})
    gate = ActionGate(f, ActionPolicy(tools={{"open": ToolRule("open")}},
                                      grants={{"ops": frozenset({{"open"}})}}))
    cert = f.certify("open-v7", [{mid!r}], "ops")
    def tool(key):
        open({marker!r}, "w").write(key)   # the side effect happens...
        os._exit(1)                         # ...and the process dies before reporting it
    gate.execute("open", "ops", tool, cert, key="k-crash")
""")


class CrashMidAction(unittest.TestCase):
    def setUp(self) -> None:
        tmp = Path(self.enterContext(TemporaryDirectory()))
        self.db, self.marker = tmp / "store.db", tmp / "side-effect"
        f = Amberlog(str(self.db), auto_activate=True)
        self.mid = f.remember("tech", "Valve V7 opens below 4 bar.", scope="team")
        f.close()
        script = CRASHER.format(root=str(ROOT), db=str(self.db), mid=self.mid,
                                marker=str(self.marker))
        done = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True,
                              timeout=120)
        self.assertEqual(done.returncode, 1, done.stderr[-2000:])
        self.assertTrue(self.marker.exists(), "the side effect did happen")

    def gate(self, f: Amberlog) -> ActionGate:
        return ActionGate(f, ActionPolicy(tools={"open": ToolRule("open")},
                                          grants={"ops": frozenset({"open"})}))

    def test_the_next_call_refuses_until_someone_says_to_retry(self) -> None:
        f = Amberlog(str(self.db))
        self.addCleanup(f.close)
        ran: list[str] = []
        cert = f.certify("open-v7", [self.mid], "ops")
        again = self.gate(f).execute("open", "ops", ran.append, cert, key="k-crash")
        self.assertEqual(again.outcome, REFUSED)
        self.assertIn("retry_required", again.error or "")
        self.assertEqual(ran, [], "not run again on the assumption it never happened")
        retried = self.gate(f).execute("open", "ops", ran.append, cert, key="k-crash", retry=True)
        self.assertEqual(retried.outcome, EXECUTED)
        self.assertEqual(ran, ["k-crash"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
