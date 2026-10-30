"""S4: recipient-side trust per (origin, context), and the transfer gate policy."""

from __future__ import annotations

import random
import unittest

from memory_fabric import MemoryFabric
from memory_fabric.exposure import Candidate, TransferGatePolicy
from memory_fabric.federation import offer
from memory_fabric.governance.firewall import (Firewall, rule_capabilities_must_be_granted,
                                               rule_must_be_active, rule_restricted_stays_private)
from memory_fabric.model import Scope, ValueEstimate
from memory_fabric.trust import DEFAULT, TransferTrust, origin_of


def store() -> MemoryFabric:
    return MemoryFabric(":memory:", auto_activate=True, firewall=Firewall(rules=(
        rule_restricted_stays_private, rule_must_be_active, rule_capabilities_must_be_granted)))


class Trust(unittest.TestCase):
    def setUp(self) -> None:
        self.r = store()
        self.good, self.bad = store(), store()
        for s in (self.r, self.good, self.bad):
            self.addCleanup(s.close)
        self.imports = {}
        for name, src in (("good", self.good), ("bad", self.bad)):
            mid = src.remember("tech", f"Fault F01 alarm: apply action from {name}.", scope="team")
            src.share(mid, Scope.FEDERATED, actor="op")
            self.imports[name] = offer(src, mid, self.r, recipient_agent="agent",
                                       activate=True).imported_memory_id

    def episode(self, relied: str | None, outcome: float, ctx: int) -> None:
        e = self.r.start_episode("agent", "task", context={"ctx": ctx})
        if relied:
            self.r.cite("agent", e.id, self.imports[relied])
        self.r.record_outcome(e.id, outcome, verifier_id="env")

    def test_trust_is_learned_per_origin_and_context_from_own_outcomes(self) -> None:
        for _ in range(8):
            self.episode("good", 1.0, 0)
            self.episode("bad", 0.0, 0)
            self.episode(None, 0.5, 0)
            self.episode("bad", 1.0, 1)  # the same sender is fine in another context
        trust = TransferTrust(self.r)
        good, bad = self.good.store_id, self.bad.store_id
        self.assertEqual(origin_of(self.r, self.imports["good"]), good)
        self.assertGreater(trust.trust(good, {"ctx": 0}).mean, 0.85)
        self.assertLess(trust.trust(bad, {"ctx": 0}).mean, 0.15)
        self.assertGreater(trust.trust(bad, {"ctx": 1}).mean, 0.85)
        self.assertAlmostEqual(trust.trust(DEFAULT, {"ctx": 0}).mean, 0.5, places=6)
        picks = [trust.choose(list(self.imports.values()), {"ctx": 0}, random.Random(i))
                 for i in range(200)]
        self.assertGreater(picks.count(self.imports["good"]), 180)
        self.assertEqual(picks.count(self.imports["bad"]), 0)

    def test_with_no_evidence_it_explores(self) -> None:
        trust = TransferTrust(self.r)
        picks = {trust.choose(list(self.imports.values()), {"ctx": 5}, random.Random(i))
                 for i in range(100)}
        self.assertEqual(picks, {self.imports["good"], self.imports["bad"], None})


class Gate(unittest.TestCase):
    def test_a_confidently_harmful_candidate_is_not_greedy_but_still_explored(self) -> None:
        harmful = Candidate("m-bad", 1, 0.9, ValueEstimate(-0.4, -0.6, -0.2, 10, "dr",
                                                           contrastive=True))
        unknown = Candidate("m-new", 1, 0.5)
        policy = TransferGatePolicy(0.2)
        exposed_bad = 0
        for seed in range(400):
            decisions = {d.candidate.memory_id: d for d in
                         policy.decide([harmful, unknown], 1, random.Random(seed))}
            exposed_bad += decisions["m-bad"].exposed
            if decisions["m-bad"].exposed:
                self.assertAlmostEqual(decisions["m-bad"].propensity, 0.1)
        self.assertTrue(10 < exposed_bad < 80, exposed_bad)  # about 10%: exploration only


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
