"""Every test a security document cites must exist.

docs/SAFETY_AND_SECURITY.md says a guarantee is listed only with test
evidence. A citation to a test that was renamed or deleted would keep the
guarantee on the page with nothing behind it, so this checks every
`test_file.py::Name` reference in those documents against the code. A trailing
`…` in a citation means "a test whose name starts with this".
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ("docs/SAFETY_AND_SECURITY.md", "docs/SECURITY_TEST_PLAN.md",
        "docs/IMPLEMENTATION_STATUS.md")
CITATION = re.compile(r"`?(test_[a-z0-9_]+\.py)(?:::([A-Za-z0-9_]+)(…)?)?")


class TestCitedTestsExist(unittest.TestCase):
    def test_every_cited_test_exists(self) -> None:
        checked = 0
        for doc in DOCS:
            text = (ROOT / doc).read_text(encoding="utf-8")
            for match in CITATION.finditer(text):
                filename, name, prefix = match.groups()
                path = ROOT / "tests" / filename
                with self.subTest(doc=doc, citation=match.group(0)):
                    self.assertTrue(path.exists(), f"{doc} cites missing {filename}")
                    if name:
                        source = path.read_text(encoding="utf-8")
                        pattern = (rf"(def|class) {re.escape(name)}"
                                   + ("" if prefix else r"\b"))
                        self.assertIsNotNone(
                            re.search(pattern, source),
                            f"{doc} cites {filename}::{name}, which does not exist")
                checked += 1
        self.assertGreater(checked, 40, "the citation pattern stopped matching")


if __name__ == "__main__":
    unittest.main()
