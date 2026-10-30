"""Crossing a store boundary.

The three rules the module promises: the recipient decides, an import arrives
unvalidated, and provenance crosses with it.
"""

from __future__ import annotations

import unittest

from memory_fabric import (
    FirewallDecision,
    LifecycleState,
    MemoryFabric,
    MemoryType,
    Scope,
    SecurityClass,
)
from memory_fabric.federation import (
    describe,
    descendants_of,
    imported_from,
    imports,
    offer,
    offer_many,
    propagate_retraction,
)
from memory_fabric.governance.firewall import (
    Firewall,
    rule_capabilities_must_be_granted,
    rule_must_be_active,
    rule_restricted_stays_private,
)


def permissive_firewall() -> Firewall:
    """Without the value rule, so tests exercise federation rather than the
    sender's value gate (which refuses everything lacking contrastive evidence)."""
    return Firewall(
        rules=(
            rule_restricted_stays_private,
            rule_must_be_active,
            rule_capabilities_must_be_granted,
        )
    )


def store(**kwargs) -> MemoryFabric:
    kwargs.setdefault("firewall", permissive_firewall())
    return MemoryFabric(auto_activate=True, **kwargs)


class TestOffer(unittest.TestCase):
    def setUp(self) -> None:
        self.source = store(seed=1)
        self.target = store(seed=2)
        self.mid = self.source.remember(
            "agent-a", "Retry a failed deploy once after 30s.", context={"domain": "ops"}
        )

    def tearDown(self) -> None:
        self.source.close()
        self.target.close()

    def test_import_arrives_as_a_candidate(self) -> None:
        """Value earned in one store is not evidence about another."""
        result = offer(self.source, self.mid, self.target, recipient_agent="agent-b")
        self.assertTrue(result.accepted)
        imported = self.target.get(result.imported_memory_id)
        self.assertIs(imported.lifecycle_state, LifecycleState.CANDIDATE)
        self.assertEqual(len(self.target.retrieve("agent-b", "retry a failed deploy")), 0)

    def test_activate_makes_it_retrievable(self) -> None:
        result = offer(
            self.source, self.mid, self.target, recipient_agent="agent-b", activate=True
        )
        imported = self.target.get(result.imported_memory_id)
        self.assertIs(imported.lifecycle_state, LifecycleState.ACTIVE)
        self.assertEqual(len(self.target.retrieve("agent-b", "retry a failed deploy")), 1)

    def test_provenance_crosses_the_boundary(self) -> None:
        """Without this a federated store cannot explain itself."""
        result = offer(self.source, self.mid, self.target, recipient_agent="agent-b")
        origin = imported_from(self.target, result.imported_memory_id)
        self.assertIsNotNone(origin)
        self.assertEqual(origin["agent"], "agent-a")
        self.assertEqual(origin["memory_id"], self.mid)

        imported = self.target.get(result.imported_memory_id)
        self.assertEqual(imported.provenance.method.value, "imported")
        self.assertIn("ops", str(imported.context))

    def test_native_memories_have_no_origin(self) -> None:
        native = self.target.remember("agent-b", "A local fact.")
        self.assertIsNone(imported_from(self.target, native))
        offer(self.source, self.mid, self.target, recipient_agent="agent-b")
        self.assertEqual(len(imports(self.target)), 1)

    def test_the_recipient_decides_not_the_sender(self) -> None:
        """A sender cannot push a memory past rules it does not control.

        The sender here is deliberately laxer than the recipient: it has no
        capability rule at all and happily releases the procedure. The import
        is still refused, because the decision that matters is made with the
        recipient's policy and the recipient's grants.
        """
        lax_source = store(
            seed=4, firewall=Firewall(rules=(rule_restricted_stays_private,
                                             rule_must_be_active))
        )
        strict_target = store(
            seed=3,
            firewall=Firewall(rules=(rule_restricted_stays_private, rule_must_be_active,
                                     rule_capabilities_must_be_granted)),
        )
        try:
            procedure = lax_source.remember(
                "agent-a",
                "Procedure: run the migration then restart the pods.",
                type=MemoryType.PROCEDURAL,
                capabilities=["shell"],
            )
            # The sender alone would allow it.
            self.assertTrue(
                lax_source.firewall_check(procedure, Scope.FEDERATED, []).permits_sharing
            )

            refused = offer(
                lax_source, procedure, strict_target, recipient_agent="agent-b",
                granted_capabilities=[],
            )
            self.assertFalse(refused.accepted)
            self.assertIs(refused.decision, FirewallDecision.DENY)
            self.assertTrue(any("recipient refused" in r for r in refused.reasons))
            self.assertEqual(imports(strict_target), [])

            allowed = offer(
                lax_source, procedure, strict_target, recipient_agent="agent-b",
                granted_capabilities=["shell"],
            )
            self.assertTrue(allowed.accepted)
        finally:
            lax_source.close()
            strict_target.close()

    def test_auto_activate_does_not_promote_an_import(self) -> None:
        """Regression: the recipient's convenience setting silently activated
        every import, defeating the guarantee that value does not cross."""
        eager = store(seed=9)  # auto_activate=True
        try:
            self.assertTrue(eager.auto_activate)
            result = offer(self.source, self.mid, eager, recipient_agent="agent-b")
            self.assertIs(
                eager.get(result.imported_memory_id).lifecycle_state,
                LifecycleState.CANDIDATE,
            )
        finally:
            eager.close()

    def test_the_sender_can_refuse_too(self) -> None:
        restricted = self.source.remember(
            "agent-a", "Internal salary bands.", security_class=SecurityClass.RESTRICTED
        )
        result = offer(self.source, restricted, self.target, recipient_agent="agent-b")
        self.assertFalse(result.accepted)
        self.assertTrue(any("sender refused" in r for r in result.reasons))

    def test_a_secret_does_not_cross(self) -> None:
        leaky = self.source.remember("agent-a", "deploy key AKIAIOSFODNN7EXAMPLE")
        # Quarantined on ingest, so it is not active and cannot be offered.
        self.assertIs(
            self.source.get(leaky).lifecycle_state, LifecycleState.QUARANTINED
        )
        result = offer(self.source, leaky, self.target, recipient_agent="agent-b")
        self.assertFalse(result.accepted)
        self.assertEqual(imports(self.target), [])

    def test_structured_payload_survives(self) -> None:
        mid = self.source.remember(
            "agent-a", "When sym3 occurs do act5.",
            structured={"kind": "claim", "symptom": "sym3", "action": "act5"},
        )
        result = offer(self.source, mid, self.target, recipient_agent="agent-b")
        imported = self.target.get(result.imported_memory_id)
        self.assertEqual(imported.structured["symptom"], "sym3")


