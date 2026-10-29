"""The MCP server: the door every non-Python agent comes through.

As with the SDK, most of these tests are about what the server **cannot** do.
A model on the other end of a pipe is the least trusted caller this project
has, so the server must not give it a single capability `AgentClient` lacks.
"""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest

from amberlog import Amberlog
from amberlog.adapters.mcp import PROTOCOL_VERSIONS, TOOLS, McpServer, serve_stdio
from amberlog.sdk import agent, operator


def _request(method: str, params: dict | None = None, msg_id: int = 1) -> dict:
    message: dict = {"jsonrpc": "2.0", "id": msg_id, "method": method}
    if params is not None:
        message["params"] = params
    return message


class McpCase(unittest.TestCase):
    def setUp(self) -> None:
        self.fabric = Amberlog(":memory:")
        self.addCleanup(self.fabric.close)
        self.operator = operator(self.fabric, "supervisor")
        writer = agent(self.fabric, "ag_writer")
        self.memory_id = writer.remember("E01 at coastal: swap the pilot cable.")
        self.operator.validate(self.memory_id)
        self.operator.share(self.memory_id, "team")
        self.server = McpServer(agent(self.fabric, "ag_mcp"), self.fabric)

    def call(self, name: str, arguments: dict) -> tuple[dict, bool]:
        response = self.server.handle(
            _request("tools/call", {"name": name, "arguments": arguments})
        )
        assert response is not None
        result = response["result"]
        payload = json.loads(result["content"][0]["text"])
        return payload, result["isError"]


class TestLifecycle(McpCase):
    def test_initialize_negotiates_a_supported_version(self) -> None:
        for requested in PROTOCOL_VERSIONS:
            result = self.server.handle(
                _request("initialize", {"protocolVersion": requested, "capabilities": {}})
            )["result"]
            self.assertEqual(result["protocolVersion"], requested)
            self.assertIn("tools", result["capabilities"])

    def test_an_unknown_version_gets_the_newest(self) -> None:
        result = self.server.handle(
            _request("initialize", {"protocolVersion": "1999-01-01"})
        )["result"]
        self.assertEqual(result["protocolVersion"], PROTOCOL_VERSIONS[0])

    def test_server_version_is_the_package_version(self) -> None:
        import amberlog

        result = self.server.handle(_request("initialize", {}))["result"]
        self.assertEqual(result["serverInfo"]["version"], amberlog.__version__)

    def test_notifications_get_no_response(self) -> None:
        self.assertIsNone(
            self.server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"})
        )

    def test_unknown_method_is_a_protocol_error(self) -> None:
        response = self.server.handle(_request("resources/list"))
        self.assertEqual(response["error"]["code"], -32601)

    def test_ping(self) -> None:
        self.assertEqual(self.server.handle(_request("ping"))["result"], {})


class TestTheSurfaceIsNarrow(McpCase):
    def test_exactly_the_agent_tools(self) -> None:
        names = {t["name"] for t in self.server.handle(_request("tools/list"))["result"]["tools"]}
        self.assertEqual(names, {"recall", "fetch", "verify", "remember"})

    def test_there_is_no_outcome_tool(self) -> None:
        """An outcome must come from a third-party verifier, and the model on
        this pipe is the agent being scored."""
        names = {t["name"] for t in TOOLS}
        self.assertFalse(any("outcome" in n for n in names))
        response = self.server.handle(
            _request("tools/call", {"name": "record_outcome", "arguments": {}})
        )
        self.assertIn("error", response)

    def test_remember_takes_no_scope(self) -> None:
        schema = next(t for t in TOOLS if t["name"] == "remember")["inputSchema"]
        self.assertNotIn("scope", schema["properties"])
        self.assertFalse(schema["additionalProperties"])


class TestTools(McpCase):
    def test_recall_returns_usable_memories(self) -> None:
        payload, is_error = self.call("recall", {"query": "pilot cable coastal"})
        self.assertFalse(is_error)
        ids = [m["memory_id"] for m in payload["memories"]]
        self.assertIn(self.memory_id, ids)
        self.assertNotIn("token", payload["memories"][0])

    def test_recall_never_returns_a_retracted_memory(self) -> None:
        self.operator.retract(self.memory_id, reason="wrong fault", basis="contradicted")
        payload, _ = self.call("recall", {"query": "pilot cable coastal"})
        self.assertNotIn(self.memory_id, [m["memory_id"] for m in payload["memories"]])

    def test_fetch_of_a_retracted_memory_is_a_tool_error_without_content(self) -> None:
        self.operator.retract(self.memory_id, reason="wrong fault", basis="contradicted")
        payload, is_error = self.call("fetch", {"memory_id": self.memory_id})
        self.assertTrue(is_error)
        self.assertNotIn("pilot cable", json.dumps(payload))

    def test_verify_catches_a_retraction_after_recall(self) -> None:
        """The time-of-check/time-of-use gap, closed for MCP callers too."""
        self.call("recall", {"query": "pilot cable coastal"})
        before, _ = self.call("verify", {"memory_id": self.memory_id})
        self.assertTrue(before["usable"])
        self.operator.retract(self.memory_id, reason="wrong fault", basis="contradicted")
        after, is_error = self.call("verify", {"memory_id": self.memory_id})
        self.assertFalse(is_error)
        self.assertFalse(after["usable"])

    def test_verify_needs_a_token_from_this_session(self) -> None:
        """The model names memories by id and cannot supply a token, so it
        cannot verify something it was never shown."""
        payload, is_error = self.call("verify", {"memory_id": self.memory_id})
        self.assertTrue(is_error)
        self.assertIn("recall or fetch it first", payload["error"])

    def test_remember_is_private_and_attributed(self) -> None:
        payload, is_error = self.call(
            "remember", {"content": "Reset the breaker before swapping a pump.", "type": "procedural"}
        )
        self.assertFalse(is_error)
        memory = self.fabric.get(payload["memory_id"])
        self.assertEqual(memory.scope.value, "private")
        self.assertEqual(memory.provenance.created_by, "ag_mcp")

    def test_remember_screens_secrets(self) -> None:
        payload, _ = self.call(
            "remember", {"content": "the key is AKIAIOSFODNN7EXAMPLE for prod"}
        )
        self.assertEqual(payload["state"], "quarantined")

    def test_bad_arguments_are_tool_errors_not_crashes(self) -> None:
        for name, args in [
            ("recall", {"query": ""}),
            ("recall", {"query": "x", "k": 0}),
            ("recall", {"query": "x", "k": True}),
            ("remember", {"content": "x", "type": "episodic"}),
            ("fetch", {}),
        ]:
            _, is_error = self.call(name, args)
            self.assertTrue(is_error, (name, args))


