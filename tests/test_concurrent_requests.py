"""Concurrent requests to one store: every one answered, none corrupted.

Found by `experiments/p12_http.py`: ten agents over the agent HTTP API, and 39
of 200 requests failed with `sqlite3.InterfaceError: bad parameter or other API
misuse`, one with "no more rows available". The API authenticated *before*
taking its lock, and authentication reads the revocation table on the store's
one connection, so it ran concurrently with another thread's operation on the
same connection. A cursor that comes back empty because of interference is a
revocation check that says "not revoked". Every failure seen was closed, but
nothing made that so.

The federation server had the same shape with no lock at all. Both now hold
the fabric's own lock, which also covers a process serving both on one store.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

from memory_fabric import MemoryFabric
from memory_fabric.agent_api import (AgentApi, build_agent_server, encode_credential,
                                     load_agents, register_all)
from memory_fabric.sdk import agent, operator
from memory_fabric.service import MemoryService

THREADS = 8
REQUESTS = 25


class ConcurrentAgentRequests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        agents_file = os.path.join(self.tmp.name, "agents")
        with open(agents_file, "w", encoding="utf-8") as fh:
            for i in range(THREADS):
                fh.write(f"ag{i}:tn_acme:{('%02x' % (i + 1)) * 32}\n")
        self.fabric = MemoryFabric(os.path.join(self.tmp.name, "store.db"))
        writer = agent(self.fabric, "ag_seed", "tn_acme")
        for i in range(30):
            operator(self.fabric, "op").validate(
                writer.remember(f"unit {i} runs at {i % 9} bar after fault E0{i % 5}"))
        self.service = MemoryService(fabric=self.fabric)
        register_all(self.service, load_agents(agents_file))
        self.server = build_agent_server(AgentApi(self.service), port=0)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.fabric.close)
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def post(self, op: str, body: dict, token: str) -> int:
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/v1/{op}", data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
            method="POST")
        try:
            with urllib.request.urlopen(req, timeout=60) as res:
                res.read()
                return res.status
        except urllib.error.HTTPError as exc:
            return exc.code

    def test_every_request_is_answered(self) -> None:
        tokens = [encode_credential(self.service.issue(f"ag{i}", ttl_seconds=600))
                  for i in range(THREADS)]
        statuses: list[int] = []
        lock = threading.Lock()
        start = threading.Barrier(THREADS)

        errors: list[str] = []

        def worker(i: int) -> None:
            start.wait()
            for n in range(REQUESTS):
                op, body = (("remember", {"content": f"ag{i} note {n}: unit {n} at {n % 9} bar"})
                            if n % 3 == 0 else ("recall", {"query": f"unit {n} bar"}))
                try:
                    status = self.post(op, body, tokens[i])
                except Exception as exc:  # noqa: BLE001 - reported, not lost with the thread
                    # A worker that raised used to die silently and show only as a
                    # short count (186 != 200 on a loaded machine, 0.11.0 RC).
                    with lock:
                        errors.append(f"ag{i} {op} #{n}: {type(exc).__name__}: {exc}")
                    continue
                with lock:
                    statuses.append(status)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(THREADS)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [], f"{len(errors)} requests raised; first: {errors[:3]}")
        self.assertEqual(len(statuses), THREADS * REQUESTS)
        failures = [s for s in statuses if s != 200]
        self.assertEqual(failures, [], f"{len(failures)} of {len(statuses)} failed")

    def test_a_revoked_credential_stays_refused_under_load(self) -> None:
        tokens = [encode_credential(self.service.issue(f"ag{i}", ttl_seconds=600))
                  for i in range(THREADS)]
        self.service.revoke_agent("ag0")
        accepted: list[int] = []
        start = threading.Barrier(THREADS)

        def worker(i: int) -> None:
            start.wait()
            for n in range(REQUESTS):
                status = self.post("recall", {"query": f"unit {n} bar"}, tokens[i])
                if i == 0 and status == 200:
                    accepted.append(n)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(THREADS)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(accepted, [], "a revoked agent was served")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