class TestOfferMany(unittest.TestCase):
    def test_offers_every_active_memory_by_default(self) -> None:
        source, target = store(seed=1), store(seed=2)
        try:
            for index in range(5):
                source.remember("agent-a", f"Fact number {index} about deploys.")
            quarantined = source.remember("agent-a", "key AKIAIOSFODNN7EXAMPLE")

            summary = offer_many(source, target, recipient_agent="agent-b")
            self.assertEqual(summary.offered, 5)
            self.assertEqual(summary.accepted, 5)
            self.assertNotIn(quarantined, [r.source_memory_id for r in summary.results])
            self.assertEqual(summary.acceptance_rate, 1.0)
        finally:
            source.close()
            target.close()

    def test_refusals_are_counted_and_explained(self) -> None:
        source, target = store(seed=1), store(seed=2)
        try:
            source.remember("agent-a", "A shareable fact about deploys.")
            source.remember(
                "agent-a", "Salary bands.", security_class=SecurityClass.RESTRICTED
            )
            summary = offer_many(source, target, recipient_agent="agent-b")
            self.assertEqual(summary.offered, 2)
            self.assertEqual(summary.accepted, 1)
            self.assertEqual(summary.refused, 1)
            refusal = next(r for r in summary.results if not r.accepted)
            self.assertTrue(refusal.reasons)
        finally:
            source.close()
            target.close()


class TestDescribe(unittest.TestCase):
    def test_metadata_carries_no_content(self) -> None:
        """Metadata-first means the body stays home until the offer is accepted."""
        source = store(seed=1)
        try:
            mid = source.remember(
                "agent-a", "A memorable and quite specific sentence about deploys."
            )
            card = describe(source, mid)
            self.assertNotIn("memorable", str(card))
            self.assertEqual(card["memory_id"], mid)
            self.assertEqual(card["content_chars"], len(source.get(mid).content))
            self.assertIn("value", card)
        finally:
            source.close()

    def test_value_is_reported_as_unmeasured_when_it_is(self) -> None:
        source = store(seed=1)
        try:
            mid = source.remember("agent-a", "Never evaluated.")
            self.assertIsNone(describe(source, mid)["value"]["mean"])
        finally:
            source.close()


class TestValueGateBlocksFederationByDefault(unittest.TestCase):
    """The product's default firewall refuses to federate without proven benefit.

    Documented because it surprised the H3 harness: with the default rules every
    offer is refused, since the value rule needs a *contrastive* estimate with a
    lower bound above zero and the default estimator is not contrastive. That is
    the rule working as designed, but it means federation does nothing until a
    store is running a contrastive estimator and has gathered evidence.
    """

    def test_default_firewall_refuses_an_unevaluated_memory(self) -> None:
        source = MemoryFabric(auto_activate=True, seed=1)  # default firewall
        target = MemoryFabric(auto_activate=True, seed=2)
        try:
            mid = source.remember("agent-a", "A fact nobody has evaluated.")
            result = offer(source, mid, target, recipient_agent="agent-b")
            self.assertFalse(result.accepted)
            self.assertIs(result.decision, FirewallDecision.REQUIRE_VALIDATION)
            self.assertTrue(any("sender refused" in r for r in result.reasons))
        finally:
            source.close()
            target.close()


