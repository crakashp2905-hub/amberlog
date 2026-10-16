"""Evidence certificates and the action gate (plan Tasks 3 and 4).

Acceptance, from the plan:

- a missing or unknown version, stale or retracted evidence, and a revoked
  permission fail closed for protected operations;
- property tests cover malformed certificates;
- stale or retracted evidence cannot pass the gate;
- memory validity never grants tool permission.
"""

from __future__ import annotations

import copy
import json
import random
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from memory_fabric import LifecycleState, MemoryFabric
from memory_fabric import certificates as C
from memory_fabric.actions import (
    ActionGate,
    ActionPolicy,
    Approval,
    ToolRule,
)
from memory_fabric.certificates import CertificateVerifier, EvidenceCertificate
from memory_fabric.identity import ROLE_AGENT, ROLE_OPERATOR
from memory_fabric.justification import JustificationKind, justification_context
from memory_fabric.service import MemoryService


class Fixture(unittest.TestCase):
    def setUp(self) -> None:
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "store.db"
        self.fabric = MemoryFabric(self.path)
        self.addCleanup(self.fabric.close)
        self.a = self.observe("ag1", "Tug A overheated at 40C in July.")
        self.b = self.observe("ag2", "Tug B overheated at 41C in August.")

    def observe(self, agent: str, content: str) -> str:
        memory_id = self.fabric.remember(agent, content)
        self.fabric.validate(memory_id, actor="supervisor")
        return memory_id

    def conclude(self, content: str, parents: dict[str, JustificationKind]) -> str:
        memory_id = self.fabric.derive(
            "ag3", content, parents=list(parents),
            context=justification_context(parents.items()))
        self.fabric.validate(memory_id, actor="supervisor")
        return memory_id

    def retract(self, memory_id: str) -> None:
        self.fabric.quarantine(memory_id, reason="contradicted", actor="safety",
                               basis="contradicted")

    def certify(self, *evidence: str, **kwargs) -> EvidenceCertificate:
        return self.fabric.certify("claim-1", list(evidence), "ag3", **kwargs)

    def verify(self, cert, **kwargs):
        return self.fabric.verify_certificate(cert, "ag3", **kwargs)


class TestVerifier(Fixture):
    def test_current_evidence_verifies(self) -> None:
        result = self.verify(self.certify(self.a, self.b))
        self.assertTrue(result.ok, result)
        self.assertEqual(result.reason_codes, (C.OK,))
        self.assertEqual(result.independent_sources, 2)

    def test_a_certificate_round_trips_through_json(self) -> None:
        cert = self.certify(self.a)
        again = EvidenceCertificate.from_json(json.loads(json.dumps(cert.to_json())))
        self.assertEqual(again, cert)
        self.assertEqual(again.digest(), cert.digest())

    def test_retracted_evidence_fails_closed(self) -> None:
        cert = self.certify(self.a)
        self.retract(self.a)
        result = self.verify(cert)
        self.assertFalse(result.ok)
        self.assertIn(C.EVIDENCE_WITHDRAWN, result.reason_codes)

    def test_revised_evidence_fails_closed(self) -> None:
        cert = self.certify(self.a)
        self.fabric.revise(self.a, "Tug A overheated at 39C in July.", "ag1", "recal")
        result = self.verify(cert)
        self.assertFalse(result.ok)
        self.assertIn(C.EVIDENCE_VERSION_MOVED, result.reason_codes)

    def test_unknown_evidence_fails_closed(self) -> None:
        cert = self.certify("01NOTAREALMEMORYID00000000")
        self.assertIn(C.EVIDENCE_NOT_FOUND, self.verify(cert).reason_codes)

    def test_a_candidate_is_not_evidence(self) -> None:
        candidate = self.fabric.remember("ag1", "unreviewed claim")
        result = self.verify(self.certify(candidate))
        self.assertIn(C.EVIDENCE_NOT_USABLE, result.reason_codes)

    def test_a_certificate_with_no_supporting_evidence_fails(self) -> None:
        cert = self.fabric.certify("claim", [(self.a, "context")], "ag3")
        self.assertIn(C.NO_SUPPORTING_EVIDENCE, self.verify(cert).reason_codes)

    def test_the_certificate_is_bound_to_agent_store_and_tenant(self) -> None:
        cert = self.certify(self.a)
        self.assertIn(C.WRONG_AGENT,
                      self.fabric.verify_certificate(cert, "someone-else").reason_codes)
        self.assertIn(C.WRONG_TENANT, self.verify(cert, tenant_id="tn_x").reason_codes)
        other = MemoryFabric(":memory:")
        self.addCleanup(other.close)
        self.assertIn(C.WRONG_STORE,
                      other.verify_certificate(cert, "ag3").reason_codes)

    def test_a_wrong_tenant_is_refused_before_any_evidence_is_examined(self) -> None:
        """Otherwise the per-evidence findings would describe memories the
        caller's tenant may not learn about."""
        result = self.verify(self.certify(self.a), tenant_id="tn_x")
        self.assertEqual(result.reason_codes, (C.WRONG_TENANT,))
        self.assertEqual(result.checks, {C.CHECK_AUTHORIZED: False})
        self.assertEqual(result.findings, ())

    def test_an_expired_certificate_fails(self) -> None:
        cert = self.certify(self.a, ttl_ms=0)
        self.assertIn(C.EXPIRED, self.verify(cert).reason_codes)

    def test_a_changed_policy_fails(self) -> None:
        cert = self.certify(self.a)
        forged = EvidenceCertificate.from_json({**cert.to_json(), "policy_id": "other"})
        self.assertIn(C.POLICY_CHANGED, self.verify(forged).reason_codes)

    def test_a_refusal_never_carries_content(self) -> None:
        cert = self.certify(self.a)
        self.retract(self.a)
        self.assertNotIn("overheated", json.dumps(self.verify(cert).to_json()))

    def test_verification_is_deterministic(self) -> None:
        cert = self.certify(self.a, self.b)
        self.retract(self.b)
        first, second = self.verify(cert), self.verify(cert)
        self.assertEqual(first, second)


