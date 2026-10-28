"""Facts about the same unit in different places are different claims (P3b regression at HEAD).

Two parser behaviours made a team's valid facts contradict each other: a code
after "at the" ("depot-7") was read as a value, and two claims sharing two
words counted as one claim even when each named a different place. P3b's
fabric arm fell from 0.97 to 0.77 task success (8% of valid evidence
invalidated). V1 and V2's registered results are unchanged by the fix.
"""

from __future__ import annotations

import json
import subprocess
import sys
import unittest

from memory_fabric import LifecycleState, MemoryFabric
from memory_fabric.conflicts import claim
from memory_fabric.validation import _same_claim


class Parser(unittest.TestCase):
    def test_a_code_after_a_place_preposition_is_context(self) -> None:
        ids, words, values = claim("tug-1 requires 2.4 m of clearance at the depot-7 site.")
        self.assertEqual(values, frozenset({"2.4"}))
        self.assertIn("tug1", ids)
        self.assertIn("depot7", ids | words)   # part of what the claim is about, never its value
        # A code that *is* the value is still a value.
        self.assertIn("fp1458", claim("Pump P-3 part number is FP-1458.")[2])

    def test_different_places_are_different_claims(self) -> None:
        coastal = claim("tug-1 requires 2.4 m of clearance at the coastal site.")
        inland = claim("tug-1 requires 3.0 m of clearance at the inland site.")
        depot7 = claim("tug-1 requires 2.4 m of clearance at the depot-7 site.")
        depot12 = claim("tug-1 requires 3.0 m of clearance at the depot-12 site.")
        self.assertFalse(_same_claim(coastal, inland))
        self.assertFalse(_same_claim(depot7, depot12))
        # An added detail on one side is still the same claim.
        self.assertTrue(_same_claim(claim("Hoist H-14 restart pressure is 5 bar."),
                                    claim("Hoist H-14 restart pressure is 9 bar per the vendor.")))

    def test_withdrawing_one_site_leaves_the_other_alone(self) -> None:
        f = MemoryFabric(":memory:", auto_activate=True)
        self.addCleanup(f.close)
        a = f.remember("a", "tug-1 requires 2.4 m of clearance at the coastal site.", scope="team")
        b = f.remember("b", "tug-1 requires 3.0 m of clearance at the inland site.", scope="team")
        self.assertIs(f.get(b).lifecycle_state, LifecycleState.ACTIVE)
        f.quarantine(a, reason="wrong", actor="r", basis="contradicted")
        self.assertIs(f.get(b).lifecycle_state, LifecycleState.ACTIVE)


class TeamWorld(unittest.TestCase):
    def test_p3b_holds_its_registered_verdict(self) -> None:
        done = subprocess.run([sys.executable, "-m", "experiments.p3b_teams", "--json"],
                              capture_output=True, text=True, timeout=600)
        self.assertEqual(done.returncode, 0, done.stderr[-500:])
        verdict = json.loads(done.stdout)["verdict"]
        self.assertTrue(verdict["verdict"].startswith("SUPPORTED"), verdict)


if __name__ == "__main__":
    unittest.main()
