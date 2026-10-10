"""Phase 4 — truth maintenance.

Exit gate: branching derivations and multiple independent justifications work;
contradictions remain inspectable; false retractions can be recovered from
without rewriting history; no indiscriminate descendant deletion.

This is the phase that answers the question the project is ultimately asked:
*can a harmful belief be corrected without withdrawing unrelated useful
knowledge?* Before Phase 4 the answer was no, and the reason was one
unconditional loop — every descendant was contested, so a conclusion resting on
two independent premises was treated exactly like one resting on a single
invalidated premise.

The tests are built around the distinctions that actually change the outcome:
conjunction versus alternatives, a copy versus independent corroboration, and a
version that moved under a conclusion's feet.
"""

from __future__ import annotations

import unittest

from memory_fabric import LifecycleState, MemoryFabric, WithdrawalBasis
from memory_fabric.justification import (
    CONTESTED,
    JUSTIFIED,
    UNSUPPORTED,
    JustificationKind,
    justification_context,
)


class JustificationCase(unittest.TestCase):
    def setUp(self) -> None:
        self.fabric = MemoryFabric(":memory:")
        self.addCleanup(self.fabric.close)

    def observe(self, agent: str, content: str) -> str:
        memory_id = self.fabric.remember(agent, content)
        self.fabric.validate(memory_id, actor="supervisor")
        return memory_id

    def conclude(
        self, agent: str, content: str, parents: dict[str, JustificationKind]
    ) -> str:
        memory_id = self.fabric.derive(
            agent, content, parents=list(parents),
            context=justification_context(parents.items()),
        )
        self.fabric.validate(memory_id, actor="supervisor")
        return memory_id

    def retract(self, memory_id: str, reason: str = "contradicted") -> list[str]:
        return self.fabric.quarantine(
            memory_id, reason=reason, actor="safety",
            basis=WithdrawalBasis.CONTRADICTED,
        )


class TestIndependentJustificationsSurvive(JustificationCase):
    """The headline requirement, and the one that was missing."""

    def test_losing_one_of_two_independent_premises_leaves_the_conclusion_alone(self) -> None:
        a = self.observe("ag1", "Tug A overheated at 40C in July.")
        b = self.observe("ag2", "Tug B overheated at 41C in August.")
        conclusion = self.conclude(
            "ag3", "Tugs overheat above 40C.",
            {a: JustificationKind.ALTERNATIVE, b: JustificationKind.ALTERNATIVE},
        )

        contested = self.retract(a, "sensor on Tug A was miscalibrated")

        self.assertEqual(contested, [], "contested a conclusion that still had support")
        self.assertEqual(
            self.fabric.get(conclusion).lifecycle_state, LifecycleState.ACTIVE
        )

    def test_losing_both_independent_premises_contests_it(self) -> None:
        a = self.observe("ag1", "Tug A overheated at 40C.")
        b = self.observe("ag2", "Tug B overheated at 41C.")
        conclusion = self.conclude(
            "ag3", "Tugs overheat above 40C.",
            {a: JustificationKind.ALTERNATIVE, b: JustificationKind.ALTERNATIVE},
        )
        self.retract(a)
        self.retract(b)
        self.assertEqual(
            self.fabric.get(conclusion).lifecycle_state, LifecycleState.CONTESTED
        )

    def test_an_unsupported_conclusion_is_contested_not_deleted(self) -> None:
        """A conclusion whose premises were withdrawn may be true anyway, and
        the project has measured what indiscriminate withdrawal costs."""
        a = self.observe("ag1", "The only observation.")
        conclusion = self.conclude("ag2", "A conclusion.", {a: JustificationKind.REQUIRED})
        self.retract(a)
        state = self.fabric.get(conclusion).lifecycle_state
        self.assertEqual(state, LifecycleState.CONTESTED)
        self.assertNotEqual(state, LifecycleState.DELETED)
        self.assertNotEqual(state, LifecycleState.QUARANTINED)

    def test_the_verdict_records_what_carried_the_conclusion(self) -> None:
        a = self.observe("ag1", "Observation A.")
        b = self.observe("ag2", "Observation B.")
        conclusion = self.conclude(
            "ag3", "Therefore X.",
            {a: JustificationKind.ALTERNATIVE, b: JustificationKind.ALTERNATIVE},
        )
        self.retract(a)
        verdict = self.fabric.justifications.recompute(conclusion)
        self.assertEqual(verdict.verdict, JUSTIFIED)
        self.assertEqual(verdict.surviving, (b,))
        self.assertEqual(verdict.lost, (a,))
        self.assertIn(b, verdict.reason)


