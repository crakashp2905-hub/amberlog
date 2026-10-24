"""docs/README.md lists every document in docs/."""

from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class DocIndex(unittest.TestCase):
    def test_every_doc_is_indexed(self) -> None:
        index = (ROOT / "docs" / "README.md").read_text(encoding="utf-8")
        missing = [p.name for p in sorted((ROOT / "docs").glob("*.md"))
                   if p.name != "README.md" and f"({p.name})" not in index]
        self.assertEqual(missing, [], "add these to docs/README.md")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