class TestDerivedEvidence(Fixture):
    """S8: a conclusion is only as good as its recorded premises."""

    def test_a_conclusion_on_a_withdrawn_required_premise_fails(self) -> None:
        conclusion = self.conclude("Tugs overheat above 40C.",
                                   {self.a: JustificationKind.REQUIRED})
        cert = self.certify(conclusion)
        self.assertEqual(cert.dependencies, (C.Dependency(self.a, 1),))
        self.retract(self.a)
        result = self.verify(cert)
        self.assertFalse(result.ok)
        self.assertIn(C.EVIDENCE_NOT_USABLE, result.reason_codes)

    def test_dependencies_are_recorded_transitively(self) -> None:
        mid = self.conclude("Tugs run hot.", {self.a: JustificationKind.REQUIRED})
        top = self.conclude("Cool tugs in summer.", {mid: JustificationKind.REQUIRED})
        deps = {d.memory_id for d in self.certify(top).dependencies}
        self.assertEqual(deps, {mid, self.a})


class TestSelectiveReassessment(Fixture):
    """S12: selective reassessment keeps what blanket invalidation loses."""

    def setUp(self) -> None:
        super().setUp()
        self.conclusion = self.conclude(
            "Tugs overheat above 40C.",
            {self.a: JustificationKind.ALTERNATIVE, self.b: JustificationKind.ALTERNATIVE})
        self.cert = self.certify(self.conclusion,
                                 required_checks=[C.CHECK_DEPENDENCIES_CURRENT])
        self.retract(self.a)

    def test_selective_keeps_independently_supported_evidence(self) -> None:
        result = self.verify(self.cert, mode="selective")
        self.assertTrue(result.ok, result)
        self.assertTrue(any("support_survived" in n for n in result.notes))

    def test_blanket_refuses_the_same_certificate(self) -> None:
        result = self.verify(self.cert, mode="blanket")
        self.assertFalse(result.ok)
        self.assertIn(C.DEPENDENCY_WITHDRAWN, result.reason_codes)

    def test_selective_still_refuses_once_no_support_is_left(self) -> None:
        self.retract(self.b)
        self.assertFalse(self.verify(self.cert, mode="selective").ok)

    def test_a_copy_is_not_independent_support(self) -> None:
        copy_id = self.fabric.derive(
            "ag4", "Tug B overheated at 41C in August (forwarded).", parents=[self.b],
            context=justification_context([(self.b, JustificationKind.COPIED)]))
        self.fabric.validate(copy_id, actor="supervisor")
        cert = self.fabric.certify(
            "claim", [self.b, copy_id], "ag3",
            required_checks=[C.CHECK_INDEPENDENT_SUPPORT], min_independent_sources=2)
        result = self.fabric.verify_certificate(cert, "ag3")
        self.assertEqual(result.independent_sources, 1)
        self.assertIn(C.INSUFFICIENT_INDEPENDENT_SUPPORT, result.reason_codes)


