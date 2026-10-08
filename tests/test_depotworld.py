"""DepotWorld's answer key and its scoring.

These tests exist because of this project's own history: three of four
hypotheses were mis-operationalised, and in every case the bug was in the
harness rather than the system under test. H1's largest effect turned out to be
a scoring bug; H3's `full` arm was penalised by a round-trip the harness
created. A world that holds the answer key and the parser that decides who was
right is exactly where the next one would hide.

Phase A's parser matters more than most. It labels the corpus *and* scores the
answers, so a parser that misses a paraphrase moves the contamination figures
and the success figures at once, in the same direction.
"""

from __future__ import annotations

import random
import unittest

from experiments import depotworld as W


class TestTruth(unittest.TestCase):
    def test_every_fault_has_an_exception_site_with_a_different_answer(self) -> None:
        truth = W.build_truth(random.Random(0))
        for fault in W.FAULTS:
            site = truth.exception_site[fault]
            self.assertNotEqual(
                truth.action(fault, site),
                truth.base[fault],
                f"{fault}: the exception site answers the same as the base, so "
                "nothing can be learned wrongly by transfer",
            )
            others = [s for s in W.SITES if s != site]
            for other in others:
                self.assertEqual(truth.action(fault, other), truth.base[fault])

    def test_the_hazard_exists_for_every_fault(self) -> None:
        """A lesson correct at a base site must be *wrong* at the exception
        site. If it were merely incomplete there, the world would contain no
        contaminating memory and the benchmark would measure nothing."""
        truth = W.build_truth(random.Random(1))
        for fault in W.FAULTS:
            base_site = next(s for s in W.SITES if not truth.is_exception(fault, s))
            exception_site = truth.exception_site[fault]
            self.assertNotEqual(
                truth.action(fault, base_site), truth.action(fault, exception_site)
            )

    def test_seeded_truth_is_reproducible(self) -> None:
        a = W.build_truth(random.Random(7))
        b = W.build_truth(random.Random(7))
        self.assertEqual(a, b)


class TestEpisodes(unittest.TestCase):
    def test_learning_covers_every_fault_and_site(self) -> None:
        """Full coverage is what keeps the oracle's ceiling a property of
        selection rather than of the sampling scheme: an exception site never
        visited has no correct lesson for perfect selection to find."""
        rng = random.Random(0)
        truth = W.build_truth(rng)
        episodes = W.learning_episodes(truth, rng)
        self.assertEqual(len(episodes), len(W.FAULTS) * len(W.SITES))
        self.assertEqual(
            {(e.fault, e.site) for e in episodes},
            {(f, s) for f in W.FAULTS for s in W.SITES},
        )

    def test_a_poisoned_episode_teaches_a_wrong_action_for_its_own_site(self) -> None:
        rng = random.Random(3)
        truth = W.build_truth(rng)
        episodes = W.learning_episodes(truth, rng, poison_rate=1.0)
        self.assertTrue(episodes)
        for episode in episodes:
            self.assertTrue(episode.poisoned)
            self.assertNotEqual(episode.action, truth.action(episode.fault, episode.site))
            # The diagnosis must agree with the action the agent is told about,
            # or the lesson it writes is incoherent rather than merely wrong.
            self.assertEqual(episode.diagnosis, W.DIAGNOSES[episode.action])

    def test_an_unpoisoned_episode_teaches_the_truth(self) -> None:
        rng = random.Random(4)
        truth = W.build_truth(rng)
        for episode in W.learning_episodes(truth, rng, poison_rate=0.0):
            self.assertEqual(episode.action, truth.action(episode.fault, episode.site))

    def test_half_the_evaluation_episodes_are_exceptions(self) -> None:
        rng = random.Random(0)
        truth = W.build_truth(rng)
        episodes = W.eval_episodes(truth, rng, count=24)
        self.assertEqual(len(episodes), 24)
        self.assertEqual(sum(e.is_exception for e in episodes), 12)

    def test_evaluation_episodes_carry_the_right_answer(self) -> None:
        rng = random.Random(5)
        truth = W.build_truth(rng)
        for episode in W.eval_episodes(truth, rng, count=24):
            self.assertEqual(episode.correct, truth.action(episode.fault, episode.site))
            self.assertEqual(episode.is_exception, truth.is_exception(episode.fault, episode.site))


class TestParsing(unittest.TestCase):
    def test_the_token_form_parses(self) -> None:
        for action in W.ACTIONS:
            self.assertEqual(W.parse_action(action), action)

    def test_prose_parses(self) -> None:
        """Every one of these came out of an actual model run. The first version
        of the parser accepted only the token form and discarded a third of the
        corpus — which measures the parser, not the memory layer."""
        cases = {
            "swap the pilot cable": "swap_pilot_cable",
            "reseating the loose main contactor resolved it": "reseat_contactor",
            "replace the residual current device": "replace_rcd",
            "For future E02 faults in urban sites, replace the residual current "
            "device": "replace_rcd",
            "recalibrated the energy meter": "recalibrate_meter",
            "clean the earth bond": "clean_earth_bond",
            "reflash the firmware": "reflash_firmware",
            "replace the pilot cable": "swap_pilot_cable",
        }
        for text, expected in cases.items():
            self.assertEqual(W.parse_action(text), expected, text)

    def test_naming_several_actions_is_not_a_commitment(self) -> None:
        self.assertIsNone(W.parse_action("either replace_rcd or reflash_firmware"))
        self.assertIsNone(W.parse_action("no idea"))
        self.assertIsNone(W.parse_action(""))

    def test_a_lesson_must_name_its_own_fault_code(self) -> None:
        """Otherwise the corpus gets mislabelled, and every contamination and
        harm figure is computed against the wrong fault."""
        self.assertEqual(
            W.asserted_action("For E01 at coastal sites, reseat_contactor.", "E01"),
            "reseat_contactor",
        )
        self.assertIsNone(W.asserted_action("reseat the contactor", "E01"))
        self.assertIsNone(W.asserted_action("For E02, reseat_contactor.", "E01"))


class TestRendering(unittest.TestCase):
    def test_nothing_retrieved_renders_as_nothing(self) -> None:
        """An empty "Relevant notes:" header is a claim that the store was
        consulted and had something, which would make a no-hit episode look
        different to the model than a no-memory one."""
        self.assertEqual(W.render_plain([]), "")

    def test_notes_are_numbered_and_carry_no_metadata(self) -> None:
        text = W.render_plain(["first note", "second note"])
        self.assertIn("1. first note", text)
        self.assertIn("2. second note", text)
        self.assertNotIn("lifecycle", text.lower())


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
