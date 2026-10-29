"""Moving a store's content keys out of the database.

The default custody keeps keys beside the ciphertext, which makes erasure
possible and does nothing against someone holding the file. External custody
existed, but only for a store *created* that way: there was no path from the
default to it, so the advice "keep keys outside the database in production"
could not be followed by anyone already running. `migrate-keys` is that path.

The order is the safety property: copy, prove a replay with the directory alone
reads everything, and only then clear the database. A failed proof clears
nothing.
"""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest

from amberlog import Amberlog
from amberlog.governance.erasure import DirectoryKeyProvider, KeyUnavailable


def _cli(*args: str, env: dict | None = None) -> subprocess.CompletedProcess:
    full_env = dict(os.environ)
    full_env.pop("AMBERLOG_KEYS", None)
    full_env.update(env or {})
    return subprocess.run([sys.executable, "-m", "amberlog", *args],
                          capture_output=True, text=True, timeout=120, env=full_env)


def _key_material_rows(db: str) -> int:
    conn = sqlite3.connect(db)
    try:
        return conn.execute(
            "SELECT COUNT(*) FROM content_keys WHERE key_material IS NOT NULL"
        ).fetchone()[0]
    finally:
        conn.close()


class MigrationCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = os.path.join(self.tmp.name, "store.db")
        self.keys = os.path.join(self.tmp.name, "keys")
        fabric = Amberlog(self.db)
        try:
            self.ids = [fabric.remember("ag", f"memory {i}: valve {i} is upstream")
                        for i in range(5)]
            self.erased = fabric.remember("ag", "to be erased")
            fabric.erase_content(self.erased, reason="subject request", actor="op")
        finally:
            fabric.close()


class TestMigrateKeys(MigrationCase):
    def test_keys_leave_the_database_and_content_stays_readable(self) -> None:
        self.assertGreater(_key_material_rows(self.db), 0)
        result = _cli("--db", self.db, "migrate-keys", self.keys)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(_key_material_rows(self.db), 0)
        fabric = Amberlog(self.db, key_provider=DirectoryKeyProvider(self.keys))
        try:
            for i, mid in enumerate(self.ids):
                self.assertIn(f"valve {i}", fabric.get(mid).content)
        finally:
            fabric.close()

    def test_the_database_alone_no_longer_reads_content(self) -> None:
        """The point of the migration: a stolen .db is not enough."""
        _cli("--db", self.db, "migrate-keys", self.keys)
        with self.assertRaises(KeyUnavailable):
            Amberlog(self.db)

    def test_an_erased_memory_stays_erased(self) -> None:
        _cli("--db", self.db, "migrate-keys", self.keys)
        self.assertFalse(os.path.exists(os.path.join(self.keys, f"{self.erased}.key")))
        fabric = Amberlog(self.db, key_provider=DirectoryKeyProvider(self.keys))
        try:
            self.assertNotIn("to be erased", fabric.get(self.erased).content)
        finally:
            fabric.close()

    def test_erasure_still_works_afterwards(self) -> None:
        _cli("--db", self.db, "migrate-keys", self.keys)
        fabric = Amberlog(self.db, key_provider=DirectoryKeyProvider(self.keys))
        try:
            self.assertTrue(fabric.erase_content(self.ids[0], reason="r", actor="op"))
            self.assertFalse(os.path.exists(os.path.join(self.keys, f"{self.ids[0]}.key")))
        finally:
            fabric.close()

    def test_the_environment_variable_supplies_the_directory(self) -> None:
        _cli("--db", self.db, "migrate-keys", self.keys)
        result = _cli("--db", self.db, "overview", env={"AMBERLOG_KEYS": self.keys})
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_key_files_are_owner_only(self) -> None:
        if os.name != "posix":
            self.skipTest("POSIX modes")
        _cli("--db", self.db, "migrate-keys", self.keys)
        mode = os.stat(os.path.join(self.keys, f"{self.ids[0]}.key")).st_mode & 0o777
        self.assertEqual(mode, 0o600)


class TestItRefusesToDoHarm(MigrationCase):
    def test_a_directory_holding_another_stores_keys_is_refused(self) -> None:
        os.makedirs(self.keys)
        with open(os.path.join(self.keys, f"{self.ids[0]}.key"), "wb") as fh:
            fh.write(b"x" * 32)
        result = _cli("--db", self.db, "migrate-keys", self.keys)
        self.assertNotEqual(result.returncode, 0)
        self.assertGreater(_key_material_rows(self.db), 0)  # nothing cleared

    def test_running_it_twice_is_refused_not_destructive(self) -> None:
        _cli("--db", self.db, "migrate-keys", self.keys)
        result = _cli("--db", self.db, "--keys", self.keys, "migrate-keys", self.keys)
        self.assertNotEqual(result.returncode, 0)
        fabric = Amberlog(self.db, key_provider=DirectoryKeyProvider(self.keys))
        fabric.close()


if __name__ == "__main__":
    unittest.main()
