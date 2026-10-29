"""The relevance contract's invariants — the P0 gate.

No ranker exists yet, deliberately. The one way this project has repeatedly
gone wrong is building a mechanism before the thing that could falsify it, and
a ranker written before the benchmark gets tuned on whichever examples flatter
it. What exists here is the contract the ranker will have to satisfy, and tests
that would fail if it did not.

Each test corresponds to a numbered invariant in `docs/RELEVANCE_SPEC.md`. Most
of them encode a mistake this project has already made and measured:

* relevance must not mutate lifecycle — Phase A measured a withdrawal policy taking success from 0.608 to 0.483, and 57 of naive blame's 87 withdrawals were about a completely different fault;
* a score must not outvote a hard gate — the whole enforcement layer exists because "probably fine" is not an authorisation decision;
* a missing feature must stay missing — `value_mean` returning 0.0 for an unmeasured memory is the bug that made an unevaluated candidate outrank a relevant one;
* an uncertain label must not carry a score — same bug, one layer up.
"""

from __future__ import annotations

import json
import unittest
from dataclasses import FrozenInstanceError

from amberlog.relevance import (
    CONTRACT_VERSION,
    MISSING,
    ContextPackage,
    ContextSnapshot,
    MissingSignal,
    ReasonCode,
    RelevanceAssessment,
    RelevanceEvidence,
    RelevanceLabel,
    SelectionDecision,
    assert_no_lifecycle_authority,
)


def _evidence() -> tuple[RelevanceEvidence, ...]:
    return (RelevanceEvidence(signal="lexical", explanation="matched 2 terms", contribution=0.5),)


def _context(**kwargs) -> ContextSnapshot:
    kwargs.setdefault("task_text", "investigate the recurring charging fault")
    return ContextSnapshot(**kwargs)


def _assessment(context: ContextSnapshot, **kwargs) -> RelevanceAssessment:
    base = dict(
        memory_id="m1",
        memory_version=1,
        context_id=context.context_id,
        label=RelevanceLabel.RELEVANT,
        score=0.8,
        evidence=_evidence(),
    )
    base.update(kwargs)
    return RelevanceAssessment(**base)


class Invariant1_TaskScoped(unittest.TestCase):
    """An assessment is scoped to a context and an exact memory version."""

    def test_an_assessment_names_its_context_and_version(self) -> None:
        context = _context()
        assessment = _assessment(context)
        self.assertEqual(
            assessment.applies_to, ("m1", 1, context.context_id)
        )

    def test_it_does_not_apply_to_another_version(self) -> None:
        """A memory revised after the assessment is a different claim."""
        context = _context()
        assessment = _assessment(context)
        self.assertTrue(assessment.applies("m1", 1, context.context_id))
        self.assertFalse(assessment.applies("m1", 2, context.context_id))

    def test_it_does_not_apply_to_another_context(self) -> None:
        """The same memory is a different answer for a different task."""
        first = _context()
        second = _context(task_text="write the monthly summary")
        assessment = _assessment(first)
        self.assertFalse(assessment.applies("m1", 1, second.context_id))

    def test_it_does_not_apply_to_another_memory(self) -> None:
        context = _context()
        assessment = _assessment(context)
        self.assertFalse(assessment.applies("m2", 1, context.context_id))

    def test_version_zero_is_refused(self) -> None:
        """"Whatever the current version is" is not a binding."""
        context = _context()
        for bad in (0, -1):
            with self.subTest(bad):
                with self.assertRaises(ValueError):
                    _assessment(context, memory_version=bad)


