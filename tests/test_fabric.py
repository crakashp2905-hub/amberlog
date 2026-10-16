"""End-to-end behaviour of the MemoryFabric facade."""

from __future__ import annotations

import unittest
from memory_fabric.governance.firewall import FirewallRuling

from memory_fabric import (
    EpsilonGreedyPolicy,
    FirewallDecision,
    LifecycleState,
    MemoryFabric,
    MemoryType,
    NotFound,
    PolicyViolation,
    Scope,
)


class FabricTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.clock = [1_700_000_000_000]
        self.fabric = MemoryFabric(
            auto_activate=True, seed=42, clock=lambda: self.clock[0]
        )

    def tearDown(self) -> None:
        self.fabric.close()

    def tick(self, ms: int = 1000) -> None:
        self.clock[0] += ms


class TestWritePath(FabricTestCase):
    def test_remember_records_provenance(self) -> None:
        f = self.fabric
        ep = f.start_episode("agent-a", "task-1", {"env": "linux"})
        mid = f.remember(
            "agent-a", "Use ripgrep for large trees.", source_episodes=[ep.id]
        )
        stored = f.get(mid)
        self.assertEqual(stored.provenance.created_by, "agent-a")
        self.assertEqual(stored.provenance.source_episodes, (ep.id,))
        self.assertEqual(stored.version, 1)
        self.assertGreater(stored.created_at, 0)

    def test_new_memories_are_candidates_by_default(self) -> None:
        f = MemoryFabric()  # auto_activate off
        try:
            mid = f.remember("agent-a", "Something unverified.")
            self.assertIs(f.get(mid).lifecycle_state, LifecycleState.CANDIDATE)
            # A candidate is not retrievable until something validates it.
            self.assertEqual(len(f.retrieve("agent-a", "something unverified")), 0)
            f.validate(mid, actor="reviewer")
            self.assertEqual(len(f.retrieve("agent-a", "something unverified")), 1)
        finally:
            f.close()

    def test_secrets_are_quarantined_on_ingest_not_dropped(self) -> None:
        """The attempt to memorise a secret is itself worth auditing."""
        f = self.fabric
        mid = f.remember("agent-a", "deploy key AKIAIOSFODNN7EXAMPLE for prod")
        self.assertIs(f.get(mid).lifecycle_state, LifecycleState.QUARANTINED)
        self.assertEqual(len(f.retrieve("agent-a", "deploy key for prod")), 0)

        trail = [e for e in f.audit_trail(mid) if e.type == "LifecycleChanged"]
        self.assertTrue(any("sensitive data" in e.payload["reason"] for e in trail))

    def test_quarantined_memory_cannot_be_validated_directly(self) -> None:
        f = self.fabric
        mid = f.remember("agent-a", "token ghp_" + "d" * 36)
        with self.assertRaises(PolicyViolation):
            f.validate(mid, actor="someone")
        # It must go through review first.
        f.release(mid, actor="reviewer")
        f.validate(mid, actor="reviewer")
        self.assertIs(f.get(mid).lifecycle_state, LifecycleState.ACTIVE)

    def test_revise_creates_a_version_and_keeps_history(self) -> None:
        f = self.fabric
        mid = f.remember("agent-a", "Threshold is 40C.")
        self.tick()
        f.revise(mid, "Threshold is 45C.", agent_id="agent-b", reason="corrected")

        self.assertEqual(f.get(mid).version, 2)
        self.assertEqual(f.get(mid).content, "Threshold is 45C.")
        history = f.history(mid)
        self.assertEqual([m.version for m in history], [1, 2])
        self.assertEqual(history[0].content, "Threshold is 40C.")

    def test_revised_content_is_reindexed(self) -> None:
        f = self.fabric
        mid = f.remember("agent-a", "Deploy with helm charts.")
        f.revise(mid, "Deploy with kustomize overlays.", agent_id="agent-a", reason="switched")
        found = {m.id for m in f.retrieve("agent-a", "kustomize overlays").exposed}
        self.assertIn(mid, found)

    def test_derive_inherits_context_and_records_edges(self) -> None:
        f = self.fabric
        parent = f.remember("agent-a", "Batteries overheat above 45C.", context={"domain": "ev"})
        child = f.derive("agent-b", "Warn above 45C.", parents=[parent])

        self.assertEqual(f.get(child).context["domain"], "ev")
        self.assertEqual(f.get(child).provenance.parents, ((parent, 1),))
        self.assertEqual(f.state.children[parent], {child})

    def test_derive_from_a_missing_parent_fails(self) -> None:
        with self.assertRaises(NotFound):
            self.fabric.derive("agent-a", "Derived.", parents=["nope"])


