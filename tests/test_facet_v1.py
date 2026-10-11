"""facet_v1: reproducibility, the control's validity, and the separation.

The fixture's entire claim rests on one comparison: the stated control is easy
and the implied families are not, with everything else held fixed. These tests
assert both halves of that, because `facet_trap` scored 1.000 with no control
and its number was therefore uninterpretable -- it could have meant the family
was easy or that the whole benchmark was.
"""

from __future__ import annotations

import json
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from experiments import relevance_bench as rb  # noqa: E402
from research.bench.facet_v1 import build  # noqa: E402
from research.bench.relevance_v2.build import key_matches  # noqa: E402

BENCH = ROOT / "research" / "bench" / "facet_v1"
MANIFEST = json.loads((BENCH / "MANIFEST.json").read_text(encoding="utf-8"))
BUILT = (BENCH / "dev.json").exists() and (BENCH / "test.json").exists()
needs_build = unittest.skipUnless(
    BUILT, "run `python -m research.bench.facet_v1.build`")

IMPLIED = ("implied_by_exclusion", "implied_by_default", "implied_by_paraphrase")


class TestReproducible(unittest.TestCase):
    def test_a_rebuild_matches_the_committed_digests(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            manifest = build.write(pathlib.Path(tmp))
        for split, expected in MANIFEST["splits"].items():
            with self.subTest(split=split):
                self.assertEqual(manifest["splits"][split]["sha256"],
                                 expected["sha256"])


class TestTheImplicationIsReal(unittest.TestCase):
    """The deciding facet must be absent from the answer and present in the
    wrong memories. If it leaks into the answer, the family is a control."""

    @needs_build
    def test_the_answer_does_not_state_the_asked_season(self):
        for split in ("dev", "test"):
            for case in rb.load(split, "facet_v1"):
                if case["family"] not in ("implied_by_exclusion",
                                          "implied_by_default"):
                    continue
                season = next(
                    s for s in ("winter", "summer", "monsoon")
                    if s in case["task"]["task_text"])
                answer = next(m for m in case["corpus"]
                              if m["id"] in case["labels"]["relevant"])
                if case["family"] == "implied_by_exclusion":
                    self.assertNotIn(
                        season, answer["content"],
                        f"{case['case_id']}: the answer states the season, so "
                        f"nothing is implied and this is a control case")

    @needs_build
    def test_the_default_rule_names_neither_the_unit_nor_the_site(self):
        """Why `implied_by_default` is 0.000 for every arm: it is not similar."""
        for split in ("dev", "test"):
            for case in rb.load(split, "facet_v1"):
                if case["family"] != "implied_by_default":
                    continue
                answer = next(m for m in case["corpus"]
                              if m["id"] in case["labels"]["relevant"])
                for entity in case["task"]["entities"]:
                    self.assertNotIn(entity, answer["content"], case["case_id"])

    @needs_build
    def test_the_asked_site_is_never_on_the_exception_list(self):
        for split in ("dev", "test"):
            for case in rb.load(split, "facet_v1"):
                if case["family"] != "implied_by_default":
                    continue
                site = next(e for e in case["task"]["entities"]
                            if e in build.SITES)
                self.assertNotIn(site, build.EXCEPTED, case["case_id"])

    @needs_build
    def test_the_paraphrase_family_shares_no_facet_token_with_the_query(self):
        for split in ("dev", "test"):
            for case in rb.load(split, "facet_v1"):
                if case["family"] != "implied_by_paraphrase":
                    continue
                answer = next(m for m in case["corpus"]
                              if m["id"] in case["labels"]["relevant"])
                for entity in case["task"]["entities"]:
                    self.assertNotIn(entity, answer["content"], case["case_id"])
                self.assertNotIn("winter", answer["content"], case["case_id"])


class TestTheControlIsMatched(unittest.TestCase):
    """A control that differs in more than the implication proves nothing."""

    @needs_build
    def test_the_control_asks_the_same_question_as_its_exclusion_twin(self):
        for split in ("dev", "test"):
            cases = {c["case_id"]: c for c in rb.load(split, "facet_v1")}
            for case_id, case in cases.items():
                if case["family"] != "stated_control":
                    continue
                twin_id = case_id.replace("stated_control",
                                          "implied_by_exclusion")
                twin = cases.get(twin_id)
                self.assertIsNotNone(twin, twin_id)
                self.assertEqual(case["task"]["task_text"],
                                 twin["task"]["task_text"], case_id)
                self.assertEqual(case["task"]["entities"],
                                 twin["task"]["entities"], case_id)

    @needs_build
    def test_the_control_answer_states_the_season(self):
        for split in ("dev", "test"):
            for case in rb.load(split, "facet_v1"):
                if case["family"] != "stated_control":
                    continue
                season = next(s for s in ("winter", "summer", "monsoon")
                              if s in case["task"]["task_text"])
                answer = next(m for m in case["corpus"]
                              if m["id"] in case["labels"]["relevant"])
                self.assertIn(season, answer["content"], case["case_id"])


class TestNoLeak(unittest.TestCase):
    @needs_build
    def test_no_answer_key_matches_an_irrelevant_memory(self):
        """Doubly important here: three families work by withholding the
        query's tokens from the answer, so a value appearing in a near-miss
        would make the fixture measure the opposite of what it claims."""
        for split in ("dev", "test"):
            for case in rb.load(split, "facet_v1"):
                relevant = set(case["labels"]["relevant"])
                for key in case["labels"].get("answer_contains") or ():
                    for memory in case["corpus"]:
                        if memory["id"] in relevant:
                            continue
                        self.assertFalse(
                            key_matches(key, memory["content"]),
                            f"{case['case_id']}: {key!r} leaks into "
                            f"{memory['id']}")


class TestSeparation(unittest.TestCase):
    """The measured claim, asserted so a regression cannot pass silently."""

    @needs_build
    def test_lexical_solves_the_control_and_fails_the_implied_families(self):
        for split in ("dev", "test"):
            result = rb.run(split, k=3, arms=["lexical", "oracle"],
                            benchmark="facet_v1")
            families = result["by_family"]["lexical"]
            self.assertEqual(
                families["stated_control"]["ndcg"], 1.0,
                f"{split}: the control is no longer easy, so the fixture can "
                f"no longer attribute difficulty to the implication")
            for family in IMPLIED:
                self.assertLessEqual(
                    families[family]["ndcg"], 0.25,
                    f"{split}/{family}: lexical now scores "
                    f"{families[family]['ndcg']}. If a change made this easy, "
                    f"that is a result and needs a write-up.")

    @needs_build
    def test_an_arm_with_no_relevance_signal_scores_zero(self):
        for split in ("dev", "test"):
            result = rb.run(split, k=3, arms=["broken_no_signal", "oracle"],
                            benchmark="facet_v1")
            self.assertEqual(result["arms"]["broken_no_signal"]["ndcg_at_k"], 0.0,
                             split)

    @needs_build
    def test_no_arm_beats_the_oracle(self):
        for split in ("dev", "test"):
            result = rb.run(split, k=3, benchmark="facet_v1",
                            arms=["lexical", "lexical_all", "oracle"])
            ceiling = result["arms"]["oracle"]["ndcg_at_k"]
            for name, row in result["arms"].items():
                self.assertLessEqual(row["ndcg_at_k"], ceiling + 1e-9,
                                     f"{split}/{name} beat the ceiling")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
