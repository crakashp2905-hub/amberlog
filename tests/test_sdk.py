"""Phase 7 — the developer platform, and the end-to-end demonstration.

Exit gate: a new developer can install the reference setup, run tests and the
demo, inspect why a memory was blocked, and verify state transitions.

The roadmap's framing for this phase is the one that matters: *make the protocol
usable and inspectable **without allowing integrations to bypass enforcement***.
So most of these tests are about what the SDK **cannot** do. An adapter that
cannot reach past the checks is a stronger guarantee than a note saying it
shouldn't.
"""

from __future__ import annotations

import unittest

from amberlog import LifecycleState, Amberlog, WithdrawalBasis
from amberlog.enforcement import RiskLevel, Verdict
from amberlog.justification import JustificationKind, justification_context
from amberlog.protocol import PropagationState
from amberlog.sdk import (
    AgentClient,
    NotUsable,
    OperatorClient,
    SdkError,
    agent,
    operator,
)


class SdkCase(unittest.TestCase):
    def setUp(self) -> None:
        self.fabric = Amberlog(":memory:")
        self.addCleanup(self.fabric.close)
        self.agent = agent(self.fabric, "ag_a")
        self.operator = operator(self.fabric, "supervisor")
        self.memory_id = self.agent.remember("E01 at coastal: swap the pilot cable.")
        self.operator.validate(self.memory_id)


class TestTheAgentClientCannotBypassEnforcement(SdkCase):
    """The defining requirement of Phase 7."""

    def test_there_is_no_unenforced_read(self) -> None:
        """`Amberlog.get()` returns a withdrawn memory to an operator tool.
        An adapter holding that method is one autocomplete away from serving
        retracted knowledge to a model, so the agent client does not have it."""
        for forbidden in ("get", "state", "log", "quarantine", "erase_content"):
            self.assertFalse(
                hasattr(self.agent, forbidden),
                f"AgentClient exposes {forbidden}, which can bypass enforcement",
            )

    def test_fetch_raises_rather_than_returning_withdrawn_content(self) -> None:
        self.operator.retract(
            self.memory_id, reason="root cause was elsewhere", basis="contradicted"
        )
        with self.assertRaises(NotUsable) as ctx:
            self.agent.fetch(self.memory_id)
        self.assertEqual(ctx.exception.decision.verdict, Verdict.DENY)

    def test_the_refusal_does_not_quote_the_memory(self) -> None:
        """A refusal that carried the content would move it into every log that
        records an exception."""
        self.operator.retract(self.memory_id, reason="r", basis="contradicted")
        try:
            self.agent.fetch(self.memory_id)
        except NotUsable as exc:
            self.assertNotIn("pilot cable", str(exc))
            self.assertNotIn("pilot cable", str(exc.decision.to_json()))

    def test_recall_omits_what_enforcement_refuses(self) -> None:
        self.operator.retract(self.memory_id, reason="r", basis="contradicted")
        self.assertEqual(self.agent.recall("coastal pilot cable"), [])

    def test_every_result_carries_a_token(self) -> None:
        """An integration that wants the content gets the means to re-verify it
        in the same object, so forgetting to is a visible omission."""
        for usable in self.agent.recall("coastal pilot cable"):
            self.assertIsNotNone(usable.token)
            self.assertEqual(usable.token.agent_id, "ag_a")
            self.assertEqual(usable.version, 1)

    def test_an_agent_cannot_write_as_another_agent(self) -> None:
        memory_id = self.agent.remember("something this agent observed")
        self.assertEqual(
            self.fabric.get(memory_id).provenance.created_by, "ag_a"
        )

    def test_an_agent_cannot_choose_its_own_scope(self) -> None:
        """Promoting a memory beyond private is the firewall's decision and
        needs contrastive evidence. Letting an adapter pass a scope would hand
        it the one thing governance exists to withhold."""
        memory_id = self.agent.remember("a private observation")
        self.assertEqual(self.fabric.get(memory_id).scope.value, "private")

    def test_an_agent_cannot_verify_its_own_outcome(self) -> None:
        episode = self.fabric.start_episode("ag_a", task_id="t1")
        with self.assertRaises(SdkError):
            self.agent.record_outcome(episode.id, outcome=1.0, verifier_id="ag_a")

    def test_a_third_party_verifier_is_accepted(self) -> None:
        episode = self.fabric.start_episode("ag_a", task_id="t2")
        self.agent.record_outcome(episode.id, outcome=1.0, verifier_id="env")
        self.assertTrue(self.fabric.state.episodes[episode.id].has_outcome)


