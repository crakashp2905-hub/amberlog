"""Agent API verify answers about a memory the agent never recalled (multi-agent pilot)."""

from __future__ import annotations

import os
import tempfile
import unittest

from memory_fabric import MemoryFabric
from memory_fabric.agent_api import AgentApi, RateLimit, _ApiError, encode_credential, load_agents, register_all
from memory_fabric.sdk import agent, operator
from memory_fabric.service import MemoryService


class VerifyUnfetched(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = os.path.join(tmp.name, "agents")
        with open(path, "w") as fh:
            fh.write(f"ag_a:tn_acme:{'aa' * 32}\nag_g:tn_globex:{'cc' * 32}\n")
        self.f = MemoryFabric(":memory:")
        self.addCleanup(self.f.close)
        writer = agent(self.f, "ag_seed", "tn_acme")
        self.mid = writer.remember("Pump P-14: the relief valve is set to 12 bar.")
        op = operator(self.f, "op")
        op.validate(self.mid)
        self.f.share(self.mid, "team", actor="op")
        self.service = MemoryService(fabric=self.f)
        register_all(self.service, load_agents(path))
        self.api = AgentApi(self.service, RateLimit(rate=0.0))

    def bearer(self, who: str) -> str:
        return encode_credential(self.service.issue(who, ttl_seconds=600))

    def test_an_active_memory_verifies_without_a_prior_recall(self) -> None:
        out = self.api.handle("verify", self.bearer("ag_a"), {"memory_id": self.mid})
        self.assertTrue(out["usable"], out)

    def test_a_withdrawn_memory_is_answered_as_withdrawn(self) -> None:
        self.f.quarantine(self.mid, reason="re-specified", basis="contradicted")
        out = self.api.handle("verify", self.bearer("ag_a"), {"memory_id": self.mid})
        self.assertFalse(out["usable"])
        self.assertNotIn("recall or fetch", out["reason"])

    def test_unknown_and_other_tenant_ids_stay_opaque(self) -> None:
        for who, mid in (("ag_a", "01NOTAREALMEMORYID00000000"), ("ag_g", self.mid)):
            with self.subTest(who=who):
                with self.assertRaises(_ApiError) as caught:
                    self.api.handle("verify", self.bearer(who), {"memory_id": mid})
                self.assertEqual(caught.exception.status, 409)


if __name__ == "__main__":
    unittest.main()
