"""Phase 3 — runtime enforcement.

Exit gate: retraction changes runtime behaviour after propagation, stale
versions are blocked or flagged on all supported paths, vector hits cannot
bypass checks, and an end-to-end integration test passes.

Two gaps made invariant 6 only partial before this. There was no enforcement
*boundary* — `fabric.get()` returned a memory whatever its lifecycle state, so
an adapter could reach past the check without knowing it had. And exposure was
checked at retrieval and never again, so a memory retracted between retrieval
and a consequential action was still acted on.
"""

from __future__ import annotations

import unittest

from amberlog import LifecycleState, Amberlog, WithdrawalBasis
from amberlog.enforcement import (
    ACTIVE,
    BLOCKED_LIFECYCLE,
    CANDIDATE_UNVALIDATED,
    CONTESTED,
    NOT_FOUND,
    TOKEN_EXPIRED,
    VERSION_MOVED,
    WITHDRAWN_ON_WEAK_EVIDENCE,
    WRONG_AGENT,
    AccessDecision,
    Enforcer,
    ExposureToken,
    RiskLevel,
    Verdict,
)


class EnforcementCase(unittest.TestCase):
    def setUp(self) -> None:
        self.fabric = Amberlog(":memory:")
        self.addCleanup(self.fabric.close)
        self.memory_id = self.fabric.remember("ag_a", "E01 at coastal: swap the cable.")
        self.fabric.validate(self.memory_id, actor="supervisor")


class TestTheCheck(EnforcementCase):
    def test_an_active_memory_is_usable_at_every_risk_level(self) -> None:
        for risk in RiskLevel:
            decision = self.fabric.enforcer.check(self.memory_id, risk=risk)
            self.assertEqual(decision.verdict, Verdict.USABLE, risk.value)
            self.assertEqual(decision.reason_code, ACTIVE)

    def test_a_quarantined_memory_is_denied_at_every_risk_level(self) -> None:
        self.fabric.quarantine(
            self.memory_id, reason="contradicted", actor="safety",
            basis=WithdrawalBasis.CONTRADICTED,
        )
        for risk in RiskLevel:
            decision = self.fabric.enforcer.check(self.memory_id, risk=risk)
            self.assertEqual(decision.verdict, Verdict.DENY, risk.value)
            self.assertEqual(decision.reason_code, BLOCKED_LIFECYCLE)

    def test_a_weak_withdrawal_is_still_denied_but_says_why(self) -> None:
        """Denied, because the memory *is* withdrawn — with a reason code that
        points an operator at releasing it rather than at the memory."""
        self.fabric.quarantine(
            self.memory_id, reason="was in context at a failure", actor="auto",
            basis=WithdrawalBasis.CO_OCCURRENCE,
        )
        decision = self.fabric.enforcer.check(self.memory_id)
        self.assertEqual(decision.verdict, Verdict.DENY)
        self.assertEqual(decision.reason_code, WITHDRAWN_ON_WEAK_EVIDENCE)

    def test_an_unknown_memory_is_denied_not_crashed(self) -> None:
        decision = self.fabric.enforcer.check("01NOPE")
        self.assertEqual(decision.verdict, Verdict.DENY)
        self.assertEqual(decision.reason_code, NOT_FOUND)

    def test_a_candidate_is_never_usable_and_is_denied_outright_at_high_risk(self) -> None:
        candidate = self.fabric.remember("ag_a", "unreviewed")
        self.assertEqual(
            self.fabric.enforcer.check(candidate, risk=RiskLevel.LOW).verdict,
            Verdict.REVALIDATE,
        )
        self.assertEqual(
            self.fabric.enforcer.check(candidate, risk=RiskLevel.HIGH).verdict,
            Verdict.DENY,
        )

    def test_a_contested_memory_scales_with_risk(self) -> None:
        """The roadmap's §3 requirement: low risk may be flagged, medium may
        require revalidation, high must be blocked."""
        other = self.fabric.remember("ag_b", "E01 at coastal: reflash firmware.")
        self.fabric.validate(other, actor="supervisor")
        self.fabric.challenge(
            [self.memory_id, other], evidence="two answers for one fault",
            detector_id="test",
        )
        expected = {
            RiskLevel.LOW: Verdict.WARN,
            RiskLevel.MEDIUM: Verdict.REVALIDATE,
            RiskLevel.HIGH: Verdict.DENY,
        }
        for risk, verdict in expected.items():
            decision = self.fabric.enforcer.check(
                self.memory_id, risk=risk, include_contested=True
            )
            self.assertEqual(decision.verdict, verdict, risk.value)
            self.assertEqual(decision.reason_code, CONTESTED)

    def test_a_decision_never_carries_content(self) -> None:
        """A decision that quoted the memory would move content into every log
        and dashboard that records one."""
        self.fabric.quarantine(
            self.memory_id, reason="leaked a credential", actor="gov",
            basis=WithdrawalBasis.SENSITIVE_DATA,
        )
        decision = self.fabric.enforcer.check(self.memory_id)
        rendered = str(decision.to_json())
        self.assertNotIn("swap the cable", rendered)
        self.assertNotIn("E01", rendered)


