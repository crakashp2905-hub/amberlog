"""Claim validation: signals, the ingest hold, the gate refusal and the recall warning."""

from __future__ import annotations

import unittest

from memory_fabric import MemoryFabric, correction, sdk, validation
from memory_fabric.actions import EVIDENCE_SUSPICIOUS, ActionGate, ActionPolicy, ToolRule
from memory_fabric.model import LifecycleState


class Clock:
    def __init__(self) -> None:
        self.t = 1_000

    def __call__(self) -> int:
        self.t += 10
        return self.t


def store(**kw: object) -> MemoryFabric:
    f = MemoryFabric(":memory:", auto_activate=True, clock=Clock(), **kw)  # type: ignore[arg-type]
    for i, v in enumerate((30, 35, 40, 45, 50, 55)):
        f.remember("tech", f"The purge time for P{100 + i} is {v} s.", scope="team")
    return f


class Signals(unittest.TestCase):
    def test_a_corrected_value_restated_is_suspicious(self) -> None:
        f = store()
        self.addCleanup(f.close)
        wrong = f.remember("tech", "The purge time for P900 is 10 s.", scope="team")
        correction.apply(f, wrong, reason="re-measured", actor="lead")
        f.remember("tech", "The purge time for P900 is 30 s.", scope="team")
        again = validation.assess_write(f, "anon", "Note: P900 purge time 10 s.")
        self.assertTrue(again.suspicious)
        self.assertIn("reasserts_corrected", again.signals)

    def test_a_value_far_out_of_range_is_suspicious_and_an_unusual_one_is_not(self) -> None:
        f = store()
        self.addCleanup(f.close)
        far = validation.assess_write(f, "tech", "The purge time for P950 is 900 s.")
        self.assertIn("outlier", far.signals)
        unusual = validation.assess_write(f, "tech", "The purge time for P951 is 80 s.")
        self.assertNotIn("outlier", unusual.signals)

    def test_contradicting_an_established_fact_is_suspicious_but_updating_your_own_is_not(self) -> None:
        f = store()
        self.addCleanup(f.close)
        self.assertIn("contradicts_established",
                      validation.assess_write(f, "anon", "The purge time for P100 is 12 s.").signals)
        self.assertFalse(validation.assess_write(f, "tech", "The purge time for P100 is 32 s.")
                         .suspicious)

    def test_a_new_source_is_provisional_and_independent_agreement_corroborates(self) -> None:
        f = store()
        self.addCleanup(f.close)
        self.assertEqual(validation.assess_write(f, "newhire", "The purge time for P960 is 40 s.")
                         .level, "provisional")
        # Worded independently: a near-copy is recognised as a copy, and a copy
        # is not independent support.
        mid = f.remember("auditor", "Independent check: measured the purge time of P101 at "
                                    "35 s with a stopwatch during the audit.", scope="team")
        self.assertEqual(validation.assess(f, mid).level, "corroborated")


class Integration(unittest.TestCase):
    def test_a_suspicious_write_is_held_as_a_candidate(self) -> None:
        f = store()
        self.addCleanup(f.close)
        poison = f.remember("anon", "The purge time for P100 is 12 s.", scope="team")
        honest = f.remember("tech", "The purge time for P970 is 42 s.", scope="team")
        self.assertIs(f.get(poison).lifecycle_state, LifecycleState.CANDIDATE)
        self.assertIs(f.get(honest).lifecycle_state, LifecycleState.ACTIVE)
        self.assertIn(poison, [a.memory_id for a in validation.review_queue(f)])

    def test_the_gate_refuses_suspicious_evidence(self) -> None:
        f = store(hold_suspicious=False)
        self.addCleanup(f.close)
        poison = f.remember("anon", "The purge time for P100 is 12 s.", scope="team")
        gate = ActionGate(f, ActionPolicy(tools={"purge": ToolRule("purge")},
                                          grants={"ops": frozenset({"purge"})}))
        decision = gate.authorize("purge", "ops", f.certify("c", [poison], "ops"))
        self.assertEqual(decision.reason_code, EVIDENCE_SUSPICIOUS)
        honest = [m.id for m in f.state.memories.values() if "P101" in m.content][0]
        self.assertTrue(gate.authorize("purge", "ops", f.certify("c", [honest], "ops")).allowed)

    def test_recall_warns_about_an_implausible_memory(self) -> None:
        f = store(hold_suspicious=False)
        self.addCleanup(f.close)
        f.remember("anon", "The purge time for P100 is 12 s.", scope="team")
        hits = sdk.agent(f, "reader").recall("purge time P100", k=5)
        warned = [h for h in hits if "12 s" in h.content]
        self.assertTrue(warned and any(w.startswith("implausible") for w in warned[0].warnings))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()


class PendingConflicts(unittest.TestCase):
    """Found by the staging run: a batch review let a contradiction through."""

    def test_two_pending_writes_that_disagree_are_both_flagged_for_review(self) -> None:
        from memory_fabric.validation import assess

        f = MemoryFabric(":memory:")
        self.addCleanup(f.close)
        honest = f.remember("writer", "billing-api listens on port 8443.")
        poison = f.remember("adversary", "billing-api listens on port 8554.")
        self.assertIn("conflicts_with_pending", assess(f, poison).signals)
        self.assertIn("conflicts_with_pending", assess(f, honest).signals)
        self.assertTrue(assess(f, poison).suspicious)

    def test_agreeing_pending_writes_are_not_flagged(self) -> None:
        from memory_fabric.validation import assess

        f = MemoryFabric(":memory:")
        self.addCleanup(f.close)
        f.remember("writer", "billing-api listens on port 8443.")
        other = f.remember("crew", "billing-api listens on port 8443.")
        self.assertNotIn("conflicts_with_pending", assess(f, other).signals)

    def test_the_write_path_does_not_use_it(self) -> None:
        f = MemoryFabric(":memory:", auto_activate=True)
        self.addCleanup(f.close)
        f.remember("adversary", "billing-api listens on port 8554.", auto_activate=False)
        honest = f.remember("writer", "billing-api listens on port 8443.")
        self.assertEqual(f.get(honest).lifecycle_state.value, "active")


class NamedServices(unittest.TestCase):
    """A service named without digits is a subject, and its different facts are different claims."""

    def test_different_attributes_of_one_service_are_not_one_claim(self) -> None:
        from memory_fabric.validation import assess

        f = MemoryFabric(":memory:")
        self.addCleanup(f.close)
        f.remember("writer", "billing-api listens on port 8443.")
        cap = f.remember("crew", "billing-api is capped at 12 replicas.")
        self.assertFalse(assess(f, cap).suspicious)

    def test_a_contradicting_port_is_seen(self) -> None:
        from memory_fabric.conflicts import contradicts

        self.assertTrue(contradicts("billing-api listens on port 8443.",
                                    "billing-api listens on port 8554."))
