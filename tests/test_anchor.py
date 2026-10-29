"""`amberlog anchor`: one command to keep checkpoints beyond the writer's reach."""

from __future__ import annotations

import json
import shutil
import subprocess
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory

from amberlog import Amberlog
from tests import test_checkpoint_rewrite as rewrite


class Anchor(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(self.enterContext(TemporaryDirectory()))
        self.db = self.tmp / "store.db"
        f = Amberlog(str(self.db), auto_activate=True)
        f.remember("tech", "Valve V7 opens below 4 bar.", scope="team")
        f.remember("tech", "Pump P1 purge time is 30 s.", scope="team")
        self.store_id = f.store_id
        f.close()

    def rewrite_history(self) -> None:
        rewrite.CheckpointRewrite.rewrite_history(self)  # type: ignore[arg-type]

    def test_dir_anchor_then_verify(self) -> None:
        target = self.tmp / "elsewhere"
        self.assertEqual(rewrite.run("--db", str(self.db), "anchor", "--to", f"dir:{target}"), 0)
        self.assertTrue((target / f"{self.store_id}.anchors.jsonl").exists())
        self.assertEqual(rewrite.run("--db", str(self.db), "anchor", "--verify", f"dir:{target}"), 0)

    def test_a_consistent_rewrite_is_caught_by_an_earlier_anchor(self) -> None:
        target = self.tmp / "elsewhere"
        rewrite.run("--db", str(self.db), "anchor", "--to", f"dir:{target}")
        self.rewrite_history()
        self.assertEqual(rewrite.run("--db", str(self.db), "anchor", "--verify", f"dir:{target}"), 5)

    @unittest.skipIf(shutil.which("git") is None, "git not installed")
    def test_git_anchor_commits(self) -> None:
        repo = self.tmp / "anchors-repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        self.assertEqual(rewrite.run("--db", str(self.db), "anchor", "--to", f"git:{repo}"), 0)
        log = subprocess.run(["git", "-C", str(repo), "log", "--oneline"], capture_output=True,
                             text=True, check=True).stdout
        self.assertIn(f"anchor {self.store_id}", log)

    def test_http_anchor_posts_the_checkpoint(self) -> None:
        got: list[dict] = []

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                got.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
                self.send_response(204)
                self.end_headers()

            def log_message(self, *a: object) -> None:
                return

        server = HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        url = f"http://127.0.0.1:{server.server_address[1]}/anchor"
        self.assertEqual(rewrite.run("--db", str(self.db), "anchor", "--to", url), 0)
        self.assertEqual(got[0]["store_id"], self.store_id)
        self.assertIn("chain_digest", got[0])

    def test_one_failing_target_does_not_hide_the_others(self) -> None:
        target = self.tmp / "ok"
        code = rewrite.run("--db", str(self.db), "anchor", "--to", "http://127.0.0.1:9/none",
                   "--to", f"dir:{target}")
        self.assertEqual(code, 5)
        self.assertTrue((target / f"{self.store_id}.anchors.jsonl").exists())

    def test_no_target_is_an_error(self) -> None:
        self.assertEqual(rewrite.run("--db", str(self.db), "anchor"), 2)


if __name__ == "__main__":
    unittest.main()