class TestTheBoundary(EnforcementCase):
    def test_use_returns_no_memory_when_the_decision_refuses(self) -> None:
        """A caller that ignores the decision still cannot act on withdrawn
        knowledge, because there is nothing to act on."""
        self.fabric.quarantine(
            self.memory_id, reason="r", actor="x", basis=WithdrawalBasis.CONTRADICTED
        )
        read = self.fabric.use(self.memory_id, "ag_a")
        self.assertFalse(read.usable)
        self.assertIsNone(read.memory)
        self.assertIsNone(read.token)

    def test_get_is_inspection_and_still_returns_withdrawn_memories(self) -> None:
        """Deliberate: `explain`, the dashboard and the CLI must be able to show
        a withdrawn memory to a human. The test pins the distinction so the two
        paths are not accidentally merged."""
        self.fabric.quarantine(
            self.memory_id, reason="r", actor="x", basis=WithdrawalBasis.CONTRADICTED
        )
        self.assertEqual(
            self.fabric.get(self.memory_id).lifecycle_state, LifecycleState.QUARANTINED
        )
        self.assertFalse(self.fabric.use(self.memory_id, "ag_a").usable)

    def test_retrieval_and_use_agree(self) -> None:
        """One enforcement layer means the two supported paths cannot disagree
        about whether a memory is usable."""
        self.fabric.quarantine(
            self.memory_id, reason="r", actor="x", basis=WithdrawalBasis.CONTRADICTED
        )
        hits = self.fabric.retrieve("ag_a", "coastal cable", k=5)
        self.assertNotIn(self.memory_id, [m.id for m in hits.exposed])
        self.assertFalse(self.fabric.use(self.memory_id, "ag_a").usable)

    def test_a_vector_hit_cannot_bypass_the_check(self) -> None:
        """The index is a candidate generator, not a validity authority."""
        self.fabric.quarantine(
            self.memory_id, reason="r", actor="x", basis=WithdrawalBasis.CONTRADICTED
        )
        raw = self.fabric.index.search("coastal cable", k=5)
        self.assertIn(self.memory_id, [key for key, _ in raw], "index should still match")
        hits = self.fabric.retrieve("ag_a", "coastal cable", k=5)
        self.assertEqual([m.id for m in hits.exposed], [])


class TestAuditedDenials(EnforcementCase):
    def test_a_denial_is_recorded(self) -> None:
        self.fabric.quarantine(
            self.memory_id, reason="r", actor="x", basis=WithdrawalBasis.CONTRADICTED
        )
        before = sum(1 for e in self.fabric.log.read() if e.type == "AccessDenied")
        self.fabric.use(self.memory_id, "ag_a")
        after = [e for e in self.fabric.log.read() if e.type == "AccessDenied"]
        self.assertEqual(len(after) - before, 1)
        self.assertEqual(after[-1].payload["reason_code"], BLOCKED_LIFECYCLE)
        self.assertEqual(after[-1].agent_id, "ag_a")

    def test_the_audit_record_excludes_the_content(self) -> None:
        self.fabric.quarantine(
            self.memory_id, reason="leaked AKIAIOSFODNN7EXAMPLE", actor="gov",
            basis=WithdrawalBasis.SENSITIVE_DATA,
        )
        self.fabric.use(self.memory_id, "ag_a")
        denied = [e for e in self.fabric.log.read() if e.type == "AccessDenied"]
        rendered = str(denied[-1].payload)
        self.assertNotIn("swap the cable", rendered)
        self.assertNotIn("AKIA", rendered)

    def test_auditing_can_be_suppressed_for_a_bulk_check(self) -> None:
        """An operator tool checking a thousand memories should not write a
        thousand denial events into the log it is inspecting."""
        self.fabric.quarantine(
            self.memory_id, reason="r", actor="x", basis=WithdrawalBasis.CONTRADICTED
        )
        before = sum(1 for e in self.fabric.log.read() if e.type == "AccessDenied")
        self.fabric.use(self.memory_id, "ag_a", audit=False)
        after = sum(1 for e in self.fabric.log.read() if e.type == "AccessDenied")
        self.assertEqual(before, after)


