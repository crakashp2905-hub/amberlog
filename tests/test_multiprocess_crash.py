"""Durability against real process death, not against a tidy close.

The deterministic fault matrix in `experiments/faultsim.py` simulates a crash by
closing a handle and opening the same file. That is a *clean* shutdown: SQLite
flushes, Python runs `finally` blocks and `atexit` hooks, and an open
transaction is rolled back politely. It exercises replay thoroughly and
durability not at all.

Here the crash is a child process calling `os._exit` — no handlers, no flush,
no close — at a named boundary, and the parent then opens the store and asks
what survived. The distinction matters because every claim in this project
about committed state rests on the database and not on the code's manners, and
the only way to tell those apart is to remove the manners.

Each test asserts one of two things, and which one is the interesting part:

* crashed **inside** a transaction → *nothing* survives, not a half of it;
* crashed **after** a commit → the whole intent survives and still converges.

The worker is `crashworker.py`, run as a script. Exit code 70 means it reached
its crash point; anything else means it failed for a reason the test did not
ask for, and the test fails rather than reading a crash it did not cause.
"""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from memory_fabric import LifecycleState, MemoryFabric
from memory_fabric.dispatcher import Dispatcher
from memory_fabric.governance.firewall import (
    Firewall,
    rule_capabilities_must_be_granted,
    rule_must_be_active,
    rule_restricted_stays_private,
)
from memory_fabric.protocol import PropagationState
from memory_fabric.transport import InProcessTransport

WORKER = Path(__file__).resolve().parent / "crashworker.py"
CRASHED = 70


def permissive() -> Firewall:
    return Firewall(
        rules=[
            rule_must_be_active,
            rule_restricted_stays_private,
            rule_capabilities_must_be_granted,
        ]
    )


class MultiProcessCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        self.origin_path = self.dir / "origin.db"
        self.alice_path = self.dir / "alice.db"
        self.bob_path = self.dir / "bob.db"

    # --- driving the child ----------------------------------------------

    def run_worker(self, scenario: str, *args: str, expect_crash: bool = True) -> str:
        result = subprocess.run(
            [sys.executable, str(WORKER), scenario, *args],
            capture_output=True,
            text=True,
            timeout=120,
        )
        expected = CRASHED if expect_crash else 0
        self.assertEqual(
            result.returncode,
            expected,
            f"{scenario}: expected exit {expected}, got {result.returncode}\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}",
        )
        return result.stdout.strip()

    def open(self, path: Path) -> MemoryFabric:
        fabric = MemoryFabric(path, firewall=permissive(), auto_activate=True)
        self.addCleanup(fabric.close)
        return fabric

    # --- fixtures built by child processes -------------------------------

    def seed_origin(self) -> str:
        return self.run_worker("seed", str(self.origin_path), expect_crash=False)

    def seed_chain(self) -> tuple[str, str, str]:
        """origin → alice → bob, each step in its own process.

        Built by children so no handle from this process is open when a later
        child dies — otherwise the parent's own connection would be doing the
        flushing and the test would be measuring the wrong process.
        """
        origin_memory = self.seed_origin()
        at_alice = self.run_worker(
            "share", str(self.origin_path), str(self.alice_path), expect_crash=False
        )
        at_bob = self.run_worker(
            "share", str(self.alice_path), str(self.bob_path), expect_crash=False
        )
        return origin_memory, at_alice, at_bob

    def store_ids(self) -> dict[str, str]:
        ids = {}
        for name, path in (
            ("origin", self.origin_path),
            ("alice", self.alice_path),
            ("bob", self.bob_path),
        ):
            if path.exists():
                fabric = MemoryFabric(path, firewall=permissive())
                try:
                    ids[name] = fabric.store_id
                finally:
                    fabric.close()
        return ids


