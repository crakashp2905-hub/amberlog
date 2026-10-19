"""The quickstart runs, end to end, exactly as docs/QUICKSTART.md shows it."""

from __future__ import annotations

import contextlib
import io
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from examples import quickstart


class Quickstart(unittest.TestCase):
    def test_store_retrieve_inspect_correct_verify(self) -> None:
        with TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()) as out:
            result = quickstart.main(str(Path(tmp) / "q.db"))
        self.assertEqual(result["status"], "contained")
        self.assertEqual(result["shown_after"], [result["right"]])
        self.assertIn("quarantined", out.getvalue())


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
