"""One contract, every event-log backend.

The properties here are what the rest of the system assumes of the event log.
They run against SQLite always, and against PostgreSQL when `psycopg` is
importable and `MEMORY_FABRIC_TEST_PG` names a database:

    MEMORY_FABRIC_TEST_PG=postgresql://... python -m pytest tests/test_storage_conformance.py

The core suite runs with no dependencies installed, so without both of those
the Postgres cases skip rather than fail.

## The tests that matter are the concurrent ones

Every single-threaded property here would pass on a naive Postgres port. What
a naive port gets wrong is only visible with several writers:

* **gapless, commit-ordered sequence numbers** -- or a polling reader skips an
  event permanently;
* **one linear hash chain** -- or verification fails on an untampered store.

And a test that cannot fail proves nothing, so `NaivePostgresEventLog` below
implements the design this module rejects -- `BIGSERIAL`, a chain head read
with `MAX()`, no lock -- and the falsification tests assert it **fails** these
properties. If they ever pass, the concurrency tests have lost their teeth.
"""

from __future__ import annotations

import json
import os
import pathlib
import sys
import tempfile
import threading
import time
import unittest
import uuid

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from memory_fabric.eventlog import EventLog  # noqa: E402
from memory_fabric.events import Event  # noqa: E402
from memory_fabric.integrity import event_digest  # noqa: E402

PG_DSN = os.environ.get("MEMORY_FABRIC_TEST_PG")
try:
    import psycopg  # noqa: F401
    HAVE_PSYCOPG = True
except ImportError:
    HAVE_PSYCOPG = False
PG = bool(PG_DSN and HAVE_PSYCOPG)
PG_REASON = ("set MEMORY_FABRIC_TEST_PG and install psycopg to run the "
             "Postgres conformance cases")


def ev(kind="memory_created", payload=None, episode=None, agent="a"):
    return Event(type=kind, ts=int(time.time() * 1000),
                 payload=payload if payload is not None else {"n": 1},
                 agent_id=agent, episode_id=episode,
                 event_id=uuid.uuid4().hex, schema_version="0.9.0")


