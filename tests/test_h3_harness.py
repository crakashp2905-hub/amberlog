"""Invariants of the H3 harness.

Two bugs here would not show as a crash, only as a wrong conclusion: unequal
sharing volumes between arms, and a sanity gate that fails to notice a world
where nothing was shared at all.
"""

from __future__ import annotations

import random
import unittest

from experiments.contexts import build_contexts, true_value_in
from experiments.h3 import ARMS, H3_WORLD, Cell, experiment_firewall, run_cell, verdict
from experiments.ruleworld import WorldConfig
from amberlog import LifecycleState, Amberlog, Scope
from amberlog.federation import offer_many


class TestContexts(unittest.TestCase):
    def test_overlap_controls_how_many_rules_agree(self) -> None:
        for overlap in (0.0, 0.25, 0.5, 0.75, 1.0):
            with self.subTest(overlap=overlap):
                pair = build_contexts(H3_WORLD, overlap, random.Random(0))
                agreeing = sum(
                    1
                    for s in pair.a.symptoms
                    if pair.a.rules[s].correct_action == pair.b.rules[s].correct_action
                )
                expected = round(overlap * len(pair.a.symptoms))
                self.assertEqual(agreeing, expected)

    def test_difficulty_is_held_constant_across_contexts(self) -> None:
        """Otherwise a change in success could be task difficulty moving rather
        than transfer working."""
        pair = build_contexts(H3_WORLD, 0.5, random.Random(0))
        for symptom in pair.a.symptoms:
            self.assertEqual(
                pair.a.rules[symptom].n_plausible, pair.b.rules[symptom].n_plausible
            )

    def test_overlap_must_be_a_fraction(self) -> None:
        for bad in (-0.1, 1.5):
            with self.assertRaises(ValueError):
                build_contexts(H3_WORLD, bad, random.Random(0))

    def test_true_value_sign_matches_the_context(self) -> None:
        pair = build_contexts(H3_WORLD, 0.0, random.Random(0))
        symptom = pair.a.symptoms[0]
        correct_in_a = {
            "kind": "claim", "symptom": symptom,
            "action": pair.a.rules[symptom].correct_action,
        }
        self.assertGreater(true_value_in(pair.a, correct_in_a), 0)
        self.assertLess(true_value_in(pair.b, correct_in_a), 0)
        self.assertEqual(
            true_value_in(pair.a, {"kind": "distractor", "symptom": symptom}), 0.0
        )


class TestSharingVolume(unittest.TestCase):
    def test_imports_are_not_re_shared_back_to_their_origin(self) -> None:
        """Regression: imports arriving active were picked up by the second
        offer direction, so each agent received its own memories back and the
        `full` arm carried double the memories it should have — penalising the
        arm that is meant to represent 'share everything'.
        """
        a = Amberlog(auto_activate=True, seed=1, firewall=experiment_firewall())
        b = Amberlog(auto_activate=True, seed=2, firewall=experiment_firewall())
        try:
            for index in range(5):
                a.remember("agent", f"Fact {index} about deploys from A.")
                b.remember("agent", f"Fact {index} about deploys from B.")

            native = [
                [
                    memory_id
                    for memory_id, memory in fabric.state.memories.items()
                    if memory.lifecycle_state is LifecycleState.ACTIVE
                ]
                for fabric in (a, b)
            ]
            fabrics = (a, b)
            total = 0
            for source, target in ((0, 1), (1, 0)):
                summary = offer_many(
                    fabrics[source], fabrics[target], recipient_agent="agent",
                    memory_ids=native[source], activate=True,
                )
                total += summary.accepted

            self.assertEqual(total, 10)
            self.assertEqual(len(a.state.memories), 10)
            self.assertEqual(len(b.state.memories), 10)
        finally:
            a.close()
            b.close()


class TestVerdictLogic(unittest.TestCase):
    def _cell(self, overlap: float, values: dict[str, float]) -> Cell:
        from experiments.h3 import ArmResult

        cell = Cell(overlap=overlap)
        for arm, value in values.items():
            cell.arms[arm] = [
                ArmResult(arm, overlap, 0.4, float("nan"), value + i * 1e-4,
                          0.0, 0, 0, 0, 0, 0)
                for i in range(10)
            ]
        return cell

    def test_void_when_full_does_not_beat_none_at_full_overlap(self) -> None:
        """A world where sharing everything does not help when everything
        transfers is broken, and the run answers nothing."""
        cells = [
            self._cell(0.0, {"none": 0.50, "full": 0.45, "selective": 0.50}),
            self._cell(1.0, {"none": 0.50, "full": 0.48, "selective": 0.52}),
        ]
        outcome, reason = verdict(cells)
        self.assertEqual(outcome, "VOID")
        self.assertIn("o=1.0", reason)

    def test_killed_when_selective_never_wins(self) -> None:
        cells = [
            self._cell(0.0, {"none": 0.50, "full": 0.45, "selective": 0.49}),
            self._cell(0.25, {"none": 0.50, "full": 0.46, "selective": 0.48}),
            self._cell(0.5, {"none": 0.50, "full": 0.49, "selective": 0.49}),
            self._cell(0.75, {"none": 0.50, "full": 0.52, "selective": 0.51}),
            self._cell(1.0, {"none": 0.50, "full": 0.55, "selective": 0.54}),
        ]
        self.assertEqual(verdict(cells)[0], "KILLED")

    def test_supported_when_margins_clear(self) -> None:
        cells = [
            self._cell(0.0, {"none": 0.50, "full": 0.45, "selective": 0.50}),
            self._cell(0.25, {"none": 0.50, "full": 0.46, "selective": 0.56}),
            self._cell(0.5, {"none": 0.50, "full": 0.49, "selective": 0.57}),
            self._cell(0.75, {"none": 0.50, "full": 0.52, "selective": 0.58}),
            self._cell(1.0, {"none": 0.50, "full": 0.55, "selective": 0.56}),
        ]
        self.assertEqual(verdict(cells)[0], "SUPPORTED")

    def test_inconclusive_when_it_wins_by_less_than_the_margin(self) -> None:
        cells = [
            self._cell(0.0, {"none": 0.50, "full": 0.45, "selective": 0.50}),
            self._cell(0.25, {"none": 0.50, "full": 0.46, "selective": 0.505}),
            self._cell(0.5, {"none": 0.50, "full": 0.49, "selective": 0.51}),
            self._cell(0.75, {"none": 0.50, "full": 0.52, "selective": 0.53}),
            self._cell(1.0, {"none": 0.50, "full": 0.55, "selective": 0.56}),
        ]
        self.assertEqual(verdict(cells)[0], "INCONCLUSIVE")


class TestArmsProduceDifferentStores(unittest.TestCase):
    def test_arms_differ_in_what_they_import(self) -> None:
        """If the arms ended up with the same store, the curve compares nothing."""
        seeds = [0]
        kept = {}
        for arm in ("none", "full", "selective"):
            rows = run_cell(0.5, arm, seeds, quick=True)
            kept[arm] = rows[0].active_imports
        self.assertEqual(kept["none"], 0)
        self.assertGreater(kept["full"], 0)
        self.assertGreater(kept["full"], kept["selective"])


if __name__ == "__main__":
    unittest.main()