class TestActionTimeVerification(EnforcementCase):
    def test_a_retraction_after_retrieval_blocks_the_action(self) -> None:
        """The time-of-check/time-of-use gap, closed. This is the case the whole
        phase exists for."""
        read = self.fabric.use(self.memory_id, "ag_a", risk=RiskLevel.HIGH)
        self.assertTrue(read.usable)

        self.fabric.quarantine(
            self.memory_id, reason="retracted at origin", actor="federation",
            basis=WithdrawalBasis.RETRACTED_AT_ORIGIN,
        )

        decision = self.fabric.verify_before_action(read.token, "ag_a")
        self.assertFalse(decision.usable)
        self.assertEqual(decision.verdict, Verdict.DENY)

    def test_an_unchanged_world_still_permits_the_action(self) -> None:
        read = self.fabric.use(self.memory_id, "ag_a", risk=RiskLevel.HIGH)
        decision = self.fabric.verify_before_action(read.token, "ag_a")
        self.assertTrue(decision.usable)

    def test_a_revision_invalidates_the_token(self) -> None:
        """The token's decision was about a different version, so it says
        nothing about this one."""
        read = self.fabric.use(self.memory_id, "ag_a")
        self.fabric.revise(
            self.memory_id,
            "E01 at coastal: swap the pilot cable.",
            agent_id="ag_a",
            reason="more precise",
        )
        decision = self.fabric.verify_before_action(read.token, "ag_a")
        self.assertEqual(decision.verdict, Verdict.REVALIDATE)
        self.assertEqual(decision.reason_code, VERSION_MOVED)

    def test_a_token_is_not_a_bearer_credential(self) -> None:
        read = self.fabric.use(self.memory_id, "ag_a")
        decision = self.fabric.verify_before_action(read.token, "ag_someone_else")
        self.assertEqual(decision.verdict, Verdict.DENY)
        self.assertEqual(decision.reason_code, WRONG_AGENT)

    def test_an_expired_token_is_refused(self) -> None:
        enforcer = Enforcer(self.fabric, token_ttl_ms=0)
        decision = enforcer.check(self.memory_id)
        token = enforcer.issue(self.memory_id, "ag_a", decision)
        verdict = enforcer.verify_at_action(token, "ag_a")
        self.assertEqual(verdict.verdict, Verdict.DENY)
        self.assertEqual(verdict.reason_code, TOKEN_EXPIRED)

    def test_a_token_from_another_store_is_refused(self) -> None:
        other = Amberlog(":memory:")
        self.addCleanup(other.close)
        foreign = ExposureToken(
            memory_id=self.memory_id, version=1, agent_id="ag_a",
            store_id=other.store_id, verdict=Verdict.USABLE,
            integrity_revision=1, issued_at_ms=self.fabric.now(),
        )
        decision = self.fabric.verify_before_action(foreign, "ag_a")
        self.assertEqual(decision.verdict, Verdict.DENY)

    def test_the_token_binds_the_version_and_the_integrity_revision(self) -> None:
        read = self.fabric.use(self.memory_id, "ag_a")
        self.assertEqual(read.token.version, 1)
        self.assertGreater(read.token.integrity_revision, 0)
        self.assertEqual(read.token.store_id, self.fabric.store_id)

    def test_action_time_defaults_to_high_risk(self) -> None:
        """The only reason to call it is that something consequential is about
        to happen, so a contested memory must not slip through as a warning."""
        other = self.fabric.remember("ag_b", "E01 at coastal: reflash firmware.")
        self.fabric.validate(other, actor="supervisor")
        read = self.fabric.use(
            self.memory_id, "ag_a", risk=RiskLevel.LOW, include_contested=True
        )
        self.fabric.challenge(
            [self.memory_id, other], evidence="conflict", detector_id="test"
        )
        decision = self.fabric.verify_before_action(read.token, "ag_a")
        self.assertEqual(decision.verdict, Verdict.DENY)


