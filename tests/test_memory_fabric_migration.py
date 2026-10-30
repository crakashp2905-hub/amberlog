"""Brand namespace and immutable pre-migration authenticated-content vectors."""
from __future__ import annotations

import importlib.resources
import json
import subprocess
import sys
import unittest
import io
from unittest import mock
from pathlib import Path

import memory_fabric
from memory_fabric.governance.cipher import associated_data, suite_for, aead_available

ROOT = Path(__file__).resolve().parents[1]


class Migration(unittest.TestCase):
    def test_brand_guard_rejects_wrapped_retired_spellings(self):
        import tempfile
        from tools import check_branding

        retired = "".join(map(chr, (97, 109, 98, 101, 114, 108, 111, 103)))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            document = root / "sample.md"
            document.write_text("prefix " + retired + " suffix", encoding="utf-8")
            with mock.patch.object(check_branding, "ROOT", root), \
                 mock.patch.object(check_branding.subprocess, "check_output", return_value=b"sample.md\0"), \
                 mock.patch("sys.stdout", new_callable=io.StringIO):
                self.assertEqual(check_branding.main(), 1)
                document.write_text("Memory Fabric", encoding="utf-8")
                self.assertEqual(check_branding.main(), 0)

    def test_tracked_tree_uses_canonical_branding(self):
        done = subprocess.run([sys.executable, str(ROOT / "tools/check_branding.py")],
                              capture_output=True, text=True, cwd=ROOT)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)

    def test_canonical_class_and_cli(self):
        self.assertEqual(memory_fabric.MemoryFabric.__module__, "memory_fabric.fabric")
        done = subprocess.run([sys.executable, "-m", "memory_fabric", "--help"],
                              capture_output=True, text=True, cwd=ROOT)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("memory_fabric", done.stdout)
        self.assertIn("MEMORY_FABRIC_", done.stdout)

    def test_pre_migration_content_vectors_still_authenticate(self):
        data = json.loads((ROOT / "tests/data/memory_fabric_cipher_vectors.json").read_text())
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
        self.assertTrue(importlib.resources.files("memory_fabric").joinpath("py.typed").is_file())
        assets = importlib.resources.files("memory_fabric.observability").joinpath("static")
        self.assertTrue(assets.joinpath("dashboard.html").is_file())

    def test_namespace_is_consistent_in_packaging(self):
        import tomllib

        project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
        self.assertEqual(project["name"], "memory-fabric")
        self.assertEqual(project["scripts"], {"memory-fabric": "memory_fabric.cli:main"})
        self.assertEqual(project["dependencies"], [])
        packaging = tomllib.loads((ROOT / "pyproject.toml").read_text())["tool"]["setuptools"]
        self.assertEqual(packaging["packages"]["find"]["where"], ["src"])
        self.assertTrue(Path(memory_fabric.__file__).resolve().is_relative_to(ROOT / "src"))