class TestMalformed(Fixture):
    """Property tests: no mutation of a valid certificate verifies unless it
    still describes current evidence, and none raises."""

    MUTATIONS = (
        lambda d, r: d.pop(r.choice(sorted(d))),
        lambda d, r: d.__setitem__(r.choice(sorted(d)), None),
        lambda d, r: d.__setitem__(r.choice(sorted(d)), r.choice(
            [-1, 0, True, "", "x" * 500, [], {}, 3.5, [None], {"a": 1}])),
        lambda d, r: d.__setitem__("checks_passed", True),
        lambda d, r: d.__setitem__("certificate_version", r.choice([0, 2, 99, "1", 1.0])),
        lambda d, r: d["evidence"].append({"memory_id": "x", "version": 1, "role": "owner"}),
        lambda d, r: d["evidence"].extend(
            [{"memory_id": f"m{i}", "version": 1} for i in range(C.MAX_EVIDENCE + 1)]),
        lambda d, r: d.__setitem__("required_checks", ["trust_me"]),
        lambda d, r: d["evidence"][0].__setitem__("version", r.choice([0, -3, "2", None])),
    )

    def test_random_mutations_fail_closed_and_never_raise(self) -> None:
        valid = self.certify(self.a, self.b).to_json()
        rng = random.Random(20261016)
        outcomes = {True: 0, False: 0}
        for i in range(600):
            data = copy.deepcopy(valid)
            for _ in range(rng.randint(1, 3)):
                try:
                    rng.choice(self.MUTATIONS)(data, rng)
                except (KeyError, IndexError, AttributeError, TypeError):
                    pass
            with self.subTest(i=i):
                result = self.verify(data)  # must not raise
                if result.ok:
                    # Only possible if the mutation left a faithful certificate.
                    self.assertEqual(EvidenceCertificate.from_json(data).evidence,
                                     EvidenceCertificate.from_json(valid).evidence)
                outcomes[result.ok] += 1
        self.assertGreater(outcomes[False], 500)

    def test_specific_malformations_have_specific_codes(self) -> None:
        valid = self.certify(self.a).to_json()
        cases = {
            C.UNKNOWN_VERSION: {**valid, "certificate_version": 2},
            C.MALFORMED: {k: v for k, v in valid.items() if k != "certificate_version"},
            C.TOO_LARGE: {**valid, "evidence": [{"memory_id": "m", "version": 1}] * 65},
            C.UNKNOWN_CHECK: {**valid, "required_checks": ["llm_says_ok"]},
        }
        for code, data in cases.items():
            with self.subTest(code):
                self.assertEqual(self.verify(data).reason_codes, (code,))
        for junk in (None, [], "certificate", 7):
            self.assertEqual(self.verify(junk).reason_codes, (C.MALFORMED,))

    def test_a_passed_field_from_a_model_is_refused_not_trusted(self) -> None:
        data = {**self.certify(self.a).to_json(), "checks_passed": True, "ok": True}
        self.retract(self.a)
        result = self.verify(data)
        self.assertFalse(result.ok)
        self.assertEqual(result.reason_codes, (C.MALFORMED,))


class _Broken:
    """A store whose authoritative state cannot be read."""

    store_id = "st_broken"
    policy = type("P", (), {"id": ""})()

    def now(self) -> int:
        return 0

    @property
    def log(self):
        raise OSError("database is locked")

    @property
    def state(self):
        raise OSError("database is locked")