class TestRetrievalPath(FabricTestCase):
    def setUp(self) -> None:
        super().setUp()
        f = self.fabric
        self.ids = {
            "rg": f.remember("agent-a", "Use ripgrep to search large repositories fast."),
            "helm": f.remember("agent-a", "Deploy the service with a helm chart."),
            "tyre": f.remember("agent-a", "Tyre pressure should be 34 psi."),
        }

    def test_retrieval_returns_relevant_memories(self) -> None:
        result = self.fabric.retrieve("agent-a", "how to search a big repository")
        self.assertIn(self.ids["rg"], {m.id for m in result.exposed})

    def test_irrelevant_memories_are_not_returned(self) -> None:
        """Top-k without a floor would pad the context with the least-bad rows."""
        result = self.fabric.retrieve("agent-a", "quantum chromodynamics lattice gauge")
        self.assertEqual(len(result.exposed), 0)

    def test_every_candidate_gets_an_exposure_event(self) -> None:
        f = self.fabric
        ep = f.start_episode("agent-a", "t", {})
        f.retrieve("agent-a", "search repository helm chart", k=1, episode_id=ep.id)

        decisions = [e for e in f.log.read() if e.type == "ExposureDecided"]
        self.assertGreaterEqual(len(decisions), 2)
        self.assertEqual(sum(1 for d in decisions if d.payload["exposed"]), 1)
        # Both arms are logged, with a propensity on each.
        for decision in decisions:
            self.assertGreater(decision.payload["propensity"], 0.0)
            self.assertLessEqual(decision.payload["propensity"], 1.0)

    def test_withheld_candidates_are_reported_to_the_caller(self) -> None:
        result = self.fabric.retrieve("agent-a", "search repository helm chart", k=1)
        self.assertEqual(len(result.exposed), 1)
        self.assertGreaterEqual(len(result.withheld), 1)

    def test_exposure_counters_are_projected(self) -> None:
        f = self.fabric
        f.retrieve("agent-a", "ripgrep search", k=1)
        self.assertEqual(f.stats(self.ids["rg"]).exposures, 1)
        self.assertIsNotNone(f.stats(self.ids["rg"]).last_exposed_at)

    def test_randomised_policy_produces_both_arms(self) -> None:
        f = MemoryFabric(
            auto_activate=True, seed=1, exposure_policy=EpsilonGreedyPolicy(epsilon=0.4)
        )
        try:
            mid = f.remember("agent-a", "Use ripgrep to search repositories.")
            arms = set()
            for index in range(60):
                ep = f.start_episode("agent-a", f"t{index}", {})
                result = f.retrieve("agent-a", "search repositories", k=1, episode_id=ep.id)
                arms.add(mid in {m.id for m in result.exposed})
            self.assertEqual(arms, {True, False})
        finally:
            f.close()


class TestOutcomes(FabricTestCase):
    def test_outcome_requires_a_verifier(self) -> None:
        f = self.fabric
        ep = f.start_episode("agent-a", "t", {})
        with self.assertRaises(PolicyViolation):
            f.record_outcome(ep.id, 1.0, verifier_id="")

    def test_an_agent_may_not_verify_its_own_episode(self) -> None:
        """Self-reported outcomes would let an agent manufacture value for any
        memory it liked (SECURITY.md T2)."""
        f = self.fabric
        ep = f.start_episode("agent-a", "t", {})
        with self.assertRaises(PolicyViolation):
            f.record_outcome(ep.id, 1.0, verifier_id="agent-a")

    def test_a_third_party_verifier_is_accepted(self) -> None:
        f = self.fabric
        ep = f.start_episode("agent-a", "t", {})
        f.record_outcome(ep.id, 0.75, verifier_id="env")
        self.assertEqual(f.state.episodes[ep.id].outcome, 0.75)

    def test_outcome_for_an_unknown_episode_fails(self) -> None:
        with self.assertRaises(NotFound):
            self.fabric.record_outcome("nope", 1.0, verifier_id="env")

    def test_citations_are_recorded_but_flagged_as_weak(self) -> None:
        f = self.fabric
        ep = f.start_episode("agent-a", "t", {})
        mid = f.remember("agent-a", "A fact.")
        f.cite("agent-a", ep.id, mid)
        self.assertEqual(f.stats(mid).citations, 1)
        self.assertIn("self-reported", f.explain(mid).narrative())


