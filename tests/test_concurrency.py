"""SQLite's limits, measured rather than asserted.

The documentation has said "SQLite single-writer limitation remains explicit"
since the first roadmap. It was explicit and it was never tested, so what
actually happens under contention was a matter of belief.

**It turns out to be fine, and my first account of why was wrong.** I added an
explicit `busy_timeout` pragma and wrote that it fixed concurrent writers
failing instantly, on the understanding that SQLite's default timeout is zero.
That is true of the C library and false of Python: `sqlite3.connect` sets 5
seconds of its own accord, so this store had always serialised writers. The
falsification run — remove the pragma, expect these tests to fail — passed
instead, which is what caught the claim. The pragma stays because it makes the
value visible and configurable rather than inherited from a stdlib default,
not because it repaired anything.

So these tests pin what is actually true: concurrent writers serialise without
losing writes, sequence numbers stay a gapless run, the hash chain survives,
readers are never blocked by a writer, and a writer with no patience fails
cleanly rather than corrupting anything.

Real processes, not threads. Threads in one interpreter share a connection pool
and a GIL and would not exercise the file locking that is the whole question.
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import textwrap
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from memory_fabric import MemoryFabric

WRITER = textwrap.dedent(
    """
    import json, sys, time
    sys.path.insert(0, {root!r})
    from memory_fabric import MemoryFabric

    path, label, count, timeout = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4])
    fabric = MemoryFabric(path, auto_activate=True, encrypt_content=False,
                          busy_timeout_ms=timeout)
    written, failures = 0, []
    try:
        for index in range(count):
            try:
                fabric.remember(agent_id=label, content=f"{{label}} observation {{index}}")
                written += 1
            except Exception as exc:
                failures.append(type(exc).__name__ + ": " + str(exc)[:80])
    finally:
        fabric.close()
    print(json.dumps({{"label": label, "written": written, "failures": failures}}))
    """
)


class ConcurrentWriters(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        self.path = self.dir / "store.db"
        # Create the store first so the writers do not race on schema creation,
        # which is a separate question from racing on appends.
        fabric = MemoryFabric(self.path, auto_activate=True, encrypt_content=False)
        fabric.close()
        self.script = self.dir / "writer.py"
        self.script.write_text(
            WRITER.format(root=str(Path(__file__).resolve().parent.parent)),
            encoding="utf-8",
        )

    def _spawn(self, label: str, count: int, timeout_ms: int = 30_000):
        # This test establishes serialisation, not the product's default wait
        # budget.  A busy CI or sandbox volume can let one process retain the
        # SQLite writer lock for longer than five seconds across its sequence
        # of transactions.  Give every contender enough patience to test the
        # stated property; the deterministic tests below separately pin the
        # configured 5 s default and the zero-timeout failure semantics.
        return subprocess.Popen(
            [sys.executable, str(self.script), str(self.path), label,
             str(count), str(timeout_ms)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )

    def _collect(self, processes) -> list[dict]:
        results = []
        for process in processes:
            out, err = process.communicate(timeout=180)
            self.assertEqual(process.returncode, 0, f"writer crashed: {err[-500:]}")
            results.append(json.loads(out.strip().splitlines()[-1]))
        return results

    def test_concurrent_writers_serialise_without_losing_writes(self) -> None:
        """Four processes, twenty appends each. All eighty must land.

        Note what this does *not* establish: it passes with the busy-timeout
        pragma removed, because Python's `sqlite3.connect` supplies one anyway.
        It is strong evidence that nothing is lost or corrupted under real
        multi-process load, and no evidence at all about the pragma. The
        deterministic contention tests below are the ones that isolate timeout
        behaviour.
        """
        processes = [self._spawn(f"w{i}", 20) for i in range(4)]
        results = self._collect(processes)

        total = sum(r["written"] for r in results)
        failures = [f for r in results for f in r["failures"]]
        self.assertEqual(failures, [], "writers should wait, not fail")
        self.assertEqual(total, 80)

        fabric = MemoryFabric(self.path, auto_activate=True, encrypt_content=False)
        self.addCleanup(fabric.close)
        self.assertEqual(len(fabric.state.memories), 80)

    def test_the_log_stays_consistent_under_contention(self) -> None:
        """Sequence numbers must be a gapless run.

        A lost or duplicated `seq` would break the hash chain and every
        projection built from it, so this is the property that makes the rest
        of the system's claims survive concurrency.
        """
        processes = [self._spawn(f"w{i}", 15) for i in range(3)]
        self._collect(processes)

        fabric = MemoryFabric(self.path, auto_activate=True, encrypt_content=False)
        self.addCleanup(fabric.close)
        sequences = [event.seq for event in fabric.log.read()]
        self.assertEqual(sequences, sorted(sequences))
        self.assertEqual(len(sequences), len(set(sequences)), "duplicate sequence")
        self.assertEqual(sequences, list(range(1, len(sequences) + 1)), "gap")

    def test_the_hash_chain_survives_concurrent_appends(self) -> None:
        """Each writer chains inside its own transaction. If the chain read a
        head another process was about to supersede, the links would fork."""
        processes = [self._spawn(f"w{i}", 15) for i in range(3)]
        self._collect(processes)

        fabric = MemoryFabric(self.path, auto_activate=True, encrypt_content=False)
        self.addCleanup(fabric.close)
        result = fabric.log.chain.verify(fabric.log.read())
        self.assertTrue(result.ok, result.detail)
        self.assertEqual(result.checked, len(fabric.log))

    def test_a_zero_timeout_fails_fast_rather_than_corrupting(self) -> None:
        """The honest limit.

        With the timeout set to nothing, contention *does* fail — and the point
        is that it fails cleanly: an exception, no partial write, no corruption,
        and the store still verifies afterwards. That is the behaviour an
        operator can build a retry on.
        """
        processes = [self._spawn(f"w{i}", 25, timeout_ms=0) for i in range(4)]
        results = self._collect(processes)
        failures = [f for r in results for f in r["failures"]]
        # Not asserted to be non-empty: on a fast disk the writers may not
        # actually overlap. What matters is that whatever happened left the
        # store sound.
        for failure in failures:
            self.assertIn("locked", failure.lower(), failure)

        fabric = MemoryFabric(self.path, auto_activate=True, encrypt_content=False)
        self.addCleanup(fabric.close)
        written = sum(r["written"] for r in results)
        self.assertEqual(len(fabric.state.memories), written)
        self.assertTrue(fabric.log.chain.verify(fabric.log.read()).ok)


class ContentionIsDeterministic(unittest.TestCase):
    """Contention forced, not hoped for.

    The multi-process tests above pass *even without a busy timeout* on a fast
    disk, because the writers do not reliably overlap — so they are evidence
    that nothing is corrupted and weak evidence about serialisation. These two
    hold a write transaction open for a known duration, so the contention is a
    fact of the schedule rather than a property of the hardware.
    """

    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        self.path = self.dir / "store.db"
        fabric = MemoryFabric(self.path, auto_activate=True, encrypt_content=False)
        fabric.close()
        self.script = self.dir / "one_write.py"
        self.ready = self.dir / "child-ready"
        self.script.write_text(
            textwrap.dedent(
                """
                import pathlib, sys
                sys.path.insert(0, {root!r})
                from memory_fabric import MemoryFabric
                path, timeout, ready = sys.argv[1], int(sys.argv[2]), sys.argv[3]
                fabric = MemoryFabric(path, auto_activate=True,
                                      encrypt_content=False,
                                      busy_timeout_ms=timeout)
                # Announced *after* the store is open and *before* the write, so
                # the parent knows the child is genuinely about to contend
                # rather than still importing. Without this handshake the
                # parent's sleep raced the child's start-up, and the test
                # passed with the busy timeout removed.
                pathlib.Path(ready).write_text("ready")
                try:
                    fabric.remember(agent_id="child", content="from the child")
                    print("WROTE")
                except Exception as exc:
                    print("FAILED " + str(exc)[:80])
                finally:
                    fabric.close()
                """
            ).format(root=str(Path(__file__).resolve().parent.parent)),
            encoding="utf-8",
        )

    def _await_ready(self, timeout: float = 30.0) -> None:
        import time

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.ready.exists():
                return
            time.sleep(0.02)
        self.fail("the child never reached the write")

    def _child(self, timeout_ms: int) -> str:
        result = subprocess.run(
            [sys.executable, str(self.script), str(self.path), str(timeout_ms),
             str(self.ready)],
            capture_output=True, text=True, timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stderr[-400:])
        return result.stdout.strip().splitlines()[-1]

    def test_a_writer_with_no_patience_is_refused_while_the_lock_is_held(self) -> None:
        """The limit, made visible.

        SQLite is single-writer: with the timeout set to zero, any overlap at
        all is a failure. This is also the test that proves the pragma takes
        effect, since it is the only way to get a timeout *below* the 5 seconds
        `sqlite3.connect` provides by default.
        """
        holder = MemoryFabric(self.path, auto_activate=True, encrypt_content=False)
        self.addCleanup(holder.close)
        manager = holder.log.transaction()
        manager.__enter__()
        try:
            holder.remember(agent_id="holder", content="holding the write lock")
            outcome = self._child(timeout_ms=0)
        finally:
            manager.__exit__(None, None, None)
        self.assertTrue(outcome.startswith("FAILED"), outcome)
        self.assertIn("locked", outcome.lower())

    def test_a_patient_writer_waits_and_then_succeeds(self) -> None:
        """The second writer serialises behind the first instead of failing.

        True with or without the explicit pragma, since the stdlib default is
        already 5 seconds — so this documents the behaviour rather than
        defending the pragma.

        No threads. The first attempt released the transaction from a worker
        thread, which the re-entrant lock correctly refused — `transaction()`
        is owned by the thread that entered it, and a cross-thread exit is a
        bug rather than a pattern. `Popen` plus a sleep in the main thread
        gives the same overlap with none of that.
        """
        import time

        holder = MemoryFabric(self.path, auto_activate=True, encrypt_content=False)
        self.addCleanup(holder.close)
        manager = holder.log.transaction()
        manager.__enter__()
        holder.remember(agent_id="holder", content="holding the write lock")

        child = subprocess.Popen(
            [sys.executable, str(self.script), str(self.path), "5000",
             str(self.ready)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        try:
            # Wait for the handshake, so the child is demonstrably past import
            # and at the write. Then a short settle so it is blocked on the
            # lock rather than merely approaching it.
            self._await_ready()
            time.sleep(0.3)
            self.assertIsNone(child.poll(), "the child should still be waiting")
        finally:
            manager.__exit__(None, None, None)

        out, err = child.communicate(timeout=60)
        self.assertEqual(child.returncode, 0, err[-400:])
        self.assertEqual(out.strip().splitlines()[-1], "WROTE", out)

        reopened = MemoryFabric(self.path, auto_activate=True, encrypt_content=False)
        self.addCleanup(reopened.close)
        self.assertTrue(reopened.log.chain.verify(reopened.log.read()).ok)


class ReadersAreNotBlocked(unittest.TestCase):
    """WAL's actual benefit, and the reason the dashboard can stay up."""

    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "store.db"
        self.fabric = MemoryFabric(
            self.path, auto_activate=True, encrypt_content=False
        )
        self.addCleanup(self.fabric.close)
        self.fabric.remember(agent_id="ag", content="valve 7 is upstream")

    def test_a_reader_sees_committed_state_mid_transaction(self) -> None:
        """An open write transaction must not block a separate reader, and the
        reader must see the state from *before* the uncommitted work."""
        reader = sqlite3.connect(self.path)
        self.addCleanup(reader.close)
        before = reader.execute("SELECT count(*) FROM events").fetchone()[0]

        manager = self.fabric.log.transaction()
        manager.__enter__()
        try:
            self.fabric.remember(agent_id="ag", content="uncommitted")
            during = reader.execute("SELECT count(*) FROM events").fetchone()[0]
            self.assertEqual(during, before, "a reader saw uncommitted writes")
        finally:
            manager.__exit__(None, None, None)

        after = reader.execute("SELECT count(*) FROM events").fetchone()[0]
        self.assertGreater(after, before)

    def test_journal_mode_is_wal(self) -> None:
        self.assertEqual(
            self.fabric.log._conn.execute("PRAGMA journal_mode").fetchone()[0],
            "wal",
        )

    def test_the_busy_timeout_is_set_and_configurable(self) -> None:
        """Pinned because the value is now part of the API.

        The first version of this comment said the default was zero and that
        the default was a bug. Python's `sqlite3.connect` sets 5 seconds, so
        neither half was true; what the pragma adds is that the figure is
        visible and a caller can lower it.
        """
        self.assertEqual(
            self.fabric.log._conn.execute("PRAGMA busy_timeout").fetchone()[0],
            5_000,
        )
        other = MemoryFabric(":memory:", busy_timeout_ms=250)
        self.addCleanup(other.close)
        self.assertEqual(
            other.log._conn.execute("PRAGMA busy_timeout").fetchone()[0], 250
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