class Invariant2_ChangingTheTaskChangesRelevance(unittest.TestCase):
    """Relevance can reverse without touching a single memory."""

    def test_a_changed_context_is_a_new_context(self) -> None:
        first = _context()
        second = first.evolve(task_text="write the monthly summary")
        self.assertNotEqual(first.context_id, second.context_id)
        self.assertEqual(second.snapshot_revision, first.snapshot_revision + 1)
        # And the original is untouched: it is frozen.
        self.assertEqual(first.task_text, "investigate the recurring charging fault")

    def test_two_labels_for_one_memory_across_two_contexts_coexist(self) -> None:
        """The same memory, relevant here and irrelevant there, with both
        assessments valid at once. Nothing about the memory changed."""
        investigating = _context()
        summarising = investigating.evolve(task_text="write the monthly summary")
        relevant = _assessment(investigating, label=RelevanceLabel.RELEVANT, score=0.9)
        irrelevant = _assessment(
            summarising, label=RelevanceLabel.IRRELEVANT, score=0.05
        )
        self.assertEqual(relevant.memory_id, irrelevant.memory_id)
        self.assertNotEqual(relevant.label, irrelevant.label)
        self.assertTrue(relevant.applies("m1", 1, investigating.context_id))
        self.assertFalse(relevant.applies("m1", 1, summarising.context_id))

    def test_a_context_is_immutable(self) -> None:
        context = _context()
        with self.assertRaises(FrozenInstanceError):
            context.task_text = "something else"  # type: ignore[misc]


class Invariant3_IrrelevanceIsNotAVerdictOnTheMemory(unittest.TestCase):
    """`irrelevant` never deletes, retracts, quarantines, or changes lifecycle.

    The measured reason: Phase A's withdrawal policy took success from 0.608 to
    0.483 by removing memories that had merely been present when an episode
    failed. A relevance signal with lifecycle authority would be that mistake
    with a new name.
    """

    def test_no_relevance_type_has_lifecycle_authority(self) -> None:
        context = _context()
        for obj in (
            context,
            _assessment(context, label=RelevanceLabel.IRRELEVANT, score=0.0),
            SelectionDecision(
                memory_id="m1", memory_version=1, included=False,
                reasons=(ReasonCode.LOW_RELEVANCE,),
            ),
            ContextPackage(
                context_id=context.context_id, decisions=(), integrity_revision=1,
                token_budget=100,
            ),
            RelevanceEvidence(signal="s", explanation="e"),
        ):
            with self.subTest(type(obj).__name__):
                assert_no_lifecycle_authority(obj)

    def test_the_guard_itself_catches_a_lifecycle_method(self) -> None:
        """A test for the test. The invariant is about what the code *cannot*
        do, and that kind of property rots silently when somebody adds a
        convenience method and nothing fails."""

        class Tempting:
            def quarantine(self) -> None:  # pragma: no cover - never called
                ...

        with self.assertRaises(AssertionError) as caught:
            assert_no_lifecycle_authority(Tempting())
        self.assertIn("quarantine", str(caught.exception))

    def test_the_relevance_module_imports_no_lifecycle_api(self) -> None:
        """Structural, so the separation cannot erode by convenience import."""
        from pathlib import Path

        import amberlog.relevance as module

        source = Path(module.__file__).read_text(encoding="utf-8")
        for forbidden in ("from .fabric", "import fabric", "LifecycleState"):
            with self.subTest(forbidden):
                self.assertNotIn(forbidden, source)


class Invariant4_AScoreNeverOverridesAGate(unittest.TestCase):
    """Hard constraints are gates, not weights to be outvoted."""

    def test_an_included_decision_cannot_carry_a_hard_gate_reason(self) -> None:
        for gate in (
            ReasonCode.UNAUTHORIZED,
            ReasonCode.RETRACTED,
            ReasonCode.BLOCKED_LIFECYCLE,
            ReasonCode.WRONG_TENANT,
            ReasonCode.SUPERSEDED,
        ):
            with self.subTest(gate.value):
                with self.assertRaises(ValueError):
                    SelectionDecision(
                        memory_id="m1", memory_version=1, included=True,
                        reasons=(ReasonCode.DIRECT_MATCH, gate),
                        relevance_score=1.0,
                    )

    def test_a_maximal_score_does_not_help(self) -> None:
        """The specific thing a ranker must not be able to do."""
        with self.assertRaises(ValueError):
            SelectionDecision(
                memory_id="m1", memory_version=1, included=True,
                reasons=(ReasonCode.UNAUTHORIZED,), relevance_score=1.0,
            )

    def test_gates_are_distinguishable_from_ranking_outcomes(self) -> None:
        """An operator asking "why did the agent not see this?" needs to know
        whether it ranked low or was refused, because the remedies differ."""
        self.assertTrue(ReasonCode.UNAUTHORIZED.is_hard_gate)
        self.assertTrue(ReasonCode.RETRACTED.is_hard_gate)
        self.assertFalse(ReasonCode.LOW_RELEVANCE.is_hard_gate)
        self.assertFalse(ReasonCode.OVER_BUDGET.is_hard_gate)
        self.assertFalse(ReasonCode.DUPLICATE_OR_REDUNDANT.is_hard_gate)

    def test_a_package_separates_gate_omissions_from_ranking_omissions(self) -> None:
        context = _context()
        package = ContextPackage(
            context_id=context.context_id,
            integrity_revision=4,
            token_budget=1000,
            decisions=(
                SelectionDecision("a", 1, True, (ReasonCode.DIRECT_MATCH,)),
                SelectionDecision("b", 1, False, (ReasonCode.LOW_RELEVANCE,)),
                SelectionDecision("c", 1, False, (ReasonCode.UNAUTHORIZED,)),
                SelectionDecision("d", 1, False, (ReasonCode.OVER_BUDGET,)),
            ),
        )
        self.assertEqual([d.memory_id for d in package.blocked_by_gate()], ["c"])
        self.assertEqual(len(package.omitted), 3)
        self.assertEqual(package.selected_ids, ("a",))