class TestTrustedLocal(McpCase):
    """The one-person local assistant, where the reviewer is the user."""

    def trusted(self) -> McpServer:
        return McpServer(agent(self.fabric, "ag_local"), self.fabric, trusted_local=True)

    def call_on(self, server: McpServer, name: str, arguments: dict) -> tuple[dict, bool]:
        result = server.handle(
            _request("tools/call", {"name": name, "arguments": arguments}))["result"]
        return json.loads(result["content"][0]["text"]), result["isError"]

    def test_off_by_default(self) -> None:
        payload, _ = self.call("remember", {"content": "The north gate sticks below freezing."})
        self.assertEqual(payload["state"], "candidate")

    def test_a_clean_write_is_recallable_at_once(self) -> None:
        server = self.trusted()
        payload, _ = self.call_on(server, "remember",
                                  {"content": "The north gate sticks below freezing."})
        self.assertEqual(payload["state"], "active")
        hits, _ = self.call_on(server, "recall", {"query": "north gate freezing"})
        self.assertIn(payload["memory_id"], [m["memory_id"] for m in hits["memories"]])

    def test_the_audit_trail_says_nobody_reviewed_it(self) -> None:
        payload, _ = self.call_on(self.trusted(), "remember",
                                  {"content": "The north gate sticks below freezing."})
        memory = self.fabric.get(payload["memory_id"])
        self.assertEqual(memory.context.get("activation"), "trusted-local")

    def test_the_sensitive_data_screen_still_applies(self) -> None:
        payload, _ = self.call_on(self.trusted(), "remember",
                                  {"content": "the key is AKIAIOSFODNN7EXAMPLE for prod"})
        self.assertEqual(payload["state"], "quarantined")

    def test_the_tool_description_tells_the_truth(self) -> None:
        tools = self.trusted().handle(_request("tools/list"))["result"]["tools"]
        remember = next(t for t in tools if t["name"] == "remember")
        self.assertIn("active immediately", remember["description"])
        self.assertNotIn("until it is reviewed", remember["description"])


class TestTransport(McpCase):
    def test_stdio_round_trip_and_garbage(self) -> None:
        lines = [
            json.dumps(_request("initialize", {"protocolVersion": PROTOCOL_VERSIONS[0]})),
            json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
            "not json",
            json.dumps([_request("ping")]),
            json.dumps(_request("tools/list", msg_id=2)),
        ]
        out = io.StringIO()
        serve_stdio(self.server, io.StringIO("\n".join(lines) + "\n"), out)
        responses = [json.loads(line) for line in out.getvalue().splitlines()]
        self.assertEqual(len(responses), 4)  # the notification gets nothing
        self.assertEqual(responses[1]["error"]["code"], -32700)
        self.assertEqual(responses[2]["error"]["code"], -32600)
        self.assertEqual(responses[3]["id"], 2)


class TestCli(unittest.TestCase):
    def test_the_console_command_speaks_mcp(self) -> None:
        """Through the real entry point, so a stray print to stdout — which
        would corrupt the protocol stream — fails here."""
        with tempfile.TemporaryDirectory() as tmp:
            db = os.path.join(tmp, "store.db")
            messages = [
                _request("initialize", {"protocolVersion": PROTOCOL_VERSIONS[0]}),
                {"jsonrpc": "2.0", "method": "notifications/initialized"},
                _request("tools/call", {"name": "remember", "arguments": {
                    "content": "The north gate sticks below freezing."}}, msg_id=2),
            ]
            proc = subprocess.run(
                [sys.executable, "-m", "amberlog", "--db", db, "--create",
                 "mcp", "--agent", "ag_cli"],
                input="".join(json.dumps(m) + "\n" for m in messages),
                capture_output=True, text=True, timeout=60,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            responses = [json.loads(line) for line in proc.stdout.splitlines()]
            self.assertEqual([r["id"] for r in responses], [1, 2])
            self.assertFalse(responses[1]["result"]["isError"])


class TestVersion(unittest.TestCase):
    def test_package_and_module_versions_agree(self) -> None:
        """`__version__` said 0.7.0 while the wheel said 0.8.0. Release
        qualification caught it; this keeps it caught."""
        import pathlib
        import tomllib

        import amberlog

        root = pathlib.Path(__file__).resolve().parent.parent
        with open(root / "pyproject.toml", "rb") as fh:
            declared = tomllib.load(fh)["project"]["version"]
        self.assertEqual(amberlog.__version__, declared)


if __name__ == "__main__":
    unittest.main()
