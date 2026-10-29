"""X1's reduced store and its extraction cache.

The reduced store is the only reason X1's primary is measurable at all: the
registered families hold 1,374 unique statements on dev and the one model that
extracts them correctly costs 54.5 s each, so a full-size arm is 20.8 hours.
That makes `reduce_case` load-bearing for a *result*, and the properties below
are the ones under which the comparison stays fair.

The property that matters most is the first: **a labelled memory is never
dropped.** Sampling one away would make the case unanswerable for the oracle
too, which would lower the measured ceiling and silently shrink the headroom
the threshold is a share of — principle 8b's failure mode, arrived at from a
new direction.
"""

from __future__ import annotations

import json
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from experiments import x1_extraction as x1  # noqa: E402
from amberlog.extraction import Extracted  # noqa: E402


def case(n_fillers: int = 200) -> dict:
    corpus = [{"id": f"h{i}", "content": f"hop {i}"} for i in (1, 2, 3, 4)]
    corpus += [{"id": f"f{i:04d}", "content": f"filler {i}"}
               for i in range(n_fillers)]
    return {
        "case_id": "multi_hop_4-01",
        "family": "multi_hop_4",
        "corpus": corpus,
        "labels": {"relevant": ["h1", "h2", "h3", "h4"],
                   "critical": ["h3", "h4"],
                   "must_not_expose": ["f0007"]},
    }


class TestReducedStore(unittest.TestCase):
    def test_no_labelled_memory_is_ever_dropped(self):
        """The one that would corrupt the ceiling rather than the arm."""
        for limit in (5, 6, 10, 60, 199):
            reduced = x1.reduce_case(case(), limit)
            kept = {m["id"] for m in reduced["corpus"]}
            for label in ("relevant", "critical", "must_not_expose"):
                for memory_id in reduced["labels"][label]:
                    self.assertIn(memory_id, kept,
                                  f"{memory_id} dropped at limit={limit}")

    def test_the_limit_is_respected(self):
        self.assertEqual(len(x1.reduce_case(case(), 60)["corpus"]), 60)

    def test_a_limit_below_the_labelled_set_keeps_the_labels(self):
        """Correctness beats the budget here. A store too small to hold the
        labelled memories is a store no arm can answer from, so the limit
        yields rather than the labels."""
        reduced = x1.reduce_case(case(), 2)
        kept = {m["id"] for m in reduced["corpus"]}
        self.assertEqual(kept, {"h1", "h2", "h3", "h4", "f0007"})

    def test_zero_and_oversize_limits_pass_the_case_through(self):
        original = case(10)
        self.assertIs(x1.reduce_case(original, 0), original)
        self.assertIs(x1.reduce_case(original, 999), original)

    def test_sampling_is_seeded_per_case_so_arms_see_one_store(self):
        """Two arms of one run call this separately. If they disagreed about
        the corpus, the comparison would be between two stores."""
        first = [m["id"] for m in x1.reduce_case(case(), 60)["corpus"]]
        second = [m["id"] for m in x1.reduce_case(case(), 60)["corpus"]]
        self.assertEqual(first, second)

    def test_two_cases_get_different_filler_samples(self):
        """Seeded per case, not globally: a single seed would give every case
        the same filler indices and make the sample a property of the seed."""
        other = {**case(), "case_id": "multi_hop_4-03"}
        self.assertNotEqual(
            [m["id"] for m in x1.reduce_case(case(), 60)["corpus"]],
            [m["id"] for m in x1.reduce_case(other, 60)["corpus"]])

    def test_corpus_order_is_preserved(self):
        """Insertion order drives the temporal mechanisms, so the sampling must
        not reorder the store or it would be changing a second variable."""
        original = [m["id"] for m in case()["corpus"]]
        reduced = [m["id"] for m in x1.reduce_case(case(), 60)["corpus"]]
        self.assertEqual(reduced, [i for i in original if i in set(reduced)])

    def test_the_original_case_is_not_mutated(self):
        original = case()
        before = len(original["corpus"])
        x1.reduce_case(original, 20)
        self.assertEqual(len(original["corpus"]), before)


class TestCache(unittest.TestCase):
    class _Extractor:
        def __init__(self, model, constrained=True):
            self.model = model
            self.constrained = constrained
            self._cache: dict[str, Extracted] = {}

    def test_a_record_survives_a_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "c.json"
            out = self._Extractor("gemma2:latest")
            out._cache["a statement"] = Extracted(
                "m", asserts=False, modifies="axle-set figure",
                excepts=("harbour",))
            x1.save_cache(out, path)
            back = self._Extractor("gemma2:latest")
            self.assertEqual(x1.load_cache(back, path), 1)
            self.assertEqual(back._cache["a statement"].modifies,
                             "axle-set figure")
            self.assertEqual(back._cache["a statement"].excepts, ("harbour",))

    def test_a_cache_from_another_model_is_refused(self):
        """Sharing one cache between models would make the result a property of
        whichever model happened to run first, which is the kind of error that
        looks like a speedup."""
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "c.json"
            out = self._Extractor("gemma2:latest")
            out._cache["s"] = Extracted("m")
            x1.save_cache(out, path)
            other = self._Extractor("qwen2.5:7b")
            self.assertEqual(x1.load_cache(other, path), 0)
            self.assertEqual(other._cache, {})

    def test_a_cache_from_the_other_decoding_mode_is_refused(self):
        """Schema-constrained and free-form decoding produce different records
        from the same statement, so a cache that crossed that boundary would
        make an arm a mixture of two mechanisms."""
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "c.json"
            out = self._Extractor("gemma2:latest", constrained=True)
            out._cache["s"] = Extracted("m")
            x1.save_cache(out, path)
            free = self._Extractor("gemma2:latest", constrained=False)
            self.assertEqual(x1.load_cache(free, path), 0)
            self.assertEqual(free._cache, {})
            same = self._Extractor("gemma2:latest", constrained=True)
            self.assertEqual(x1.load_cache(same, path), 1)

    def test_the_decoding_mode_is_recorded_beside_the_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "c.json"
            extractor = self._Extractor("m", constrained=False)
            extractor._cache["s"] = Extracted("m")
            x1.save_cache(extractor, path)
            self.assertFalse(
                json.loads(path.read_text(encoding="utf-8"))["constrained"])

    def test_a_missing_cache_is_not_an_error(self):
        extractor = self._Extractor("gemma2:latest")
        self.assertEqual(
            x1.load_cache(extractor, pathlib.Path("no-such-file.json")), 0)

    def test_the_model_is_recorded_beside_the_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "c.json"
            extractor = self._Extractor("gemma2:latest")
            extractor._cache["s"] = Extracted("m")
            x1.save_cache(extractor, path)
            stored = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(stored["model"], "gemma2:latest")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
