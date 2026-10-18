"""`agent-api-revoke`: an operator can revoke a leaked credential mid-incident.

Revocation used to exist only as a Python API, so the credential-compromise
runbook would have had to tell an operator to write code. The command runs on
its own handle to the store, as a separate process would, and a server already
running on that store must refuse the credential on its very next request.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

from memory_fabric import MemoryFabric
from memory_fabric.agent_api import (AgentApi, build_agent_server, encode_credential,
                                     load_agents, register_all)
from memory_fabric.cli import main
from memory_fabric.service import MemoryService


class RevokeFromTheCommandLine(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = os.path.join(self.tmp.name, "store.db")
        self.agents = os.path.join(self.tmp.name, "agents")
        with open(self.agents, "w", encoding="utf-8") as fh:
            fh.write(f"ag_a:tn_default:{'aa' * 32}\nag_b:tn_default:{'bb' * 32}\n")
        self.fabric = MemoryFabric(self.db)
        self.service = MemoryService(fabric=self.fabric)
        register_all(self.service, load_agents(self.agents))
        self.server = build_agent_server(AgentApi(self.service), port=0)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.fabric.close)
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def status(self, token: str) -> int:
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/v1/recall", data=json.dumps({"query": "x"}).encode(),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
            method="POST")
        try:
            with urllib.request.urlopen(req, timeout=10) as res:
                return res.status
        except urllib.error.HTTPError as exc:
            return exc.code

    def run_cli(self, *args: str, stdin: str = "") -> tuple[int, str]:
        out, err = io.StringIO(), io.StringIO()
        old_stdin = sys.stdin
        sys.stdin = io.StringIO(stdin)
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = main(["--db", self.db, "agent-api-revoke", "--agents-file", self.agents,
                             *args])
        finally:
            sys.stdin = old_stdin
        return code, out.getvalue() + err.getvalue()

    def test_a_leaked_token_is_refused_on_the_next_request(self) -> None:
        leaked = encode_credential(self.service.issue("ag_a"))
        other = encode_credential(self.service.issue("ag_a"))
        self.assertEqual(self.status(leaked), 200)
        code, output = self.run_cli("--token", "-", stdin=leaked)
        self.assertEqual(code, 0, output)
        self.assertNotIn(leaked, output, "the token must not be echoed")
        self.assertEqual(self.status(leaked), 401)
        self.assertEqual(self.status(other), 200, "only the leaked credential is revoked")

    def test_an_agent_can_be_cut_off_entirely(self) -> None:
        a1 = encode_credential(self.service.issue("ag_a"))
        a2 = encode_credential(self.service.issue("ag_a"))
        b = encode_credential(self.service.issue("ag_b"))
        code, output = self.run_cli("--agent", "ag_a")
        self.assertEqual(code, 0, output)
        self.assertEqual((self.status(a1), self.status(a2), self.status(b)), (401, 401, 200))

    def test_garbage_is_an_error_not_a_revocation(self) -> None:
        code, _ = self.run_cli("--token", "not-a-credential")
        self.assertEqual(code, 5)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
