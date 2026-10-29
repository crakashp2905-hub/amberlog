"""Active auditing (plan Task 10).

Acceptance, from the plan: detection, false quarantine and cost are measured
(experiments/p10_audit.py); a risk score cannot override mandatory checks; no
automatic forgetting. The last two are structural, and pinned here.
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

from amberlog import LifecycleState, Amberlog
from amberlog import auditor as A
from amberlog.actions import ActionGate, ActionPolicy, ToolRule
from amberlog.certificates import CHECK_INDEPENDENT_SUPPORT

ROOT = Path(__file__).resolve().parent.parent / "amberlog"
MUTATORS = {"quarantine", "forget", "release", "validate", "erase_content", "revise",
            "remember", "derive", "share", "request_retraction", "receive_retraction",
            "_emit", "append_many", "record_attempt", "advance", "challenge",
            "resolve", "sweep_retention", "execute_write"}
# `append` is not listed: it is also `list.append`. A log append would move the
# head, which `test_auditing_writes_nothing` checks directly.


class TestObservationOnly(unittest.TestCase):
    def setUp(self) -> None:
        f = self.fabric = Amberlog(auto_activate=True)
        self.addCleanup(f.close)
        a, b = f.remember("ana", "gauge A 4 bar", scope="team"), f.remember("ben", "gauge B 4 bar", scope="team")
        gate = ActionGate(f, ActionPolicy(
            tools={"override": ToolRule("override", min_independent_sources=2,
                                        required_checks=(CHECK_INDEPENDENT_SUPPORT,))},
            grants={"ops": frozenset({"override"})}))
        self.gate, self.a, self.b = gate, a, b
        self.cert = f.certify("c", [a, b], "ops")
        gate.authorize("override", "ops", self.cert)
        for i in range(12):
            f.remember("mallory", f"bulletin {i}: clearance 9.9 m", scope="team")
        f.quarantine(a, reason="gauge A miscalibrated", basis="contradicted")
        x, y = f.remember("ana", "crane 2 max 10 t", scope="team"), f.remember("ben", "crane 2 max 14 t", scope="team")
        f.challenge([x, y], evidence="conflict")

    def test_every_trigger_kind_fires_on_its_signal(self) -> None:
        kinds = {t.kind for t in A.Auditor(self.fabric).scan()}
        self.assertTrue({A.HIGH_IMPACT, A.SOURCE_WITHDRAWN, A.CONTRADICTION,
                         A.WRITE_BURST} <= kinds, kinds)

    def test_auditing_writes_nothing(self) -> None:
        head = self.fabric.log.head_seq
        states = {m: x.lifecycle_state for m, x in self.fabric.state.memories.items()}
        auditor = A.Auditor(self.fabric)
        for trigger in auditor.scan():
            auditor.audit(trigger)
        self.assertEqual(self.fabric.log.head_seq, head)
        self.assertEqual({m: x.lifecycle_state for m, x in self.fabric.state.memories.items()},
                         states)

    def test_a_withdrawal_audit_finds_the_action_that_used_it(self) -> None:
        auditor = A.Auditor(self.fabric)
        trigger = next(t for t in auditor.scan()
                       if t.kind == A.SOURCE_WITHDRAWN and t.subject == self.a)
        result = auditor.audit(trigger)
        self.assertTrue(result.finding)
        self.assertIn("ana", result.related)

    def test_a_burst_alone_is_not_a_finding(self) -> None:
        """Writing fast is not evidence of compromise."""
        auditor = A.Auditor(self.fabric)
        burst = next(t for t in auditor.scan() if t.kind == A.WRITE_BURST)
        self.assertEqual(burst.subject, "mallory")
        self.assertFalse(auditor.audit(burst).finding)

    def test_the_gate_decides_identically_with_or_without_an_audit(self) -> None:
        cert = self.fabric.certify("c2", [self.b], "ops")
        before = self.gate.authorize("override", "ops", cert)
        auditor = A.Auditor(self.fabric)
        for trigger in auditor.scan():
            auditor.audit(trigger)
        after = self.gate.authorize("override", "ops", cert)
        self.assertEqual((before.allowed, before.reason_codes), (after.allowed, after.reason_codes))
        self.assertIs(self.fabric.get(self.b).lifecycle_state, LifecycleState.ACTIVE)


class TestStructure(unittest.TestCase):
    def test_the_auditor_calls_no_mutating_method(self) -> None:
        tree = ast.parse((ROOT / "auditor.py").read_text(encoding="utf-8"))
        called = {node.func.attr for node in ast.walk(tree)
                  if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
        self.assertEqual(called & MUTATORS, set())
        source = (ROOT / "auditor.py").read_text(encoding="utf-8")
        for verb in ("INSERT", "UPDATE", "DELETE"):
            self.assertNotIn(verb, source)

    def test_no_check_consults_the_auditor(self) -> None:
        """A risk score cannot loosen or tighten a mandatory check if no check
        can see it."""
        for module in ("enforcement.py", "certificates.py", "actions.py", "fabric.py",
                       "service.py", "justification.py"):
            with self.subTest(module):
                tree = ast.parse((ROOT / module).read_text(encoding="utf-8"))
                imported = {alias.name for node in ast.walk(tree)
                            if isinstance(node, (ast.Import, ast.ImportFrom))
                            for alias in node.names} | {
                    node.module or "" for node in ast.walk(tree)
                    if isinstance(node, ast.ImportFrom)}
                self.assertFalse(any("auditor" in name for name in imported), imported)


if __name__ == "__main__":
    unittest.main()
