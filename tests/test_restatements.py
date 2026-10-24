"""A correction reaches the notes that repeat the old value (GME matrix gap).

Nothing links "measured again: P1 at 40 bar" to the fact it repeats, so a
revision or a withdrawal used to leave it active and retrievable.
"""

from __future__ import annotations

import unittest

from memory_fabric import MemoryFabric


class Restatements(unittest.TestCase):
    def setUp(self) -> None:
        self.f = MemoryFabric(":memory:", auto_activate=True, hold_suspicious=False)
        self.addCleanup(self.f.close)
        self.fact = self.f.remember("ops", "Pump P1-ROT pressurised to 40 bar at Rotterdam.",
                                    scope="team")
        self.repeat = self.f.remember(
            "crew", "Measured again on the night shift: P1-ROT pressurised to 40 bar.",
            scope="team")
        self.other = self.f.remember("crew", "Pump P2-ROT pressurised to 40 bar.", scope="team")
        self.handover = self.f.remember("crew", "Shift handover: P1-ROT inspected.", scope="team")

    def state(self, mid: str) -> str:
        return self.f.get(mid).lifecycle_state.value

    def test_a_revision_contests_notes_repeating_the_old_value(self) -> None:
        self.f.revise(self.fact, "Pump P1-ROT pressurised to 44 bar at Rotterdam.",
                      agent_id="ops", reason="recalibrated")
        self.assertEqual(self.state(self.repeat), "contested")
        self.assertIn(self.fact, self.f.audit_trail(self.repeat)[-1].payload.get("reason", ""))
        served = {m.id for m in self.f.retrieve("a", "pressure P1-ROT", k=10).exposed}
        self.assertNotIn(self.repeat, served)

    def test_other_claims_and_valueless_notes_are_untouched(self) -> None:
        self.f.revise(self.fact, "Pump P1-ROT pressurised to 44 bar at Rotterdam.",
                      agent_id="ops", reason="recalibrated")
        self.assertEqual(self.state(self.other), "active")
        self.assertEqual(self.state(self.handover), "active")

    def test_a_rewording_with_the_same_value_contests_nothing(self) -> None:
        self.f.revise(self.fact, "Pump P1-ROT is pressurised to 40 bar, Rotterdam plant.",
                      agent_id="ops", reason="reworded")
        self.assertEqual(self.state(self.repeat), "active")

    def test_withdrawal_as_contradicted_contests_them_and_other_bases_do_not(self) -> None:
        self.f.quarantine(self.fact, reason="sensor fault", actor="lead", basis="contradicted")
        self.assertEqual(self.state(self.repeat), "contested")

    def test_withdrawal_for_another_reason_leaves_them(self) -> None:
        self.f.quarantine(self.fact, reason="contained a token", actor="lead",
                          basis="sensitive_data")
        self.assertEqual(self.state(self.repeat), "active")

    def test_off_switch(self) -> None:
        f = MemoryFabric(":memory:", auto_activate=True, contest_restatements=False)
        self.addCleanup(f.close)
        fact = f.remember("ops", "Pump P1-ROT pressurised to 40 bar at Rotterdam.", scope="team")
        repeat = f.remember("crew", "Measured again: P1-ROT pressurised to 40 bar.", scope="team")
        f.revise(fact, "Pump P1-ROT pressurised to 44 bar at Rotterdam.", agent_id="ops",
                 reason="recalibrated")
        self.assertEqual(f.get(repeat).lifecycle_state.value, "active")

    def test_other_tenants_are_untouched(self) -> None:
        theirs = self.f.remember("zed", "Measured again: P1-ROT pressurised to 40 bar.",
                                 scope="team", tenant_id="tn_other")
        self.f.revise(self.fact, "Pump P1-ROT pressurised to 44 bar at Rotterdam.",
                      agent_id="ops", reason="recalibrated")
        self.assertEqual(self.state(theirs), "active")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