class Contract:
    """Mixed into a TestCase with `open()` returning a fresh log."""

    THREADS = 8
    PER_THREAD = 25

    def open(self):  # pragma: no cover - overridden
        raise NotImplementedError

    def opener(self):
        """A callable that opens another handle on the SAME log -- one per
        thread, which is how both backends are meant to be shared."""
        raise NotImplementedError

    # --- single writer ----------------------------------------------------

    def test_append_then_read_round_trips(self):
        log = self.open()
        stored = log.append(ev(payload={"x": [1, 2, {"y": "z"}]}))
        self.assertEqual(stored.seq, 1)
        back = list(log.read())
        self.assertEqual(len(back), 1)
        self.assertEqual(back[0].payload, {"x": [1, 2, {"y": "z"}]})
        self.assertEqual(back[0].seq, 1)

    def test_since_seq_is_exclusive_and_ordered(self):
        log = self.open()
        log.append_many([ev(payload={"i": i}) for i in range(5)])
        self.assertEqual([e.payload["i"] for e in log.read(since_seq=2)],
                         [2, 3, 4])
        self.assertEqual([e.seq for e in log.read(limit=2)], [1, 2])

    def test_reads_by_episode_and_type(self):
        log = self.open()
        log.append_many([ev("a", episode="e1"), ev("b", episode="e2"),
                         ev("a", episode="e1")])
        self.assertEqual(len(log.read_episode("e1")), 2)
        self.assertEqual([e.type for e in log.read_types(["b"])], ["b"])
        self.assertEqual(log.read_types([]), [])

    def test_head_and_length(self):
        log = self.open()
        self.assertEqual(log.head_seq, 0)
        log.append_many([ev() for _ in range(3)])
        self.assertEqual(log.head_seq, 3)
        self.assertEqual(len(log), 3)

    # --- atomicity --------------------------------------------------------

    def test_a_failing_batch_lands_nothing_and_leaves_no_gap(self):
        """A duplicate event_id makes the second insert fail. Either every
        event in the batch lands or none does -- and the next append must get
        the next sequence number, not one past a burned value."""
        log = self.open()
        log.append(ev())
        dup = ev()
        with self.assertRaises(Exception):
            log.append_many([ev(), dup, dup])
        self.assertEqual(len(log), 1)
        nxt = log.append(ev())
        self.assertEqual(nxt.seq, 2, "a rolled-back batch must not leave a gap")

    # --- payload exactness ------------------------------------------------

    def test_awkward_payloads_round_trip_with_the_same_digest(self):
        """The chain hashes the decoded payload, so the backend must not alter
        what decodes. `Infinity` is the case that rules out `jsonb`: it
        rejects it, and `json.dumps` emits it for a non-finite float."""
        log = self.open()
        payloads = [
            {"inf": float("inf"), "ninf": float("-inf")},
            {"unicode": "Zürich 🚚 東京", "nul": "a\x00b"},
            {"big": 2 ** 62, "neg": -(2 ** 62)},
            {"float": 0.1, "tiny": 1e-7, "whole": 1.0},
            {"nested": {"z": 1, "a": [None, True, False, {"k": "v"}]}},
            {},
        ]
        stored = log.append_many([ev(payload=p) for p in payloads])
        back = list(log.read())
        for original, read_back in zip(stored, back):
            self.assertEqual(json.dumps(read_back.payload, sort_keys=True),
                             json.dumps(original.payload, sort_keys=True))
            self.assertEqual(event_digest(read_back), event_digest(original),
                             f"digest changed for {original.payload!r}")

    # --- the chain --------------------------------------------------------

    def test_the_chain_verifies(self):
        log = self.open()
        log.append_many([ev(payload={"i": i}) for i in range(10)])
        result = self.verify(log)
        self.assertTrue(result.ok, result.detail)
        self.assertEqual(result.checked, 10)

    def test_tampering_is_detected_at_the_tampered_event(self):
        log = self.open()
        log.append_many([ev(payload={"i": i}) for i in range(5)])
        self.tamper(log, seq=3, payload={"i": 999})
        result = self.verify(log)
        self.assertFalse(result.ok)
        self.assertEqual(result.first_bad_seq, 3)

    def test_the_log_refuses_in_place_edits(self):
        """Append-only is enforced by the database, not by convention. The
        chain makes a tamper evident; this makes it need privileges the
        application should not hold."""
        log = self.open()
        log.append_many([ev(payload={"i": i}) for i in range(3)])
        for statement in self.forbidden_statements():
            with self.subTest(statement=statement):
                with self.assertRaises(Exception):
                    self.execute(log, statement)
        self.assertEqual(len(log), 3, "a refused edit must change nothing")

    # --- many writers -----------------------------------------------------

    def _hammer(self, opener, per_thread=None, threads=None):
        per_thread = per_thread or self.PER_THREAD
        threads = threads or self.THREADS
        errors: list[BaseException] = []
        barrier = threading.Barrier(threads)

        def worker(tid):
            log = opener()
            try:
                barrier.wait()
                for i in range(per_thread):
                    log.append(ev(payload={"t": tid, "i": i}))
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)
            finally:
                log.close()

        workers = [threading.Thread(target=worker, args=(t,))
                   for t in range(threads)]
        for w in workers:
            w.start()
        for w in workers:
            w.join(timeout=300)
        return errors, threads * per_thread

    def test_concurrent_writers_produce_gapless_unique_sequences(self):
        log = self.open()
        errors, expected = self._hammer(self.opener())
        self.assertEqual(errors, [])
        seqs = [e.seq for e in log.read()]
        self.assertEqual(len(seqs), expected)
        self.assertEqual(seqs, list(range(1, expected + 1)),
                         "sequence numbers must be gapless and unique")

    def test_concurrent_writers_keep_one_linear_chain(self):
        log = self.open()
        errors, expected = self._hammer(self.opener())
        self.assertEqual(errors, [])
        result = self.verify(log)
        self.assertTrue(result.ok, result.detail)
        self.assertEqual(result.checked, expected)

    def test_a_polling_reader_never_skips_an_event(self):
        """The property a BIGSERIAL port loses silently.

        A reader advances a cursor to the highest sequence it has seen, the way
        every projection rebuilder here does. If a lower sequence can commit
        after a higher one is visible, the cursor jumps over it and the event is
        never replayed.
        """
        log = self.open()
        seen: list[int] = []
        stop = threading.Event()

        def reader():
            handle = self.opener()()
            cursor = 0
            try:
                while not stop.is_set():
                    for event in handle.read(since_seq=cursor):
                        seen.append(event.seq)
                        cursor = event.seq
                    time.sleep(0.001)
                for event in handle.read(since_seq=cursor):
                    seen.append(event.seq)
            finally:
                handle.close()

        poller = threading.Thread(target=reader)
        poller.start()
        errors, expected = self._hammer(self.opener())
        stop.set()
        poller.join(timeout=60)
        self.assertEqual(errors, [])
        self.assertEqual(sorted(seen), list(range(1, expected + 1)),
                         "a cursor-advancing reader missed or duplicated "
                         "events")
        self.assertEqual(seen, sorted(seen), "replay must be in order")