class TestActionTimeVerificationThroughTheSdk(SdkCase):
    def test_verify_returns_the_current_decision(self) -> None:
        usable = self.agent.fetch(self.memory_id)
        self.assertTrue(self.agent.verify(usable).usable)
        self.operator.retract(self.memory_id, reason="r", basis="contradicted")
        self.assertFalse(self.agent.verify(usable).usable)

    def test_require_raises_for_a_path_that_must_not_proceed(self) -> None:
        usable = self.agent.fetch(self.memory_id)
        self.operator.retract(self.memory_id, reason="r", basis="contradicted")
        with self.assertRaises(NotUsable):
            self.agent.require(usable)

    def test_verify_defaults_to_high_risk(self) -> None:
        """The only reason to call it is that something consequential is about
        to happen, so a contested memory must not pass as a warning."""
        other = self.agent.remember("E01 at coastal: reflash the firmware.")
        self.operator.validate(other)
        usable = self.agent.fetch(self.memory_id)
        self.fabric.challenge(
            [self.memory_id, other], evidence="two answers", detector_id="test"
        )
        self.assertEqual(self.agent.verify(usable).verdict, Verdict.DENY)


class TestTheOperatorClient(SdkCase):
    def test_an_operator_may_read_a_withdrawn_memory(self) -> None:
        """Deciding whether a withdrawal was justified requires reading the
        thing that was withdrawn. That is why it is a separate object."""
        self.operator.retract(self.memory_id, reason="r", basis="contradicted")
        memory = self.operator.inspect(self.memory_id)
        self.assertEqual(memory.lifecycle_state, LifecycleState.QUARANTINED)
        self.assertIn("pilot cable", memory.content)

    def test_an_operator_cannot_act_as_an_agent(self) -> None:
        for forbidden in ("recall", "fetch", "remember"):
            self.assertFalse(hasattr(self.operator, forbidden))

    def test_release_returns_to_candidate_not_active(self) -> None:
        self.operator.retract(self.memory_id, reason="r", basis="contradicted")
        self.operator.release(self.memory_id)
        self.assertEqual(
            self.operator.inspect(self.memory_id).lifecycle_state,
            LifecycleState.CANDIDATE,
        )

    def test_support_explains_why_a_conclusion_stands(self) -> None:
        other = self.agent.remember("Tug B overheated too.")
        self.operator.validate(other)
        conclusion = self.fabric.derive(
            "ag_a", "Tugs overheat.", parents=[self.memory_id, other],
            context=justification_context(
                [
                    (self.memory_id, JustificationKind.ALTERNATIVE),
                    (other, JustificationKind.ALTERNATIVE),
                ]
            ),
        )
        self.operator.validate(conclusion)
        self.operator.retract(self.memory_id, reason="r", basis="contradicted")

        verdict = self.operator.support(conclusion)
        self.assertTrue(verdict.still_justified)
        self.assertIn(other, verdict.surviving)

    def test_propagation_shows_pending_recipients(self) -> None:
        """Invariant 9: offline, pending and failed must be explicit."""
        self.operator.retract(
            self.memory_id, reason="r",
            recipients=["st_" + "A" * 26, "st_" + "B" * 26], basis="contradicted",
        )
        rows = self.operator.propagation()
        self.assertEqual(len(rows), 2)
        for row in rows:
            self.assertEqual(row["state"], PropagationState.QUEUED.value)
            self.assertEqual(row["origin_memory_version"], 1)

    def test_an_unreachable_recipient_is_never_shown_as_verified(self) -> None:
        self.operator.retract(
            self.memory_id, reason="r", recipients=["st_" + "Z" * 26],
            basis="contradicted",
        )
        states = {row["state"] for row in self.operator.propagation()}
        self.assertNotIn(PropagationState.VERIFIED.value, states)

    def test_the_attention_list_is_reachable(self) -> None:
        self.operator.retract(self.memory_id, reason="in context at a failure")
        kinds = {item.kind for item in self.operator.attention()}
        self.assertIn("withdrawn_on_weak_evidence", kinds)

    def test_erasure_is_an_operator_capability(self) -> None:
        self.assertTrue(self.operator.erase_content(self.memory_id, reason="request"))
        self.assertNotIn("pilot cable", self.operator.inspect(self.memory_id).content)


