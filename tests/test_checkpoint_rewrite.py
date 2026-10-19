"""An attacker who rewrites the log *and* the chain is caught by a checkpoint stored elsewhere.

End to end, as an operator would run it: the background manager writes a
checkpoint per cycle to a directory off the store's disk; someone with write
access to the database then edits an event, drops the append-only triggers
and recomputes every chain link, so the store verifies against itself; and
`memory-fabric checkpoint --verify` against the independent file fails.
"""

from __future__ import annotations

import contextlib
import io
import sqlite3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from memory_fabric import MemoryFabric
from memory_fabric.cli import main
from memory_fabric.eventlog import EventLog
from memory_fabric.integrity import GENESIS, event_digest, link
from memory_fabric.manager import MemoryManager


def run(*argv: str) -> int:
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        return main(list(argv))


class CheckpointRewrite(unittest.TestCase):
    def setUp(self) -> None:
        tmp = Path(self.enterContext(TemporaryDirectory()))
        self.db, self.checkpoints = tmp / "store.db", tmp / "elsewhere"
        f = MemoryFabric(str(self.db), auto_activate=True)
        f.remember("tech", "Valve V7 opens below 4 bar.", scope="team")
        f.remember("tech", "Pump P1 purge time is 30 s.", scope="team")
        MemoryManager(f, holder="m", checkpoint_dir=str(self.checkpoints)).run_once()
        f.remember("tech", "Fan F2 trips at 12 A.", scope="team")
        MemoryManager(f, holder="m", checkpoint_dir=str(self.checkpoints)).run_once()
        self.file = next(self.checkpoints.glob("*.checkpoint.jsonl"))
        f.close()

    def rewrite_history(self) -> None:
        """Edit an early event, then rebuild the chain so the store is self-consistent."""
        conn = sqlite3.connect(self.db)
        try:
            with conn:
                for trigger in ("events_no_update", "integrity_chain_no_update",
                                "integrity_chain_no_delete"):
                    conn.execute(f"DROP TRIGGER IF EXISTS {trigger}")
                conn.execute("UPDATE events SET agent_id = 'someone-else' WHERE seq = 2")
                conn.execute("DELETE FROM integrity_chain")
        finally:
            conn.close()
        log = EventLog(str(self.db))
        try:
            previous = GENESIS
            with log.transaction():
                for event in list(log.read()):
                    digest = event_digest(event)
                    previous = link(previous, digest)
                    log._conn.execute(
                        "INSERT INTO integrity_chain (seq, event_digest, chain_digest, "
                        "recorded_ms) VALUES (?, ?, ?, ?)", (event.seq, digest, previous, 0))
            self.assertTrue(log.chain.verify(log.read()).ok, "the forgery is self-consistent")
        finally:
            log.close()

    def test_an_untouched_store_matches_its_independent_checkpoints(self) -> None:
        self.assertEqual(len(self.file.read_text(encoding="utf-8").splitlines()), 2)
        self.assertEqual(run("--db", str(self.db), "checkpoint", "--verify", str(self.file)), 0)

    def test_a_consistent_rewrite_is_detected_against_the_independent_checkpoint(self) -> None:
        self.rewrite_history()
        self.assertEqual(run("--db", str(self.db), "checkpoint", "--verify", str(self.file)), 5)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
