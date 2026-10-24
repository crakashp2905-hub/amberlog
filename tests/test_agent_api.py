"""The authenticated agent API, over a real socket.

As with the SDK and the MCP server, most of these are about what a caller
cannot do: act without a valid credential, act as another agent, cross a
tenant, reach a withdrawn memory, or tell one kind of auth failure from another.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

from memory_fabric import MemoryFabric
from memory_fabric.agent_api import (
    AgentApi, ConfigurationError, build_agent_server, check_bind,
    decode_credential, encode_credential, load_agents, register_all,
)
from memory_fabric.service import MemoryService
from memory_fabric.sdk import agent, operator

KEY_A = "aa" * 32
KEY_B = "bb" * 32
KEY_C = "cc" * 32


class ApiCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.agents_file = os.path.join(self.tmp.name, "agents")
        with open(self.agents_file, "w") as fh:
            fh.write(f"# agents\nag_a:tn_acme:{KEY_A}\nag_b:tn_acme:{KEY_B}\n"
                     f"ag_other:tn_globex:{KEY_C}\n")
        self.fabric = MemoryFabric(":memory:")
        writer = agent(self.fabric, "ag_seed", "tn_acme")
        self.mid = writer.remember("E01 at coastal sites: swap the pilot cable.")
        operator(self.fabric, "op").validate(self.mid)
        # An agent's write is private to it until shared; the other agents here
        # read it, so the operator shares it to the team.
        operator(self.fabric, "op").share(self.mid, "team")
        self.service = MemoryService(fabric=self.fabric)
        register_all(self.service, load_agents(self.agents_file))
        self.server = build_agent_server(AgentApi(self.service), port=0)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.fabric.close)
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def token(self, agent_id: str = "ag_a", ttl: int = 600) -> str:
        return encode_credential(self.service.issue(agent_id, ttl_seconds=ttl))

    def post(self, op: str, body: dict, token: str | None = None,
             headers: dict | None = None) -> tuple[int, dict]:
        h = {"Content-Type": "application/json", **(headers or {})}
        if token:
            h["Authorization"] = f"Bearer {token}"
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}/v1/{op}",
                                     data=json.dumps(body).encode(), headers=h,
                                     method="POST")
        try:
            with urllib.request.urlopen(req, timeout=10) as res:
                return res.status, json.loads(res.read())
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read() or b"{}")


class TestTheSurface(ApiCase):
    def test_recall_verify_remember(self) -> None:
        token = self.token()
        status, body = self.post("recall", {"query": "pilot cable coastal"}, token)
        self.assertEqual(status, 200)
        self.assertIn(self.mid, [m["memory_id"] for m in body["memories"]])
        status, body = self.post("verify", {"memory_id": self.mid}, token)
        self.assertEqual((status, body["usable"]), (200, True))
        status, body = self.post("remember", {"content": "Reset the breaker first."}, token)
        self.assertEqual((status, body["state"]), (200, "candidate"))
        self.assertEqual(self.fabric.get(body["memory_id"]).provenance.created_by, "ag_a")

    def test_a_retraction_reaches_the_next_verify(self) -> None:
        token = self.token()
        self.post("recall", {"query": "pilot cable coastal"}, token)
        operator(self.fabric, "op").retract(self.mid, reason="wrong", basis="contradicted")
        status, body = self.post("verify", {"memory_id": self.mid}, token)
        self.assertEqual((status, body["usable"]), (200, False))
        status, _ = self.post("fetch", {"memory_id": self.mid}, token)
        self.assertEqual(status, 403)

    def test_there_is_no_outcome_endpoint(self) -> None:
        status, _ = self.post("record_outcome", {"episode_id": "x", "outcome": 1.0},
                              self.token())
        self.assertEqual(status, 404)


class TestIdentityAndTenancy(ApiCase):
    def test_no_credential_is_refused(self) -> None:
        self.assertEqual(self.post("recall", {"query": "pilot"})[0], 401)

    def test_every_auth_failure_looks_the_same(self) -> None:
        good = self.service.issue("ag_a", ttl_seconds=600)
        from dataclasses import replace
        forged = encode_credential(replace(good, agent_id="ag_b"))
        # Correctly signed, only the expiry wrong: the registry will not issue
        # one, so it is built and signed here with the agent's own key.
        expired = encode_credential(
            replace(good, expires_at=good.issued_at - 1).sign(bytes.fromhex(KEY_A)))
        revoked_cred = self.service.issue("ag_a", ttl_seconds=600)
        self.service.revoke(revoked_cred)
        bodies = []
        for token in (forged, expired, encode_credential(revoked_cred), "garbage!!"):
            status, body = self.post("recall", {"query": "pilot"}, token)
            self.assertEqual(status, 401)
            bodies.append(body)
        self.assertEqual(len({json.dumps(b) for b in bodies}), 1)

    def test_another_tenant_cannot_see_it(self) -> None:
        status, body = self.post("recall", {"query": "pilot cable coastal"},
                                 self.token("ag_other"))
        self.assertEqual(status, 200)
        self.assertEqual(body["memories"], [])
        self.assertEqual(self.post("fetch", {"memory_id": self.mid},
                                   self.token("ag_other"))[0], 403)

    def test_tokens_are_per_agent(self) -> None:
        """ag_b cannot verify on the strength of ag_a's recall."""
        self.post("recall", {"query": "pilot cable coastal"}, self.token("ag_a"))
        status, _ = self.post("verify", {"memory_id": self.mid}, self.token("ag_b"))
        self.assertEqual(status, 409)


