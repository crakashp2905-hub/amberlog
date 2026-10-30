"""Frozen evidence must survive Git checkout on every supported platform."""
import hashlib
import json
from pathlib import Path
import unittest

from tools.reproduce_readiness import conformance_complete


class ReplicationArtifacts(unittest.TestCase):
    def test_empty_skipped_or_failed_conformance_cannot_qualify(self):
        self.assertTrue(conformance_complete({"run": 1}))
        for incomplete in ({"run": 0}, {"run": 1, "skipped": {"test": "optional dependency"}},
                           {"run": 1, "failures": ["test"]}, {"run": 1, "missing": ["test"]},
                           {"run": 1, "discovery_errors": ["import failed"]}):
            with self.subTest(incomplete=incomplete):
                self.assertFalse(conformance_complete(incomplete))

    def test_published_bundle_matches_every_frozen_hash(self):
        root = Path(__file__).resolve().parents[1]
        summary = json.loads((root / "research/results/no-budget-replication.json").read_text())
        manifest_path = root / summary["raw_manifest"]
        self.assertEqual(hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
                         summary["raw_manifest_sha256"])
        manifest = json.loads(manifest_path.read_text())
        self.assertEqual(manifest["independence"], "NOT_ESTABLISHED")
        self.assertEqual(manifest["release_decision"], "INCONCLUSIVE")
        self.assertTrue(manifest["deterministic_outcomes_match"])
        self.assertGreaterEqual(len(manifest["files"]), 10)
        for name, digest in manifest["files"].items():
            with self.subTest(name=name):
                self.assertEqual(hashlib.sha256((manifest_path.parent / name).read_bytes()).hexdigest(), digest)