class TestSharing(FabricTestCase):
    def test_sharing_without_evidence_is_refused(self) -> None:
        f = self.fabric
        mid = f.remember("agent-a", "An unproven but harmless claim.")
        ruling = f.share(mid, Scope.TEAM)
        self.assertIs(ruling.decision, FirewallDecision.REQUIRE_VALIDATION)
        self.assertIs(f.get(mid).scope, Scope.PRIVATE)

    def test_a_refusal_is_recorded_in_the_audit_trail(self) -> None:
        f = self.fabric
        mid = f.remember("agent-a", "An unproven claim.")
        f.share(mid, Scope.TEAM)
        self.assertIn("share refused", f.explain(mid).narrative())

    def test_restricted_memory_cannot_be_shared(self) -> None:
        f = self.fabric
        mid = f.remember("agent-a", "Internal salary bands.", security_class="restricted")
        ruling = f.share(mid, Scope.TEAM)
        self.assertIs(ruling.decision, FirewallDecision.DENY)
        self.assertIs(f.get(mid).scope, Scope.PRIVATE)

    def test_procedure_needs_granted_capabilities(self) -> None:
        f = self.fabric
        mid = f.remember(
            "agent-a",
            "Procedure: run the migration script then restart the pods.",
            type=MemoryType.PROCEDURAL,
            capabilities=["shell"],
        )
        refused = f.share(mid, Scope.TEAM, granted_capabilities=[])
        self.assertIs(refused.decision, FirewallDecision.DENY)
        self.assertTrue(any("shell" in r for r in refused.reasons))

    def test_sharing_a_sensitive_memory_quarantines_it(self) -> None:
        f = MemoryFabric(auto_activate=True)
        try:
            # Bypass the ingest screen to test the share-time check on its own.
            # This used to go through `revise`, which skipped the screen; that
            # was a bypass and is closed (test_security_regression.py), so the
            # screen is switched off explicitly here instead.
            screen = f.firewall.screen_ingest
            f.firewall.screen_ingest = lambda content: FirewallRuling(
                FirewallDecision.ALLOW, [])
            mid = f.remember("agent-a", "key AKIAIOSFODNN7EXAMPLE")
            f.firewall.screen_ingest = screen
            self.assertIs(f.get(mid).lifecycle_state, LifecycleState.ACTIVE)
            ruling = f.share(mid, Scope.TEAM)
            self.assertIs(ruling.decision, FirewallDecision.QUARANTINE)
            self.assertIs(f.get(mid).lifecycle_state, LifecycleState.QUARANTINED)
        finally:
            f.close()


class TestHypothesisSets(FabricTestCase):
    def setUp(self) -> None:
        super().setUp()
        f = self.fabric
        self.a = f.remember("agent-a", "Retry the request three times on failure.")
        self.b = f.remember("agent-b", "Never retry the request; fail fast instead.")

    def test_challenge_preserves_both_sides(self) -> None:
        """Nothing is deleted and no winner is picked: the disagreement is the
        information (CRITICAL_REVIEW section 4)."""
        f = self.fabric
        set_id = f.challenge([self.a, self.b], evidence="contradictory retry advice")

        self.assertIs(f.get(self.a).lifecycle_state, LifecycleState.CONTESTED)
        self.assertIs(f.get(self.b).lifecycle_state, LifecycleState.CONTESTED)
        self.assertEqual(f.state.hypothesis_sets[set_id].memory_ids, {self.a, self.b})
        self.assertFalse(f.state.hypothesis_sets[set_id].resolved)

    def test_contested_memories_are_linked_in_explanations(self) -> None:
        f = self.fabric
        f.challenge([self.a, self.b], evidence="conflict")
        explanation = f.explain(self.a)
        self.assertEqual(explanation.contested_with, [self.b])
        self.assertIn("unresolved", explanation.narrative())

    def test_resolution_deprecates_the_loser_rather_than_deleting_it(self) -> None:
        f = self.fabric
        set_id = f.challenge([self.a, self.b], evidence="conflict")
        f.resolve(
            set_id,
            winner_id=self.a,
            design={"trials": 100},
            results={"a_success": 0.8, "b_success": 0.4},
        )
        self.assertIs(f.get(self.a).lifecycle_state, LifecycleState.ACTIVE)
        self.assertIs(f.get(self.b).lifecycle_state, LifecycleState.DEPRECATED)
        # The loser still exists, so later evidence can reopen the question.
        self.assertEqual(f.get(self.b).content, "Never retry the request; fail fast instead.")
        self.assertTrue(f.state.hypothesis_sets[set_id].resolved)

    def test_resolving_an_unknown_set_fails(self) -> None:
        with self.assertRaises(NotFound):
            self.fabric.resolve("nope", winner_id=None, design={}, results={})

    def test_challenge_requires_existing_memories(self) -> None:
        with self.assertRaises(NotFound):
            self.fabric.challenge([self.a, "ghost"], evidence="x")


