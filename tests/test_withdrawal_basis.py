"""Why a memory was withdrawn, and why the store insists on knowing.

This is a product change traceable to a measurement. Phase A put the obvious
rule — withdraw whatever was in context when an episode failed — on a real task
and found it cut the rate at which a *correct* memory reached the prompt from 60%
of episodes to 18%. Actions are shared between situations, so the memory that
asserted what the agent wrongly said was usually a correct memory about a
different situation. Agreement with a mistake is not evidence of having caused
it.

The lifecycle makes withdrawal a single command, and nothing used to distinguish
a credential finding from a coincidence. Now the basis is recorded, a missing one
is recorded as `unstated` rather than guessed at, and both weak bases are
surfaced to a human instead of being presented as equivalent to evidence.
"""

from __future__ import annotations

import unittest

from amberlog import (
    WEAK_BASES,
    LifecycleState,
    Amberlog,
    WithdrawalBasis,
)
from amberlog.events import EventType, lifecycle_changed
from amberlog.observability import report


def store(**kwargs) -> Amberlog:
    return Amberlog(":memory:", **kwargs)


class TestBasisIsRecorded(unittest.TestCase):
    def setUp(self) -> None:
        self.fabric = store()
        self.addCleanup(self.fabric.close)
        self.memory_id = self.fabric.remember("agent-a", "a durable note")
        self.fabric.validate(self.memory_id, actor="supervisor")

    def test_a_stated_basis_is_kept(self) -> None:
        self.fabric.quarantine(
            self.memory_id,
            reason="contradicted by a verified reading",
            actor="safety",
            basis=WithdrawalBasis.CONTRADICTED,
        )
        self.assertEqual(
            self.fabric.state.withdrawal_basis[self.memory_id],
            WithdrawalBasis.CONTRADICTED.value,
        )

    def test_a_string_basis_works_too(self) -> None:
        """Callers outside this package pass strings, and the CLI passes the
        choice argparse gave it."""
        self.fabric.quarantine(
            self.memory_id, reason="r", actor="a", basis="operator_judgement"
        )
        self.assertEqual(
            self.fabric.state.withdrawal_basis[self.memory_id], "operator_judgement"
        )

    def test_an_omitted_basis_becomes_unstated_not_empty(self) -> None:
        """"Nobody said" is a fact worth keeping, and it is not the same fact as
        "nobody was asked"."""
        self.fabric.quarantine(self.memory_id, reason="felt wrong", actor="operator")
        self.assertEqual(
            self.fabric.state.withdrawal_basis[self.memory_id],
            WithdrawalBasis.UNSTATED.value,
        )
        self.assertIn(WithdrawalBasis.UNSTATED, WEAK_BASES)

    def test_it_survives_a_rebuild(self) -> None:
        """The event log is the source of truth, so a projection that holds this
        only in memory would lose it on restart."""
        self.fabric.quarantine(
            self.memory_id, reason="r", actor="a",
            basis=WithdrawalBasis.CONTRASTIVE_HARM,
        )
        self.fabric.rebuild()
        self.assertEqual(
            self.fabric.state.withdrawal_basis[self.memory_id],
            WithdrawalBasis.CONTRASTIVE_HARM.value,
        )

    def test_a_release_leaves_the_basis_readable(self) -> None:
        """Deciding whether a withdrawal was justified is a question asked after
        the release, so clearing it on release would delete the evidence."""
        self.fabric.quarantine(
            self.memory_id, reason="r", actor="a", basis=WithdrawalBasis.CO_OCCURRENCE
        )
        self.fabric.release(self.memory_id, actor="reviewer")
        self.assertEqual(
            self.fabric.get(self.memory_id).lifecycle_state, LifecycleState.CANDIDATE
        )
        self.assertEqual(
            self.fabric.state.withdrawal_basis[self.memory_id],
            WithdrawalBasis.CO_OCCURRENCE.value,
        )


class TestGovernancePathsStateTheirOwn(unittest.TestCase):
    def test_the_firewall_quarantines_on_sensitive_data(self) -> None:
        """The firewall's own withdrawal is the strong case — a finding about the
        memory — and it should not be lumped in with coincidence."""
        fabric = store()
        self.addCleanup(fabric.close)
        memory_id = fabric.remember(
            "agent-a", "deploy with AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE"
        )
        self.assertEqual(
            fabric.get(memory_id).lifecycle_state, LifecycleState.QUARANTINED
        )
        self.assertEqual(
            fabric.state.withdrawal_basis[memory_id],
            WithdrawalBasis.SENSITIVE_DATA.value,
        )