class TestTransportDefences(ApiCase):
    def test_browser_requests_are_refused(self) -> None:
        status, _ = self.post("recall", {"query": "pilot"}, self.token(),
                              headers={"Origin": "https://evil.example"})
        self.assertEqual(status, 403)

    def test_oversized_bodies_are_refused(self) -> None:
        status, _ = self.post("remember", {"content": "x" * 70_000}, self.token())
        self.assertEqual(status, 413)

    def test_plain_http_off_loopback_is_refused(self) -> None:
        with self.assertRaises(ConfigurationError):
            check_bind("0.0.0.0", behind_tls=False)
        check_bind("0.0.0.0", behind_tls=True)

    def test_credential_round_trip(self) -> None:
        credential = self.service.issue("ag_a", ttl_seconds=60)
        self.assertEqual(decode_credential(encode_credential(credential)), credential)


class TestAgentsFile(unittest.TestCase):
    def test_refuses_weak_or_malformed_entries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "agents")
            for name, text in {
                "short key": "ag:tn:abcd",
                "not hex": "ag:tn:" + "zz" * 32,
                "missing field": "ag:" + "aa" * 32,
                "duplicate": f"ag:tn:{KEY_A}\nag:tn:{KEY_B}",
                "empty": "# none",
            }.items():
                with self.subTest(name):
                    with open(path, "w") as fh:
                        fh.write(text)
                    with self.assertRaises(ConfigurationError):
                        load_agents(path)


class TestCli(unittest.TestCase):
    def test_issue_prints_a_credential_the_server_accepts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = os.path.join(tmp, "s.db")
            agents = os.path.join(tmp, "agents")
            with open(agents, "w") as fh:
                fh.write(f"ag_a:tn_default:{KEY_A}\n")
            done = subprocess.run(
                [sys.executable, "-m", "memory_fabric", "--db", db, "--create",
                 "agent-api-issue", "--agents-file", agents, "--agent", "ag_a"],
                capture_output=True, text=True, timeout=60)
            self.assertEqual(done.returncode, 0, done.stderr)
            credential = decode_credential(done.stdout.strip())
            self.assertEqual(credential.agent_id, "ag_a")


if __name__ == "__main__":
    unittest.main()
