"""Extraction: the structural half, with no model in the loop.

`memory_fabric/extraction.py` has two halves. One calls a model; the other
turns its output into relations and applicability, and that half is pure. Every
test here exercises the pure half, using `StubExtractor` or hand-built records.

`StubExtractor` is **not an arm** — a stub fitted to this project's fixtures is
the pattern problem the registration rejected, and no result may quote it. It
is here so the structural half has tests that do not need a model reachable,
which is also why CI never calls one.
"""

from __future__ import annotations

import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from memory_fabric import MemoryFabric  # noqa: E402
from memory_fabric.extraction import (  # noqa: E402
    Extracted, StubExtractor, _entities, applicable_defaults, infer_relations,
    parse,
)
from memory_fabric.relations import RelationKind  # noqa: E402

RULE = "All yard vehicles run 3.9 bar in winter, except at the harbour and quarry sites."
MARGIN = "At the depot-12 site, add 0.35 bar to the axle-set figure as a salt-corrosion margin."
PRESSURE = "Vehicles with the standard axle set run 4.0 bar in summer."


class TestParsingModelOutput(unittest.TestCase):
    """Models wrap JSON in prose, fences and preambles. That is the normal
    case, not an error."""

    def test_a_fenced_object_is_read(self):
        record = parse("m", '```json\n{"asserts": false, "modifies": "x"}\n```')
        self.assertFalse(record.asserts)
        self.assertEqual(record.modifies, "x")

    def test_a_preamble_is_tolerated(self):
        record = parse("m", 'Sure! Here is the JSON:\n{"subject": "Crane-5"}')
        self.assertEqual(record.subject, "crane-5")

    def test_an_unparseable_reply_asserts_nothing(self):
        """Distinguishable from a memory that asserts nothing: this one has no
        structure at all, which is the honest representation of a model with
        nothing to say."""
        record = parse("m", "I am not able to help with that.")
        self.assertFalse(record.asserts)
        self.assertIsNone(record.predicate)
        self.assertEqual(record.excepts, ())

    def test_a_string_where_a_list_was_asked_for_is_accepted(self):
        record = parse("m", '{"excepts": "at the harbour and quarry sites"}')
        self.assertEqual(record.excepts, ("harbour", "quarry"))


class TestEntitySplitting(unittest.TestCase):
    def test_a_prose_exclusion_becomes_entities(self):
        self.assertEqual(_entities("at the harbour and quarry sites"),
                         ["harbour", "quarry"])

    def test_a_list_is_left_alone(self):
        self.assertEqual(_entities("harbour, quarry"), ["harbour", "quarry"])

    def test_word_boundaries_are_respected(self):
        """A regression with a visible cause: `\\b` is a valid Python escape
        for backspace, so a single-backslash occurrence reached the module as
        an invisible control character and the split matched inside words."""
        self.assertEqual(_entities("the island site"), ["the island"])
        self.assertEqual(_entities("in the northern or southern depots"),
                         ["northern", "southern"])


class TestAFailedParseIsNotASilentSuccess(unittest.TestCase):
    """The flaw that inflated a published column.

    An unparseable reply became `Extracted(asserts=False)`, which has no
    `modify_target` and no `excepts` -- so every classifier read it as an
    ordinary statement, the majority class. A model that failed on all 19
    statements scored **17/17** on the `plain` column, which exists precisely
    to catch a model behaving badly. The module docstring had claimed the two
    cases were distinguishable "by `parsed`" since before the field existed.
    """

    def test_an_unparseable_reply_is_marked_unparsed(self):
        self.assertFalse(parse("m", "I am not able to help with that.").parsed)

    def test_malformed_json_is_marked_unparsed(self):
        self.assertFalse(parse("m", '{"asserts": tru').parsed)

    def test_an_object_with_none_of_the_schema_keys_is_unparsed(self):
        """A model replying `{"answer": "3.9 bar"}` has produced an object but
        not a record, and counting it as one would file it in the majority
        class beside everything that genuinely asserts nothing."""
        self.assertFalse(parse("m", '{"answer": "3.9 bar"}').parsed)

    def test_a_record_wrapped_in_a_list_still_parses(self):
        """Tolerance worth keeping, and the reason the check is on the keys
        rather than on the top-level type: models wrap the object."""
        record = parse("m", '[{"asserts": false, "modifies": "axle-set"}]')
        self.assertTrue(record.parsed)
        self.assertEqual(record.modifies, "axle-set")

    def test_a_real_record_is_marked_parsed(self):
        self.assertTrue(parse("m", '{"asserts": true}').parsed)

    def test_an_unparsed_record_cannot_be_a_default(self):
        """Otherwise a garbled reply that happened to contain the word
        "except" would add an applicability rule nothing asserted."""
        record = Extracted("m", excepts=("harbour",), parsed=False)
        self.assertFalse(record.is_default)

    def test_an_unparsed_record_cannot_be_a_modifier(self):
        record = Extracted("m", asserts=False, modifies="axle-set",
                           parsed=False)
        self.assertFalse(record.is_modifier)

    def test_a_memory_that_genuinely_asserts_nothing_is_still_parsed(self):
        """The distinction the field is for: the model replied, and what it
        replied was that this statement asserts nothing."""
        record = parse("m", '{"asserts": false, "predicate": null}')
        self.assertTrue(record.parsed)
        self.assertFalse(record.asserts)


