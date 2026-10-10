"""`memory-fabric doctor` — and whether it can tell a broken store from a sound one.

A health check that only ever reports health is worse than no health check,
because it is read as evidence. So every test here breaks something specific
and asserts that the matching check turns red — and, as importantly, that the
*other* checks do not, since a doctor that fails everything whenever anything
is wrong tells an operator nothing about where to look.

`doctor` is deliberately a different question from `attention`. That one asks
"what in this knowledge base needs a human?"; this one asks "is this
installation sound enough that its answers can be believed?". A store can be
perfectly sound and full of memories needing review, or hold nothing worth
reviewing while its append-only triggers are gone.
"""

from __future__ import annotations

import json
import sqlite3
import unittest
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from memory_fabric import MemoryFabric
from memory_fabric.cli import main
from memory_fabric.model import MemoryType, WithdrawalBasis


class DoctorTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.path = Path(self._tmp.name) / "store.db"
        fabric = MemoryFabric(self.path)
        self.memory_id = fabric.remember(
            agent_id="a",
            content="valve 7 is upstream of the pump",
            type=MemoryType.SEMANTIC,
            auto_activate=True,
        )
        fabric.close()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _run(self) -> tuple[int, dict]:
        buffer = StringIO()
        with patch("sys.stdout", buffer):
            code = main(["--json", "--db", str(self.path), "doctor"])
        return code, json.loads(buffer.getvalue())

    def _events(self) -> list[tuple]:
        # Closed explicitly: an open handle keeps a Windows file locked and the
        # temporary directory then fails to clean up, which reads as a test
        # failure in whichever test happens to run last.
        conn = sqlite3.connect(self.path)
        try:
            return conn.execute(
                "SELECT seq, ts, event_id FROM events ORDER BY seq"
            ).fetchall()
        finally:
            conn.close()

    def _status(self, report: dict, name: str) -> str:
        for finding in report["findings"]:
            if finding["name"] == name:
                return finding["status"]
        raise AssertionError(f"no check named {name!r}")

    # --- the sound case --------------------------------------------------

    def test_a_sound_store_passes_every_check(self) -> None:
        code, report = self._run()
        self.assertEqual(code, 0)
        self.assertTrue(report["sound"])
        self.assertEqual(
            [f["name"] for f in report["findings"] if f["status"] != "ok"], []
        )

    def test_the_probe_does_not_modify_the_log(self) -> None:
        """The append-only check writes, on purpose, and must roll back.

        A probe that committed on success would modify the event log of exactly
        the store it had just found unprotected.
        """
        before = self._events()
        self._run()
        self.assertEqual(before, self._events())

    # --- the broken cases ------------------------------------------------

    def test_a_dropped_trigger_is_restored_on_open(self) -> None:
        """Dropping a trigger does not survive the next open, and the check
        reports the state it actually found.

        Worth pinning down, because it bounds what the append-only check can
        tell anyone: `EventLog` creates both triggers `IF NOT EXISTS` on every
        open, so a store opened by this code is protected whatever was done to
        it while closed. What the check still catches is a build or a replica
        where that recreation did not happen — and the behavioural probe is the
        half that can tell protection from the mere presence of a trigger.
        """
        conn = sqlite3.connect(self.path)
        try:
            with conn:
                conn.execute("DROP TRIGGER events_no_update")
            self.assertEqual(
                conn.execute(
                    "SELECT count(*) FROM sqlite_master WHERE type = 'trigger'"
                ).fetchone()[0],
                1,
            )
        finally:
            conn.close()

        code, report = self._run()
        self.assertEqual(code, 0)
        self.assertEqual(self._status(report, "append-only enforcement"), "ok")
        self.assertEqual(self._events()[0][0], 1)

    def test_a_missing_trigger_is_a_failure(self) -> None:
        """The check itself, against a store whose protection is really absent.

        Driven directly rather than through a file, because `EventLog` restores
        the triggers on open and so no on-disk store can reach the CLI in this
        state. A check nobody can reach is still worth testing: the condition it
        describes is reachable through a tampered build or a replica opened by
        something other than this code, and an untested branch in a health
        check is a branch that reports the wrong thing when it finally fires.
        """
        from memory_fabric.cli import _check_append_only

        fabric = MemoryFabric(self.path)
        try:
            fabric.log._conn.execute("DROP TRIGGER events_no_update")
            fabric.log._conn.execute("DROP TRIGGER events_no_delete")
            fabric.log._conn.commit()
            finding = _check_append_only(fabric)
            self.assertEqual(finding.status, "fail")
            self.assertIn("events_no_update", finding.detail)
            self.assertIn("events_no_delete", finding.detail)
        finally:
            fabric.close()

    def test_a_log_from_a_newer_version_is_a_failure(self) -> None:
        """Events this install does not understand are skipped silently.

        Which is the right behaviour for forward compatibility and the wrong
        thing to do without telling anyone.
        """
        conn = sqlite3.connect(self.path)
        try:
            with conn:
                conn.execute("DROP TRIGGER events_no_update")
                conn.execute("UPDATE events SET schema_version = '9.0.0'")
                conn.execute(
                    "CREATE TRIGGER events_no_update BEFORE UPDATE ON events "
                    "BEGIN SELECT RAISE(ABORT, 'append-only'); END"
                )
        finally:
            conn.close()

        code, report = self._run()
        self.assertEqual(code, 5)
        self.assertEqual(self._status(report, "schema version"), "fail")

    def test_a_failed_retraction_delivery_is_a_failure(self) -> None:
        """The one guarantee the research supported is the one that rots quietly.

        Nothing raises when a retraction gives up: the origin's own copy is
        withdrawn, the local store looks right, and the recipient goes on
        exposing knowledge that was withdrawn hours ago.
        """
        fabric = MemoryFabric(self.path)
        fabric.request_retraction(
            self.memory_id, reason="contradicted",
            recipients=["st_unreachable"], basis=WithdrawalBasis.CONTRADICTED,
        )
        fabric.log._conn.execute("UPDATE outbox SET state = 'failed'")
        fabric.log._conn.commit()
        fabric.close()

        code, report = self._run()
        self.assertEqual(code, 5)
        self.assertEqual(self._status(report, "retraction delivery"), "fail")

    def test_a_retrying_retraction_is_a_warning_not_a_failure(self) -> None:
        """A recipient restarting is not a broken installation."""
        fabric = MemoryFabric(self.path)
        fabric.request_retraction(
            self.memory_id, reason="contradicted",
            recipients=["st_slow"], basis=WithdrawalBasis.CONTRADICTED,
        )
        fabric.log._conn.execute("UPDATE outbox SET state = 'retrying', attempts = 2")
        fabric.log._conn.commit()
        fabric.close()

        code, report = self._run()
        self.assertEqual(code, 1)
        self.assertTrue(report["sound"])
        self.assertEqual(self._status(report, "retraction delivery"), "warn")

    def test_a_withdrawal_on_a_weak_basis_is_a_warning(self) -> None:
        """PA′ measured this: of naive blame's 87 withdrawals, 57 were about a
        completely different fault. So the finding points at *releasing* the
        memory, and it is a warning rather than a failure because the store
        itself is working exactly as designed."""
        fabric = MemoryFabric(self.path)
        fabric.quarantine(
            self.memory_id, reason="in context when the episode failed",
            actor="operator", basis=WithdrawalBasis.CO_OCCURRENCE,
        )
        fabric.close()

        code, report = self._run()
        self.assertEqual(code, 1)
        self.assertEqual(self._status(report, "withdrawal evidence"), "warn")

    def test_no_check_crashes_against_a_populated_store(self) -> None:
        """The warn-on-exception path makes silent breakage possible.

        A check that calls a method with the wrong signature degrades to a
        warning naming the *function*, not the check — which is the honest
        thing to report and also very easy to not notice. This test found
        exactly that: `_check_blocked_not_exposed` passed an argument
        `Enforcer.check` does not take, and only a store with blocked memories
        in it reached the line. So the fixture has to be populated; an empty
        store exercises almost none of these branches.
        """
        from memory_fabric import cli
        from memory_fabric.demo import seed

        fabric = MemoryFabric(self.path)
        try:
            seed(fabric)
        finally:
            fabric.close()

        _, report = self._run()
        internal = {check.__name__ for check in cli.DOCTOR_CHECKS}
        crashed = [f for f in report["findings"] if f["name"] in internal]
        self.assertEqual(
            crashed, [], f"check(s) failed to run: {[f['detail'] for f in crashed]}"
        )
        self.assertEqual(len(report["findings"]), len(cli.DOCTOR_CHECKS))

    def test_a_multi_tenant_store_is_a_warning_even_when_the_boundary_holds(self) -> None:
        """One SQLite file holding several tenants is one blast radius.

        Reported as a warning rather than `ok` on purpose: the labels are
        enforced and the enforcement works, and an operator who believes that
        amounts to isolation against a compromised process should read it here
        rather than in an incident.
        """
        fabric = MemoryFabric(self.path, auto_activate=True)
        try:
            fabric.remember(
                agent_id="b", content="the east gate closes at 1800",
                type=MemoryType.SEMANTIC, tenant_id="tn_other",
            )
        finally:
            fabric.close()

        code, report = self._run()
        self.assertEqual(code, 1)
        self.assertTrue(report["sound"])
        self.assertEqual(self._status(report, "tenant isolation"), "warn")

    def test_a_cross_tenant_leak_is_a_failure(self) -> None:
        """The check itself, against an enforcement layer that does leak.

        Driven with a stubbed decision because the real one does not leak, and
        an untested branch in a health check is a branch that reports the wrong
        thing when it finally fires. The same reasoning as the missing-trigger
        case.
        """
        from memory_fabric.cli import _check_tenant_isolation
        from memory_fabric.enforcement import ACTIVE, AccessDecision, RiskLevel, Verdict

        fabric = MemoryFabric(self.path, auto_activate=True)
        try:
            fabric.remember(
                agent_id="b", content="the east gate closes at 1800",
                type=MemoryType.SEMANTIC, tenant_id="tn_other",
            )
            permissive = lambda memory_id, **kwargs: AccessDecision(  # noqa: E731
                memory_id=memory_id, version=1, verdict=Verdict.USABLE,
                reason_code=ACTIVE, risk=RiskLevel.LOW, integrity_revision=0,
            )
            with patch.object(fabric.enforcer, "check", permissive):
                finding = _check_tenant_isolation(fabric)
            self.assertEqual(finding.status, "fail")
            self.assertIn("readable from", finding.detail)
        finally:
            fabric.close()

    def test_a_check_that_cannot_run_is_never_reported_as_ok(self) -> None:
        """The honest outcome of "I could not tell" is a warning with the reason."""
        from memory_fabric import cli

        def exploding(fabric):
            raise RuntimeError("no idea")

        with patch.object(cli, "DOCTOR_CHECKS", (exploding,)):
            code, report = self._run()
        self.assertEqual(code, 1)
        self.assertEqual(len(report["findings"]), 1)
        self.assertEqual(report["findings"][0]["status"], "warn")
        self.assertIn("no idea", report["findings"][0]["detail"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