class CrashInsideATransaction(MultiProcessCase):
    """Nothing survives, and "nothing" means not a half of it."""

    def test_a_retraction_killed_mid_transaction_leaves_no_trace(self) -> None:
        memory_id = self.seed_origin()
        ids = self.store_ids()
        self.run_worker(
            "crash_mid_retraction_transaction", str(self.origin_path), "st_anyone"
        )

        origin = self.open(self.origin_path)
        # Not withdrawn, nothing owed, no event. A memory withdrawn locally
        # with no record that recipients are owed anything is precisely what
        # invariant 3 exists to prevent.
        self.assertIs(origin.get(memory_id).lifecycle_state, LifecycleState.ACTIVE)
        self.assertEqual(origin.outbox.pending(), [])
        self.assertEqual(origin.retractions_since(-1), [])
        self.assertEqual(origin.store_id, ids["origin"], "identity survived the kill")

    def test_a_forwarding_commit_killed_mid_transaction_leaves_neither_half(self) -> None:
        """The Phase D claim, against a process that really died.

        The withdrawal and the onward obligation commit together. A withdrawal
        without the obligation would leave a live copy two hops out that
        nothing is tracking — and nothing would notice, because the upstream
        acknowledgement would truthfully report `enforced` about the one copy
        it was asked about.
        """
        _, at_alice, at_bob = self.seed_chain()
        ids = self.store_ids()

        origin = MemoryFabric(self.origin_path, firewall=permissive(), auto_activate=True)
        try:
            memory_id = next(
                mid for mid, m in origin.state.memories.items()
                if m.provenance.method.value != "imported"
            )
            origin.request_retraction(
                memory_id, reason="contradicted",
                recipients=[ids["alice"]], basis="contradicted",
            )
        finally:
            origin.close()

        self.run_worker(
            "crash_mid_forwarding_commit", str(self.alice_path), str(self.origin_path)
        )

        alice = self.open(self.alice_path)
        bob = self.open(self.bob_path)
        self.assertIs(
            alice.get(at_alice).lifecycle_state,
            LifecycleState.ACTIVE,
            "the withdrawal must not survive its own transaction",
        )
        self.assertEqual(
            alice.outbox.pending(), [], "nor may the onward obligation"
        )
        self.assertIs(bob.get(at_bob).lifecycle_state, LifecycleState.ACTIVE)

    def test_the_store_survives_a_kill_during_a_batch_of_writes(self) -> None:
        """A corrupted store would make every other guarantee untestable."""
        memory_id = self.seed_origin()
        self.run_worker("crash_mid_write", str(self.origin_path))

        origin = self.open(self.origin_path)
        self.assertIs(origin.get(memory_id).lifecycle_state, LifecycleState.ACTIVE)
        self.assertEqual(len(origin.state.memories), 1, "uncommitted writes are gone")
        # And the log still replays to the same state, which is the actual
        # integrity claim rather than "it opened".
        from memory_fabric.projections import Projection

        rebuilt = Projection.rebuild(origin.log, unsealer=origin._unseal_content)
        self.assertEqual(
            set(rebuilt.state.memories), set(origin.state.memories)
        )


