"""The container's choice of key custody, tested without Docker.

`docker-entrypoint.sh` decides whether the dashboard opens a store with external
keys. Getting it wrong either way is bad: a new store with in-database keys
silently loses the protection the image advertises, and an old store pointed at
an empty key directory cannot be opened at all. CI's docker job builds and runs
the real image; this pins the decision itself, with a stub `memory_fabric` on
PATH that records what it was asked to do.
"""

from __future__ import annotations

import os
import pathlib
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
ENTRYPOINT = ROOT / "docker-entrypoint.sh"


@unittest.skipUnless(os.name == "posix", "the entrypoint is a POSIX shell script")
class TestEntrypoint(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = pathlib.Path(self.tmp.name)
        self.bin = base / "bin"
        self.bin.mkdir()
        self.record = base / "invocation"
        stub = self.bin / "memory_fabric"
        stub.write_text(
            "#!/bin/sh\n"
            f'echo "KEYS=${{MEMORY_FABRIC_KEYS:-}} ARGS=$*" > "{self.record}"\n'
        )
        stub.chmod(0o755)
        self.db = base / "data" / "store.db"
        self.db.parent.mkdir()
        self.keys = base / "keys"
        self.keys.mkdir()

    def run_entrypoint(self) -> tuple[str, str]:
        env = {
            "PATH": f"{self.bin}:/usr/bin:/bin",
            "MEMORY_FABRIC_DB": str(self.db),
            "MEMORY_FABRIC_KEYS": str(self.keys),
        }
        done = subprocess.run(["sh", str(ENTRYPOINT)], env=env,
                              capture_output=True, text=True, timeout=30)
        self.assertEqual(done.returncode, 0, done.stderr)
        return self.record.read_text().strip(), done.stderr

    def test_a_new_store_uses_the_key_volume(self) -> None:
        invocation, _ = self.run_entrypoint()
        self.assertIn(f"KEYS={self.keys}", invocation)
        self.assertIn("serve --host 0.0.0.0", invocation)

    def test_an_existing_store_with_external_keys_keeps_them(self) -> None:
        self.db.write_bytes(b"")
        (self.keys / "01ABC.key").write_bytes(b"k" * 32)
        invocation, _ = self.run_entrypoint()
        self.assertIn(f"KEYS={self.keys}", invocation)

    def test_an_old_store_with_in_database_keys_still_opens_and_is_warned(self) -> None:
        self.db.write_bytes(b"")
        invocation, stderr = self.run_entrypoint()
        self.assertIn("KEYS= ", invocation + " ")
        self.assertIn("migrate-keys", stderr)


if __name__ == "__main__":
    unittest.main()
