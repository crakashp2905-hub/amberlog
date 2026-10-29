"""The P1 gate (ROADMAP.md).

Two properties must hold before anything is built on top of this layer:

1. A poisoned memory can be traced to its source and retracted, with every
   memory derived from it marked contested. Without the propagation a poisoned
   memory survives its own rollback through its descendants (SECURITY.md T5).
2. Projections rebuild identically from the log, so the audit trail and the
   live state can never disagree.
"""

from __future__ import annotations

import json
import unittest

from amberlog import LifecycleState, Amberlog


def snapshot(fabric: Amberlog) -> str:
    """Canonical serialisation of all derived state, for equality comparison."""
    state = fabric.state
    return json.dumps(
        {
            "memories": {k: v.to_json() for k, v in sorted(state.memories.items())},
            "history": {
                k: [m.to_json() for m in v] for k, v in sorted(state.history.items())
            },
            "stats": {
                k: {
                    "value": v.value_estimate.to_json(),
                    "by_context": {ck: cv.to_json() for ck, cv in sorted(v.value_by_context.items())},
                    "exposures": v.exposures,
                    "withholdings": v.withholdings,
                    "citations": v.citations,
                    "last_exposed_at": v.last_exposed_at,
                }
                for k, v in sorted(state.stats.items())
            },
            "episodes": {
                k: {
                    "agent": v.agent_id,
                    "task": v.task_id,
                    "outcome": v.outcome,
                    "verifier": v.verifier_id,
                }
                for k, v in sorted(state.episodes.items())
            },
            "exposures": [
                [e.episode_id, e.memory_id, e.exposed, e.propensity, e.policy_id]
                for e in state.exposures
            ],
            "hypothesis_sets": {
                k: {"members": sorted(v.memory_ids), "resolved": v.resolved}
                for k, v in sorted(state.hypothesis_sets.items())
            },
            "children": {k: sorted(v) for k, v in sorted(state.children.items())},
            "parents": {k: sorted(v) for k, v in sorted(state.parents.items())},
        },
        sort_keys=True,
    )