class TestHealthAndRetention(FabricTestCase):
    def test_health_summarises_the_store(self) -> None:
        f = self.fabric
        f.remember("agent-a", "Fact one.")
        f.remember("agent-a", "Fact two.", type=MemoryType.PROCEDURAL)
        f.remember("agent-a", "leaked key ghp_" + "e" * 36)
        ep = f.start_episode("agent-a", "t", {})
        f.record_outcome(ep.id, 1.0, verifier_id="env")

        health = f.health()
        self.assertEqual(health.total, 3)
        self.assertEqual(health.quarantined, 1)
        self.assertEqual(health.by_type["procedural"], 1)
        self.assertEqual(health.episodes, 1)
        self.assertEqual(health.episodes_with_outcome, 1)
        self.assertEqual(health.never_exposed, 3)
        self.assertGreater(health.events, 0)

    def test_retention_sweep_is_a_dry_run_by_default(self) -> None:
        f = self.fabric
        mid = f.remember("agent-a", "Short-lived note.")
        f.forget(mid, reason="no longer needed")
        self.clock[0] += 200 * 86_400_000

        decisions = f.sweep_retention()
        self.assertEqual([d.action for d in decisions], ["delete"])
        # Nothing changed without apply=True.
        self.assertIs(f.get(mid).lifecycle_state, LifecycleState.DEPRECATED)

        f.sweep_retention(apply=True)
        self.assertIs(f.get(mid).lifecycle_state, LifecycleState.DELETED)

    def test_forget_removes_a_memory_from_retrieval(self) -> None:
        f = self.fabric
        mid = f.remember("agent-a", "Use the legacy deployment script.")
        self.assertEqual(len(f.retrieve("agent-a", "legacy deployment script")), 1)
        f.forget(mid, reason="superseded")
        self.assertEqual(len(f.retrieve("agent-a", "legacy deployment script")), 0)


class TestExplain(FabricTestCase):
    def test_narrative_covers_provenance_and_caveats(self) -> None:
        f = self.fabric
        ep = f.start_episode("agent-a", "diagnose", {"domain": "ev"})
        root = f.remember(
            "agent-a", "Cell voltage sagged under load.", source_episodes=[ep.id]
        )
        derived = f.derive("agent-b", "Suspect cell imbalance.", parents=[root])

        narrative = f.explain(derived).narrative()
        self.assertIn(derived, narrative)
        self.assertIn("agent-b", narrative)
        self.assertIn(root, narrative)          # derived from
        self.assertIn("Caveats:", narrative)
        self.assertIn("No value evidence", narrative)

    def test_explanation_states_that_a_deterministic_policy_cannot_show_cause(self) -> None:
        f = self.fabric
        mid = f.remember("agent-a", "A claim.")
        self.assertIn("deterministic", f.explain(mid).narrative())

    def test_explanation_serialises(self) -> None:
        f = self.fabric
        mid = f.remember("agent-a", "A claim.")
        payload = f.explain(mid).to_json()
        self.assertEqual(payload["memory_id"], mid)
        self.assertIn("caveats", payload)
        self.assertIn("value", payload)

    def test_explaining_a_missing_memory_fails(self) -> None:
        with self.assertRaises(NotFound):
            self.fabric.explain("nope")


class TestContextManager(unittest.TestCase):
    def test_closes_cleanly(self) -> None:
        with MemoryFabric(auto_activate=True) as f:
            mid = f.remember("agent-a", "A fact.")
            self.assertTrue(f.get(mid))


if __name__ == "__main__":
    unittest.main()


