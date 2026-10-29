"""Backing up the one thing that cannot be rebuilt.

The event log is the source of truth and every projection is derivable from it
(AGENTS.md principle 3), which makes backup the single operation that protects
the data — and makes a *silently incomplete* backup the worst outcome available.
A truncated SQLite file opens perfectly well and reports fewer rows, so these
tests care less about the happy path than about whether the command would notice.
"""

from __future__ import annotations

import sqlite3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from amberlog import Amberlog, WithdrawalBasis
from amberlog.cli import main


class TestBackup(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.source = str(Path(self.tmp.name) / "store.db")
        self.target = str(Path(self.tmp.name) / "copy.db")

        fabric = Amberlog(self.source)
        episode = fabric.start_episode("agent-a", task_id="t1")
        kept = fabric.remember("agent-a", "a durable lesson", source_episodes=[episode.id])
        fabric.validate(kept, actor="supervisor")
        fabric.retrieve("agent-a", "lesson", episode_id=episode.id)
        fabric.record_outcome(episode.id, outcome=1.0, verifier_id="env")
        withdrawn = fabric.remember("agent-a", "a mistaken lesson")
        fabric.validate(withdrawn, actor="supervisor")
        fabric.quarantine(
            withdrawn, reason="contradicted", actor="safety",
            basis=WithdrawalBasis.CONTRADICTED,
        )
        self.events = len(fabric.log)
        self.memories = len(fabric.state.memories)
        self.withdrawn = withdrawn
        fabric.close()

    def test_it_copies_every_event(self) -> None:
        self.assertEqual(main(["--db", self.source, "backup", self.target]), 0)
        copy = Amberlog(self.target)
        self.addCleanup(copy.close)
        self.assertEqual(len(copy.log), self.events)
        self.assertEqual(len(copy.state.memories), self.memories)

    def test_the_copy_replays_to_the_same_state(self) -> None:
        """Copying the bytes is not the point — the copy has to *fold* into the
        same projections, including the ones that only exist in the log."""
        main(["--db", self.source, "backup", self.target])
        copy = Amberlog(self.target)
        self.addCleanup(copy.close)

        self.assertEqual(
            copy.state.withdrawal_basis[self.withdrawn],
            WithdrawalBasis.CONTRADICTED.value,
        )
        # Propensities live only in the log; an unbiased value estimate is
        # impossible without them, so losing them loses the data's usefulness
        # while leaving it apparently intact.
        self.assertTrue(copy.state.exposures)
        self.assertTrue(
            any(e.has_outcome for e in copy.state.episodes.values())
        )

    def test_it_runs_while_the_store_is_open(self) -> None:
        """The reason not to use `cp`: WAL mode means a mid-write copy is a
        database plus an uncommitted write-ahead log."""
        live = Amberlog(self.source)
        self.addCleanup(live.close)
        extra = live.remember("agent-b", "written just before the backup")
        live.validate(extra, actor="supervisor")

        self.assertEqual(main(["--db", self.source, "backup", self.target]), 0)
        copy = Amberlog(self.target)
        self.addCleanup(copy.close)
        self.assertIn(extra, copy.state.memories)

    def test_it_refuses_to_overwrite_without_force(self) -> None:
        Path(self.target).write_text("not a database", encoding="utf-8")
        self.assertEqual(main(["--db", self.source, "backup", self.target]), 4)
        self.assertEqual(Path(self.target).read_text(encoding="utf-8"), "not a database")

    def test_force_overwrites(self) -> None:
        main(["--db", self.source, "backup", self.target])
        self.assertEqual(
            main(["--db", self.source, "backup", self.target, "--force"]), 0
        )

    def test_it_creates_missing_directories(self) -> None:
        nested = str(Path(self.tmp.name) / "backups" / "daily" / "copy.db")
        self.assertEqual(main(["--db", self.source, "backup", nested]), 0)
        self.assertTrue(Path(nested).exists())

    def test_a_short_copy_is_reported_and_fails(self) -> None:
        """The check that justifies the command existing.

        A backup that opens but holds fewer events is the failure nothing else
        would surface, so it has to be a non-zero exit rather than a line of
        output. `sqlite3.Connection` is immutable, so the short copy is produced
        where it would actually be detected: the file is truncated between the
        copy and the replay that verifies it.
        """
        import sqlite3 as sqlite

        import amberlog.cli as cli

        real_fabric = cli.Amberlog
        target = Path(self.target).resolve()

        def truncate_then_open(path, *args, **kwargs):
            if Path(str(path)).resolve() == target and target.exists():
                scratch = sqlite.connect(str(target))
                try:
                    scratch.executescript(
                        "DROP TRIGGER IF EXISTS events_no_update;"
                        "DROP TRIGGER IF EXISTS events_no_delete;"
                        "DELETE FROM events WHERE seq = (SELECT MAX(seq) FROM events);"
                    )
                    scratch.commit()
                finally:
                    scratch.close()
            return real_fabric(path, *args, **kwargs)

        cli.Amberlog = truncate_then_open
        try:
            code = main(["--db", self.source, "backup", self.target])
        finally:
            cli.Amberlog = real_fabric
        self.assertEqual(code, 5)

    def test_the_copy_is_append_only_too(self) -> None:
        """The guarantee has to survive the copy, or a restored store is a
        weaker store than the one it replaced."""
        main(["--db", self.source, "backup", self.target])
        copy = Amberlog(self.target)
        self.addCleanup(copy.close)
        with self.assertRaises(sqlite3.IntegrityError):
            copy.log._conn.execute(
                "UPDATE events SET payload = '{}' "
                "WHERE seq = (SELECT MAX(seq) FROM events)"
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()


class TestInMemoryStoreIsRefused(unittest.TestCase):
    """`--db :memory:` opens a fresh, empty store.

    Before this check the command copied that store's zero events, compared
    zero against zero, and reported success — handing back a verified-looking
    backup of nothing. The live validation found it by asking for a backup of an
    in-memory store and getting a green tick. A command whose only job is
    protecting the event log must fail loudly here.
    """

    def test_it_refuses_rather_than_copying_nothing(self) -> None:
        with TemporaryDirectory() as tmp:
            target = Path(tmp) / "copy.db"
            self.assertNotEqual(main(["--db", ":memory:", "backup", str(target)]), 0)

    def test_it_does_not_leave_a_misleading_file_behind(self) -> None:
        """An empty file beside a non-zero exit would still read as a backup to
        anything that only checks for the path existing."""
        with TemporaryDirectory() as tmp:
            target = Path(tmp) / "copy.db"
            main(["--db", ":memory:", "backup", str(target)])
            self.assertFalse(target.exists())


class TestExternalKeys(unittest.TestCase):
    """Backup crashed with a traceback on any store whose keys are outside the
    database -- the custody SECURITY.md recommends for production. Its
    verification replay opened the copy with the default in-database key
    provider, which holds nothing for such a store."""

    def setUp(self) -> None:
        from amberlog.governance.erasure import DirectoryKeyProvider

        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.source = str(Path(self.tmp.name) / "store.db")
        self.target = str(Path(self.tmp.name) / "copy.db")
        self.keys = str(Path(self.tmp.name) / "keys")
        fabric = Amberlog(self.source, key_provider=DirectoryKeyProvider(self.keys))
        fabric.remember("agent-a", "a sealed lesson about valve 7")
        self.events = len(fabric.log)
        fabric.close()

    def test_backup_verifies_with_the_same_keys(self) -> None:
        from amberlog.governance.erasure import DirectoryKeyProvider

        self.assertEqual(
            main(["--db", self.source, "--keys", self.keys, "backup", self.target]), 0)
        copy = Amberlog(self.target, key_provider=DirectoryKeyProvider(self.keys))
        self.addCleanup(copy.close)
        self.assertEqual(len(copy.log), self.events)

    def test_it_says_the_keys_are_not_in_the_backup(self) -> None:
        import contextlib
        import io

        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            main(["--db", self.source, "--keys", self.keys, "backup", self.target])
        self.assertIn("key directory", out.getvalue())
