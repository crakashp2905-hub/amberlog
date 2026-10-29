"""S6: no window between verifying an action's evidence and the action's side effect."""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from amberlog import Amberlog
from amberlog.actions import (ALREADY_EXECUTED, EXECUTED, FAILED, REFUSED, TIMED_OUT,
                                   ActionGate, ActionPolicy, ToolRule, unfenced_changes)
from amberlog.events import EventType
from amberlog.model import LifecycleState

ROOT = Path(__file__).resolve().parents[1]


def gate_for(fabric: Amberlog) -> ActionGate:
    return ActionGate(fabric, ActionPolicy(tools={"open_valve": ToolRule("open_valve")},
                                           grants={"ops": frozenset({"open_valve"})}))


class Fence(unittest.TestCase):
    def setUp(self) -> None:
        self.f = Amberlog(":memory:", auto_activate=True)
        self.addCleanup(self.f.close)
        self.m = self.f.remember("ana", "valve 7 is safe to open below 4 bar", scope="team")
        self.cert = self.f.certify("open-7", [self.m], "ops")
        self.gate = gate_for(self.f)
        self.effects: list[str] = []

    def tool(self, key: str) -> str:
        self.effects.append(key)
        return "opened"

    def test_it_runs_once_and_records_the_run(self) -> None:
        first = self.gate.execute("open_valve", "ops", self.tool, self.cert, key="k1")
        self.assertEqual((first.outcome, first.result, first.fenced), (EXECUTED, "opened", True))
        again = self.gate.execute("open_valve", "ops", self.tool, self.cert, key="k1")
        self.assertEqual(again.outcome, ALREADY_EXECUTED)
        self.assertEqual(self.effects, ["k1"])

    def test_withdrawn_evidence_stops_it_before_the_side_effect(self) -> None:
        self.f.quarantine(self.m, reason="wrong", actor="op")
        result = self.gate.execute("open_valve", "ops", self.tool, self.cert, key="k2")
        self.assertEqual(result.outcome, REFUSED)
        self.assertEqual(self.effects, [])

    def test_an_ungranted_agent_never_runs(self) -> None:
        result = self.gate.execute("open_valve", "mallory", self.tool, self.cert, key="k3")
        self.assertEqual(result.outcome, REFUSED)
        self.assertEqual(self.effects, [])

    def test_an_ungranted_agent_with_its_own_valid_certificate_is_refused_for_the_grant(self) -> None:
        """Refused because the tool is not granted, not because the certificate names someone else.

        `test_an_ungranted_agent_never_runs` uses another agent's certificate,
        so it is refused by the certificate check even with no grant check at
        all (found by tools/mutation_check.py).
        """
        from amberlog.actions import TOOL_NOT_GRANTED

        own = self.f.certify("open-7", [self.m], "mallory")
        decision = self.gate.authorize("open_valve", "mallory", own)
        self.assertEqual(decision.reason_code, TOOL_NOT_GRANTED)
        result = self.gate.execute("open_valve", "mallory", self.tool, own, key="k-own")
        self.assertEqual((result.outcome, self.effects), (REFUSED, []))

    def test_a_concurrent_retraction_waits_for_the_action(self) -> None:
        marks: dict[str, float] = {}

        # perf_counter, not monotonic: on Python 3.12 for Windows monotonic
        # ticks every 15.6 ms, and a withdrawal that commits just after the
        # fence lands in the same tick (found on the RC's Postgres run).
        def slow(key: str) -> None:
            time.sleep(0.3)
            marks["effect"] = time.perf_counter()

        def retract() -> None:
            time.sleep(0.05)  # starts while the tool is running
            marks["retract_started"] = time.perf_counter()
            self.f.quarantine(self.m, reason="wrong", actor="op")

        other = threading.Thread(target=retract)
        other.start()
        result = self.gate.execute("open_valve", "ops", slow, self.cert, key="k4", lease_s=2.0)
        other.join()
        self.assertEqual(result.outcome, EXECUTED)
        self.assertLess(marks["retract_started"], marks["effect"],
                        "the withdrawal was attempted while the tool was running")
        # The authoritative order is the log's: the fenced run committed first.
        log = self.f.log.read_types([EventType.ACTION_EXECUTED, EventType.LIFECYCLE_CHANGED])
        executed = next(e.seq for e in log if e.type == EventType.ACTION_EXECUTED)
        withdrawn = next(e.seq for e in log if e.type == EventType.LIFECYCLE_CHANGED
                         and e.payload.get("memory_id") == self.m
                         and e.payload.get("to") == "quarantined")
        self.assertLess(executed, withdrawn, "the withdrawal committed only after the action")
        self.assertEqual(unfenced_changes(self.f), [])

    def test_an_overrun_releases_the_fence_and_is_recorded(self) -> None:
        release = threading.Event()

        def hung(key: str) -> None:
            release.wait(5)

        result = self.gate.execute("open_valve", "ops", hung, self.cert, key="k5", lease_s=0.2)
        self.assertEqual((result.outcome, result.fenced), (TIMED_OUT, False))
        self.f.quarantine(self.m, reason="wrong", actor="op")  # not blocked any more
        release.set()
        changes = unfenced_changes(self.f)
        self.assertEqual([(c["key"], c["memory_id"]) for c in changes], [("k5", self.m)])

    def test_an_unknown_outcome_needs_an_explicit_retry_that_re_verifies(self) -> None:
        def broken(key: str) -> None:
            raise RuntimeError("valve controller unreachable")

        first = self.gate.execute("open_valve", "ops", broken, self.cert, key="k6")
        self.assertEqual(first.outcome, FAILED)
        self.assertIn("unreachable", first.error or "")
        blocked = self.gate.execute("open_valve", "ops", self.tool, self.cert, key="k6")
        self.assertEqual(blocked.outcome, REFUSED)
        self.assertIn("retry_required", blocked.error or "")
        self.f.quarantine(self.m, reason="wrong", actor="op")
        retried = self.gate.execute("open_valve", "ops", self.tool, self.cert, key="k6",
                                    retry=True)
        self.assertEqual(retried.outcome, REFUSED, "the retry verified afresh")
        self.assertEqual(self.effects, [])

    def test_the_lease_stays_below_the_busy_timeout(self) -> None:
        with self.assertRaises(ValueError):
            self.gate.execute("open_valve", "ops", self.tool, self.cert, key="k7", lease_s=10)


