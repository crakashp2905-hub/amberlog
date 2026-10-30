"""PostgreSQL-specific properties of the optional backend.

Skipped unless `MF_TEST_POSTGRES_URL` points at a server the tests may create
databases on. The general behaviour is covered by running the *whole* suite
with that variable set (see `tests/__init__.py`); this file covers what only a
multi-host backend has to get right.
"""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
import unittest
import time
import uuid

URL = os.environ.get("MF_TEST_POSTGRES_URL")

WRITER = r"""
import sys
from memory_fabric.eventlog import EventLog
from memory_fabric.events import Event
log = EventLog(sys.argv[1])
for i in range(int(sys.argv[3])):
    log.append(Event(type="Probe", ts=i, payload={"writer": sys.argv[2], "i": i}))
log.close()
"""


@unittest.skipUnless(URL, "set MF_TEST_POSTGRES_URL to run the Postgres backend tests")
class PostgresCase(unittest.TestCase):
    def setUp(self) -> None:
        import psycopg

        self.db = f"mf_pg_{uuid.uuid4().hex[:12]}"
        with psycopg.connect(URL, autocommit=True) as conn:
            conn.execute(f"CREATE DATABASE {self.db}")
        base, _, _ = URL.rpartition("/")
        self.url = f"{base}/{self.db}"

    def tearDown(self) -> None:
        import psycopg

        with psycopg.connect(URL, autocommit=True) as conn:
            conn.execute(f"DROP DATABASE IF EXISTS {self.db} WITH (FORCE)")


class TestConcurrentWriters(PostgresCase):
    def test_writers_on_separate_processes_produce_a_gapless_chained_log(self) -> None:
        """The reason to run on Postgres at all: writers that are not on one
        machine. They serialise on the table lock, so the sequence stays
        gapless and the hash chain stays a total order."""
        from memory_fabric.eventlog import EventLog

        EventLog(self.url).close()  # schema first, so writers do not race it
        procs = [subprocess.Popen([sys.executable, "-c", WRITER, self.url, f"w{n}", "25"])
                 for n in range(4)]
        for proc in procs:
            self.assertEqual(proc.wait(timeout=120), 0)
        log = EventLog(self.url)
        try:
            seqs = [event.seq for event in log.read()]
            self.assertEqual(seqs, list(range(1, 101)))
            report = log.chain.verify(list(log.read()))
            self.assertTrue(report.ok, report)
        finally:
            log.close()


class TestSimultaneousStartup(PostgresCase):
    def test_many_processes_can_open_the_store_at_once(self) -> None:
        """Every connection used to replace the trigger function, so processes
        starting together failed with "tuple concurrently updated" -- 5 of 80
        in a local reproduction, and the first CI run of this file. Now it is
        created once, under the schema lock."""
        from memory_fabric.eventlog import EventLog

        EventLog(self.url).close()
        opener = "import sys; from memory_fabric.eventlog import EventLog; EventLog(sys.argv[1]).close()"
        for _ in range(3):
            procs = [subprocess.Popen([sys.executable, "-c", opener, self.url],
                                      stderr=subprocess.PIPE, text=True)
                     for _ in range(12)]
            for proc in procs:
                _, err = proc.communicate(timeout=120)
                self.assertEqual(proc.returncode, 0, err[-500:])


class TestAppendOnly(PostgresCase):
    def test_update_and_delete_are_refused_by_the_database(self) -> None:
        from memory_fabric import MemoryFabric

        fabric = MemoryFabric(self.url)
        try:
            fabric.remember("ag", "a fact")
            for statement in ("UPDATE events SET ts = ts + 1", "DELETE FROM events",
                              "UPDATE integrity_chain SET recorded_ms = 0"):
                with self.subTest(statement):
                    with self.assertRaises(sqlite3.IntegrityError):
                        fabric.log._conn.execute(statement)
        finally:
            fabric.close()


class TestOperations(PostgresCase):
    def cli(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, "-m", "memory_fabric", "--db", *args],
                              capture_output=True, text=True, timeout=120)

    def test_doctor_reports_sound(self) -> None:
        self.assertEqual(self.cli(self.url, "demo").returncode, 0)
        done = self.cli(self.url, "doctor")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)

    def test_backup_points_at_pg_dump(self) -> None:
        self.cli(self.url, "demo")
        done = self.cli(self.url, "backup", os.devnull)
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("pg_dump", done.stdout + done.stderr)

    def test_a_password_in_the_url_is_never_printed(self) -> None:
        from memory_fabric.pgcompat import redact

        secret = "s3cr3t-" + uuid.uuid4().hex
        self.assertNotIn(secret, redact(f"postgresql://user:{secret}@db.example:5432/mf"))
        started = time.monotonic()
        done = self.cli(f"postgresql://postgres:{secret}@127.0.0.1:1/nope", "overview")
        self.assertNotEqual(done.returncode, 0)
        self.assertLess(time.monotonic() - started, 60,
                        "a bad URL must fail promptly, not on the OS's TCP retry schedule")
        self.assertNotIn(secret, done.stdout + done.stderr)


if __name__ == "__main__":
    unittest.main()


BRANCH_WRITER = r"""
import sys
from memory_fabric import MemoryFabric
from memory_fabric.branching import Branches, HeadMoved
f = MemoryFabric(sys.argv[1], auto_activate=True, hold_suspicious=False)
b = Branches(f)
for n in range(int(sys.argv[3])):
    while True:
        try:
            with b.commit("shared", sys.argv[2], f"{sys.argv[2]} {n}") as c:
                c.add(f"Note {sys.argv[2]}-{n}: pump P{n} checked at {n} bar.")
            break
        except HeadMoved:
            pass
f.close()
"""


class TestConcurrentBranchCommits(PostgresCase):
    def test_processes_committing_to_one_branch_lose_nothing(self) -> None:
        """Compare-and-swap of a branch head across processes on Postgres."""
        from memory_fabric import MemoryFabric
        from memory_fabric.branching import Branches

        f = MemoryFabric(self.url)
        Branches(f).create("shared", owner="w0", members=("w1", "w2"))
        f.close()
        procs = [subprocess.Popen([sys.executable, "-c", BRANCH_WRITER, self.url, f"w{n}", "5"])
                 for n in range(3)]
        for proc in procs:
            self.assertEqual(proc.wait(timeout=300), 0)
        f = MemoryFabric(self.url)
        try:
            history = Branches(f).history("shared")
            self.assertEqual(len(history), 15)
            for newer, older in zip(history, history[1:]):
                self.assertEqual(newer["parents"], [older["commit_id"]])
        finally:
            f.close()
