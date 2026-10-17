"""The suite CI runs is the suite the documents describe.

Two ways that broke here. A test file written in pytest style (plain
`def test_` functions, `import pytest`) is collected by pytest locally and
**not at all** by CI's `unittest discover`, which also fails on the import
because CI installs nothing: `tests/test_memeval.py` was such a file for a
day. And documents quoted test counts that had drifted from the suite by
hundreds. Both are checked here.
"""

from __future__ import annotations

import ast
import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

_spec = importlib.util.spec_from_file_location("count_tests", ROOT / "tools" / "count_tests.py")
assert _spec and _spec.loader
count_tests = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(count_tests)


class TestEveryTestRunsUnderUnittest(unittest.TestCase):
    def test_no_file_needs_pytest(self) -> None:
        for path in sorted((ROOT / "tests").glob("test_*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            with self.subTest(file=path.name):
                for node in tree.body:
                    if isinstance(node, (ast.Import, ast.ImportFrom)):
                        names = ([a.name for a in node.names] if isinstance(node, ast.Import)
                                 else [node.module or ""])
                        self.assertFalse(any(n.split(".")[0] == "pytest" for n in names),
                                         "imports pytest, which CI does not install")
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        self.assertFalse(node.name.startswith("test"),
                                         f"module-level {node.name}() is invisible to unittest")


class TestCitedCountsAreCurrent(unittest.TestCase):
    def test_documents_cite_the_real_count(self) -> None:
        n = count_tests.count()
        for doc, cited in count_tests.cited().items():
            with self.subTest(doc=doc):
                self.assertIsNotNone(cited, f"{doc}: no current test count found")
                self.assertEqual(cited, n, f"{doc} cites {cited} tests; the suite has {n}. "
                                 "Fix: python tools/count_tests.py --write")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