class CrashAfterACommit(MultiProcessCase):
    """The whole intent survives, and still converges."""

    def test_a_committed_retraction_is_still_owed_after_a_kill(self) -> None:
        memory_id = self.seed_origin()
        _ = self.run_worker(
            "share", str(self.origin_path), str(self.alice_path), expect_crash=False
        )
        ids = self.store_ids()
        self.run_worker(
            "crash_after_retraction_commit", str(self.origin_path), ids["alice"]
        )

        origin = self.open(self.origin_path)
        self.assertIs(
            origin.get(memory_id).lifecycle_state, LifecycleState.QUARANTINED
        )
        owed = origin.outbox.pending()
        self.assertEqual([row.recipient for row in owed], [ids["alice"]])
        self.assertEqual(len(origin.retractions_since(-1)), 1)

    def test_it_converges_after_the_restart(self) -> None:
        """Durability is only interesting if the surviving intent still works."""
        self.seed_origin()
        at_alice = self.run_worker(
            "share", str(self.origin_path), str(self.alice_path), expect_crash=False
        )
        ids = self.store_ids()
        self.run_worker(
            "crash_after_retraction_commit", str(self.origin_path), ids["alice"]
        )

        origin = self.open(self.origin_path)
        alice = self.open(self.alice_path)
        transport = InProcessTransport(
            {origin.store_id: origin, alice.store_id: alice}
        )
        report = Dispatcher(origin, transport).drain()
        self.assertEqual(report.enforced, 1, report.errors)
        self.assertIs(
            alice.get(at_alice).lifecycle_state, LifecycleState.QUARANTINED
        )

    def test_a_lost_acknowledgement_converges_on_redelivery(self) -> None:
        """The recipient committed; the origin died before learning it.

        On restart the origin re-sends, the recipient deduplicates on event
        identity and returns its **first** outcome, and the origin records
        enforcement. At-least-once delivery plus idempotent processing is
        supposed to give exactly this, and here the acknowledgement was lost by
        a process that really died rather than by a stubbed error.
        """
        self.seed_origin()
        at_alice = self.run_worker(
            "share", str(self.origin_path), str(self.alice_path), expect_crash=False
        )
        ids = self.store_ids()

        origin = MemoryFabric(self.origin_path, firewall=permissive(), auto_activate=True)
        try:
            memory_id = next(iter(origin.state.memories))
            origin.request_retraction(
                memory_id, reason="contradicted",
                recipients=[ids["alice"]], basis="contradicted",
            )
        finally:
            origin.close()

        # Alice applies and commits, then dies before acknowledging.
        state = self.run_worker(
            "crash_after_recipient_applies", str(self.alice_path), str(self.origin_path)
        )
        self.assertEqual(state, PropagationState.ENFORCED.value)

        alice = self.open(self.alice_path)
        self.assertIs(
            alice.get(at_alice).lifecycle_state,
            LifecycleState.QUARANTINED,
            "the recipient's own commit survived",
        )

        origin = self.open(self.origin_path)
        self.assertEqual(
            len(origin.outbox.pending()), 1, "the origin still believes it is owed"
        )

        transport = InProcessTransport(
            {origin.store_id: origin, alice.store_id: alice}
        )
        report = Dispatcher(origin, transport).drain()
        self.assertEqual(report.enforced, 1, report.errors)
        self.assertEqual(origin.outbox.pending(), [])

        # One semantic effect despite two deliveries.
        applied = [
            event for event in alice.log.read()
            if event.type == "RetractionApplied"
        ]
        self.assertEqual(len(applied), 1)

    def test_repeated_kills_still_converge(self) -> None:
        """Three hard kills in a row, then convergence.

        A single crash can be survived by luck — a flush that happened to land.
        Repeating it at different boundaries is what distinguishes durability
        from a lucky interleaving.
        """
        self.seed_origin()
        at_alice = self.run_worker(
            "share", str(self.origin_path), str(self.alice_path), expect_crash=False
        )
        ids = self.store_ids()

        self.run_worker("crash_mid_retraction_transaction", str(self.origin_path), ids["alice"])
        self.run_worker("crash_mid_write", str(self.origin_path))
        self.run_worker("crash_after_retraction_commit", str(self.origin_path), ids["alice"])

        origin = self.open(self.origin_path)
        alice = self.open(self.alice_path)
        transport = InProcessTransport(
            {origin.store_id: origin, alice.store_id: alice}
        )
        Dispatcher(origin, transport).drain()
        self.assertIs(
            alice.get(at_alice).lifecycle_state, LifecycleState.QUARANTINED
        )
        self.assertEqual(origin.outbox.pending(), [])
        self.assertEqual(len(origin.state.memories), 1)


class TheIntegritySnapshotSurvives(MultiProcessCase):
    def test_unresolved_retractions_are_named_after_a_kill(self) -> None:
        """A restore that dropped pending retractions would reintroduce
        withdrawn knowledge with nothing downstream able to detect it."""
        self.seed_origin()
        self.run_worker(
            "share", str(self.origin_path), str(self.alice_path), expect_crash=False
        )
        ids = self.store_ids()
        self.run_worker(
            "crash_after_retraction_commit", str(self.origin_path), ids["alice"]
        )

        origin = self.open(self.origin_path)
        snapshot = origin.integrity_snapshot()
        self.assertEqual(len(snapshot["unresolved_retractions"]), 1)
        self.assertEqual(
            snapshot["unresolved_retractions"][0]["recipient"], ids["alice"]
        )
        self.assertTrue(snapshot["checksum"].startswith("sha256:"))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
