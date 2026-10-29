"""Upgrade-and-rollback drill with real older code (docs/OPERATIONS.md §4–5).

    python -m experiments.rollback_drill --old-ref v0.11.0

1. **Old code:** create a store, seed it (`demo`) and take a backup.
2. **New code (this checkout):** open the store, maintain it, write
   newer-schema events, and check that `doctor` is sound.
3. **Old code on the upgraded store:** `doctor` must *refuse* it (exit 5,
   schema version), never half-read it.
4. **Rollback:** restore the pre-upgrade backup. The old code's `doctor` must
   be sound again.
5. **Re-upgrade:** the new code opens the restored store and `doctor` is
   sound.

Exits non-zero on the first step that does not behave as documented.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from experiments.checkout_namespace import namespace_at

ROOT = Path(__file__).resolve().parents[1]


def run(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-m", namespace_at(cwd), *args], cwd=cwd,
                          capture_output=True, text=True, timeout=300)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--old-ref", default="v0.11.0")
    args = parser.parse_args(argv)
    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        old = tmpdir / "old"
        subprocess.run(["git", "worktree", "add", "--detach", "-q", str(old), args.old_ref],
                       cwd=ROOT, check=True)
        try:
            store, backup = tmpdir / "store.db", tmpdir / "pre-upgrade.db"
            keys = ["--keys", str(tmpdir / "keys")]
            steps = [
                ("old: seed", run(old, "--db", str(store), *keys, "--create", "demo"), {0}),
                ("old: backup", run(old, "--db", str(store), *keys, "backup", str(backup)), {0}),
                ("new: maintain (writes newer-schema events)",
                 run(ROOT, "--db", str(store), *keys, "maintain", "--once"), {0}),
                ("new: doctor", run(ROOT, "--db", str(store), *keys, "doctor"), {0, 1}),
                ("old: doctor refuses the upgraded store",
                 run(old, "--db", str(store), *keys, "doctor"), {5}),
            ]
            for name, done, ok in steps:
                print(f"  {'ok ' if done.returncode in ok else 'BAD'} {name} (exit {done.returncode})")
                if done.returncode not in ok:
                    print(done.stdout[-1500:], done.stderr[-1500:])
                    return 1
            for suffix in ("", "-wal", "-shm"):
                Path(str(store) + suffix).unlink(missing_ok=True)
            shutil.copy(backup, store)
            for name, done, ok in [
                ("rollback: old doctor on the restored backup",
                 run(old, "--db", str(store), *keys, "doctor"), {0, 1}),
                ("re-upgrade: new doctor on the restored store",
                 run(ROOT, "--db", str(store), *keys, "doctor"), {0, 1}),
            ]:
                print(f"  {'ok ' if done.returncode in ok else 'BAD'} {name} (exit {done.returncode})")
                if done.returncode not in ok:
                    print(done.stdout[-1500:], done.stderr[-1500:])
                    return 1
        finally:
            subprocess.run(["git", "worktree", "remove", "--force", str(old)], cwd=ROOT)
    print("rollback drill: every step behaved as documented")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