class TestEndToEndDemonstration(unittest.TestCase):
    """The roadmap's eleven-step demonstration, as a test.

    1. Agent A records a fact with provenance and a version.
    2. Agent B imports it and derives a conclusion with a dependency edge.
    3. B goes offline.
    4. The origin retracts the source version and durably queues the event.
    5. B reconnects and reconciles.
    6. B persists and enforces the retraction.
    7. The imported version is blocked from usable retrieval.
    8. The dependent conclusion becomes contested based on remaining support.
    9. A stale consequential action is blocked by an action-time check.
    10. An operator inspects lineage, events, recipient state and reason.
    11. Restarts preserve the result.
    """

    def test_the_whole_sequence(self) -> None:
        import sqlite3
        from pathlib import Path
        from tempfile import TemporaryDirectory

        from amberlog.dispatcher import Dispatcher, reconcile
        from amberlog.federation import offer
        from amberlog.governance.firewall import (
            Firewall,
            rule_capabilities_must_be_granted,
            rule_must_be_active,
            rule_restricted_stays_private,
        )
        from amberlog.transport import InProcessTransport, Peer, PeerRegistry

        def permissive() -> Firewall:
            return Firewall(
                rules=(
                    rule_restricted_stays_private,
                    rule_must_be_active,
                    rule_capabilities_must_be_granted,
                )
            )

        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        a_path = str(Path(tmp.name) / "a.db")
        b_path = str(Path(tmp.name) / "b.db")

        store_a = Amberlog(a_path, firewall=permissive())
        store_b = Amberlog(b_path, firewall=permissive())
        self.addCleanup(lambda: self._close(store_a))

        # 1. A records a fact.
        agent_a = agent(store_a, "ag_a")
        op_a = operator(store_a, "sup_a")
        fact = agent_a.remember("Yard tug tyre pressure is 3.5 bar in winter.")
        op_a.validate(fact)
        self.assertEqual(store_a.get(fact).version, 1)
        self.assertEqual(store_a.get(fact).provenance.created_by, "ag_a")

        # 2. B imports it and derives a conclusion.
        imported = offer(store_a, fact, store_b, recipient_agent="ag_b")
        self.assertTrue(imported.accepted)
        op_b = operator(store_b, "sup_b")
        op_b.validate(imported.imported_memory_id)
        plan = store_b.derive(
            "ag_b", "Inflate the yard tug to 3.5 bar before the frost.",
            parents=[imported.imported_memory_id],
            context=justification_context(
                [(imported.imported_memory_id, JustificationKind.REQUIRED)]
            ),
        )
        op_b.validate(plan)

        agent_b = agent(store_b, "ag_b")
        usable = agent_b.fetch(plan, risk=RiskLevel.HIGH)
        self.assertIn("3.5 bar", usable.content)

        # 3. B goes offline. 4. The origin retracts and durably queues.
        registry = PeerRegistry({store_a.store_id: Peer(store_a.store_id, "x", b"k")})
        offline = InProcessTransport(
            {store_b.store_id: store_b}, registry=registry,
            offline={store_b.store_id},
        )
        op_a.retract(
            fact, reason="manufacturer bulletin: 2.8 bar",
            recipients=[store_b.store_id], basis=WithdrawalBasis.CONTRADICTED.value,
        )
        report = Dispatcher(store_a, offline).run_once()
        self.assertEqual(report.enforced, 0)
        self.assertEqual(len(op_a.propagation()), 1, "the retraction is still owed")

        # 5. B reconnects and reconciles. 6. It persists and enforces.
        since = store_b.outbox.missed_since(store_a.store_id)
        acks = reconcile(store_b, store_a.retractions_since(since), store_a.store_id)
        self.assertEqual([a.state for a in acks], [PropagationState.ENFORCED])

        # 7. The imported version is blocked from usable retrieval.
        self.assertEqual(agent_b.recall("tyre pressure winter"), [])
        with self.assertRaises(NotUsable):
            agent_b.fetch(imported.imported_memory_id)

        # 8. The dependent conclusion is contested, not deleted.
        self.assertEqual(
            store_b.get(plan).lifecycle_state, LifecycleState.CONTESTED
        )
        self.assertFalse(op_b.support(plan).still_justified)

        # 9. The stale consequential action is blocked.
        decision = agent_b.verify(usable)
        self.assertFalse(decision.usable)

        # 10. An operator can inspect lineage, events, recipient state, reason.
        self.assertIn(
            plan,
            [n.memory_id for n in store_b.lineage_graph.descendants(
                imported.imported_memory_id
            )],
        )
        self.assertTrue(op_b.audit_trail(plan))
        self.assertEqual(
            store_b.state.withdrawal_basis[imported.imported_memory_id],
            WithdrawalBasis.RETRACTED_AT_ORIGIN.value,
        )
        self.assertTrue(op_a.integrity_snapshot()["checksum"].startswith("sha256:"))

        # 11. Restarts preserve the result.
        store_b.close()
        reopened = Amberlog(b_path, firewall=permissive())
        self.addCleanup(lambda: self._close(reopened))
        self.assertEqual(
            reopened.get(imported.imported_memory_id).lifecycle_state,
            LifecycleState.QUARANTINED,
        )
        self.assertEqual(reopened.get(plan).lifecycle_state, LifecycleState.CONTESTED)
        self.assertEqual(agent(reopened, "ag_b").recall("tyre pressure winter"), [])

    @staticmethod
    def _close(store: Amberlog) -> None:
        try:
            store.close()
        except Exception:
            pass


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
