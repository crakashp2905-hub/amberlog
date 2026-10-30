"""Seven separate permissions: read, write, delete, correct, export, administer, execute."""

from __future__ import annotations

import os
import unittest

from memory_fabric import MemoryFabric
from memory_fabric.actions import PERMISSION_DENIED, ActionGate, ActionPolicy, ToolRule
from memory_fabric.identity import (PERMISSIONS, ROLE_AGENT, ROLE_AUDITOR, ROLE_OPERATOR,
                                    IdentityError, Principal)
from memory_fabric.service import MemoryService


class RoleBundles(unittest.TestCase):
    def test_each_role_holds_exactly_its_permissions(self) -> None:
        def perms(*roles: str) -> set[str]:
            return set(Principal("x", roles=frozenset(roles)).permissions())

        self.assertEqual(perms(ROLE_AGENT), {"read", "write", "execute"})
        self.assertEqual(perms(ROLE_OPERATOR),
                         {"read", "write", "delete", "correct", "export", "administer"})
        self.assertEqual(perms(ROLE_AUDITOR), {"read", "export"})
        self.assertEqual(perms("perm:execute"), {"execute"})
        self.assertEqual(len(PERMISSIONS), 7)

    def test_an_unknown_permission_is_an_error_not_a_denial(self) -> None:
        with self.assertRaises(ValueError):
            Principal("x").can("fly")


class ThroughTheService(unittest.TestCase):
    def setUp(self) -> None:
        self.fabric = MemoryFabric(":memory:", auto_activate=True)
        self.addCleanup(self.fabric.close)
        self.service = MemoryService(fabric=self.fabric)
        self.s: dict[str, object] = {}
        for name, roles in (("agent", (ROLE_AGENT,)), ("op", (ROLE_OPERATOR,)),
                            ("aud", (ROLE_AUDITOR,))):
            self.service.register_agent(name, key=os.urandom(32), tenant_id="tn_a", roles=roles)
            self.s[name] = self.service.session(self.service.issue(name))
        self.m = self.s["agent"].remember("Valve V7 opens below 4 bar.", scope="team")

    def test_an_auditor_reads_and_exports_but_cannot_write_or_correct(self) -> None:
        aud = self.s["aud"]
        self.assertTrue(aud.export_audit())
        self.assertTrue(aud.retrieve("valve V7").exposed)
        with self.assertRaises(IdentityError):
            aud.remember("x")
        with self.assertRaises(IdentityError):
            aud.quarantine(self.m, reason="x")

    def test_an_agent_cannot_correct_delete_export_or_administer(self) -> None:
        agent = self.s["agent"]
        for call in (lambda: agent.quarantine(self.m, reason="x"),
                     lambda: agent.erase_content(self.m, reason="x"),
                     lambda: agent.export_audit(),
                     lambda: agent.inspect(self.m)):
            with self.assertRaises(IdentityError):
                call()

    def test_an_operator_corrects_but_cannot_execute(self) -> None:
        op = self.s["op"]
        gate = ActionGate(self.fabric, ActionPolicy(
            tools={"open": ToolRule("open")},
            grants={"op": frozenset({"open"}), "agent": frozenset({"open"})}))
        cert = self.fabric.certify("c", [self.m], "op")
        self.assertEqual(gate.authorize("open", "op", cert, session=op).reason_code,
                         PERMISSION_DENIED)
        agent_cert = self.s["agent"].certify("c", [self.m])
        self.assertTrue(gate.authorize("open", "agent", agent_cert, session=self.s["agent"]).allowed)
        op.quarantine(self.m, reason="wrong")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
