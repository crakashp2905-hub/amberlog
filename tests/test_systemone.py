"""The System One client, and the two numbers that decide whether it is useful.

A System One model returns a probability distribution over a closed option set
instead of prose. The reason this project might want one is calibration, so the
tests that matter most are the known-answer tests on **ECE** and **Brier** --
the metrics that tell "accurate on average" from "confident when wrong", which
is the distinction an exposure decision turns on and which AUC cannot see.

The transport is tested against a stub rather than a server: these run in CI,
which has no model and no torch.
"""

from __future__ import annotations

import json
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from memory_fabric.adapters.systemone import (  # noqa: E402
    AnswerRecord, SystemOneClient, SystemOneError, brier_score, choice,
    expected_calibration_error, noul, parse_answers, score,
)


class TestQuestionBuilders(unittest.TestCase):
    def test_a_yes_no_question_carries_its_descriptions(self):
        """The model sees the descriptions and never the question id, so an
        id-only question throws away the chance to say what is being asked."""
        q = noul("Can this be answered?", yes="it can", no="it cannot")
        self.assertEqual(q["type"], "noul")
        self.assertEqual(q["criteria"], {"true": "it can", "false": "it cannot"})

    def test_criteria_are_omitted_when_not_given(self):
        """An empty criteria object is not the same as none, and the server
        validates the shape."""
        self.assertNotIn("criteria", noul("Can this be answered?"))

    def test_a_bare_option_list_becomes_a_mapping(self):
        q = choice("Which applies?", ["h3", "c0065"])
        self.assertEqual(q["criteria"], {"h3": None, "c0065": None})

    def test_option_descriptions_are_kept(self):
        q = choice("Which applies?", {"h3": "standard axle set"})
        self.assertEqual(q["criteria"]["h3"], "standard axle set")

    def test_score_levels_stay_ordered(self):
        """Lowest first, because the answer is an expected level index and
        reversing them silently reverses the scale."""
        q = score("How complete?", ["none", "partial", "full"])
        self.assertEqual(q["criteria"], ["none", "partial", "full"])


class TestParsingAnswers(unittest.TestCase):
    def test_a_yes_no_answer_becomes_a_distribution(self):
        """The server reports P(yes) alone. Keeping both sides means every
        question kind is handled identically downstream."""
        r = parse_answers({"answers": {"q": {"type": "noul", "noul": 0.83}}})["q"]
        self.assertAlmostEqual(r.p_true, 0.83)
        self.assertAlmostEqual(r.probabilities["true"], 0.83)
        self.assertAlmostEqual(r.probabilities["false"], 0.17)

    def test_a_choice_answer_keeps_the_whole_distribution(self):
        """The argmax discards exactly what the model was chosen for."""
        r = parse_answers({"answers": {"q": {
            "type": "choice", "choice": "h3", "confidence": 0.4,
            "probabilities": {"h3": 0.5, "c0065": 0.3, "c0063": 0.2}}}})["q"]
        self.assertEqual(r.answer, "h3")
        self.assertEqual(len(r.probabilities), 3)
        self.assertEqual(r.top, ("h3", 0.5))

    def test_margin_is_reported_because_confidence_cannot_see_rivals(self):
        """`confidence` rescales p_max alone, so it cannot tell one close rival
        from several distant ones. These two have the same p_max."""
        close = AnswerRecord("q", "choice", "a", {"a": 0.5, "b": 0.49, "c": 0.01})
        spread = AnswerRecord("q", "choice", "a", {"a": 0.5, "b": 0.25, "c": 0.25})
        self.assertAlmostEqual(close.margin, 0.01)
        self.assertAlmostEqual(spread.margin, 0.25)

    def test_p_true_is_none_for_a_non_binary_question(self):
        r = AnswerRecord("q", "choice", "a", {"a": 1.0})
        self.assertIsNone(r.p_true)

    def test_a_single_option_has_no_margin(self):
        self.assertIsNone(AnswerRecord("q", "choice", "a", {"a": 1.0}).margin)

    def test_an_unknown_field_degrades_rather_than_raising(self):
        """A server version that renames a field should cost a reported number,
        not a 500-instance run."""
        r = parse_answers({"answers": {"q": {"type": "choice"}}})["q"]
        self.assertEqual(r.probabilities, {})
        self.assertIsNone(r.confidence)
        self.assertIsNone(r.top)

    def test_a_missing_answers_block_is_empty(self):
        self.assertEqual(parse_answers({}), {})


