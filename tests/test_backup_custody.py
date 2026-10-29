"""Backup with keys and config, a manifest of hashes, and a restore that checks it."""

from __future__ import annotations

import contextlib
import io
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from amberlog import Amberlog
from amberlog.cli import main
from amberlog.governance.erasure import DirectoryKeyProvider


def quiet(*argv: str) -> int:
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        return main(list(argv))


class Custody(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(self.enterContext(TemporaryDirectory()))
        self.assertEqual(quiet("init", str(self.tmp / "memory")), 0)
        self.db, self.keys = self.tmp / "memory" / "store.db", self.tmp / "memory" / "keys"
        f = Amberlog(str(self.db), key_provider=DirectoryKeyProvider(str(self.keys)))
        self.mid = f.remember("a", "Valve V7 opens below 4 bar.", scope="team")
        f.close()
        self.backup = self.tmp / "bk" / "store.bak"
        self.assertEqual(quiet("--db", str(self.db), "--keys", str(self.keys), "backup",
                               str(self.backup), "--with-keys", "--include",
                               str(self.tmp / "memory" / "agents.txt")), 0)

    def test_restore_brings_back_readable_content_keys_and_config(self) -> None:
        dest = self.tmp / "restored"
        self.assertEqual(quiet("restore", str(self.backup), str(dest)), 0)
        self.assertTrue((dest / "config" / "agents.txt").is_file())
        f = Amberlog(str(dest / "store.db"),
                         key_provider=DirectoryKeyProvider(str(dest / "keys")))
        self.addCleanup(f.close)
        self.assertEqual(f.get(self.mid).content, "Valve V7 opens below 4 bar.")

    def test_a_tampered_backup_is_refused(self) -> None:
        manifest = self.backup.with_name(self.backup.name + ".manifest.json")
        data = json.loads(manifest.read_text(encoding="utf-8"))
        self.assertIn("store.bak.keys", " ".join(data["files"]))
        with open(self.backup, "r+b") as handle:
            handle.seek(200)
            handle.write(b"\x00tampered\x00")
        self.assertEqual(quiet("restore", str(self.backup), str(self.tmp / "r2")), 5)
        self.assertFalse((self.tmp / "r2").exists())

    def test_restore_never_overwrites(self) -> None:
        (self.tmp / "taken").mkdir()
        self.assertEqual(quiet("restore", str(self.backup), str(self.tmp / "taken")), 4)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