class TestClassification(unittest.TestCase):
    def test_a_modifier_target_is_read_from_either_field(self):
        """Models disagree about where it goes: `gemma2` fills `modifies`,
        `qwen2.5:7b` recognises the statement asserts nothing and puts the
        target in `predicate`. Reading both is robustness across models."""
        explicit = Extracted("a", asserts=False, modifies="axle-set figure")
        implicit = Extracted("b", asserts=False, predicate="axle-set figure")
        self.assertEqual(explicit.modify_target, "axle-set figure")
        self.assertEqual(implicit.modify_target, "axle-set figure")
        self.assertTrue(explicit.is_modifier)
        self.assertTrue(implicit.is_modifier)

    def test_an_assertion_is_not_a_modifier_whatever_its_predicate(self):
        record = Extracted("a", asserts=True, predicate="axle-set figure")
        self.assertIsNone(record.modify_target)
        self.assertFalse(record.is_modifier)

    def test_a_default_may_also_be_scoped(self):
        """The schema error the first version made. "All vehicles run X in
        winter, except at two sites" is scoped to a season *and* excepts two
        sites, and every model tested reported the season as scope."""
        record = Extracted("a", asserts=True, scope=("winter",),
                           excepts=("harbour",))
        self.assertTrue(record.is_default)


class TestApplicability(unittest.TestCase):
    RULE = Extracted("rule", asserts=True, scope=("winter",),
                     excepts=("harbour", "quarry"))

    def test_a_default_applies_where_it_is_not_excepted(self):
        self.assertTrue(self.RULE.applies_to(["crane-5", "depot-7"]))

    def test_a_default_does_not_apply_where_it_is_excepted(self):
        self.assertFalse(self.RULE.applies_to(["crane-5", "harbour"]))

    def test_applicable_defaults_selects_only_defaults(self):
        plain = Extracted("plain", asserts=True, predicate="clearance")
        found = applicable_defaults([self.RULE, plain], ["depot-7"])
        self.assertEqual(found, ["rule"])

    def test_no_entities_means_no_defaults(self):
        """A query naming nothing cannot have a default's scope checked
        against it, and guessing would admit every rule in the store."""
        self.assertEqual(applicable_defaults([self.RULE], []), [])


class TestTheMatcherIsFittedToMyPhrasing(unittest.TestCase):
    """The circularity the registration thought it had escaped.

    `research/prereg/x1-extraction-at-ingest.md` declined a *pattern*
    extractor because the target text is this project's own generated phrasing,
    so a regex would pass by construction; a general-purpose model is not
    fitted to my phrasing, so the objection did not transfer. True of the
    extractor — and **the matcher was still fitted to it.**

    `infer_relations` joins a modifier's `modifies` to a stated memory's
    `predicate` by containment. `test_a_modifier_qualifies_what_it_adjusts`
    below passes on `modifies="axle-set"` against
    `predicate="tyre pressure for the axle set"`. Measured, `gemma2` extracts
    `modifies='axle-set figure'` and `predicate='tyre pressure'`, and **no
    containment exists between them**: the modifier names the quantity being
    adjusted and the assertion names the property, which is a semantic link and
    not a lexical one.

    Both halves of that fixture were hand-written by me, and the pairing
    matches on exactly one of the four combinations of
    {fixture, measured} x {target, predicate} — the one where I chose both.
    Not one of seven models produced the edge
    (`research/results/x1-extraction.md` section 11).

    These tests pin the gap so the next change to the matcher has to confront
    it rather than rediscover it.
    """

    FIXTURE_TARGET, FIXTURE_PREDICATE = "axle-set", "tyre pressure for the axle set"
    MEASURED_TARGET, MEASURED_PREDICATE = "axle-set figure", "tyre pressure"

    def _edge(self, target, predicate):
        records = [
            Extracted("h3", asserts=True, predicate=predicate),
            Extracted("h4", asserts=False, modifies=target),
        ]
        return infer_relations(records)

    def test_the_hand_written_pair_matches(self):
        """The combination the unit test below uses, and the only one of four
        that works."""
        self.assertEqual(
            self._edge(self.FIXTURE_TARGET, self.FIXTURE_PREDICATE),
            [("h4", RelationKind.QUALIFIES, "h3")])

    def test_what_a_model_actually_produces_does_not_match(self):
        """`gemma2`'s own extraction of the two memories, which is correct on
        both sides and yields no edge."""
        self.assertEqual(
            self._edge(self.MEASURED_TARGET, self.MEASURED_PREDICATE), [],
            "if this now passes, the matcher was changed and section 11 of "
            "the result needs re-measuring")

    def test_changing_either_side_alone_also_fails(self):
        """So the fixture is not merely approximate -- both halves are
        load-bearing, which is what 'fitted' means."""
        self.assertEqual(
            self._edge(self.MEASURED_TARGET, self.FIXTURE_PREDICATE), [])
        self.assertEqual(
            self._edge(self.FIXTURE_TARGET, self.MEASURED_PREDICATE), [])