class TestExplainRedactsSecrets(unittest.TestCase):
    """Regression, found by a live model run rather than by the suite.

    `explain()` built its narrative straight from raw content while only the
    dashboard scrubbed. Printing an explanation to a terminal therefore showed
    the exact credential the firewall had just quarantined the memory for
    containing. An explanation is a display surface too.
    """

    SECRET = "AKIAIOSFODNN7EXAMPLE"

    def setUp(self) -> None:
        self.fabric = MemoryFabric(auto_activate=True)
        self.mid = self.fabric.remember(
            "agent-a", f"To deploy, export AWS_ACCESS_KEY_ID={self.SECRET} and ship."
        )

    def tearDown(self) -> None:
        self.fabric.close()

    def test_narrative_does_not_contain_the_secret(self) -> None:
        narrative = self.fabric.explain(self.mid).narrative()
        self.assertNotIn(self.SECRET, narrative)
        self.assertIn("REDACTED", narrative)

    def test_serialised_explanation_does_not_contain_the_secret(self) -> None:
        import json

        self.assertNotIn(self.SECRET, json.dumps(self.fabric.explain(self.mid).to_json()))

    def test_the_kind_is_still_reported(self) -> None:
        explanation = self.fabric.explain(self.mid)
        self.assertIn("aws_access_key", explanation.redacted_kinds)
        self.assertIn("Secrets redacted", explanation.narrative())

    def test_the_stored_record_is_untouched(self) -> None:
        """Redaction is a display concern; it must not rewrite the memory."""
        self.assertIn(self.SECRET, self.fabric.get(self.mid).content)

    def test_clean_content_is_unchanged(self) -> None:
        mid = self.fabric.remember("agent-a", "Prefer email follow-up after onboarding.")
        explanation = self.fabric.explain(mid)
        self.assertEqual(explanation.redacted_kinds, [])
        self.assertIn("Prefer email follow-up", explanation.narrative())


class TestDuplicateSuppression(FabricTestCase):
    """Found live: a model called `remember` four times in one run.

    Duplicates inflate apparent consensus the way several agents repeating one
    source do (SECURITY.md T3), except from a single agent — which the
    evidence-independence check never looks at.
    """

    CLAIM = "Fault code E31: broken conductor in pilot cable."

    def test_same_content_in_one_episode_is_suppressed(self) -> None:
        session = self.fabric.session("agent-a", "task-1")
        first = session.remember(self.CLAIM)
        second = session.remember(self.CLAIM)
        self.assertEqual(first, second)
        self.assertEqual(len(self.fabric.state.memories), 1)
        self.assertEqual(self.fabric.state.suppressed_duplicates, 1)

    def test_whitespace_and_case_are_not_new_content(self) -> None:
        session = self.fabric.session("agent-a", "task-1")
        first = session.remember(self.CLAIM)
        again = session.remember("  fault code e31:   BROKEN conductor in pilot cable. ")
        self.assertEqual(first, again)

    def test_different_content_is_still_written(self) -> None:
        session = self.fabric.session("agent-a", "task-1")
        first = session.remember(self.CLAIM)
        other = session.remember("Fault code E31: loose contactor.")
        self.assertNotEqual(first, other)
        self.assertEqual(len(self.fabric.state.memories), 2)

    def test_re_observation_in_a_later_episode_is_evidence(self) -> None:
        """The scope is deliberate: the same claim seen twice on two occasions
        genuinely is more evidence, and must not be collapsed."""
        first = self.fabric.session("agent-a", "task-1").remember(self.CLAIM)
        later = self.fabric.session("agent-a", "task-2").remember(self.CLAIM)
        self.assertNotEqual(first, later)

    def test_another_agent_writing_the_same_thing_is_not_suppressed(self) -> None:
        episode = self.fabric.start_episode("agent-a", "task-1")
        a = self.fabric.remember("agent-a", self.CLAIM, episode_id=episode.id)
        b = self.fabric.remember("agent-b", self.CLAIM, episode_id=episode.id)
        self.assertNotEqual(a, b)

    def test_writes_outside_an_episode_are_not_deduplicated(self) -> None:
        a = self.fabric.remember("agent-a", self.CLAIM)
        b = self.fabric.remember("agent-a", self.CLAIM)
        self.assertNotEqual(a, b)

    def test_the_attempt_is_recorded_not_silently_dropped(self) -> None:
        session = self.fabric.session("agent-a", "task-1")
        session.remember(self.CLAIM)
        session.remember(self.CLAIM)
        events = [e for e in self.fabric.log.read()
                  if e.type == "MemoryDuplicateSuppressed"]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].agent_id, "agent-a")

    def test_suppression_survives_a_rebuild(self) -> None:
        session = self.fabric.session("agent-a", "task-1")
        session.remember(self.CLAIM)
        session.remember(self.CLAIM)
        self.fabric.rebuild()
        self.assertEqual(self.fabric.state.suppressed_duplicates, 1)
        self.assertEqual(len(self.fabric.state.memories), 1)
