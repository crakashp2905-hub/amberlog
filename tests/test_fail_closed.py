"""The fail-closed audit, pinned (plan Phase 2).

Every exception handler on an authorisation, integrity or screening path was
read (docs/SAFETY_AND_SECURITY.md §6 lists the results). The handlers that
could turn an error into an answer are tested here. Two defects were found and
fixed:

- the agent HTTP API and the MCP server returned the text of *any* exception
  to the caller, internals included;
- with `conceal_cross_tenant`, deriving from another tenant's memory still
  said the id "belongs to another tenant", which confirmed it exists.
"""

from __future__ import annotations

import json
import unittest
from unittest import mock

from memory_fabric import MemoryFabric
from memory_fabric.enforcement import RiskLevel, Verdict
from memory_fabric.fabric import NotFound, PolicyViolation
from memory_fabric.identity import IdentityError
from memory_fabric.sdk import AgentClient, agent, operator, public_error

INTERNAL = "sqlite3.OperationalError at /srv/secret/store.db: row 41 tn_other"


class TestPublicErrors(unittest.TestCase):
    def test_expected_refusals_keep_their_message(self) -> None:
        for exc in (PolicyViolation("cannot revise erased content"),
                    NotFound("no memory 'x'"), IdentityError("credential expired"),
                    ValueError("k must be an integer")):
            with self.subTest(type(exc).__name__):
                self.assertIn(str(exc), public_error(exc))

    def test_a_fault_never_reaches_the_caller(self) -> None:
        for exc in (RuntimeError(INTERNAL), KeyError(INTERNAL), OSError(INTERNAL)):
            with self.subTest(type(exc).__name__):
                message = public_error(exc)
                self.assertNotIn("secret", message)
                self.assertNotIn("tn_other", message)


class TestMcpFault(unittest.TestCase):
    def test_an_internal_fault_is_a_generic_tool_error(self) -> None:
        from memory_fabric.adapters.mcp import McpServer

        fabric = MemoryFabric(":memory:")
        self.addCleanup(fabric.close)
        server = McpServer(agent(fabric, "ag"), fabric)
        with mock.patch.object(AgentClient, "recall", side_effect=RuntimeError(INTERNAL)), \
                self.assertLogs("memory_fabric.adapters.mcp", level="WARNING"):
            response = server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                      "params": {"name": "recall",
                                                 "arguments": {"query": "x"}}})
        result = response["result"]
        self.assertTrue(result["isError"])
        self.assertNotIn("secret", json.dumps(result))


class TestAgentApiFault(unittest.TestCase):
    def test_an_internal_fault_is_a_generic_422(self) -> None:
        import os
        import tempfile
        import threading
        import urllib.error
        import urllib.request

        from memory_fabric.agent_api import (AgentApi, build_agent_server,
                                             encode_credential, load_agents, register_all)
        from memory_fabric.service import MemoryService

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = os.path.join(tmp.name, "agents")
        with open(path, "w") as fh:
            fh.write(f"ag_a:tn_acme:{'aa' * 32}\n")
        fabric = MemoryFabric(":memory:")
        service = MemoryService(fabric=fabric)
        register_all(service, load_agents(path))
        server = build_agent_server(AgentApi(service), port=0)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(fabric.close)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        bearer = encode_credential(service.issue("ag_a", ttl_seconds=600))
        request = urllib.request.Request(
            f"http://127.0.0.1:{server.server_address[1]}/v1/recall",
            data=json.dumps({"query": "x"}).encode(), method="POST",
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {bearer}"})
        with mock.patch.object(AgentClient, "recall", side_effect=RuntimeError(INTERNAL)), \
                self.assertLogs("memory_fabric.agent_api", level="WARNING"):
            with self.assertRaises(urllib.error.HTTPError) as caught:
                urllib.request.urlopen(request, timeout=10)
        self.assertEqual(caught.exception.code, 422)
        body = caught.exception.read().decode()
        self.assertNotIn("secret", body)
        self.assertNotIn("tn_other", body)


class TestConcealedDerive(unittest.TestCase):
    def test_deriving_from_another_tenant_looks_like_a_missing_id(self) -> None:
        fabric = MemoryFabric(auto_activate=True, conceal_cross_tenant=True)
        self.addCleanup(fabric.close)
        theirs = fabric.remember("a", "tenant A fact", tenant_id="tn_a")
        view = fabric.for_tenant("tn_b", "b")
        missing_id = "01NOTAREALMEMORYID00000000"
        with self.assertRaises(NotFound) as other:
            view.derive("x", [theirs])
        with self.assertRaises(NotFound) as missing:
            view.derive("x", [missing_id])
        self.assertEqual(str(other.exception).replace(theirs, "ID"),
                         str(missing.exception).replace(missing_id, "ID"))


class TestChecksThatRaiseRefuse(unittest.TestCase):
    """An exception inside a check must surface as a refusal, never as usable."""

    def test_a_failing_enforcer_check_is_not_a_usable_read(self) -> None:
        fabric = MemoryFabric(auto_activate=True)
        self.addCleanup(fabric.close)
        mid = fabric.remember("a", "valve 7 is upstream")
        with mock.patch.object(type(fabric.enforcer), "check", side_effect=RuntimeError("db")):
            with self.assertRaises(RuntimeError):
                fabric.use(mid, agent_id="b", risk=RiskLevel.HIGH)

    def test_a_failing_screen_refuses_the_write(self) -> None:
        """The screen raising must not store the memory unscreened."""
        fabric = MemoryFabric(auto_activate=True)
        self.addCleanup(fabric.close)
        before = len(fabric.state.memories)
        with mock.patch.object(type(fabric.firewall), "screen_ingest",
                               side_effect=RuntimeError("regex engine")):
            with self.assertRaises(RuntimeError):
                fabric.remember("a", "valve 7 is upstream")
        self.assertEqual(len(fabric.state.memories), before)

    def test_an_unmodelled_lifecycle_is_unknown_not_usable(self) -> None:
        fabric = MemoryFabric(auto_activate=True)
        self.addCleanup(fabric.close)
        mid = fabric.remember("a", "valve 7 is upstream")
        memory = fabric.state.memories[mid]
        fake = type("State", (), {"value": "from_the_future"})()
        with mock.patch.dict(fabric.state.memories,
                             {mid: memory.evolve(lifecycle_state=fake)}):
            decision = fabric.enforcer.check(mid, risk=RiskLevel.LOW)
        self.assertIs(decision.verdict, Verdict.UNKNOWN)
        self.assertFalse(decision.usable)


if __name__ == "__main__":
    unittest.main()