class TestAttentionFlagsWeakWithdrawals(unittest.TestCase):
    def _item(self, fabric: Amberlog, memory_id: str):
        return next(
            (i for i in report.attention(fabric) if i.memory_id == memory_id), None
        )

    def test_a_weak_basis_makes_the_withdrawal_the_finding(self) -> None:
        fabric = store()
        self.addCleanup(fabric.close)
        memory_id = fabric.remember("agent-a", "a note about E01")
        fabric.validate(memory_id, actor="supervisor")
        fabric.quarantine(
            memory_id,
            reason="in context when an episode failed",
            actor="auto",
            basis=WithdrawalBasis.CO_OCCURRENCE,
        )

        item = self._item(fabric, memory_id)
        self.assertIsNotNone(item)
        self.assertEqual(item.kind, "withdrawn_on_weak_evidence")
        self.assertIn("agreement, not causation", item.detail)
        # The suggested action is to undo it, because the withdrawal is what is
        # in question.
        self.assertIn("release", item.action)

    def test_a_strong_basis_reads_as_an_ordinary_review(self) -> None:
        fabric = store()
        self.addCleanup(fabric.close)
        memory_id = fabric.remember("agent-a", "a note about E02")
        fabric.validate(memory_id, actor="supervisor")
        fabric.quarantine(
            memory_id, reason="contradicted by telemetry", actor="safety",
            basis=WithdrawalBasis.CONTRADICTED,
        )

        item = self._item(fabric, memory_id)
        self.assertEqual(item.kind, "quarantined")
        self.assertIn("contradicted", item.detail)
        self.assertNotIn("agreement, not causation", item.detail)

    def test_both_surfaces_read_the_same_basis(self) -> None:
        """The CLI and the dashboard share one read model, so they cannot tell
        different stories about why something was withdrawn."""
        fabric = store()
        self.addCleanup(fabric.close)
        memory_id = fabric.remember("agent-a", "a note about E03")
        fabric.validate(memory_id, actor="supervisor")
        fabric.quarantine(
            memory_id, reason="r", actor="a", basis=WithdrawalBasis.OPERATOR_JUDGEMENT
        )

        row = next(r for r in report.memory_rows(fabric) if r.id == memory_id)
        self.assertEqual(row.withdrawal_basis, WithdrawalBasis.OPERATOR_JUDGEMENT.value)

    def test_a_memory_never_withdrawn_has_no_basis(self) -> None:
        fabric = store()
        self.addCleanup(fabric.close)
        memory_id = fabric.remember("agent-a", "an untroubled note")
        fabric.validate(memory_id, actor="supervisor")
        row = next(r for r in report.memory_rows(fabric) if r.id == memory_id)
        self.assertIsNone(row.withdrawal_basis)


class TestOldLogsStillReplay(unittest.TestCase):
    """VERSIONING.md's guarantee: any event written by a released version
    replays on every later version of the same major series. `basis` is
    additive, so a 0.2.0 log has lifecycle events without it."""

    def test_a_lifecycle_event_without_a_basis_replays(self) -> None:
        fabric = store()
        self.addCleanup(fabric.close)
        memory_id = fabric.remember("agent-a", "written by an older version")
        fabric.validate(memory_id, actor="supervisor")

        # Exactly what 0.2.0 wrote: no `basis` key in the payload at all.
        event = lifecycle_changed(
            ts=fabric.now(),
            memory_id=memory_id,
            from_state=LifecycleState.ACTIVE.value,
            to_state=LifecycleState.QUARANTINED.value,
            reason="an old withdrawal",
            actor="operator",
        )
        self.assertEqual(event.type, EventType.LIFECYCLE_CHANGED)
        self.assertNotIn("basis", event.payload)

        fabric.log.append(event)
        fabric.rebuild()

        self.assertEqual(
            fabric.get(memory_id).lifecycle_state, LifecycleState.QUARANTINED
        )
        # Read back as `unstated`, which is the truthful answer about an event
        # that never carried one.
        self.assertEqual(
            fabric.state.withdrawal_basis[memory_id], WithdrawalBasis.UNSTATED.value
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
