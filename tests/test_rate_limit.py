"""Rate limits and bounded state on the agent HTTP API (plan Phase 4)."""

from __future__ import annotations

import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from unittest import mock

from memory_fabric import MemoryFabric
from memory_fabric import agent_api
from memory_fabric.agent_api import (AgentApi, RateLimit, RateLimiter, _ApiError,
                                     build_agent_server, encode_credential, load_agents,
                                     register_all)
from memory_fabric.sdk import agent, operator
from memory_fabric.service import MemoryService

KEY_A, KEY_B = "aa" * 32, "bb" * 32


class Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


class TestRateLimiter(unittest.TestCase):
    def test_burst_then_refill_at_the_rate(self) -> None:
        clock = Clock()
        limiter = RateLimiter(rate=2.0, burst=3, clock=clock)
        self.assertEqual([limiter.acquire("a") for _ in range(3)], [0.0, 0.0, 0.0])
        wait = limiter.acquire("a")
        self.assertAlmostEqual(wait, 0.5)
        clock.t += 0.5
        self.assertEqual(limiter.acquire("a"), 0.0)
        self.assertGreater(limiter.acquire("a"), 0.0)

    def test_keys_are_independent(self) -> None:
        limiter = RateLimiter(rate=1.0, burst=1, clock=Clock())
        self.assertEqual(limiter.acquire("a"), 0.0)
        self.assertGreater(limiter.acquire("a"), 0.0)
        self.assertEqual(limiter.acquire("b"), 0.0)

    def test_zero_rate_turns_it_off(self) -> None:
        limiter = RateLimiter(rate=0.0, burst=0, clock=Clock())
        self.assertTrue(all(limiter.acquire("a") == 0.0 for _ in range(1000)))

    def test_the_key_table_is_bounded(self) -> None:
        limiter = RateLimiter(rate=1.0, burst=1, clock=Clock(), max_keys=10)
        for i in range(100):
            limiter.acquire(f"k{i}")
        self.assertEqual(len(limiter._buckets), 10)


class ApiCase(unittest.TestCase):
    limits = RateLimit(rate=1.0, burst=2, auth_failures=1.0)

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = os.path.join(tmp.name, "agents")
        with open(path, "w") as fh:
            fh.write(f"ag_a:tn_acme:{KEY_A}\nag_b:tn_acme:{KEY_B}\n")
        self.fabric = MemoryFabric(":memory:")
        self.addCleanup(self.fabric.close)
        self.mid = agent(self.fabric, "ag_seed", "tn_acme").remember(
            "E01 at coastal sites: swap the pilot cable.")
        operator(self.fabric, "op").validate(self.mid)
        self.service = MemoryService(fabric=self.fabric)
        register_all(self.service, load_agents(path))
        self.clock = Clock()
        self.api = AgentApi(self.service, self.limits, clock=self.clock)

    def bearer(self, agent_id: str = "ag_a") -> str:
        return encode_credential(self.service.issue(agent_id, ttl_seconds=600))


class TestApiLimits(ApiCase):
    def test_an_agent_over_its_budget_gets_429_with_a_wait(self) -> None:
        a = self.bearer("ag_a")
        for _ in range(2):
            self.api.handle("recall", a, {"query": "E01 coastal"})
        with self.assertRaises(_ApiError) as caught:
            self.api.handle("recall", a, {"query": "E01 coastal"})
        self.assertEqual(caught.exception.status, 429)
        self.assertGreater(caught.exception.retry_after, 0)
        self.clock.t += 1.0
        self.api.handle("recall", a, {"query": "E01 coastal"})

    def test_one_agent_cannot_spend_another_agents_budget(self) -> None:
        a, b = self.bearer("ag_a"), self.bearer("ag_b")
        for _ in range(2):
            self.api.handle("recall", a, {"query": "E01"})
        with self.assertRaises(_ApiError):
            self.api.handle("recall", a, {"query": "E01"})
        self.api.handle("recall", b, {"query": "E01"})

    def test_failed_authentication_is_limited_per_address(self) -> None:
        statuses = []
        for _ in range(5):
            try:
                self.api.handle("recall", "garbage", {"query": "x"}, remote="10.0.0.9")
            except _ApiError as exc:
                statuses.append(exc.status)
        self.assertEqual(statuses[0], 401)
        self.assertIn(429, statuses)
        with self.assertRaises(_ApiError) as other:
            self.api.handle("recall", "garbage", {"query": "x"}, remote="10.0.0.10")
        self.assertEqual(other.exception.status, 401)

    def test_a_valid_caller_is_not_limited_by_others_failures(self) -> None:
        for _ in range(5):
            with self.assertRaises(_ApiError):
                self.api.handle("recall", None, {"query": "x"}, remote="10.0.0.9")
        self.api.handle("recall", self.bearer(), {"query": "E01"}, remote="10.0.0.9")

    def test_concurrent_agents_do_not_share_the_connection_unlocked(self) -> None:
        """P12b found authentication reading SQLite outside the store lock."""
        api = AgentApi(self.service, RateLimit(rate=0.0))
        bearers = [self.bearer("ag_a"), self.bearer("ag_b")] * 8
        errors: list[BaseException] = []

        def hammer(bearer: str) -> None:
            try:
                for _ in range(25):
                    api.handle("recall", bearer, {"query": "E01 coastal"})
            except BaseException as exc:  # noqa: BLE001 - collected for the assertion
                errors.append(exc)

        threads = [threading.Thread(target=hammer, args=(b,)) for b in bearers]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])


class TestBoundedTokens(ApiCase):
    limits = RateLimit(rate=0.0)

    def test_issued_tokens_are_bounded_per_agent(self) -> None:
        a = self.bearer()
        with mock.patch.object(agent_api, "MAX_TOKENS_PER_AGENT", 1):
            self.api.handle("recall", a, {"query": "E01 coastal"})
            other = agent(self.fabric, "ag_seed", "tn_acme").remember(
                "E02 at inland sites: check the float switch.")
            operator(self.fabric, "op").validate(other)
            self.api.handle("fetch", a, {"memory_id": other})
            self.assertEqual(list(self.api._issued["ag_a"]), [other])
            with self.assertRaises(_ApiError) as caught:
                self.api.handle("verify", a, {"memory_id": self.mid})
            self.assertEqual(caught.exception.status, 409)
            self.api.handle("fetch", a, {"memory_id": self.mid})
            self.assertTrue(self.api.handle("verify", a, {"memory_id": self.mid})["usable"])


class TestOverHttp(ApiCase):
    def test_429_carries_retry_after(self) -> None:
        server = build_agent_server(self.api, port=0)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        a = self.bearer()

        def post() -> tuple[int, dict, dict]:
            request = urllib.request.Request(
                f"http://127.0.0.1:{server.server_address[1]}/v1/recall",
                data=json.dumps({"query": "E01"}).encode(), method="POST",
                headers={"Content-Type": "application/json", "Authorization": f"Bearer {a}"})
            try:
                with urllib.request.urlopen(request, timeout=10) as response:
                    return response.status, dict(response.headers), json.loads(response.read())
            except urllib.error.HTTPError as exc:
                return exc.code, dict(exc.headers), json.loads(exc.read())

        codes = [post() for _ in range(3)]
        self.assertEqual([c[0] for c in codes], [200, 200, 429])
        self.assertEqual(codes[2][1].get("Retry-After"), "1")
        self.assertEqual(codes[2][2], {"error": "too many requests"})


if __name__ == "__main__":
    unittest.main()