class TestFailClosed(Fixture):
    def test_unreadable_state_is_a_refusal(self) -> None:
        cert = EvidenceCertificate.from_json(
            {**self.certify(self.a).to_json(), "store_id": "st_broken"})
        result = CertificateVerifier(_Broken()).verify(cert, "ag3")
        self.assertFalse(result.ok)
        self.assertEqual(result.reason_codes, (C.STATE_UNAVAILABLE,))

    def test_the_gate_refuses_a_protected_action_when_state_is_unreadable(self) -> None:
        cert = EvidenceCertificate.from_json(
            {**self.certify(self.a).to_json(), "store_id": "st_broken"})
        gate = ActionGate(_Broken(), _policy(), audit=False)
        decision = gate.authorize("open_valve", "ag3", cert)
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason_code, C.STATE_UNAVAILABLE)
        # An unprotected tool does not depend on memory and is not blocked.
        self.assertTrue(gate.authorize("read_gauge", "ag3").allowed)


def _policy(**overrides) -> ActionPolicy:
    tools = {
        "open_valve": ToolRule("open_valve"),
        "read_gauge": ToolRule("read_gauge", protected=False),
        "shutdown_plant": ToolRule("shutdown_plant", requires_human_approval=True,
                                   min_independent_sources=2,
                                   required_checks=(C.CHECK_INDEPENDENT_SUPPORT,)),
    }
    grants = {"ag3": frozenset(tools), "ag9": frozenset({"read_gauge"})}
    return ActionPolicy(**{"tools": tools, "grants": grants,
                           "approvers": frozenset({"human-1"}), **overrides})


class TestToolPermission(Fixture):
    """Memory validity never grants tool permission."""

    def setUp(self) -> None:
        super().setUp()
        self.gate = ActionGate(self.fabric, _policy())

    def test_a_valid_certificate_does_not_grant_an_ungranted_tool(self) -> None:
        cert = self.fabric.certify("claim", [self.a], "ag9")
        self.assertTrue(self.fabric.verify_certificate(cert, "ag9").ok)
        decision = self.gate.authorize("open_valve", "ag9", cert)
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason_code, "tool_not_granted")

    def test_an_unknown_tool_is_refused(self) -> None:
        self.assertEqual(self.gate.authorize("rm_rf", "ag3").reason_code, "unknown_tool")

    def test_a_protected_tool_needs_a_certificate(self) -> None:
        self.assertEqual(self.gate.authorize("open_valve", "ag3").reason_code,
                         "certificate_required")

    def test_current_evidence_and_a_grant_allow_the_action(self) -> None:
        decision = self.gate.authorize("open_valve", "ag3", self.certify(self.a))
        self.assertTrue(decision.allowed, decision)

    def test_retracted_evidence_cannot_pass_the_gate(self) -> None:
        cert = self.certify(self.a)
        self.retract(self.a)
        decision = self.gate.authorize("open_valve", "ag3", cert)
        self.assertFalse(decision.allowed)
        self.assertIn(C.EVIDENCE_WITHDRAWN, decision.reason_codes)

    def test_stale_evidence_cannot_pass_the_gate(self) -> None:
        cert = self.certify(self.a)
        self.fabric.revise(self.a, "Tug A overheated at 38C.", "ag1", "recal")
        self.assertFalse(self.gate.authorize("open_valve", "ag3", cert).allowed)

    def test_the_rule_strengthens_a_weak_certificate(self) -> None:
        """A certificate cannot opt out of checks the tool requires."""
        cert = self.certify(self.a)  # one source, no independence check declared
        approval = Approval("human-1", cert.digest())
        decision = self.gate.authorize("shutdown_plant", "ag3", cert, approval=approval)
        self.assertFalse(decision.allowed)
        self.assertIn(C.INSUFFICIENT_INDEPENDENT_SUPPORT, decision.reason_codes)

    def test_human_approval_is_required_and_bound_to_the_certificate(self) -> None:
        cert = self.certify(self.a, self.b)
        self.assertEqual(self.gate.authorize("shutdown_plant", "ag3", cert).reason_code,
                         "human_approval_required")
        for approval in (Approval("ag3", cert.digest()),       # self-approval
                         Approval("mallory", cert.digest()),   # not an approver
                         Approval("human-1", "0" * 64)):       # another certificate
            with self.subTest(approval=approval):
                self.assertEqual(self.gate.authorize(
                    "shutdown_plant", "ag3", cert, approval=approval).reason_code,
                    "approval_invalid")
        self.assertTrue(self.gate.authorize(
            "shutdown_plant", "ag3", cert, approval=Approval("human-1", cert.digest())).allowed)

    def test_every_protected_decision_is_audited_without_content(self) -> None:
        cert = self.certify(self.a)
        self.gate.authorize("open_valve", "ag3", cert)
        self.retract(self.a)
        self.gate.authorize("open_valve", "ag3", cert)
        events = [e for e in self.fabric.log.read() if e.type == "ActionGated"]
        self.assertEqual([e.payload["allowed"] for e in events], [True, False])
        self.assertEqual(events[0].payload["evidence"], [[self.a, 1]])
        self.assertEqual(events[0].payload["certificate_digest"], cert.digest())
        self.assertNotIn("overheated", json.dumps([e.payload for e in events]))

    def test_the_audit_event_replays(self) -> None:
        self.gate.authorize("open_valve", "ag3", self.certify(self.a))
        self.fabric.close()
        reopened = MemoryFabric(self.path)
        self.addCleanup(reopened.close)
        self.assertIs(reopened.get(self.a).lifecycle_state, LifecycleState.ACTIVE)
        self.assertTrue(reopened.log.chain.verify(list(reopened.log.read())).ok)


