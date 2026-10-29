"""Model-based property: the store's authorisation agrees with a simple oracle, after every step.

A seeded random walk over the operations that change who may read what:
writes at private or team scope in two tenants, validation, quarantine,
revision, collection membership, and collection grants given and revoked.
After **every** step, for every agent and every memory:

- the enforced read (`use`) is usable exactly when the oracle says the agent
  may read it now;
- a token issued earlier verifies at action time exactly when the oracle says
  the agent may read it now *and* the memory has not been revised since.

The oracle is written from the specification, not from the code: same
tenant, an exposable lifecycle state, and either a non-private scope, the
agent being the author, or the memory being in a collection the agent holds
`read` on. Dependency-free, like `test_properties.py`: a failure prints the
seed and the trace, which reproduce it.
"""

from __future__ import annotations

import random
import unittest
from dataclasses import dataclass, field

from amberlog import Amberlog
from amberlog.model import EXPOSABLE_STATES

AGENTS = {"a1": "tn_a", "a2": "tn_a", "b1": "tn_b"}


@dataclass
class Model:
    tenant: dict[str, str] = field(default_factory=dict)
    author: dict[str, str] = field(default_factory=dict)
    scope: dict[str, str] = field(default_factory=dict)
    members: dict[str, set[str]] = field(default_factory=lambda: {"tn_a": set(), "tn_b": set()})
    readers: dict[str, set[str]] = field(default_factory=lambda: {"tn_a": set(), "tn_b": set()})

    def visible(self, agent: str, mid: str, state: object) -> bool:
        tenant = self.tenant[mid]
        if AGENTS[agent] != tenant or state not in EXPOSABLE_STATES:
            return False
        if self.scope[mid] != "private" or self.author[mid] == agent:
            return True
        return mid in self.members[tenant] and agent in self.readers[tenant]


class Walk:
    def __init__(self, seed: int) -> None:
        self.rng = random.Random(seed)
        self.seed = seed
        self.f = Amberlog(":memory:", hold_suspicious=False)
        self.model = Model()
        self.mids: list[str] = []
        self.tokens: dict[tuple[str, str], tuple[object, int]] = {}
        self.trace: list[str] = []

    def pick(self) -> str | None:
        return self.rng.choice(self.mids) if self.mids else None

    def step(self) -> None:
        op = self.rng.choice(["write", "write", "validate", "validate", "quarantine", "revise",
                              "add", "remove", "grant", "revoke", "read"])
        getattr(self, f"op_{op}")()

    def op_write(self) -> None:
        agent = self.rng.choice(list(AGENTS))
        scope = self.rng.choice(["private", "team"])
        n = len(self.mids)
        mid = self.f.remember(agent, f"Note {n}: valve V{n} opens at {n % 9 + 1} bar.",
                              scope=scope, tenant_id=AGENTS[agent])
        self.model.tenant[mid], self.model.author[mid], self.model.scope[mid] = (
            AGENTS[agent], agent, scope)
        self.mids.append(mid)
        self.trace.append(f"write {agent} {scope} {mid[-5:]}")

    def op_validate(self) -> None:
        mid = self.pick()
        if mid and self.f.get(mid).lifecycle_state.value == "candidate":
            self.f.validate(mid, actor="lead")
            self.trace.append(f"validate {mid[-5:]}")

    def op_quarantine(self) -> None:
        mid = self.pick()
        if mid and self.f.get(mid).lifecycle_state.value == "active" and self.rng.random() < 0.3:
            self.f.quarantine(mid, reason="wrong", actor="lead")
            self.trace.append(f"quarantine {mid[-5:]}")

    def op_revise(self) -> None:
        mid = self.pick()
        if mid and self.f.get(mid).lifecycle_state.value == "active":
            self.f.revise(mid, f"Revised: valve opens at {self.rng.randint(1, 9)} bar.",
                          agent_id=self.model.author[mid], reason="re-measured")
            self.trace.append(f"revise {mid[-5:]}")

    def op_add(self) -> None:
        mid = self.pick()
        if mid and self.f.get(mid).security_class.value != "restricted":
            self.f.collection_add("ops", mid, actor="lead")
            self.model.members[self.model.tenant[mid]].add(mid)
            self.trace.append(f"add {mid[-5:]}")

    def op_remove(self) -> None:
        mid = self.pick()
        if mid and mid in self.model.members[self.model.tenant[mid]]:
            self.f.collection_remove("ops", mid, actor="lead")
            self.model.members[self.model.tenant[mid]].discard(mid)
            self.trace.append(f"remove {mid[-5:]}")

    def op_grant(self) -> None:
        agent = self.rng.choice(list(AGENTS))
        self.f.collection_grant("ops", agent, ["read"], actor="lead", tenant_id=AGENTS[agent])
        self.model.readers[AGENTS[agent]].add(agent)
        self.trace.append(f"grant {agent}")

    def op_revoke(self) -> None:
        agent = self.rng.choice(list(AGENTS))
        if agent in self.model.readers[AGENTS[agent]]:
            self.f.collection_revoke("ops", agent, actor="lead", tenant_id=AGENTS[agent])
            self.model.readers[AGENTS[agent]].discard(agent)
            self.trace.append(f"revoke {agent}")

    def op_read(self) -> None:
        """Take a token where the read is usable, to check it at action time later."""
        mid, agent = self.pick(), self.rng.choice(list(AGENTS))
        if mid is None:
            return
        read = self.f.use(mid, agent_id=agent, tenant_id=AGENTS[agent])
        if read.usable:
            self.tokens[(agent, mid)] = (read.token, self.f.get(mid).version)
            self.trace.append(f"token {agent} {mid[-5:]}")

    def check(self) -> list[str]:
        problems = []
        for mid in self.mids:
            state = self.f.get(mid).lifecycle_state
            for agent in AGENTS:
                expected = self.model.visible(agent, mid, state)
                got = self.f.use(mid, agent_id=agent, tenant_id=AGENTS[agent], audit=False).usable
                if got != expected:
                    problems.append(f"use({agent}, {mid[-5:]}) = {got}, oracle {expected}")
        for (agent, mid), (token, version) in self.tokens.items():
            expected = (self.model.visible(agent, mid, self.f.get(mid).lifecycle_state)
                        and self.f.get(mid).version == version)
            got = self.f.verify_before_action(token, agent, audit=False).usable
            if got != expected:
                problems.append(f"token({agent}, {mid[-5:]}) = {got}, oracle {expected}")
        return problems


class AuthorisationAgreesWithTheOracle(unittest.TestCase):
    def test_seeded_walks(self) -> None:
        for seed in range(30):
            walk = Walk(seed)
            try:
                for i in range(60):
                    walk.step()
                    problems = walk.check()
                    if problems:
                        self.fail(f"seed {seed}, step {i}: {problems[:3]}\n"
                                  + "\n".join(walk.trace[-15:]))
            finally:
                walk.f.close()

    def test_walks_exercise_the_interesting_operations(self) -> None:
        seen: set[str] = set()
        for seed in range(30):
            walk = Walk(seed)
            for _ in range(60):
                walk.step()
            seen |= {t.split()[0] for t in walk.trace}
            walk.f.close()
        self.assertTrue({"write", "validate", "quarantine", "revise", "add", "remove",
                         "grant", "revoke", "token"} <= seen, seen)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
