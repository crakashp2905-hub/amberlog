"""The branch, merge and context commands drive the real operations end to end."""

from __future__ import annotations

import contextlib
import io
import json
import os
import tempfile
import unittest

from memory_fabric import MemoryFabric
from memory_fabric.cli import main


class Commands(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        self.db = os.path.join(self.tmp.name, "store.db")
        f = MemoryFabric(self.db, auto_activate=True)
        self.p1 = f.remember("ann", "Pump P1 runs at 4 bar.", scope="team")
        f.remember("ann", "Pump P1 seal is not leaking.", scope="team")
        f.close()

    def cli(self, *args: str) -> tuple[int, str]:
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            code = main(["--db", self.db, *args])
        return code, out.getvalue()

    def test_branch_commit_preview_apply_and_replay(self) -> None:
        self.assertEqual(self.cli("branch", "create", "trial", "--actor", "ann",
                                  "--reviewer", "lead")[0], 0)
        code, out = self.cli("branch", "revise", "trial", "--actor", "ann", "--memory", self.p1,
                             "--text", "Pump P1 runs at 5 bar.")
        self.assertEqual(code, 0, out)
        code, out = self.cli("--json", "merge", "preview", "trial", "--actor", "lead")
        self.assertEqual(code, 0, out)
        preview = json.loads(out)
        self.assertEqual(preview["changes"][0]["decision"], "allow")
        args = ("merge", "apply", "trial", "--actor", "lead", "--preview", preview["digest"],
                "--key", "k1")
        self.assertEqual(self.cli(*args)[0], 0)
        self.assertEqual(self.cli(*args)[0], 0)  # a retry replays
        f = MemoryFabric(self.db)
        self.assertEqual((f.get(self.p1).content, f.get(self.p1).version),
                         ("Pump P1 runs at 5 bar.", 2))
        f.close()
        code, out = self.cli("merge", "apply", "trial", "--actor", "lead", "--preview",
                             "0" * 64, "--key", "k2")
        self.assertEqual(code, 5, out)
        self.assertIn("STALE_PREVIEW", out)

    def test_branch_list_show_and_diff(self) -> None:
        self.cli("branch", "create", "trial", "--actor", "ann")
        self.cli("branch", "add", "trial", "--actor", "ann", "--text", "Pump P2 runs at 3 bar.")
        for action in ("list", "show", "diff"):
            code, out = self.cli("--json", "branch", action, *(["trial"] if action != "list" else []))
            self.assertEqual(code, 0, out)
            self.assertTrue(json.loads(out))

    def test_a_non_member_cannot_commit(self) -> None:
        self.cli("branch", "create", "trial", "--actor", "ann")
        code, out = self.cli("branch", "add", "trial", "--actor", "mallory", "--text", "x 1")
        self.assertEqual(code, 4)
        self.assertIn("BRANCH_NOT_PERMITTED", out)

    def test_context_build_receipts_and_explain(self) -> None:
        code, out = self.cli("--json", "context", "build", "--agent", "ann", "--query",
                             "pump p1 seal", "--mode", "evidence-first")
        self.assertEqual(code, 0, out)
        receipt = json.loads(out)["receipt"]
        self.assertTrue(receipt["selected"])
        code, out = self.cli("--json", "context", "explain", receipt["receipt_id"])
        self.assertEqual(code, 0, out)
        self.assertTrue(all(i["admissible_now"] for i in json.loads(out)["selected"]))
        code, out = self.cli("--json", "context", "receipts")
        self.assertEqual(len(json.loads(out)), 1)
        self.assertEqual(self.cli("context", "explain", "ctx_missing")[0], 4)



class DecayCommands(unittest.TestCase):
    def test_wake_pending_summarise_zoom(self) -> None:
        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmp.cleanup)
        db = os.path.join(tmp.name, "s.db")
        f = MemoryFabric(db, auto_activate=True)
        for i in range(24):
            f.remember("ann", f"Pump P{i} runs at {i + 10} bar.", scope="team")
        f.close()

        def cli(*args: str) -> tuple[int, str]:
            out = io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
                code = main(["--db", db, *args])
            return code, out.getvalue()

        code, out = cli("context", "wake", "--agent", "ann", "--budget", "100")
        self.assertEqual(code, 0, out)
        self.assertIn("#", out)
        code, out = cli("--json", "context", "pending", "--agent", "ann", "--budget", "100")
        node = json.loads(out)[0]["node"]
        code, out = cli("context", "summarise", "--agent", "ann", "--node", node,
                        "--text", "Pumps run at 999 bar.")
        self.assertEqual(code, 4)
        code, out = cli("--json", "context", "zoom", "--agent", "ann", "--node", node)
        self.assertEqual(code, 0, out)
        self.assertEqual(len(json.loads(out)), 2)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