class TestRevokedPermission(unittest.TestCase):
    """S13: a credential revoked after the certificate was issued."""

    def setUp(self) -> None:
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.service = MemoryService(MemoryFabric(Path(tmp.name) / "s.db"))
        self.addCleanup(self.service.close)
        self.service.register_agent("ag3", key=b"k3", tenant_id="tn_a")
        self.service.register_agent("bob", key=b"kb", tenant_id="tn_b")
        self.service.register_agent("ops", key=b"ko", tenant_id="tn_a",
                                    roles=(ROLE_AGENT, ROLE_OPERATOR))
        self.cred = self.service.issue("ag3")
        self.session = self.service.session(self.cred)
        ops = self.service.session(self.service.issue("ops"))
        self.fact = self.session.remember("valve 7 is upstream")
        ops.validate(self.fact)
        self.cert = self.session.certify("claim", [self.fact])
        self.gate = ActionGate(self.service._fabric, _policy())

    def test_the_session_verifies_its_own_certificate(self) -> None:
        self.assertTrue(self.session.verify_certificate(self.cert).ok)
        self.assertTrue(self.gate.authorize("open_valve", "", self.cert,
                                            session=self.session).allowed)

    def test_a_revoked_credential_stops_the_action(self) -> None:
        self.service.revoke(self.cred)
        decision = self.gate.authorize("open_valve", "", self.cert, session=self.session)
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason_code, "credential_invalid")

    def test_another_tenant_cannot_use_the_certificate(self) -> None:
        bob = self.service.session(self.service.issue("bob"))
        result = bob.verify_certificate(self.cert)
        self.assertFalse(result.ok)
        self.assertEqual(result.checks, {C.CHECK_AUTHORIZED: False})
        self.assertEqual(result.findings, ())

    def test_issuing_reveals_nothing_about_another_tenants_memory(self) -> None:
        bob = self.service.session(self.service.issue("bob"))
        theirs = bob.certify("claim", [self.fact])
        missing = bob.certify("claim", ["01NOTAREALMEMORYID00000000"])
        self.assertEqual((theirs.evidence[0].version, theirs.dependencies,
                          theirs.source_roots),
                         (missing.evidence[0].version, missing.dependencies,
                          missing.source_roots))
        self.assertFalse(bob.verify_certificate(theirs).ok)


class TestExample(unittest.TestCase):
    def test_the_action_gate_example_runs_and_refuses_what_it_should(self) -> None:
        import subprocess
        import sys
        root = Path(__file__).resolve().parent.parent
        done = subprocess.run([sys.executable, str(root / "examples" / "action_gate.py")],
                              capture_output=True, text=True, timeout=120)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("tool_not_granted", done.stdout)
        self.assertIn("evidence_withdrawn", done.stdout)


if __name__ == "__main__":
    unittest.main()
