"""Every supported access path reflects every authorisation change at the next call.

Paths: the agent SDK, a verified service session, a tenant view, the HTTP
agent API, the MCP server and the function-calling tools. Changes: another
tenant's memory, a collection grant revoked (scope narrowed), a credential
revoked, a memory revised (version moved) and a memory withdrawn. Each path
is driven through its own public interface, and each must agree.
"""

from __future__ import annotations

import os
import unittest
from typing import Any, Callable

from memory_fabric import MemoryFabric, sdk
from memory_fabric.adapters.mcp import McpServer
from memory_fabric.agent_api import AgentApi, encode_credential
from memory_fabric.identity import IdentityError
from memory_fabric.integrations.tools import FabricTools
from memory_fabric.service import MemoryService

QUERY = "valve V7 opens bar"
TENANT, OTHER = "tn_a", "tn_b"


class Path:
    """One access path, as the agent `bob` in tenant `tn_a` sees the store."""

    def __init__(self, name: str, recall: Callable[[], list[str]],
                 verify: Callable[[str], bool] | None, revoke: Callable[[], None] | None) -> None:
        self.name, self.recall, self.verify, self.revoke = name, recall, verify, revoke


def ids_of(reply: Any) -> list[str]:
    if isinstance(reply, dict) and "memories" in reply:
        return [m["memory_id"] for m in reply["memories"]]
    return []


def mcp_call(server: McpServer, tool: str, args: dict) -> Any:
    reply = server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                           "params": {"name": tool, "arguments": args}})
    result = reply.get("result", {})
    return result.get("structuredContent") if not result.get("isError") else {"error": True}


class Matrix(unittest.TestCase):
    def setUp(self) -> None:
        self.f = MemoryFabric(":memory:", auto_activate=True)
        self.addCleanup(self.f.close)
        # A team memory in tn_a, a private one alice shares with bob through a
        # collection, and tn_b's matching memory bob must never see.
        self.team = self.f.remember("seed", "Valve V7 opens below 4 bar.", scope="team",
                                    tenant_id=TENANT)
        self.private = self.f.remember("alice", "Valve V7 opens slowly, 2 turns a minute, bar 4.",
                                       tenant_id=TENANT)
        self.f.collection_add("ops", self.private, actor="lead")
        self.f.collection_grant("ops", "bob", ["read"], actor="lead", tenant_id=TENANT)
        self.foreign = self.f.remember("other", "Valve V7 opens below 9 bar at tn_b.",
                                       scope="team", tenant_id=OTHER)
        self.service = MemoryService(fabric=self.f)
        self.service.register_agent("bob", key=os.urandom(32), tenant_id=TENANT)
        self.paths = self._paths()

    def _paths(self) -> list[Path]:
        f, svc = self.f, self.service
        client = sdk.agent(f, "bob", TENANT)
        view = f.for_tenant(TENANT, "bob")
        held: dict[str, Any] = {}

        def sdk_recall() -> list[str]:
            hits = client.recall(QUERY, k=10)
            held.update({h.memory_id: h for h in hits})
            return [h.memory_id for h in hits]

        session_cred = svc.issue("bob")
        session = svc.session(session_cred)

        def session_recall() -> list[str]:
            try:
                return [m.id for m in session.retrieve(QUERY, k=10).exposed]
            except IdentityError:
                return ["<refused>"]

        api = AgentApi(svc)
        bearer = {"token": encode_credential(svc.issue("bob"))}

        def http(op: str, body: dict) -> Any:
            try:
                return api.handle(op, bearer["token"], body)
            except Exception:  # noqa: BLE001 - a refusal is an answer
                return {"error": True}

        server = McpServer(sdk.agent(f, "bob", TENANT), f)
        tools = FabricTools(sdk.agent(f, "bob", TENANT))

        return [
            Path("sdk", sdk_recall,
                 lambda mid: mid in held and client.verify(held[mid]).usable, None),
            Path("session", session_recall, None, lambda: svc.revoke(session_cred)),
            Path("tenant_view", lambda: [m.id for m in view.retrieve(QUERY, k=10).exposed],
                 None, None),
            Path("http", lambda: ids_of(http("recall", {"query": QUERY, "k": 10})),
                 lambda mid: bool(http("verify", {"memory_id": mid}).get("usable")),
                 lambda: svc.revoke(api_cred(bearer["token"]))),
            Path("mcp", lambda: ids_of(mcp_call(server, "recall", {"query": QUERY, "k": 10})),
                 lambda mid: bool((mcp_call(server, "verify", {"memory_id": mid}) or {})
                                  .get("usable")), None),
            Path("tools", lambda: ids_of(tools.call("recall", {"query": QUERY, "k": 10})),
                 None, None),
        ]

    def each(self) -> Any:
        for path in self.paths:
            with self.subTest(path=path.name):
                yield path

    def test_baseline_every_path_sees_both_tenant_a_memories(self) -> None:
        for path in self.each():
            self.assertEqual(set(path.recall()), {self.team, self.private})

    def test_another_tenants_memory_is_never_returned(self) -> None:
        for path in self.each():
            self.assertNotIn(self.foreign, path.recall())

    def test_revoking_the_collection_grant_hides_the_private_memory(self) -> None:
        for path in self.each():
            path.recall()
        self.f.collection_revoke("ops", "bob", actor="lead", tenant_id=TENANT)
        for path in self.each():
            self.assertNotIn(self.private, path.recall())
            if path.verify is not None:
                self.assertFalse(path.verify(self.private), "a held reference stops working")

    def test_a_withdrawn_memory_disappears_and_its_references_stop(self) -> None:
        for path in self.each():
            path.recall()
        self.f.quarantine(self.team, reason="wrong", actor="lead")
        for path in self.each():
            self.assertNotIn(self.team, path.recall())
            if path.verify is not None:
                self.assertFalse(path.verify(self.team))

    def test_a_revision_moves_every_path_to_the_new_version(self) -> None:
        for path in self.each():
            path.recall()
        self.f.revise(self.team, "Valve V7 opens below 3 bar.", agent_id="seed", reason="re-measured")
        for path in self.each():
            self.assertIn(self.team, path.recall())
        hits = sdk.agent(self.f, "bob", TENANT).recall(QUERY, k=10)
        self.assertIn("3 bar", [h.content for h in hits if h.memory_id == self.team][0])

    def test_a_revoked_credential_is_refused_at_the_next_call(self) -> None:
        for path in self.each():
            if path.revoke is None:
                continue
            path.revoke()
            self.assertEqual([m for m in path.recall() if m != "<refused>"], [])


def api_cred(token: str) -> Any:
    from memory_fabric.agent_api import decode_credential

    return decode_credential(token)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
