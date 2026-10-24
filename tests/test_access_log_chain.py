"""The dashboard access log is hash-chained (security review O6)."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from io import StringIO
from unittest import mock

from memory_fabric.cli import main
from memory_fabric.observability.server import AccessLog, verify_access_log


class AccessLogChain(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = os.path.join(tmp.name, "access.jsonl")

    def write(self, n: int) -> list[str]:
        log = AccessLog(self.path)
        for i in range(n):
            log.record(f"op{i}", "GET", f"/api/m/{i}", 200, "127.0.0.1")
        with open(self.path) as fh:
            return fh.read().splitlines()

    def rewrite(self, lines: list[str]) -> None:
        with open(self.path, "w") as fh:
            fh.write("\n".join(lines) + "\n")

    def test_an_untouched_log_verifies(self) -> None:
        self.write(5)
        self.assertEqual(verify_access_log(self.path)[:2], (True, None))

    def test_the_chain_continues_across_restarts(self) -> None:
        self.write(3)
        self.write(3)
        self.assertTrue(verify_access_log(self.path)[0])

    def test_an_edited_line_breaks_it(self) -> None:
        lines = self.write(5)
        entry = json.loads(lines[2])
        entry["operator"] = "someone_else"
        lines[2] = json.dumps(entry, sort_keys=True)
        self.rewrite(lines)
        self.assertEqual(verify_access_log(self.path)[:2], (False, 4))

    def test_a_deleted_line_breaks_it(self) -> None:
        lines = self.write(5)
        del lines[1]
        self.rewrite(lines)
        self.assertEqual(verify_access_log(self.path)[:2], (False, 2))

    def test_reordering_breaks_it(self) -> None:
        lines = self.write(4)
        lines[1], lines[2] = lines[2], lines[1]
        self.rewrite(lines)
        self.assertFalse(verify_access_log(self.path)[0])

    def test_a_legacy_unchained_prefix_is_accepted(self) -> None:
        self.rewrite([json.dumps({"operator": "old", "status": 200})])
        self.write(3)
        self.assertTrue(verify_access_log(self.path)[0])

    def test_the_cli_exits_5_on_a_broken_chain(self) -> None:
        lines = self.write(3)
        del lines[0]
        self.rewrite(lines)
        with mock.patch("sys.stdout", StringIO()) as out:
            code = main(["access-log-verify", self.path])
        self.assertEqual(code, 5)
        self.assertIn("BROKEN", out.getvalue())


if __name__ == "__main__":
    unittest.main()
