"""Bitemporal validity: the three temporal questions a caller can ask.

Schema 0.7.0 added `valid_from` / `valid_to` and this file did not exist. The
behaviour was covered incidentally -- `test_version_skew.py` checks that an
absent window preserves pre-0.7.0 behaviour, and `relevance_v1`'s
`temporal_drift` family exercises it through the benchmark -- but nothing
asserted what the modes mean, which is how a mis-specified call survived until
an external benchmark measured what it cost.
"""

from __future__ import annotations

import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from memory_fabric import MemoryFabric  # noqa: E402


class TestTheThreeTemporalQuestions(unittest.TestCase):
    """`as_of`, `until`, and neither -- three different questions.

    Added after an external benchmark found that conflating the first and the
    third costs 19 points of turn recall. LongMemEval's temporal-reasoning
    questions ask "which did I do first", and passing the question's own date
    as `as_of` discards 20% of the turns, because the evidence for an ordering
    question is spread across the whole history and some of it postdates the
    moment the question is asked.

    Every internal benchmark agreed with the old advice, because none of them
    placed evidence after the task's event time.
    """

    T = 1_700_000_000
    DAY = 86_400

    def _store(self):
        fabric = MemoryFabric(":memory:", auto_activate=True,
                              encrypt_content=False, retrieval="lexical")
        ids = {
            "superseded": fabric.remember(
                agent_id="a",
                content="The yard speed limit is 8 km/h for all vehicles.",
                valid_from=self.T - 400 * self.DAY,
                valid_to=self.T - 10 * self.DAY),
            "current": fabric.remember(
                agent_id="a",
                content="The yard speed limit is 5 km/h for all vehicles now.",
                valid_from=self.T - 10 * self.DAY),
            "future": fabric.remember(
                agent_id="a",
                content="The yard speed limit review is scheduled for all vehicles.",
                valid_from=self.T + 50 * self.DAY),
        }
        return fabric, {v: k for k, v in ids.items()}

    def _ask(self, fabric, names, **kwargs):
        result = fabric.retrieve(
            agent_id="a",
            query="what is the yard speed limit for all vehicles",
            k=10, min_relevance=0.0, **kwargs)
        return {names[m.id] for m in result.exposed}

    def test_as_of_gives_the_state_at_that_moment(self):
        fabric, names = self._store()
        try:
            self.assertEqual(self._ask(fabric, names, as_of=self.T), {"current"})
        finally:
            fabric.close()

    def test_until_gives_the_history_through_that_moment(self):
        """Including claims since superseded, excluding ones not yet in force."""
        fabric, names = self._store()
        try:
            self.assertEqual(self._ask(fabric, names, until=self.T),
                             {"current", "superseded"})
        finally:
            fabric.close()

    def test_neither_gives_the_whole_history(self):
        """What an ordering question needs. Filtering it is where the 19 points
        went."""
        fabric, names = self._store()
        try:
            self.assertEqual(self._ask(fabric, names),
                             {"current", "superseded", "future"})
        finally:
            fabric.close()

    def test_the_two_bounds_compose(self):
        fabric, names = self._store()
        try:
            # State at T, and nothing recorded as beginning after T. The
            # intersection, not the union: each bound only ever removes.
            self.assertEqual(
                self._ask(fabric, names, as_of=self.T, until=self.T),
                {"current"})
        finally:
            fabric.close()

    def test_reconstruct_takes_the_same_bounds(self):
        """A chain must not be able to reach round the temporal filter."""
        fabric, names = self._store()
        try:
            chain = fabric.reconstruct(
                agent_id="a",
                query="what is the yard speed limit for all vehicles",
                as_of=self.T)
            reached = {names[s.memory_id] for s in chain.steps}
            self.assertNotIn("superseded", reached)
            self.assertNotIn("future", reached)
        finally:
            fabric.close()
