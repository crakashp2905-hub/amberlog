"""The complete memory lifecycle, as a user runs it: an MCP server and the CLI in separate processes.

remember (candidate, not recallable) -> a reviewer approves from the CLI ->
the running server recalls it and verify passes -> an operator withdraws it
from the CLI -> the running server no longer recalls it and verify fails.
Each step crosses a process boundary, so this also checks cross-process
freshness on the path an MCP client depends on.
"""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]


class LifecycleThroughMcp(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = str(Path(self.tmp.name) / "store.db")
        self.server = subprocess.Popen(
            [sys.executable, "-m", "amberlog", "--db", self.db, "--create", "mcp",
             "--agent", "ag1", "--no-maintain"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, cwd=ROOT)
        self.addCleanup(self._stop)
        self.n = 0
        self.rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                "clientInfo": {"name": "t", "version": "1"}})
        self.notify("notifications/initialized")

    def _stop(self) -> None:
        assert self.server.stdin is not None and self.server.stdout is not None
        self.server.stdin.close()
        self.server.wait(15)
        self.server.stdout.close()

    def notify(self, method: str) -> None:
        assert self.server.stdin is not None
        self.server.stdin.write(json.dumps({"jsonrpc": "2.0", "method": method}) + "\n")
        self.server.stdin.flush()

    def rpc(self, method: str, params: dict) -> dict:
        assert self.server.stdin is not None and self.server.stdout is not None
        self.n += 1
        self.server.stdin.write(json.dumps({"jsonrpc": "2.0", "id": self.n, "method": method,
                                            "params": params}) + "\n")
        self.server.stdin.flush()
        return json.loads(self.server.stdout.readline())

    def tool(self, name: str, arguments: dict) -> tuple[dict, bool]:
        result = self.rpc("tools/call", {"name": name, "arguments": arguments})["result"]
        return result.get("structuredContent", {}), bool(result.get("isError"))

    def cli(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, "-m", "amberlog", "--db", self.db, *args],
                              capture_output=True, text=True, cwd=ROOT, timeout=120)

    def recalled(self) -> list[str]:
        payload, _ = self.tool("recall", {"query": "pump P4 restart pressure"})
        return [m.get("memory_id") or m.get("id") for m in payload.get("memories", [])]

    def test_remember_review_recall_verify_withdraw(self) -> None:
        payload, is_error = self.tool("remember", {"content": "Pump P4 restart: hold 4 bar for two minutes."})
        self.assertFalse(is_error)
        mid = payload["memory_id"]
        self.assertEqual(payload["state"], "candidate")
        self.assertNotIn(mid, self.recalled(), "a candidate is not recallable")

        done = self.cli("review", mid, "--approve", "--actor", "reviewer-1")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn(mid, self.recalled(), "the running server sees the other process's review")
        ok, is_error = self.tool("verify", {"memory_id": mid})
        self.assertFalse(is_error, ok)
        self.assertIs(ok.get("usable"), True, ok)

        done = self.cli("quarantine", mid, "--reason", "found wrong", "--actor", "op")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertNotIn(mid, self.recalled(), "a withdrawn memory is never recalled")
        stale, is_error = self.tool("verify", {"memory_id": mid})
        self.assertTrue(is_error or stale.get("usable") is False, stale)
        self.assertEqual(stale.get("verdict"), "deny")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
