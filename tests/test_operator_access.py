"""Named dashboard operators and the audit of who looked.

DEPLOYMENT.md recorded two limits of the dashboard: one shared token with no
identity, and "no audit of *who looked*". These tests are about closing both
without weakening anything the shared-token server already guaranteed: tokens
compared in constant time and never printed or logged, and browsing writing
nothing to the event log.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

from amberlog import Amberlog
from amberlog.observability.auth import (
    AuthConfig, Authenticator, InsecureConfiguration, build_config,
    default_allowed_hosts, load_operators,
)
from amberlog.observability.server import build_server

ALICE = "alice-" + "a" * 40
BOB = "bob-" + "b" * 40


def _write(path: str, text: str) -> str:
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)
    return path


class TestOperatorsFile(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, "operators")

    def test_reads_names_and_tokens(self) -> None:
        _write(self.path, f"# ops\nalice:{ALICE}\n\nbob:{BOB}\n")
        self.assertEqual(load_operators(self.path), {"alice": ALICE, "bob": BOB})

    def test_refuses_what_would_defeat_attribution(self) -> None:
        for name, text in {
            "short token": "alice:short",
            "shared token": f"alice:{ALICE}\nbob:{ALICE}",
            "duplicate name": f"alice:{ALICE}\nalice:{BOB}",
            "missing separator": f"alice {ALICE}",
            "empty": "# nobody\n",
            "bad name": f"al ice:{ALICE}",
        }.items():
            with self.subTest(name):
                _write(self.path, text)
                with self.assertRaises(InsecureConfiguration):
                    load_operators(self.path)

    def test_operators_and_no_auth_contradict(self) -> None:
        with self.assertRaises(InsecureConfiguration):
            build_config("127.0.0.1", token=None, no_auth=True, operators={"a": ALICE})

    def test_no_unattributed_shared_token_is_invented(self) -> None:
        config = build_config("127.0.0.1", token=None, no_auth=False,
                              operators={"alice": ALICE})
        self.assertIsNone(config.token)
        self.assertEqual([n for n, _ in config.credentials()], ["alice"])


class TestIdentity(unittest.TestCase):
    def setUp(self) -> None:
        self.auth = Authenticator(AuthConfig(
            token=None, operators={"alice": ALICE, "bob": BOB}))

    def test_each_token_is_its_owner(self) -> None:
        self.assertEqual(self.auth.identify(ALICE), "alice")
        self.assertEqual(self.auth.identify(BOB), "bob")
        self.assertIsNone(self.auth.identify(ALICE[:-1] + "x"))
        self.assertIsNone(self.auth.identify(""))

    def test_the_bootstrap_cookie_carries_the_operators_own_token(self) -> None:
        outcome = self.auth.authenticate(f"/?token={BOB}", {"Host": "127.0.0.1:8765"})
        self.assertEqual(outcome.operator, "bob")
        self.assertIn(BOB, outcome.set_cookie)
        self.assertNotIn(ALICE, outcome.set_cookie)


class TestAccessLog(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.TemporaryDirectory()
        cls.log_path = os.path.join(cls.tmp.name, "access.jsonl")
        cls.fabric = Amberlog(auto_activate=True, seed=1)
        cls.mid = cls.fabric.remember("agent-a", "A memory worth protecting.")
        config = AuthConfig(token=None, allowed_hosts=default_allowed_hosts("127.0.0.1"),
                            operators={"alice": ALICE, "bob": BOB})
        cls.server = build_server(cls.fabric, host="127.0.0.1", port=0, quiet=True,
                                  auth=config, access_log=cls.log_path)
        cls.port = cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.fabric.close()
        cls.tmp.cleanup()

    def get(self, path: str, token: str | None = None) -> int:
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=10) as res:
                res.read()
                return res.status
        except urllib.error.HTTPError as exc:
            return exc.code

    def entries(self) -> list[dict]:
        with open(self.log_path, encoding="utf-8") as handle:
            return [json.loads(line) for line in handle if line.strip()]

    def test_it_records_who_looked_at_what(self) -> None:
        self.assertEqual(self.get(f"/api/memories/{self.mid}", ALICE), 200)
        self.assertEqual(self.get("/api/overview", BOB), 200)
        seen = {(e["operator"], e["path"]) for e in self.entries()}
        self.assertIn(("alice", f"/api/memories/{self.mid}"), seen)
        self.assertIn(("bob", "/api/overview"), seen)

    def test_it_records_refusals_too(self) -> None:
        self.assertEqual(self.get("/api/overview"), 401)
        self.assertEqual(self.get("/api/overview", "wrong-" + "z" * 40), 401)
        refused = [e for e in self.entries() if e["status"] == 401]
        self.assertGreaterEqual(len(refused), 2)
        self.assertTrue(all(e["operator"] is None for e in refused))

    def test_no_token_ever_reaches_the_log(self) -> None:
        self.get(f"/?token={ALICE}")
        self.get("/api/overview", BOB)
        with open(self.log_path, encoding="utf-8") as handle:
            text = handle.read()
        self.assertNotIn(ALICE, text)
        self.assertNotIn(BOB, text)

    def test_browsing_still_writes_nothing_to_the_event_log(self) -> None:
        """The audit is a separate file on purpose: the event log is evidence
        for value estimates, and an operator's reading is not evidence."""
        before = len(self.fabric.log)
        self.get(f"/api/memories/{self.mid}", ALICE)
        self.get("/api/overview", BOB)
        self.assertEqual(len(self.fabric.log), before)


if __name__ == "__main__":
    unittest.main()
