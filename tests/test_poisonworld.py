"""P5 harness checks (experiments/poisonworld.py).

Not the result -- that is research/results/p5-poisonworld.md. These pin the
properties the result depends on: the world is seeded, no arm beats the
oracle (AGENTS.md 8b), the degenerate arm is reported and fails, and the gate
never lets an ungranted agent act.
"""

from __future__ import annotations

import unittest

from experiments import poisonworld as P


class TestPoisonWorld(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.results = {arm: P.run_one(arm, 3) for arm in P.ARMS}

    def test_the_world_is_seeded(self) -> None:
        again = P.run_one("fabric", 3).rates()
        self.assertEqual(again, self.results["fabric"].rates())

    def test_no_arm_beats_the_oracle(self) -> None:
        ceiling = self.results["oracle"].rates()["M2_task_success"]
        for arm, res in self.results.items():
            with self.subTest(arm):
                self.assertLessEqual(res.rates()["M2_task_success"], ceiling + 1e-9)

    def test_the_degenerate_arm_never_acts(self) -> None:
        rates = self.results["abstain"].rates()
        self.assertEqual((rates["M1_invalid_action"], rates["M2_task_success"]), (0.0, 0.0))

    def test_the_gate_lets_no_ungranted_agent_act(self) -> None:
        for arm in ("fabric", "fabric_blanket", "oracle"):
            with self.subTest(arm):
                self.assertGreater(self.results[arm].ungranted_tasks, 0)
                self.assertEqual(self.results[arm].unauthorized, 0)

    def test_matched_injections_never_reach_a_fabric_agent(self) -> None:
        self.assertEqual(self.results["fabric"].injected_followed["inject_matched"], 0)
        self.assertGreater(self.results["shared"].injected_followed["inject_matched"], 0)

    def test_every_invalid_action_has_a_cause(self) -> None:
        for arm, res in self.results.items():
            with self.subTest(arm):
                self.assertEqual(sum(res.invalid_causes.values()), res.acted_invalid)
                self.assertNotIn("unknown", res.invalid_causes)


if __name__ == "__main__":
    unittest.main()
