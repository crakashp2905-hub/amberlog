"""Every Python block in the user-facing docs runs, as written."""

from __future__ import annotations

import contextlib
import io
import os
import re
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ["README.md", "docs/COOKBOOK.md", "docs/QUICKSTART.md", "docs/CONCEPTS.md"]
BLOCK = re.compile(r"```python\n(.*?)```", re.S)


def blocks() -> list[tuple[str, int, str]]:
    out = []
    for doc in DOCS:
        path = ROOT / doc
        if path.exists():
            for n, code in enumerate(BLOCK.findall(path.read_text(encoding="utf-8")), 1):
                out.append((doc, n, code))
    return out


class DocExamples(unittest.TestCase):
    def test_every_block_runs(self) -> None:
        self.assertGreater(len(blocks()), 5)
        for doc, n, code in blocks():
            with self.subTest(doc=doc, block=n), tempfile.TemporaryDirectory() as tmp:
                cwd = os.getcwd()
                os.chdir(tmp)
                try:
                    with contextlib.redirect_stdout(io.StringIO()):
                        exec(compile(code, f"{doc}#{n}", "exec"), {"__name__": "__doc_example__"})
                finally:
                    os.chdir(cwd)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
