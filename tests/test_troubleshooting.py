"""Every reason code a user can be shown is explained in docs/TROUBLESHOOTING.md."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def codes() -> set[str]:
    found = set()
    for module in ("memory_fabric/actions.py", "memory_fabric/certificates.py"):
        text = (ROOT / module).read_text(encoding="utf-8")
        for name, value in re.findall(r'^([A-Z_]+) = "([a-z_]+)"$', text, re.M):
            if not name.startswith("CHECK_") and name not in ("OK", "ALLOWED",
                                                               "ACTION_POLICY_VERSION"):
                found.add(value)
    limits = (ROOT / "memory_fabric/limits.py").read_text(encoding="utf-8")
    found |= set(re.findall(r'LimitExceeded\("([a-z_]+)"', limits))
    found |= set(re.findall(r'^\s+"([a-z_]+_exhausted)"\)', limits, re.M))
    return found


class Troubleshooting(unittest.TestCase):
    def test_every_code_is_explained(self) -> None:
        doc = (ROOT / "docs" / "TROUBLESHOOTING.md").read_text(encoding="utf-8")
        self.assertGreater(len(codes()), 30)
        missing = sorted(c for c in codes() if f"`{c}`" not in doc)
        self.assertEqual(missing, [])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
