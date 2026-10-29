"""Brand namespace and immutable pre-migration authenticated-content vectors."""
from __future__ import annotations

import importlib.resources
import json
import subprocess
import sys
import unittest
from pathlib import Path

import amberlog
from amberlog.governance.cipher import associated_data, suite_for, aead_available

ROOT = Path(__file__).resolve().parents[1]


class Migration(unittest.TestCase):
    def test_tracked_tree_uses_canonical_branding(self):
        done = subprocess.run([sys.executable, str(ROOT / "tools/check_branding.py")],
                              capture_output=True, text=True, cwd=ROOT)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)

    def test_canonical_class_and_cli(self):
        self.assertEqual(amberlog.Amberlog.__module__, "amberlog.fabric")
        done = subprocess.run([sys.executable, "-m", "amberlog", "--help"],
                              capture_output=True, text=True, cwd=ROOT)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("amberlog", done.stdout)
        self.assertIn("AMBERLOG_", done.stdout)

    def test_pre_migration_content_vectors_still_authenticate(self):
        data = json.loads((ROOT / "tests/data/amberlog_cipher_vectors.json").read_text())
        aad = associated_data("st_prior", "01PRIOR", 1)
        self.assertEqual(aad.hex(), data["aad_hex"])
        checked = 0
        for vector in data["vectors"]:
            if vector["envelope"].startswith("enc:v3:") and not aead_available():
                continue
            plain = suite_for(vector["envelope"]).unseal(
                vector["envelope"], bytes.fromhex(data["key_hex"]), aad)
            self.assertEqual(plain.decode(), vector["plaintext"])
            checked += 1
        self.assertGreaterEqual(checked, 1)

    def test_runtime_resources_remain_in_canonical_package(self):
        self.assertTrue(importlib.resources.files("amberlog").joinpath("py.typed").is_file())
        assets = importlib.resources.files("amberlog.observability").joinpath("static")
        self.assertTrue(assets.joinpath("dashboard.html").is_file())

    def test_namespace_is_consistent_in_packaging(self):
        import tomllib

        project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
        self.assertEqual(project["name"], "amberlog")
        self.assertEqual(project["scripts"], {"amberlog": "amberlog.cli:main"})
        self.assertEqual(project["dependencies"], [])
