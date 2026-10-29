"""The log is the source of truth, so its guarantees are tested first."""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from amberlog.eventlog import EventLog
from amberlog.events import Event
from amberlog.ids import UlidFactory, new_ulid, ulid_time_ms


class TestUlid(unittest.TestCase):
    def test_sorts_by_time(self) -> None:
        clock = [1000]
        factory = UlidFactory(time_ms=lambda: clock[0], randbits=lambda n: 0)
        first = factory.new()
        clock[0] = 2000
        second = factory.new()
        self.assertLess(first, second)

    def test_monotonic_within_one_millisecond(self) -> None:
        factory = UlidFactory(time_ms=lambda: 42, randbits=lambda n: 0)
        ids = [factory.new() for _ in range(100)]
        self.assertEqual(ids, sorted(ids))
        self.assertEqual(len(set(ids)), 100)

    def test_encodes_timestamp(self) -> None:
        factory = UlidFactory(time_ms=lambda: 1_700_000_000_000, randbits=lambda n: 0)
        self.assertEqual(ulid_time_ms(factory.new()), 1_700_000_000_000)

    def test_length(self) -> None:
        self.assertEqual(len(new_ulid()), 26)


class TestEventLog(unittest.TestCase):
    def setUp(self) -> None:
        self.log = EventLog(":memory:")

    def tearDown(self) -> None:
        self.log.close()

    def _event(self, kind: str = "T", ts: int = 1) -> Event:
        return Event(type=kind, ts=ts, payload={"k": kind})

    def test_append_assigns_increasing_seq(self) -> None:
        a = self.log.append(self._event("A"))
        b = self.log.append(self._event("B"))
        self.assertEqual(a.seq, 1)
        self.assertEqual(b.seq, 2)
        self.assertEqual(self.log.head_seq, 2)

    def test_replay_preserves_order_and_payload(self) -> None:
        self.log.append_many([self._event(k) for k in "ABCDE"])
        replayed = list(self.log.read())
        self.assertEqual([e.type for e in replayed], list("ABCDE"))
        self.assertEqual([e.payload["k"] for e in replayed], list("ABCDE"))

    def test_read_since_is_exclusive(self) -> None:
        self.log.append_many([self._event(k) for k in "ABC"])
        self.assertEqual([e.type for e in self.log.read(since_seq=1)], ["B", "C"])

    def test_updates_are_rejected(self) -> None:
        self.log.append(self._event("A"))
        with self.assertRaises(sqlite3.IntegrityError):
            self.log._conn.execute("UPDATE events SET type = 'X' WHERE seq = 1")

    def test_deletes_are_rejected(self) -> None:
        self.log.append(self._event("A"))
        with self.assertRaises(sqlite3.IntegrityError):
            self.log._conn.execute("DELETE FROM events WHERE seq = 1")

    def test_duplicate_event_id_is_rejected(self) -> None:
        event = self._event("A")
        self.log.append(event)
        with self.assertRaises(sqlite3.IntegrityError):
            self.log.append(event)

    def test_append_many_is_atomic(self) -> None:
        good = self._event("A")
        duplicate = Event(type="B", ts=1, payload={}, event_id=good.event_id)
        with self.assertRaises(sqlite3.IntegrityError):
            self.log.append_many([good, duplicate])
        # Neither event landed: a partial batch would break replay.
        self.assertEqual(len(self.log), 0)

    def test_survives_reopen(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "nested" / "events.db"
            log = EventLog(path)
            log.append_many([self._event(k) for k in "ABC"])
            log.close()

            reopened = EventLog(path)
            self.assertEqual([e.type for e in reopened.read()], list("ABC"))
            reopened.close()

    def test_read_by_episode_and_type(self) -> None:
        self.log.append(Event(type="X", ts=1, episode_id="ep1"))
        self.log.append(Event(type="Y", ts=2, episode_id="ep1"))
        self.log.append(Event(type="X", ts=3, episode_id="ep2"))
        self.assertEqual(len(self.log.read_episode("ep1")), 2)
        self.assertEqual(len(self.log.read_types(["X"])), 2)


if __name__ == "__main__":
    unittest.main()