if __name__ == "__main__":
    unittest.main()


class TestRetractionFollowsTheMemory(unittest.TestCase):
    """The claim PRIOR_ART.md says survives the novelty downgrade: a retraction
    reaches the stores a memory travelled to. None of the four adjacent papers
    carries provenance across a federation boundary, so none can do this.
    """

    def setUp(self) -> None:
        self.origin = store(seed=1)
        self.first = store(seed=2)
        self.second = store(seed=3)
        for fabric in (self.origin, self.first, self.second):
            self.addCleanup(fabric.close)

        self.memory_id = self.origin.remember(
            "north", "E01 at coastal sites: swap_pilot_cable."
        )
        self.origin.validate(self.memory_id, actor="supervisor")
        self.offers = [
            offer(self.origin, self.memory_id, target, recipient_agent=agent)
            for target, agent in ((self.first, "south"), (self.second, "east"))
        ]
        self.assertTrue(all(result.accepted for result in self.offers))

    def test_it_finds_the_imports_by_origin_store_and_id(self) -> None:
        found = descendants_of(self.origin, self.memory_id, [self.first, self.second])
        self.assertEqual(len(found), 2)

    def test_an_unrelated_store_sharing_an_id_is_not_touched(self) -> None:
        """Ids are per-store, so two stores can mint the same one. Matching on
        the id alone would quarantine a memory that merely shares an identifier."""
        impostor = store(seed=9)
        self.addCleanup(impostor.close)
        native = impostor.remember("west", "unrelated local note")
        impostor.validate(native, actor="supervisor")

        found = descendants_of(self.origin, native, [impostor])
        self.assertEqual(found, [])

    def test_quarantine_reaches_both_importers(self) -> None:
        self.origin.quarantine(self.memory_id, reason="poisoned", actor="north")
        results = propagate_retraction(
            self.origin, self.memory_id, [self.first, self.second]
        )
        self.assertEqual(len(results), 2)
        self.assertTrue(all(result.acted for result in results))
        for target, result in zip((self.first, self.second), self.offers):
            self.assertEqual(
                target.get(result.imported_memory_id).lifecycle_state,
                LifecycleState.QUARANTINED,
            )

    def test_it_quarantines_rather_than_deletes(self) -> None:
        """An importer may have built on the memory. Its descendants need to
        become contested rather than vanish, and the origin may itself turn out
        to have been wrong — both of which a deletion forecloses."""
        derived = self.first.derive(
            "south",
            "Therefore carry spare pilot cables to coastal sites.",
            parents=[self.offers[0].imported_memory_id],
        )
        self.first.validate(derived, actor="supervisor")

        self.origin.quarantine(self.memory_id, reason="poisoned", actor="north")
        propagate_retraction(self.origin, self.memory_id, [self.first])

        self.assertEqual(
            self.first.get(self.offers[0].imported_memory_id).lifecycle_state,
            LifecycleState.QUARANTINED,
        )
        self.assertEqual(
            self.first.get(derived).lifecycle_state, LifecycleState.CONTESTED
        )

        # Reversible: the origin can be wrong about being wrong. Release
        # returns it to *candidate*, not active — a remote retraction that has
        # been reviewed and rejected still leaves a memory nobody has re-tested
        # here, so the recipient has to validate it again deliberately.
        self.first.release(self.offers[0].imported_memory_id, actor="south")
        self.assertEqual(
            self.first.get(self.offers[0].imported_memory_id).lifecycle_state,
            LifecycleState.CANDIDATE,
        )

    def test_a_local_withdrawal_is_not_overwritten(self) -> None:
        """The recipient having independently found the problem is exactly the
        evidence that matters when deciding whether to trust that sender again,
        and overwriting the local reason with the remote one would lose it."""
        self.second.quarantine(
            self.offers[1].imported_memory_id, reason="failed here", actor="east"
        )
        self.origin.quarantine(self.memory_id, reason="poisoned", actor="north")

        results = propagate_retraction(self.origin, self.memory_id, [self.second])
        self.assertEqual(len(results), 1)
        self.assertFalse(results[0].acted)
        self.assertIn("already withdrawn", results[0].reason)

        trail = " ".join(
            event.type for event in self.second.audit_trail(self.offers[1].imported_memory_id)
        )
        self.assertTrue(trail)

    def test_propagating_without_a_retraction_still_only_affects_imports(self) -> None:
        """The function does not check that the origin retracted — a caller may
        have its own reason. What it must never do is touch native memories."""
        native = self.first.remember("south", "a local note of our own")
        self.first.validate(native, actor="supervisor")

        propagate_retraction(self.origin, self.memory_id, [self.first])
        self.assertEqual(self.first.get(native).lifecycle_state, LifecycleState.ACTIVE)