class TestRetraction(unittest.TestCase):
    """A chain of derived knowledge, then a retraction at the root."""

    def setUp(self) -> None:
        self.fabric = Amberlog(auto_activate=True)
        f = self.fabric

        # An observation that will later turn out to be poisoned.
        self.root = f.remember(
            "agent-a",
            "The battery temperature threshold is 45 degrees C.",
            context={"domain": "ev"},
        )
        # A belief consolidated from it.
        self.middle = f.derive(
            "agent-a",
            "Warn the operator above 45 degrees C.",
            parents=[self.root],
        )
        # A procedure built on that belief.
        self.leaf = f.derive(
            "agent-b",
            "Procedure: poll temperature, warn above 45, shut down above 60.",
            parents=[self.middle],
            type="procedural",
        )
        # An unrelated memory that must not be touched.
        self.unrelated = f.remember("agent-c", "Tyre pressure is 34 psi.")

    def tearDown(self) -> None:
        self.fabric.close()

    def test_lineage_is_traceable_in_both_directions(self) -> None:
        f = self.fabric
        descendants = {n.memory_id for n in f.lineage_graph.descendants(self.root)}
        self.assertEqual(descendants, {self.middle, self.leaf})

        ancestors = {n.memory_id for n in f.lineage_graph.ancestors(self.leaf)}
        self.assertEqual(ancestors, {self.middle, self.root})

        # The leaf traces back to the original observation.
        self.assertEqual(f.lineage_graph.roots(self.leaf), [self.root])

    def test_depth_is_recorded(self) -> None:
        by_id = {n.memory_id: n.depth for n in self.fabric.lineage_graph.descendants(self.root)}
        self.assertEqual(by_id[self.middle], 1)
        self.assertEqual(by_id[self.leaf], 2)

    def test_quarantine_propagates_to_all_descendants(self) -> None:
        f = self.fabric
        contested = f.quarantine(self.root, reason="source episode was poisoned")

        self.assertEqual(set(contested), {self.middle, self.leaf})
        self.assertIs(f.get(self.root).lifecycle_state, LifecycleState.QUARANTINED)
        self.assertIs(f.get(self.middle).lifecycle_state, LifecycleState.CONTESTED)
        self.assertIs(f.get(self.leaf).lifecycle_state, LifecycleState.CONTESTED)
        # The unrelated memory is untouched.
        self.assertIs(f.get(self.unrelated).lifecycle_state, LifecycleState.ACTIVE)

    def test_retracted_memories_are_not_retrievable(self) -> None:
        f = self.fabric
        f.quarantine(self.root, reason="poisoned")
        result = f.retrieve("agent-a", "battery temperature threshold warn shut down")
        exposed = {m.id for m in result.exposed}
        self.assertNotIn(self.root, exposed)
        self.assertNotIn(self.middle, exposed)
        self.assertNotIn(self.leaf, exposed)

    def test_contested_memories_are_retrievable_only_when_asked_for(self) -> None:
        f = self.fabric
        f.quarantine(self.root, reason="poisoned")
        query = "warn the operator above 45"

        self.assertEqual(len(f.retrieve("agent-a", query).exposed), 0)

        exploratory = f.retrieve("agent-a", query, include_contested=True)
        self.assertIn(self.middle, {m.id for m in exploratory.exposed})

    def test_quarantine_can_be_scoped_to_one_memory(self) -> None:
        f = self.fabric
        contested = f.quarantine(self.root, reason="narrow", propagate=False)
        self.assertEqual(contested, [])
        self.assertIs(f.get(self.middle).lifecycle_state, LifecycleState.ACTIVE)

    def test_retraction_is_visible_in_the_audit_trail(self) -> None:
        """The reason now names the *recomputation*, not just the ancestor.

        Phase 4 replaced the unconditional contest loop with support
        recomputation, so the audit records why the conclusion lost its
        justification rather than only that an ancestor was withdrawn — and it
        records the same for a conclusion that survived.
        """
        f = self.fabric
        f.quarantine(self.root, reason="source episode was poisoned", actor="sec-team")

        trail = f.audit_trail(self.leaf)
        lifecycle = [e for e in trail if e.type == "LifecycleChanged"]
        self.assertTrue(lifecycle)
        reason = lifecycle[-1].payload["reason"]
        self.assertIn("support recomputed", reason)
        self.assertIn(self.root, reason)
        self.assertEqual(lifecycle[-1].payload["actor"], "sec-team")

        recomputed = [e for e in f.log.read() if e.type == "SupportRecomputed"]
        self.assertTrue(recomputed, "the recomputation itself must be auditable")
        for event in recomputed:
            self.assertIn(event.payload["verdict"], ("justified", "contested", "unsupported"))
            self.assertEqual(event.payload["trigger_memory_id"], self.root)

    def test_explain_names_the_retracted_ancestor(self) -> None:
        f = self.fabric
        f.quarantine(self.root, reason="poisoned")
        narrative = f.explain(self.leaf).narrative()
        self.assertIn("contested", narrative)
        self.assertIn(self.middle, narrative)

    def test_caveat_distinguishes_retraction_from_disagreement(self) -> None:
        """Contested has two causes needing different actions: a live
        disagreement needs evidence, a retracted ancestor needs re-checking."""
        f = self.fabric
        f.quarantine(self.root, reason="poisoned")
        caveats = " ".join(f.explain(self.leaf).caveats)
        self.assertIn("ancestor", caveats)
        self.assertIn("retracted", caveats)
        self.assertNotIn("conflicting memory exists", caveats)

        # A genuine disagreement reports the other cause.
        other = f.remember("agent-d", "Tyre pressure is 40 psi.")
        f.challenge([self.unrelated, other], evidence="conflicting tyre pressures")
        conflict_caveats = " ".join(f.explain(self.unrelated).caveats)
        self.assertIn("conflicting memory exists", conflict_caveats)

    def test_quarantine_is_idempotent_for_already_quarantined(self) -> None:
        f = self.fabric
        f.quarantine(self.root, reason="first")
        # Re-running must not resurrect or re-contest anything already handled.
        second = f.quarantine(self.middle, reason="second")
        self.assertEqual(set(second), {self.leaf})
        self.assertIs(f.get(self.middle).lifecycle_state, LifecycleState.QUARANTINED)


class TestRebuildDeterminism(unittest.TestCase):
    def test_state_is_identical_after_rebuild(self) -> None:
        f = Amberlog(auto_activate=True, seed=7)
        try:
            ep = f.start_episode("agent-a", "task-1", {"env": "linux"})
            a = f.remember("agent-a", "Use ripgrep to search large trees.", source_episodes=[ep.id])
            b = f.derive("agent-a", "Prefer ripgrep over grep for repositories.", parents=[a])
            f.retrieve("agent-a", "how to search a big repository?", episode_id=ep.id)
            f.record_outcome(ep.id, 1.0, verifier_id="env")
            f.value(a, persist=True)
            f.share(b, "team")
            f.challenge([a, b], evidence="conflicting advice about grep")
            f.forget(a, reason="superseded")

            before = snapshot(f)
            f.rebuild()
            after = snapshot(f)
            self.assertEqual(before, after)
        finally:
            f.close()

    def test_rebuild_restores_the_search_index(self) -> None:
        f = Amberlog(auto_activate=True)
        try:
            mid = f.remember("agent-a", "Rotate the signing key every ninety days.")
            f.rebuild()
            result = f.retrieve("agent-a", "how often to rotate the signing key?")
            self.assertIn(mid, {m.id for m in result.exposed})
        finally:
            f.close()

    def test_unknown_event_types_do_not_break_replay(self) -> None:
        """Forward compatibility: an older reader meeting a newer schema."""
        from amberlog.events import Event

        f = Amberlog(auto_activate=True)
        try:
            mid = f.remember("agent-a", "Something worth keeping.")
            f.log.append(Event(type="SomeFutureEvent", ts=f.now(), payload={"x": 1}))
            f.rebuild()
            self.assertEqual(f.get(mid).content, "Something worth keeping.")
        finally:
            f.close()


if __name__ == "__main__":
    unittest.main()