def _shared_store_path(tmp: str) -> str:
    """A store two processes can open: a file, or a fresh Postgres schema.

    On Postgres the fence is `LOCK TABLE events IN EXCLUSIVE MODE` rather than
    SQLite's `BEGIN IMMEDIATE`, so the cross-process claim has to be tested on
    both, not inferred from one.
    """
    url = os.environ.get("MF_TEST_POSTGRES_URL")
    if not url:
        return str(Path(tmp) / "store.db")
    import uuid

    import psycopg

    schema = f"mf_fence_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute(f"CREATE SCHEMA {schema}")
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}options=-csearch_path%3D{schema}"


class AcrossProcesses(unittest.TestCase):
    def test_a_writer_in_another_process_waits_for_the_action(self) -> None:
        with TemporaryDirectory() as tmp:
            path = _shared_store_path(tmp)
            f = Amberlog(path, auto_activate=True)
            try:
                m = f.remember("ana", "valve 7 is safe to open below 4 bar", scope="team")
                cert = f.certify("open-7", [m], "ops")
                marks: dict[str, float] = {}
                child = subprocess.Popen(
                    [sys.executable, "-c",
                     "import sys, time; from amberlog import Amberlog; "
                     "f = Amberlog(sys.argv[1]); print('ready', flush=True); "
                     "sys.stdin.readline(); f.quarantine(sys.argv[2], reason='wrong', actor='op'); "
                     "print(time.time(), flush=True); f.close()", path, m],
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, cwd=ROOT)
                assert child.stdout is not None and child.stdin is not None
                self.assertEqual(child.stdout.readline().strip(), "ready")

                def slow(key: str) -> None:
                    child.stdin.write("go\n")  # the other process starts its write now
                    child.stdin.flush()
                    time.sleep(0.5)
                    marks["effect"] = time.time()

                result = gate_for(f).execute("open_valve", "ops", slow, cert, key="x1",
                                             lease_s=3.0)
                retracted_at = float(child.stdout.readline())
                child.wait(30)
                child.stdin.close()
                child.stdout.close()
                self.assertEqual(result.outcome, EXECUTED)
                self.assertLessEqual(marks["effect"], retracted_at)
                f.refresh()
                self.assertIs(f.get(m).lifecycle_state, LifecycleState.QUARANTINED)
                log = f.log.read_types([EventType.ACTION_EXECUTED, EventType.LIFECYCLE_CHANGED])
                executed = next(e.seq for e in log if e.type == EventType.ACTION_EXECUTED)
                withdrawn = next(e.seq for e in log if e.type == EventType.LIFECYCLE_CHANGED
                                 and e.payload.get("memory_id") == m
                                 and e.payload.get("to") == "quarantined")
                self.assertLess(executed, withdrawn, "the other process committed after the action")
            finally:
                f.close()


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