class TestConjunctions(JustificationCase):
    """A conclusion needing *all* its premises is the unsafe default for a
    reason: assuming independence that was never stated would keep a conclusion
    alive on support that does not exist."""

    def test_losing_one_required_premise_contests_the_conclusion(self) -> None:
        a = self.observe("ag1", "The charger is on circuit 3.")
        b = self.observe("ag2", "Circuit 3 is rated 32A.")
        conclusion = self.conclude(
            "ag3", "The charger is limited to 32A.",
            {a: JustificationKind.REQUIRED, b: JustificationKind.REQUIRED},
        )
        self.retract(a, "it is on circuit 4")
        self.assertEqual(
            self.fabric.get(conclusion).lifecycle_state, LifecycleState.CONTESTED
        )

    def test_required_is_the_default_when_nothing_was_stated(self) -> None:
        """A caller that does not record the edge kind gets the safe reading."""
        a = self.observe("ag1", "Premise.")
        plain = self.fabric.derive("ag2", "Conclusion.", parents=[a])
        self.fabric.validate(plain, actor="supervisor")
        self.assertEqual(
            self.fabric.justifications.kind_of(plain, a), JustificationKind.REQUIRED
        )
        self.retract(a)
        self.assertEqual(self.fabric.get(plain).lifecycle_state, LifecycleState.CONTESTED)

    def test_an_alternative_cannot_rescue_a_lost_requirement(self) -> None:
        """If one premise was genuinely necessary, an independent alternative
        for a *different* part of the argument does not restore it."""
        needed = self.observe("ag1", "Necessary premise.")
        extra = self.observe("ag2", "An independent corroboration.")
        conclusion = self.conclude(
            "ag3", "Conclusion.",
            {needed: JustificationKind.REQUIRED, extra: JustificationKind.ALTERNATIVE},
        )
        self.retract(needed)
        verdict = self.fabric.justifications.recompute(conclusion)
        self.assertEqual(verdict.verdict, CONTESTED)
        self.assertIn("required", verdict.reason)


class TestCopiesAreNotCorroboration(JustificationCase):
    """SECURITY.md T3: several agents can "confirm" a claim they all inherited
    from one source. Shared ancestry is correlated evidence."""

    def test_a_copy_of_a_retracted_premise_does_not_keep_a_conclusion_alive(self) -> None:
        source = self.observe("ag1", "The original observation.")
        copy = self.fabric.derive(
            "ag2", "The original observation.", parents=[source],
            context=justification_context([(source, JustificationKind.COPIED)]),
        )
        self.fabric.validate(copy, actor="supervisor")
        conclusion = self.conclude(
            "ag3", "Therefore X.",
            {source: JustificationKind.ALTERNATIVE, copy: JustificationKind.ALTERNATIVE},
        )

        self.retract(source, "the original was wrong")
        self.assertEqual(
            self.fabric.get(conclusion).lifecycle_state,
            LifecycleState.CONTESTED,
            "a copy of the retracted premise was counted as independent support",
        )

    def test_independent_support_thins_out_shared_ancestry(self) -> None:
        root = self.observe("ag1", "Root.")
        left = self.fabric.derive("ag2", "Left reading.", parents=[root])
        right = self.fabric.derive("ag3", "Right reading.", parents=[root])
        for memory_id in (left, right):
            self.fabric.validate(memory_id, actor="supervisor")

        kept = self.fabric.justifications.independent_support([left, right])
        self.assertEqual(len(kept), 1, "two descendants of one root are one piece of evidence")

    def test_two_genuinely_independent_observations_both_count(self) -> None:
        a = self.observe("ag1", "Independent A.")
        b = self.observe("ag2", "Independent B.")
        kept = self.fabric.justifications.independent_support([a, b])
        self.assertEqual(set(kept), {a, b})

    def test_an_import_is_a_copy_whatever_the_caller_said(self) -> None:
        """An import is a copy of its origin by construction, so it can never be
        independent corroboration even if a caller claims otherwise."""
        from memory_fabric.federation import offer
        from memory_fabric.governance.firewall import (
            Firewall,
            rule_capabilities_must_be_granted,
            rule_must_be_active,
            rule_restricted_stays_private,
        )

        permissive = Firewall(
            rules=(
                rule_restricted_stays_private,
                rule_must_be_active,
                rule_capabilities_must_be_granted,
            )
        )
        origin = MemoryFabric(":memory:", firewall=permissive)
        recipient = MemoryFabric(":memory:", firewall=permissive)
        self.addCleanup(origin.close)
        self.addCleanup(recipient.close)

        source = origin.remember("ag_n", "A claim.")
        origin.validate(source, actor="supervisor")
        result = offer(origin, source, recipient, recipient_agent="ag_s")
        recipient.validate(result.imported_memory_id, actor="ag_s")

        self.assertEqual(
            recipient.justifications.kind_of(result.imported_memory_id, source),
            JustificationKind.COPIED,
        )


class TestVersionAwareness(JustificationCase):
    """A conclusion derived from v2 is not supported by v3 having replaced it.

    Provenance always recorded the parent version; before Phase 1 the
    projection discarded it.
    """

    def test_a_revised_premise_contests_the_conclusion(self) -> None:
        premise = self.observe("ag1", "Pressure is 3.5 bar.")
        conclusion = self.conclude(
            "ag2", "Inflate to 3.5 bar.", {premise: JustificationKind.REQUIRED}
        )
        self.fabric.revise(
            premise, "Pressure is 2.8 bar.", agent_id="ag1", reason="bulletin"
        )
        verdict = self.fabric.justifications.recompute(conclusion)
        self.assertEqual(verdict.verdict, CONTESTED)
        self.assertEqual(verdict.lost, (premise,))

    def test_the_recorded_parent_version_is_available(self) -> None:
        premise = self.observe("ag1", "Premise v1.")
        conclusion = self.conclude(
            "ag2", "Conclusion.", {premise: JustificationKind.REQUIRED}
        )
        self.assertEqual(
            self.fabric.justifications.parent_version(conclusion, premise), 1
        )


