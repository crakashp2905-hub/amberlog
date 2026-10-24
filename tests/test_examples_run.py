"""Every offline example runs to completion from a clean process."""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OFFLINE = ["quickstart", "wrong_memory_demo", "reference_agent", "poisoning_and_rollback", "action_gate",
           "agent_on_the_fabric"]


class Examples(unittest.TestCase):
    def test_offline_examples_run(self) -> None:
        listed = {p.stem for p in (ROOT / "examples").glob("*.py")}
        self.assertEqual(listed - set(OFFLINE), {"live_memory_os"},
                         "a new example must be added here, or to the live list")
        for name in OFFLINE:
            with self.subTest(example=name):
                done = subprocess.run([sys.executable, str(ROOT / "examples" / f"{name}.py")],
                                      capture_output=True, text=True, timeout=300, cwd=ROOT)
                self.assertEqual(done.returncode, 0, done.stderr[-2000:])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