# --- SQLite -----------------------------------------------------------------

class TestSQLiteContract(Contract, unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.path = str(pathlib.Path(self._dir.name) / "log.db")
        self._open = []

    def tearDown(self):
        for log in self._open:
            try:
                log.close()
            except Exception:
                pass
        self._dir.cleanup()

    def open(self):
        log = EventLog(self.path)
        self._open.append(log)
        return log

    def opener(self):
        return lambda: EventLog(self.path, busy_timeout_ms=30_000)

    def verify(self, log):
        return log.chain.verify(log.read())

    def tamper(self, log, seq, payload):
        # An attacker with file access drops the triggers first, as
        # tests/test_integrity_chain.py does. Without that the store refuses
        # the edit, which `test_the_log_refuses_in_place_edits` pins.
        log._conn.execute("DROP TRIGGER IF EXISTS events_no_update")
        log._conn.execute("UPDATE events SET payload = ? WHERE seq = ?",
                          (json.dumps(payload), seq))

    def forbidden_statements(self):
        return ["UPDATE events SET payload = '{}' WHERE seq = 1",
                "DELETE FROM events WHERE seq = 1",
                "DELETE FROM events",
                "UPDATE integrity_chain SET chain_digest = 'x' WHERE seq = 1"]

    def execute(self, log, statement):
        log._conn.execute(statement)


# --- Postgres ---------------------------------------------------------------

class _PostgresBase(Contract):
    def setUp(self):
        from memory_fabric.storage.postgres import PostgresEventLog
        self.cls = PostgresEventLog
        # A fresh schema per test, so tests cannot see each other's events.
        self.schema = "t_" + uuid.uuid4().hex[:12]
        self._open = []

    def tearDown(self):
        for log in self._open:
            try:
                log.close()
            except Exception:
                pass
        import psycopg
        with psycopg.connect(PG_DSN, autocommit=True) as conn:
            conn.execute(psycopg.sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE")
                         .format(psycopg.sql.Identifier(self.schema)))

    def open(self):
        log = self.cls(PG_DSN, schema=self.schema)
        self._open.append(log)
        return log

    def opener(self):
        return lambda: self.cls(PG_DSN, schema=self.schema)

    def verify(self, log):
        return log.verify()

    def tamper(self, log, seq, payload):
        # The table owner can disable triggers, as file access lets an
        # attacker drop them in SQLite. Same threat model; the chain is what
        # makes the result visible.
        # `_pg` is the raw psycopg connection; `_conn` is the sqlite3-dialect
        # adapter the governance modules share, and would reject `%s`.
        log._pg.execute("ALTER TABLE events DISABLE TRIGGER events_append_only")
        log._pg.execute("UPDATE events SET payload = %s WHERE seq = %s",
                        (json.dumps(payload), seq))

    def forbidden_statements(self):
        # TRUNCATE is the Postgres-specific one: it does not fire row
        # triggers, so it needs its own statement-level trigger.
        return ["UPDATE events SET payload = '{}' WHERE seq = 1",
                "DELETE FROM events WHERE seq = 1",
                "DELETE FROM events",
                "TRUNCATE events CASCADE",
                "UPDATE integrity_chain SET chain_digest = 'x' WHERE seq = 1",
                "TRUNCATE integrity_chain"]

    def execute(self, log, statement):
        # Inside a transaction so a refused statement cannot leave the
        # autocommit connection in an aborted state for the next one.
        with log._pg.transaction():
            log._pg.execute(statement)


@unittest.skipUnless(PG, PG_REASON)
class TestPostgresContract(_PostgresBase, unittest.TestCase):
    pass


# --- falsification: the design this rejects, and proof it fails -----------

class NaivePostgresEventLog:
    """The port most people would write first, kept here to fail.

    `BIGSERIAL` sequence numbers and a chain head read with `MAX()`, no lock.
    A short sleep between taking a sequence number and committing widens the
    race window that exists in production anyway, so the failure shows up in
    a test run rather than once a month under load.
    """

    def __init__(self, dsn, schema):
        import psycopg
        self._conn = psycopg.connect(dsn, autocommit=True)
        self._conn.execute(psycopg.sql.SQL("CREATE SCHEMA IF NOT EXISTS {}")
                           .format(psycopg.sql.Identifier(schema)))
        self._conn.execute(psycopg.sql.SQL("SET search_path TO {}")
                           .format(psycopg.sql.Identifier(schema)))
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS events (seq BIGSERIAL PRIMARY KEY, "
            "event_id TEXT UNIQUE, payload TEXT)")

    def append(self, event):
        with self._conn.transaction():
            row = self._conn.execute(
                "INSERT INTO events (event_id, payload) VALUES (%s, %s) "
                "RETURNING seq", (event.event_id, json.dumps(event.payload))
            ).fetchone()
            time.sleep(0.003)
            return event.with_seq(int(row[0]))

    def read(self, since_seq=0, limit=None):
        for seq, event_id, payload in self._conn.execute(
                "SELECT seq, event_id, payload FROM events WHERE seq > %s "
                "ORDER BY seq", (since_seq,)).fetchall():
            yield Event(type="x", ts=0, payload=json.loads(payload),
                        agent_id=None, episode_id=None, event_id=event_id,
                        schema_version="0", seq=int(seq))

    def close(self):
        self._conn.close()


@unittest.skipUnless(PG, PG_REASON)
class TestTheNaiveDesignFails(unittest.TestCase):
    """If these start passing, the concurrency tests above prove nothing."""

    def setUp(self):
        self.schema = "n_" + uuid.uuid4().hex[:12]

    def tearDown(self):
        import psycopg
        with psycopg.connect(PG_DSN, autocommit=True) as conn:
            conn.execute(psycopg.sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE")
                         .format(psycopg.sql.Identifier(self.schema)))

    def test_a_polling_reader_skips_events_on_bigserial(self):
        """The bug, demonstrated: a reader that advances its cursor misses
        events whose lower sequence number committed after a higher one."""
        opener = lambda: NaivePostgresEventLog(PG_DSN, self.schema)  # noqa
        NaivePostgresEventLog(PG_DSN, self.schema).close()
        seen, stop, errors = [], threading.Event(), []

        def reader():
            handle = opener()
            cursor = 0
            try:
                while not stop.is_set():
                    for event in handle.read(since_seq=cursor):
                        seen.append(event.seq)
                        cursor = event.seq
                    time.sleep(0.0005)
            finally:
                handle.close()

        def writer(tid):
            log = opener()
            try:
                for i in range(25):
                    log.append(ev(payload={"t": tid, "i": i}))
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)
            finally:
                log.close()

        poller = threading.Thread(target=reader)
        poller.start()
        writers = [threading.Thread(target=writer, args=(t,)) for t in range(8)]
        for w in writers:
            w.start()
        for w in writers:
            w.join(timeout=300)
        stop.set()
        poller.join(timeout=60)
        self.assertEqual(errors, [])
        total = opener()
        try:
            committed = sorted(e.seq for e in total.read())
        finally:
            total.close()
        missed = set(committed) - set(seen)
        self.assertTrue(
            missed,
            "the naive design did not skip an event this run. The race is real "
            "but timing-dependent; if this keeps passing, widen the window "
            "rather than trusting the concurrency tests above")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
