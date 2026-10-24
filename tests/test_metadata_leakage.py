"""Another tenant's memory leaks nothing through a tenant view: not content, not existence.

Each channel a tenant can reach is probed twice: once against a world where
another tenant holds a closely matching memory, and once where it does not.
With `conceal_cross_tenant`, the two observations must be identical, except
for the other tenant's id itself, which a caller can only have guessed.
"""

from __future__ import annotations

import unittest
from typing import Any, Callable

from memory_fabric import MemoryFabric
from memory_fabric.actions import ActionGate, ActionPolicy, ToolRule

CONFIDENTIAL = "Tenant A plans to acquire Contoso for 4.2 billion in Q3."
MINE = "Tenant B notes: Contoso is a supplier of valves."


def world(with_secret: bool) -> tuple[MemoryFabric, Any, str, str]:
    f = MemoryFabric(":memory:", auto_activate=True, conceal_cross_tenant=True, seed=7)
    theirs = (f.remember("a", CONFIDENTIAL, tenant_id="tn_a", scope="team") if with_secret
              else "01NOTAREALMEMORYID00000000")
    view = f.for_tenant("tn_b", "b")
    mine = view.remember(MINE, scope="team")
    return f, view, theirs, mine


def observe(probe: Callable[[Any, str, str], Any], with_secret: bool) -> str:
    f, view, theirs, mine = world(with_secret)
    try:
        try:
            out = repr(probe(view, theirs, mine))
        except Exception as exc:  # noqa: BLE001 - the error is the observation
            out = f"{type(exc).__name__}: {exc}"
        return out.replace(theirs, "<ID>").replace(mine, "<MINE>")
    finally:
        f.close()


PROBES: dict[str, Callable[[Any, str, str], Any]] = {
    "retrieve ids": lambda v, t, m: [r.memory.id for r in v.retrieve("Contoso acquire billion",
                                                                       k=5).results],
    "retrieve count": lambda v, t, m: len(v.retrieve("Contoso acquire billion", k=5).results),
    "use": lambda v, t, m: v.use(t).content,
    "derive": lambda v, t, m: v.derive("x", [t]),
    # The certificate's own id is fresh and random; what could leak is
    # whether verification treats a foreign id differently from a missing one.
    "certify and verify": lambda v, t, m: (lambda c: (c.ok, c.reason_codes))(
        v.verify_certificate(v.certify("c", [t]))),
    "memory_ids": lambda v, t, m: sorted(v.memory_ids()),
}


class Leakage(unittest.TestCase):
    def test_no_channel_distinguishes_a_world_with_the_secret(self) -> None:
        for name, probe in PROBES.items():
            with self.subTest(channel=name):
                self.assertEqual(observe(probe, True), observe(probe, False))

    def test_the_secret_content_never_appears(self) -> None:
        for name, probe in PROBES.items():
            with self.subTest(channel=name):
                self.assertNotIn("4.2 billion", observe(probe, True))

    def test_an_action_gate_refusal_does_not_confirm_existence(self) -> None:
        def gated(view: Any, theirs: str, mine: str) -> Any:
            gate = ActionGate(view.fabric, ActionPolicy(tools={"t": ToolRule("t")},
                                                        grants={"b": frozenset({"t"})}))
            cert = {"claim_id": "c", "agent_id": "b", "tenant_id": "tn_b",
                    "evidence": [{"memory_id": theirs, "version": 1}]}
            decision = gate.authorize("t", "b", cert, tenant_id="tn_b")
            return (decision.allowed, decision.reason_codes)

        self.assertEqual(observe(gated, True), observe(gated, False))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