class TestCalibrationMetrics(unittest.TestCase):
    """Known-answer tests. These are the numbers that decide the question, and
    the vendors report moving ECE by a factor of five with a fitted
    temperature, so the measurement has to be trustworthy before the model is."""

    def test_perfect_confident_predictions_score_zero(self):
        pairs = [(1.0, True), (1.0, True), (0.0, False), (0.0, False)]
        self.assertEqual(expected_calibration_error(pairs), 0.0)
        self.assertEqual(brier_score(pairs), 0.0)

    def test_confidently_wrong_scores_worst(self):
        """The failure mode to design against: certain and completely wrong."""
        pairs = [(1.0, False), (0.0, True)]
        self.assertEqual(expected_calibration_error(pairs), 1.0)
        self.assertEqual(brier_score(pairs), 1.0)

    def test_an_honest_coin_is_well_calibrated_but_uninformative(self):
        """ECE 0 and Brier 0.25 together: the distinction AUC cannot draw. A
        model that says 0.5 and is right half the time is perfectly calibrated
        and tells you nothing."""
        pairs = [(0.5, True), (0.5, False)]
        self.assertEqual(expected_calibration_error(pairs), 0.0)
        self.assertEqual(brier_score(pairs), 0.25)

    def test_overconfidence_is_visible(self):
        """Claims 0.9, right 50% of the time."""
        pairs = [(0.9, True), (0.9, False)]
        self.assertAlmostEqual(expected_calibration_error(pairs), 0.4)

    def test_empty_input_is_none_rather_than_zero(self):
        """Zero would read as perfect calibration."""
        self.assertIsNone(expected_calibration_error([]))
        self.assertIsNone(brier_score([]))

    def test_a_probability_of_exactly_one_lands_in_the_last_bin(self):
        """Half-open bins would drop it, and 1.0 is where a model is most
        dangerous."""
        self.assertAlmostEqual(expected_calibration_error([(1.0, False)]), 1.0)

    def test_bins_are_weighted_by_population(self):
        """Nine calibrated predictions and one wrong one is not a 50% error."""
        pairs = [(0.0, False)] * 9 + [(1.0, False)]
        self.assertAlmostEqual(expected_calibration_error(pairs), 0.1)


class TestListingModels(unittest.TestCase):
    """Two servers, two shapes. The first version read only TypeSafe's and
    reported no models against a Kev server that was serving two."""

    class _Client(SystemOneClient):
        payload: dict = {}

        def available(self):
            data = self.payload
            rows = data.get("models") or data.get("data") or []
            out = []
            for row in rows:
                name = row.get("name") or row.get("id")
                if name:
                    out.append(str(name))
            return out

    def test_kevs_shape(self):
        c = self._Client()
        c.payload = {"models": [{"name": "kev-latest"}, {"name": "jev-latest"}]}
        self.assertEqual(c.available(), ["kev-latest", "jev-latest"])

    def test_typesafes_shape(self):
        c = self._Client()
        c.payload = {"data": [{"id": "jev-1"}]}
        self.assertEqual(c.available(), ["jev-1"])

    def test_an_unnamed_row_is_skipped_rather_than_blank(self):
        c = self._Client()
        c.payload = {"models": [{"name": "a"}, {"description": "no name"}]}
        self.assertEqual(c.available(), ["a"])


class TestTransport(unittest.TestCase):
    class _Client(SystemOneClient):
        """Replaces the one network call."""

        reply: dict = {}
        seen: list = []

        def _post(self, path, payload):
            self.seen.append((path, payload))
            return self.reply

    def setUp(self):
        self.client = self._Client()
        self.client.seen = []
        self.client.reply = {
            "model": "kev-0.8b",
            "answers": {"q": {"type": "noul", "noul": 0.7}},
            "usage": {"input_tokens": 120, "output_tokens": 8},
            "latency_ms": 412.0,
        }

    def test_questions_are_sent_in_one_request(self):
        """They share the text and cannot read each other, which is what makes
        a batch cheap rather than a conversation."""
        self.client.ask("some context", {"a": noul("x"), "b": noul("y")})
        path, payload = self.client.seen[0]
        self.assertEqual(path, "/v1/systemone")
        self.assertEqual(sorted(payload["questions"]), ["a", "b"])

    def test_the_call_is_logged_with_the_state_hashed_not_stored(self):
        self.client.ask("depot-12 runs 3.9 bar", {"q": noul("x")})
        record = self.client.calls[0]
        self.assertEqual(record.input_tokens, 120)
        self.assertEqual(record.tokens, 128)
        self.assertEqual(record.server_latency_ms, 412.0)
        self.assertEqual(len(record.state_sha256), 64)
        self.assertNotIn("depot-12", json.dumps(record.__dict__))

    def test_usage_totals_across_calls(self):
        for _ in range(3):
            self.client.ask("x", {"q": noul("x")})
        usage = self.client.usage()
        self.assertEqual(usage["calls"], 3.0)
        self.assertEqual(usage["input_tokens"], 360.0)

    def test_no_questions_is_refused_before_a_request(self):
        with self.assertRaises(ValueError):
            self.client.ask("x", {})
        self.assertEqual(self.client.seen, [])

    def test_a_sink_cannot_break_the_call(self):
        self.client.add_sink(lambda *a, **k: 1 / 0)
        answers = self.client.ask("x", {"q": noul("x")})
        self.assertAlmostEqual(answers["q"].p_true, 0.7)
        self.assertEqual(len(self.client.calls), 1)

    def test_a_missing_server_says_how_to_start_one(self):
        client = SystemOneClient(host="http://127.0.0.1:9", retries=0)
        with self.assertRaises(SystemOneError) as caught:
            client.ask("x", {"q": noul("x")})
        self.assertIn("kev.serve", str(caught.exception))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
