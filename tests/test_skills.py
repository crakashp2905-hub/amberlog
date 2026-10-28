"""MF-020 / GOV-23: governed skills never outlive their premises, never grant a tool, need approval per version."""

from __future__ import annotations

import unittest

from memory_fabric import LifecycleState, MemoryFabric, skills
from memory_fabric.actions import ActionPolicy, ToolRule


class Skills(unittest.TestCase):
    def setUp(self) -> None:
        self.f = MemoryFabric(":memory:")
        self.addCleanup(self.f.close)
        self.policy_memory = self.f.remember("lead", "Gate codes rotate every 30 days.", scope="team")
        self.f.validate(self.policy_memory, actor="r")
        self.sid = skills.propose(self.f, "agent-a", "rotate-gate-code", trigger="code older than 30 days",
                                  steps=["read current code", "issue a new code", "notify security"],
                                  tools=["issue_gate_code"], checks=["new code differs"],
                                  prerequisites=[self.policy_memory])
        self.policy = ActionPolicy(tools={"issue_gate_code": ToolRule("issue_gate_code")},
                                   grants={"agent-b": frozenset({"issue_gate_code"}), "agent-c": frozenset()},
                                   approvers=frozenset())

    def approve(self, sid: str) -> None:
        skills.approve(self.f, sid, reviewer="lead", results={"new code differs": True})

    def test_proposed_is_a_candidate_and_not_runnable(self) -> None:
        self.assertIs(self.f.get(self.sid).lifecycle_state, LifecycleState.CANDIDATE)
        v = skills.runnable(self.f, self.sid, "agent-b", self.policy)
        self.assertFalse(v.ok)
        self.assertIn("candidate", v.reasons[0])

    def test_approval_rules(self) -> None:
        with self.assertRaises(PermissionError):
            skills.approve(self.f, self.sid, reviewer="agent-a", results={"new code differs": True})
        with self.assertRaises(ValueError):
            skills.approve(self.f, self.sid, reviewer="lead", results={"new code differs": False})
        self.approve(self.sid)
        self.assertTrue(skills.runnable(self.f, self.sid, "agent-b", self.policy).ok)

    def test_a_skill_grants_no_tool(self) -> None:
        self.approve(self.sid)
        v = skills.runnable(self.f, self.sid, "agent-c", self.policy)
        self.assertFalse(v.ok)
        self.assertIn("confers no permission", v.reasons[0])
        self.assertFalse(skills.runnable(self.f, self.sid, "agent-b", None).ok)

    def test_a_withdrawn_prerequisite_stops_it(self) -> None:
        self.approve(self.sid)
        self.f.quarantine(self.policy_memory, reason="policy rescinded", actor="lead", basis="contradicted")
        v = skills.runnable(self.f, self.sid, "agent-b", self.policy)
        self.assertFalse(v.ok)

    def test_a_revision_needs_its_own_approval_and_retires_the_old_one(self) -> None:
        self.approve(self.sid)
        v2 = skills.revise(self.f, self.sid, "agent-a", ["issue a new code", "notify security"])
        self.assertTrue(skills.runnable(self.f, self.sid, "agent-b", self.policy).ok)
        self.assertFalse(skills.runnable(self.f, v2, "agent-b", self.policy).ok)
        self.approve(v2)
        self.assertTrue(skills.runnable(self.f, v2, "agent-b", self.policy).ok)
        self.assertFalse(skills.runnable(self.f, self.sid, "agent-b", self.policy).ok)
        self.assertEqual(skills.history(self.f, v2), [v2, self.sid])
        v3 = skills.rollback(self.f, v2, "agent-a", to=self.sid)
        self.assertEqual(skills.spec(self.f, v3)["steps"], skills.spec(self.f, self.sid)["steps"])
        self.assertIs(self.f.get(v3).lifecycle_state, LifecycleState.CANDIDATE)
        with self.assertRaises(ValueError):
            skills.rollback(self.f, v2, "agent-a", to=self.policy_memory)


if __name__ == "__main__":
    unittest.main()
