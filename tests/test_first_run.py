"""The first run: `init` leaves a working, production-shaped store.

The test for a first-run command is whether what it prints works: so this runs
the MCP server with exactly the arguments `init` prints and talks to it.
"""

from __future__ import annotations

import ast
import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from amberlog import Amberlog
from amberlog.agent_api import load_agents
from amberlog.cli import main
from amberlog.governance.erasure import DirectoryKeyProvider
from amberlog.posture import posture

ROOT = Path(__file__).resolve().parent.parent


class Init(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = os.path.join(self.tmp.name, "mf")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.code = main(["init", self.dir, "--agent", "helper"])
        self.output = out.getvalue()

    def test_it_creates_a_sound_store_with_external_keys(self) -> None:
        self.assertEqual(self.code, 0, self.output)
        self.assertIn("Sound.", self.output)
        fabric = Amberlog(os.path.join(self.dir, "store.db"),
                              key_provider=DirectoryKeyProvider(os.path.join(self.dir, "keys")))
        try:
            keys = next(c for c in posture(fabric)["controls"]
                        if c["name"] == "content keys kept outside the database")
            self.assertEqual(keys["state"], "on")
        finally:
            fabric.close()

    def test_the_agents_file_is_valid_and_its_key_is_not_printed(self) -> None:
        entries = load_agents(os.path.join(self.dir, "agents.txt"))
        self.assertEqual([e.agent_id for e in entries], ["helper"])
        self.assertNotIn(entries[0].key.hex(), self.output)

    def test_it_never_overwrites(self) -> None:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main(["init", self.dir]), 2)

    def test_the_printed_mcp_configuration_works(self) -> None:
        config = json.loads(self.output[self.output.index("{"):self.output.index("\nNext:")])
        args = config["mcpServers"]["amberlog"]["args"]
        messages = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize",
             "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                        "clientInfo": {"name": "test", "version": "0"}}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        ]
        proc = subprocess.run(
            [sys.executable, "-m", "amberlog", *args],
            input="\n".join(json.dumps(m) for m in messages) + "\n",
            capture_output=True, text=True, timeout=60, cwd=str(ROOT))
        replies = [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]
        tools = next(r for r in replies if r.get("id") == 2)["result"]["tools"]
        self.assertEqual({t["name"] for t in tools}, {"recall", "fetch", "verify", "remember"})


class DoctorAlwaysSaysWhatToDo(unittest.TestCase):
    def test_every_warning_and_failure_carries_a_fix(self) -> None:
        tree = ast.parse((ROOT / "src" / "amberlog" / "cli.py").read_text(encoding="utf-8"))
        missing = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "Finding":
                status = node.args[0].value if node.args and isinstance(node.args[0], ast.Constant) else ""
                has_fix = len(node.args) >= 4 or any(k.arg == "fix" for k in node.keywords)
                if status in ("warn", "fail") and not has_fix:
                    missing.append(node.lineno)
        self.assertEqual(missing, [], f"doctor findings without a fix at cli.py lines {missing}")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