class TestRootsAndBranches(JustificationCase):
    def test_a_root_observation_is_its_own_justification(self) -> None:
        """Invalidating a conclusion does not invalidate the observation it came
        from."""
        root = self.observe("ag1", "An observation.")
        verdict = self.fabric.justifications.recompute(root)
        self.assertEqual(verdict.verdict, JUSTIFIED)
        self.assertEqual(verdict.surviving, ())

    def test_a_branch_is_recomputed_nearest_first(self) -> None:
        a = self.observe("ag1", "A.")
        mid = self.conclude("ag2", "Mid.", {a: JustificationKind.REQUIRED})
        leaf = self.conclude("ag3", "Leaf.", {mid: JustificationKind.REQUIRED})
        verdicts = self.fabric.justifications.recompute_descendants(a)
        self.assertEqual([v.memory_id for v in verdicts], [mid, leaf])

    def test_an_unrelated_memory_is_untouched(self) -> None:
        """The plainest reading of "without withdrawing unrelated useful
        knowledge"."""
        a = self.observe("ag1", "A premise.")
        self.conclude("ag2", "A conclusion.", {a: JustificationKind.REQUIRED})
        unrelated = self.observe("ag3", "Something else entirely.")
        self.retract(a)
        self.assertEqual(
            self.fabric.get(unrelated).lifecycle_state, LifecycleState.ACTIVE
        )


class TestAuditability(JustificationCase):
    def test_the_recomputation_is_recorded_even_when_nothing_changed(self) -> None:
        """"We checked and it still stands" is the fact an operator most needs,
        and the one an unconditional contest loop could never record."""
        a = self.observe("ag1", "A.")
        b = self.observe("ag2", "B.")
        self.conclude(
            "ag3", "Therefore X.",
            {a: JustificationKind.ALTERNATIVE, b: JustificationKind.ALTERNATIVE},
        )
        self.retract(a)
        events = [e for e in self.fabric.log.read() if e.type == "SupportRecomputed"]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].payload["verdict"], JUSTIFIED)
        self.assertEqual(events[0].payload["surviving"], [b])
        self.assertEqual(events[0].payload["lost"], [a])

    def test_an_unsupported_verdict_is_recorded_with_its_reason(self) -> None:
        a = self.observe("ag1", "Only premise.")
        self.conclude("ag2", "Conclusion.", {a: JustificationKind.REQUIRED})
        self.retract(a)
        events = [e for e in self.fabric.log.read() if e.type == "SupportRecomputed"]
        self.assertEqual(events[-1].payload["verdict"], UNSUPPORTED)
        self.assertTrue(events[-1].payload["reason"])

    def test_history_is_not_rewritten_by_a_recomputation(self) -> None:
        a = self.observe("ag1", "A premise.")
        conclusion = self.conclude("ag2", "A conclusion.", {a: JustificationKind.REQUIRED})
        before = len(self.fabric.log)
        self.retract(a)
        self.assertGreater(len(self.fabric.log), before, "corrections are appended")
        trail = self.fabric.audit_trail(conclusion)
        self.assertTrue(trail)


class TestSafeRecovery(JustificationCase):
    """§4.4: recover from a false retraction without rewriting history."""

    def test_releasing_a_premise_lets_support_be_recomputed(self) -> None:
        a = self.observe("ag1", "A premise.")
        conclusion = self.conclude("ag2", "A conclusion.", {a: JustificationKind.REQUIRED})
        self.retract(a, "thought it was wrong")
        self.assertEqual(
            self.fabric.get(conclusion).lifecycle_state, LifecycleState.CONTESTED
        )

        # The retraction was itself mistaken.
        self.fabric.release(a, actor="reviewer")
        self.assertEqual(self.fabric.get(a).lifecycle_state, LifecycleState.CANDIDATE)
        verdict = self.fabric.justifications.recompute(conclusion)
        self.assertFalse(
            verdict.still_justified,
            "a released premise is a candidate, so support is not yet restored",
        )

        self.fabric.validate(a, actor="reviewer")
        self.assertEqual(
            self.fabric.justifications.recompute(conclusion).verdict, JUSTIFIED
        )

    def test_the_false_retraction_remains_in_the_audit_trail(self) -> None:
        a = self.observe("ag1", "A premise.")
        self.retract(a, "mistaken")
        self.fabric.release(a, actor="reviewer")
        trail = [e.type for e in self.fabric.audit_trail(a)]
        self.assertIn("LifecycleChanged", trail)
        self.assertGreaterEqual(
            sum(1 for t in trail if t == "LifecycleChanged"), 3,
            "validate, quarantine and release should all be on the record",
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