class TestRelationInference(unittest.TestCase):
    def test_a_modifier_qualifies_what_it_adjusts(self):
        records = [
            Extracted("h3", asserts=True, predicate="tyre pressure for the axle set"),
            Extracted("h4", asserts=False, modifies="axle-set"),
        ]
        self.assertEqual(infer_relations(records),
                         [("h4", RelationKind.QUALIFIES, "h3")])

    def test_nothing_is_inferred_without_a_modifier(self):
        records = [
            Extracted("a", asserts=True, predicate="clearance"),
            Extracted("b", asserts=True, predicate="tyre pressure"),
        ]
        self.assertEqual(infer_relations(records), [])

    def test_a_memory_cannot_qualify_itself(self):
        records = [Extracted("a", asserts=False, modifies="clearance",
                             predicate="clearance")]
        self.assertEqual(infer_relations(records), [])


class TestInTheStore(unittest.TestCase):
    def _fabric(self):
        return MemoryFabric(":memory:", auto_activate=True,
                            encrypt_content=False, retrieval="lexical")

    def test_an_applicable_default_is_admitted(self):
        fabric = self._fabric()
        stub = StubExtractor()
        try:
            rule = fabric.remember(agent_id="a", content=RULE)
            fabric.index_extraction(stub.extract(rule, RULE))
            result = fabric.retrieve(
                agent_id="a",
                query="What is the winter tyre pressure for crane-5 at the depot-7 site?",
                k=5, min_relevance=0.0, entities=["crane-5", "depot-7"],
                use_extraction=True)
            self.assertIn(rule, [m.id for m in result.exposed])
        finally:
            fabric.close()

    def test_an_excepted_default_is_withheld_even_when_it_ranks(self):
        """The half the first implementation missed.

        A rule saying "except at the harbour site" shares enough words with a
        question about the harbour site to be retrieved by similarity, and
        serving it there is a wrong answer rather than an incomplete one.
        """
        fabric = self._fabric()
        stub = StubExtractor()
        try:
            rule = fabric.remember(agent_id="a", content=RULE)
            fabric.index_extraction(stub.extract(rule, RULE))
            without = fabric.retrieve(
                agent_id="a", query="winter tyre pressure for yard vehicles",
                k=5, min_relevance=0.0)
            self.assertIn(rule, [m.id for m in without.exposed],
                          "the rule must rank, or this proves nothing")
            withheld = fabric.retrieve(
                agent_id="a", query="winter tyre pressure for yard vehicles",
                k=5, min_relevance=0.0, entities=["harbour"],
                use_extraction=True)
            self.assertNotIn(rule, [m.id for m in withheld.exposed])
        finally:
            fabric.close()

    def test_an_inferred_relation_pulls_the_modifier_in(self):
        fabric = self._fabric()
        try:
            rule = fabric.remember(agent_id="a", content=PRESSURE)
            margin = fabric.remember(agent_id="a", content=MARGIN)
            records = [
                Extracted(rule, asserts=True, predicate="tyre pressure for the axle set"),
                Extracted(margin, asserts=False, modifies="axle-set"),
            ]
            for record in records:
                fabric.index_extraction(record)
            for subject, kind, obj in infer_relations(records):
                fabric.relate(subject, kind, obj, actor="extraction")
            self.assertEqual(fabric.relations_of(margin, "qualifies"), [rule])
        finally:
            fabric.close()

    def test_a_scoped_adjustment_is_admitted_for_its_own_site(self):
        """Gap 1, end to end through the public API.

        X1's mechanism scored 0.000 with *correct* extractions because an
        adjustment carrying a scope and no exceptions had no path into a
        context: `_admit_defaults` admitted only records with exceptions. The
        adjustment is not similar to the query -- it names a site and a
        quantity, not the unit asked about -- and it is not a relation to one
        rule rather than another, because twelve of them differ only by site.
        """
        fabric = self._fabric()
        try:
            margin = fabric.remember(agent_id="a", content=MARGIN)
            fabric.index_extraction(Extracted(
                margin, asserts=False, modifies="axle-set figure",
                scope=("depot-12",), adjustment="0.35 bar"))
            without = fabric.retrieve(
                agent_id="a", query="winter tyre pressure for crane-5",
                k=5, min_relevance=0.0)
            self.assertNotIn(margin, [m.id for m in without.exposed],
                             "it must not rank, or this proves nothing")
            with_it = fabric.retrieve(
                agent_id="a", query="winter tyre pressure for crane-5",
                k=5, min_relevance=0.0, entities=["crane-5", "depot-12"],
                use_extraction=True)
            self.assertIn(margin, [m.id for m in with_it.exposed])
        finally:
            fabric.close()

    def test_an_adjustment_for_another_site_is_withheld(self):
        """The half that matters more. Twelve adjustments differ only by site
        name, so admitting on the quantity alone would add eleven wrong
        figures to every context -- which is a wrong answer rather than an
        incomplete one."""
        fabric = self._fabric()
        try:
            margin = fabric.remember(agent_id="a", content=MARGIN)
            fabric.index_extraction(Extracted(
                margin, asserts=False, modifies="axle-set figure",
                scope=("harbour",)))
            result = fabric.retrieve(
                agent_id="a", query="winter tyre pressure for crane-5",
                k=5, min_relevance=0.0, entities=["crane-5", "depot-12"],
                use_extraction=True)
            self.assertNotIn(margin, [m.id for m in result.exposed])
        finally:
            fabric.close()

    def test_an_unscoped_modifier_is_not_admitted_as_an_adjustment(self):
        """`is_adjustment` requires a scope. A modifier that names no site
        cannot be selected by the query's entities, and admitting it for every
        query would be a mechanism that only ever adds."""
        fabric = self._fabric()
        try:
            margin = fabric.remember(agent_id="a", content=MARGIN)
            fabric.index_extraction(Extracted(
                margin, asserts=False, modifies="axle-set figure"))
            result = fabric.retrieve(
                agent_id="a", query="winter tyre pressure for crane-5",
                k=5, min_relevance=0.0, entities=["crane-5", "depot-12"],
                use_extraction=True)
            self.assertNotIn(margin, [m.id for m in result.exposed])
        finally:
            fabric.close()

    def test_a_default_and_an_adjustment_are_both_admitted(self):
        """They are different shapes reached by the same rule, and a context
        needing both must get both."""
        fabric = self._fabric()
        stub = StubExtractor()
        try:
            rule = fabric.remember(agent_id="a", content=RULE)
            margin = fabric.remember(agent_id="a", content=MARGIN)
            fabric.index_extraction(stub.extract(rule, RULE))
            fabric.index_extraction(Extracted(
                margin, asserts=False, modifies="axle-set figure",
                scope=("depot-12",)))
            result = fabric.retrieve(
                agent_id="a",
                query="winter tyre pressure for crane-5 at depot-12",
                k=5, min_relevance=0.0, entities=["crane-5", "depot-12"],
                use_extraction=True)
            exposed = [m.id for m in result.exposed]
            self.assertIn(rule, exposed)
            self.assertIn(margin, exposed)
        finally:
            fabric.close()

    def test_extraction_is_off_unless_asked_for(self):
        """One model call per memory is not something a write should do by
        default, and the registered prediction is that the cost makes it a
        batch job."""
        fabric = self._fabric()
        try:
            rule = fabric.remember(agent_id="a", content=RULE)
            self.assertEqual(fabric.extracted, {})
            result = fabric.retrieve(
                agent_id="a", query="winter tyre pressure for yard vehicles",
                k=5, min_relevance=0.0, entities=["harbour"])
            self.assertIn(rule, [m.id for m in result.exposed])
        finally:
            fabric.close()


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
