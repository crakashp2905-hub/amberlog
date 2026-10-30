"""The background memory manager runs the store's maintenance on its own, safely."""

from __future__ import annotations

import json
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from memory_fabric import MemoryFabric
from memory_fabric.federation import offer
from memory_fabric.governance.firewall import (Firewall, rule_capabilities_must_be_granted,
                                               rule_must_be_active, rule_restricted_stays_private)
from memory_fabric.governance.retention import RetentionPolicy
from memory_fabric.manager import MemoryManager, findings, last_run
from memory_fabric.model import LifecycleState, Scope
from memory_fabric.transport import InProcessTransport, PeerRegistry

DAY_S = 86_400.0


def permissive() -> Firewall:
    return Firewall(rules=(rule_restricted_stays_private, rule_must_be_active,
                           rule_capabilities_must_be_granted))


class Clock:
    def __init__(self) -> None:
        self.t = time.time()

    def __call__(self) -> float:
        return self.t


class Leadership(unittest.TestCase):
    def test_one_manager_leads_and_another_takes_over_when_it_stops(self) -> None:
        f = MemoryFabric(":memory:")
        self.addCleanup(f.close)
        clock = Clock()
        a = MemoryManager(f, interval_s=10, holder="a", clock=clock)
        b = MemoryManager(f, interval_s=10, holder="b", clock=clock)
        self.assertTrue(a.run_once().leader)
        self.assertFalse(b.run_once().leader, "a's lease is still live")
        self.assertTrue(a.run_once().leader, "the holder renews")
        clock.t += 31  # past three intervals: a has stopped renewing
        self.assertTrue(b.run_once().leader)
        self.assertFalse(a.run_once().leader)


class Isolation(unittest.TestCase):
    def test_a_failing_task_backs_off_and_the_others_still_run(self) -> None:
        f = MemoryFabric(":memory:")
        self.addCleanup(f.close)
        manager = MemoryManager(f, interval_s=1, holder="m")

        def broken(since: int) -> dict:
            raise RuntimeError("disk on fire")

        manager._task_audit = broken  # type: ignore[method-assign]
        first = manager.run_once().tasks
        self.assertIn("disk on fire", first["audit"]["error"])
        self.assertIn("seq", first["checkpoint"], "the other tasks ran")
        second = manager.run_once().tasks
        self.assertIn("skipped", second["audit"], "backing off")
        self.assertEqual(last_run(f)["tasks"]["audit"], second["audit"], "every cycle is logged")


class Retention(unittest.TestCase):
    def test_deletions_wait_for_the_owners_opt_in(self) -> None:
        clock = Clock()
        f = MemoryFabric(":memory:", retention=RetentionPolicy(deprecated_grace_days=1))
        self.addCleanup(f.close)
        m = f.remember("ana", "an old note nobody needs", auto_activate=True)
        f.forget(m, reason="superseded", actor="op")
        f.now = lambda: int((clock.t + 10 * DAY_S) * 1000)  # type: ignore[method-assign]
        report = MemoryManager(f, holder="m", clock=clock).run_once().tasks["retention"]
        self.assertEqual(report["deletions_waiting_for_opt_in"], 1)
        self.assertIs(f.get(m).lifecycle_state, LifecycleState.DEPRECATED)
        MemoryManager(f, holder="m", clock=clock, allow_delete=True).run_once()
        self.assertIs(f.get(m).lifecycle_state, LifecycleState.DELETED)


class Delivery(unittest.TestCase):
    def test_owed_retractions_are_delivered_without_anyone_running_the_dispatcher(self) -> None:
        origin, peer = (MemoryFabric(":memory:", firewall=permissive(), auto_activate=True)
                        for _ in range(2))
        self.addCleanup(origin.close)
        self.addCleanup(peer.close)
        mid = origin.remember("ana", "valve A runs at 4 bar", scope="team")
        origin.share(mid, Scope.FEDERATED, actor="op")
        copy = offer(origin, mid, peer, recipient_agent="x", activate=True).imported_memory_id
        origin.request_retraction(mid, reason="wrong", recipients=[peer.store_id], actor="op")
        transport = InProcessTransport({peer.store_id: peer}, registry=PeerRegistry())
        manager = MemoryManager(origin, interval_s=0.05, holder="m", transport=transport).start()
        self.addCleanup(manager.stop)
        deadline = time.time() + 10
        while time.time() < deadline and peer.get(copy).lifecycle_state is LifecycleState.ACTIVE:
            time.sleep(0.05)
            peer.refresh()
        self.assertIs(peer.get(copy).lifecycle_state, LifecycleState.QUARANTINED)


class Findings(unittest.TestCase):
    def test_conflicts_and_checkpoints_are_recorded_for_a_person(self) -> None:
        with TemporaryDirectory() as tmp:
            f = MemoryFabric(":memory:", auto_activate=True)
            self.addCleanup(f.close)
            f.remember("tech", "At site North, protocol P7 runs the centrifuge at 4000 rpm.")
            f.remember("mallory", "Protocol P7 at site North: the centrifuge setting is 3500 rpm.")
            MemoryManager(f, holder="m", checkpoint_dir=tmp).run_once()
            kinds = [x["kind"] for x in findings(f)]
            self.assertIn("conflict", kinds)
            written = list(Path(tmp).glob("*.checkpoint.jsonl"))
            self.assertEqual(len(written), 1)
            self.assertIn("chain_digest", json.loads(written[0].read_text().splitlines()[-1]))


class Doctor(unittest.TestCase):
    def test_a_stopped_manager_is_reported(self) -> None:
        from memory_fabric.cli import _check_manager

        f = MemoryFabric(":memory:")
        self.addCleanup(f.close)
        self.assertEqual(_check_manager(f).status, "ok", "never run: manual, not broken")
        MemoryManager(f, holder="m").run_once()
        self.assertEqual(_check_manager(f).status, "ok")
        real_now = f.now
        f.now = lambda: real_now() + 2 * 3600 * 1000  # type: ignore[method-assign]
        self.assertEqual(_check_manager(f).status, "warn")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