class Invariant5_UncertainIsAValidOutcome(unittest.TestCase):
    def test_uncertain_is_a_label_not_an_error(self) -> None:
        context = _context()
        assessment = _assessment(context, label=RelevanceLabel.UNCERTAIN, score=None)
        self.assertIs(assessment.label, RelevanceLabel.UNCERTAIN)

    def test_an_uncertain_assessment_must_not_carry_a_score(self) -> None:
        """Same bug as `value_mean` returning 0.0 for an unmeasured memory: a
        score on "we do not know" is read as a rank, and then the unknown
        outranks the evaluated."""
        context = _context()
        with self.assertRaises(ValueError):
            _assessment(context, label=RelevanceLabel.UNCERTAIN, score=0.5)


class Invariant6_MissingIsNotZero(unittest.TestCase):
    def test_missing_is_a_distinct_sentinel(self) -> None:
        self.assertIsNot(MISSING, None)
        self.assertNotEqual(MISSING, 0.0)
        self.assertIs(MissingSignal(), MISSING, "singleton")

    def test_missing_is_falsey_so_it_cannot_be_read_as_a_score(self) -> None:
        """A truthy sentinel would be worse: it would read as a present signal
        wherever someone forgot to check."""
        self.assertFalse(bool(MISSING))

    def test_a_missing_signal_stays_missing_in_the_explanation(self) -> None:
        unconfigured = RelevanceEvidence(
            signal="vector", explanation="no vector index configured"
        )
        self.assertTrue(unconfigured.is_missing)
        payload = unconfigured.to_json()
        self.assertIsNone(payload["contribution"])
        self.assertTrue(payload["contribution_missing"])

    def test_a_zero_contribution_is_not_missing(self) -> None:
        """The distinction that decides whether a low rank is a property of the
        memory or of the deployment."""
        scored_zero = RelevanceEvidence(
            signal="lexical", explanation="no overlapping terms", contribution=0.0
        )
        self.assertFalse(scored_zero.is_missing)
        self.assertEqual(scored_zero.to_json()["contribution"], 0.0)

    def test_an_assessment_lists_its_missing_signals(self) -> None:
        context = _context()
        assessment = _assessment(
            context,
            evidence=(
                RelevanceEvidence("lexical", "matched", 0.4),
                RelevanceEvidence("vector", "no index configured"),
                RelevanceEvidence("temporal", "no event_time on the context"),
            ),
        )
        self.assertEqual(assessment.missing_signals, ("vector", "temporal"))


