"""The model-backed free-text claim check, with a fake model."""

from __future__ import annotations

import json
import types
import unittest

from memory_fabric import MemoryFabric
from memory_fabric.claimcheck import ModelClaimChecker, parse
from memory_fabric.models import ModelClient


def model(reply: str | None):
    def runner(cmd, **kw):
        if reply is None:
            return types.SimpleNamespace(stdout=json.dumps({"is_error": True, "result": "down"}))
        return types.SimpleNamespace(stdout=json.dumps({"result": reply, "usage": {}}))
    return ModelClient("claude-cli:fake", runner=runner)


class TestClaimCheck(unittest.TestCase):
    def store(self, reply):
        checker = ModelClaimChecker(model(reply))
        f = MemoryFabric(":memory:", auto_activate=True, claim_checker=checker)
        self.addCleanup(f.close)
        f.remember("inspector", "The east wing is safe to enter.", scope="team")
        return f, checker

    def test_contradiction_is_held(self):
        f, c = self.store('{"contradicts": [1], "why": "safe vs unsafe"}')
        mid = f.remember("visitor", "The east wing is not safe to enter.", scope="team")
        self.assertNotEqual(f.lifecycle_of(mid).value, "active")
        self.assertEqual(c.calls, 1)

    def test_no_contradiction_passes(self):
        f, _ = self.store('{"contradicts": [], "why": "detail"}')
        mid = f.remember("visitor", "The east wing was repainted.", scope="team")
        self.assertEqual(f.lifecycle_of(mid).value, "active")

    def test_a_model_failure_never_blocks_a_write(self):
        for reply in (None, "I think so", '{"contradicts": "x"}'):
            f, c = self.store(reply)
            mid = f.remember("visitor", "The east wing is not safe to enter.", scope="team")
            self.assertEqual(f.lifecycle_of(mid).value, "active")
            self.assertEqual(c.errors, 1)

    def test_structured_claims_skip_the_model(self):
        f, c = self.store('{"contradicts": [1]}')
        f.remember("visitor", "Pump P-14 relief valve is set to 12 bar.", scope="team")
        self.assertEqual(c.calls, 0)

    def test_parse(self):
        self.assertEqual(parse('ok {"contradicts": [2, 9]} done', 3), [2])
        self.assertIsNone(parse("no json", 3))


if __name__ == "__main__":
    unittest.main()