class TestUnknownIsNotUsable(unittest.TestCase):
    def test_unknown_integrity_is_not_treated_as_usable(self) -> None:
        """Invariant 9: an unavailable check is a refusal, not an assumption.
        `Verdict.UNKNOWN` must never read as permission."""
        decision = AccessDecision(
            memory_id="x", version=1, verdict=Verdict.UNKNOWN, reason_code="whatever"
        )
        self.assertFalse(decision.usable)

    def test_revalidate_is_distinct_from_deny(self) -> None:
        """Conflating them loses the information that the answer may become
        yes."""
        self.assertNotEqual(Verdict.REVALIDATE, Verdict.DENY)
        for verdict in (Verdict.REVALIDATE, Verdict.DENY, Verdict.UNKNOWN):
            self.assertFalse(
                AccessDecision("x", 1, verdict, "r").usable, verdict.value
            )
        for verdict in (Verdict.USABLE, Verdict.WARN):
            self.assertTrue(AccessDecision("x", 1, verdict, "r").usable, verdict.value)


class TestEndToEnd(unittest.TestCase):
    """Roadmap §3: integrate one real path end to end before adding adapters.

    A memory crosses a boundary, is used, is retracted at its origin, and the
    consequential action is blocked by the action-time check — the sequence the
    roadmap's Phase 7 demonstration is built around, tested here at the
    enforcement layer.
    """

    def test_retraction_at_origin_blocks_a_stale_action_at_the_recipient(self) -> None:
        from amberlog.dispatcher import Dispatcher
        from amberlog.federation import offer
        from amberlog.governance.firewall import (
            Firewall,
            rule_capabilities_must_be_granted,
            rule_must_be_active,
            rule_restricted_stays_private,
        )
        from amberlog.transport import InProcessTransport, Peer, PeerRegistry

        permissive = Firewall(
            rules=(
                rule_restricted_stays_private,
                rule_must_be_active,
                rule_capabilities_must_be_granted,
            )
        )
        origin = Amberlog(":memory:", firewall=permissive)
        recipient = Amberlog(":memory:", firewall=permissive)
        self.addCleanup(origin.close)
        self.addCleanup(recipient.close)

        source = origin.remember("ag_n", "Tug tyre pressure is 3.5 bar in winter.")
        origin.validate(source, actor="supervisor")
        imported = offer(origin, source, recipient, recipient_agent="ag_s")
        recipient.validate(imported.imported_memory_id, actor="ag_s")

        # The recipient retrieves and is about to act.
        read = recipient.use(imported.imported_memory_id, "ag_s", risk=RiskLevel.HIGH)
        self.assertTrue(read.usable)

        # The origin discovers it was wrong and the retraction propagates.
        origin.request_retraction(
            source, reason="manufacturer bulletin: 2.8 bar",
            recipients=[recipient.store_id], actor="ag_n",
            basis=WithdrawalBasis.CONTRADICTED,
        )
        registry = PeerRegistry({origin.store_id: Peer(origin.store_id, "x", b"k")})
        transport = InProcessTransport({recipient.store_id: recipient}, registry=registry)
        report = Dispatcher(origin, transport).run_once()
        self.assertEqual(report.enforced, 1)

        # The stale action is blocked, and the refusal is auditable.
        decision = recipient.verify_before_action(read.token, "ag_s")
        self.assertFalse(decision.usable)
        denied = [e for e in recipient.log.read() if e.type == "AccessDenied"]
        self.assertTrue(denied)
        self.assertNotIn("3.5 bar", str(denied[-1].payload))

        # And it is no longer retrievable at all.
        hits = recipient.retrieve("ag_s", "tug tyre pressure winter", k=5)
        self.assertEqual([m.id for m in hits.exposed], [])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