class Invariant7_Auditable(unittest.TestCase):
    def test_an_assessment_without_evidence_is_refused(self) -> None:
        context = _context()
        with self.assertRaises(ValueError):
            _assessment(context, evidence=())

    def test_a_decision_without_a_reason_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            SelectionDecision("m1", 1, True, ())

    def test_inclusions_are_recorded_as_well_as_omissions(self) -> None:
        """Logging only what was included makes an omission undiagnosable."""
        context = _context()
        package = ContextPackage(
            context_id=context.context_id, integrity_revision=1, token_budget=500,
            decisions=(
                SelectionDecision("a", 1, True, (ReasonCode.DIRECT_MATCH,)),
                SelectionDecision("b", 1, False, (ReasonCode.OVER_BUDGET,)),
            ),
        )
        self.assertEqual(len(package.decisions), 2)
        self.assertEqual(
            package.reason_counts(), {"direct_match": 1, "over_budget": 1}
        )

    def test_everything_serialises_to_json(self) -> None:
        context = _context(entities=("valve-7",), constraints=("ignore retracted",))
        assessment = _assessment(context)
        package = ContextPackage(
            context_id=context.context_id, integrity_revision=9, token_budget=800,
            token_count=120,
            decisions=(SelectionDecision("a", 1, True, (ReasonCode.DIRECT_MATCH,)),),
            unresolved_conflicts=("hs_1",),
            missing_evidence=("measurement",),
        )
        for obj in (context, assessment, package):
            with self.subTest(type(obj).__name__):
                # Round-trips through strict JSON: no NaN, no non-serialisable
                # values, which is what an audit record has to survive.
                json.loads(json.dumps(obj.to_json(), allow_nan=False))

    def test_versions_travel_with_the_record(self) -> None:
        context = _context()
        assessment = _assessment(
            context, model_version="hybrid-0", feature_version="f3"
        )
        self.assertEqual(assessment.contract_version, CONTRACT_VERSION)
        self.assertEqual(assessment.to_json()["model_version"], "hybrid-0")
        self.assertEqual(assessment.to_json()["feature_version"], "f3")


class Invariant8_BudgetIsRespected(unittest.TestCase):
    def test_a_package_cannot_exceed_its_budget(self) -> None:
        """The assembler must omit rather than overflow, so an overflowing
        package is a construction error rather than something to report."""
        context = _context(token_budget=100)
        with self.assertRaises(ValueError):
            ContextPackage(
                context_id=context.context_id, decisions=(), integrity_revision=1,
                token_budget=100, token_count=101,
            )

    def test_a_zero_budget_means_unbounded(self) -> None:
        """Explicit, because a default of 0 would otherwise silently forbid
        every assembly."""
        context = _context()
        package = ContextPackage(
            context_id=context.context_id, decisions=(), integrity_revision=1,
            token_budget=0, token_count=5_000,
        )
        self.assertEqual(package.token_count, 5_000)

    def test_a_negative_budget_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            _context(token_budget=-1)


class Invariant9_ObservedAndInferredStaySeparate(unittest.TestCase):
    """An inferred field must never set authorisation or risk, and the only way
    to guarantee that downstream is to be able to tell them apart."""

    def test_both_fields_exist_and_are_distinct(self) -> None:
        context = _context(
            state_facts={"site": "north"}, inferred={"likely_cause": "valve"}
        )
        self.assertEqual(dict(context.state_facts), {"site": "north"})
        self.assertEqual(dict(context.inferred), {"likely_cause": "valve"})

    def test_a_field_cannot_be_both(self) -> None:
        """Otherwise a reader cannot tell which value won, and the one that won
        might be the guess."""
        with self.assertRaises(ValueError) as caught:
            _context(state_facts={"site": "north"}, inferred={"site": "south"})
        self.assertIn("site", str(caught.exception))

    def test_the_json_keeps_them_apart(self) -> None:
        context = _context(state_facts={"a": 1}, inferred={"b": 2})
        payload = context.to_json()
        self.assertEqual(payload["state_facts"], {"a": 1})
        self.assertEqual(payload["inferred"], {"b": 2})


class Invariant10_ContextValidity(unittest.TestCase):
    def test_a_context_needs_a_task(self) -> None:
        for bad in ("", "   ", "\n"):
            with self.subTest(repr(bad)):
                with self.assertRaises(ValueError):
                    ContextSnapshot(task_text=bad)

    def test_event_time_is_separate_from_recorded_time(self) -> None:
        """"What was true then" and "what did we know then" are different
        questions, and one timestamp cannot answer both."""
        context = _context(event_time=1_700_000_000)
        self.assertEqual(context.event_time, 1_700_000_000)
        # And it is optional, because most tasks are about now.
        self.assertIsNone(_context().event_time)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
