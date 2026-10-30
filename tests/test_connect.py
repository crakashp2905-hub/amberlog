"""`connect`: each tool's format, and --write merges without touching the rest."""

from __future__ import annotations

import json
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest import mock

from memory_fabric.connect import TARGETS, snippet, write


class TestConnect(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name)
        patcher = mock.patch("pathlib.Path.home", return_value=self.home)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_every_target_renders(self):
        for name in TARGETS:
            s = snippet(name, "store.db", "ag-1")
            self.assertIn("ag-1", s["text"], name)
            if s["kind"] == "json":
                json.loads(s["text"])
            if s["kind"] == "toml":
                tomllib.loads(s["text"])

    def test_write_merges_and_keeps_a_backup(self):
        path = self.home / ".cursor" / "mcp.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"mcpServers": {"other": {"command": "x"}}, "theme": 1}))
        write("cursor", "store.db", "cursor-alice")
        data = json.loads(path.read_text())
        self.assertEqual(data["mcpServers"]["other"], {"command": "x"})
        self.assertEqual(data["theme"], 1)
        self.assertIn("cursor-alice", data["mcpServers"]["memory-fabric"]["args"])
        self.assertTrue((path.parent / "mcp.json.bak").exists())

    def test_codex_toml_appends_once(self):
        path = self.home / ".codex" / "config.toml"
        path.parent.mkdir(parents=True)
        path.write_text('model = "o4"\n')
        write("codex", "store.db", "codex")
        parsed = tomllib.loads(path.read_text())
        self.assertEqual(parsed["model"], "o4")
        self.assertEqual(parsed["mcp_servers"]["memory-fabric"]["args"][-1], "codex")
        with self.assertRaises(ValueError):
            write("codex", "store.db", "codex")

    def test_refuses_what_it_cannot_merge(self):
        path = self.home / ".cursor" / "mcp.json"
        path.parent.mkdir(parents=True)
        path.write_text("[]")
        with self.assertRaises(ValueError):
            write("cursor", "store.db", "a")
        with self.assertRaises(ValueError):
            write("claude-code", "store.db", "a")

    def test_zed_and_vscode_use_their_own_keys(self):
        self.assertIn("context_servers", snippet("zed", "s.db", "a")["text"])
        self.assertIn('"servers"', snippet("vscode", "s.db", "a")["text"])


if __name__ == "__main__":
    unittest.main()
