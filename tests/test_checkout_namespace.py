"""Cross-version runners must select the baseline's actual code, not ambient code."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

from experiments.checkout_namespace import load_from_checkout, namespace_at
from experiments.rollback_drill import run


class CheckoutNamespace(unittest.TestCase):
    def test_historical_launcher_and_module_use_declared_package(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package = root / "prior_fixture_package"
            package.mkdir()
            (root / "pyproject.toml").write_text(
                '[tool.setuptools.packages.find]\ninclude=["prior_fixture_package*"]\n')
            (package / "__init__.py").write_text('VALUE="baseline"\n')
            (package / "__main__.py").write_text('print("baseline-launcher")\n')
            self.assertEqual(namespace_at(root), "prior_fixture_package")
            done = run(root)
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertEqual(done.stdout.strip(), "baseline-launcher")
            # Import the package through a harmless submodule and check origin.
            (package / "probe.py").write_text('VALUE="baseline"\n')
            try:
                self.assertEqual(load_from_checkout(root, "probe").VALUE, "baseline")
            finally:
                sys.path.remove(str(root.resolve()))
                load_from_checkout.cache_clear()
                sys.modules.pop("prior_fixture_package.probe", None)
                sys.modules.pop("prior_fixture_package", None)

    def test_ambiguous_checkout_fails_instead_of_guessing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pyproject.toml").write_text(
                '[tool.setuptools.packages.find]\ninclude=["one*", "two*"]\n')
            for name in ("one", "two"):
                (root / name).mkdir()
            with self.assertRaises(ValueError):
                namespace_at(root)

    def test_src_layout_launcher_resolves_the_declared_source_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package = root / "src" / "src_fixture_package"
            package.mkdir(parents=True)
            (root / "pyproject.toml").write_text(
                '[tool.setuptools.packages.find]\nwhere=["src"]\ninclude=["src_fixture_package*"]\n')
            (package / "__init__.py").write_text("")
            (package / "__main__.py").write_text('print("src-launcher")\n')
            self.assertEqual(namespace_at(root), "src_fixture_package")
            done = run(root)
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertEqual(done.stdout.strip(), "src-launcher")
