"""The capability registry names only things that exist, and its status matches the code's tier.

`product/capabilities.json` is what the docs and the dashboard's status
badges say the product does. A capability listed as available must point at
modules and tests that exist, at module tiers that are stable or beta, and
at SDK, CLI, MCP and dashboard surfaces that resolve. Planned capabilities
must not claim code. The generated page must be current.
"""

from __future__ import annotations

import importlib
import json
import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = json.loads((ROOT / "product" / "capabilities.json").read_text(encoding="utf-8"))
CLI = (ROOT / "amberlog" / "cli.py").read_text(encoding="utf-8")
MCP = (ROOT / "amberlog" / "adapters" / "mcp.py").read_text(encoding="utf-8")
SERVER = (ROOT / "amberlog" / "observability" / "server.py").read_text(encoding="utf-8")


def _resolve_sdk(name: str) -> object:
    owner, _, attr = name.rpartition(".")
    if owner == "Amberlog":
        from amberlog import Amberlog
        return getattr(Amberlog, attr)
    return getattr(importlib.import_module(f"amberlog.{owner}"), attr)


class Registry(unittest.TestCase):
    def test_ids_are_unique_and_statuses_known(self) -> None:
        ids = [c["id"] for c in DATA["capabilities"]]
        self.assertEqual(len(ids), len(set(ids)))
        for c in DATA["capabilities"]:
            self.assertIn(c["status"], DATA["statuses"], c["id"])

    def test_available_capabilities_point_at_real_code_and_tests(self) -> None:
        for c in DATA["capabilities"]:
            if c["status"] not in ("available", "experimental"):
                continue
            with self.subTest(capability=c["id"]):
                self.assertTrue(c["modules"] and c["tests"], "needs code and tests")
                for path in c["modules"] + c["tests"]:
                    self.assertTrue((ROOT / path).exists(), path)
                for module in c["modules"]:
                    if not module.startswith("amberlog/"):
                        continue
                    text = (ROOT / module).read_text(encoding="utf-8")
                    tier = re.search(r'__stability__ = "(\w+)"', text)
                    if tier and c["status"] == "available":
                        self.assertIn(tier.group(1), ("stable", "beta"), module)

    def test_planned_and_unsupported_claim_no_code(self) -> None:
        for c in DATA["capabilities"]:
            if c["status"] in ("planned", "unsupported"):
                self.assertEqual((c["modules"], c["tests"]), ([], []), c["id"])
                self.assertFalse(any(c["surfaces"].values()), c["id"])

    def test_surfaces_resolve(self) -> None:
        for c in DATA["capabilities"]:
            s = c["surfaces"]
            with self.subTest(capability=c["id"]):
                if s.get("sdk"):
                    self.assertIsNotNone(_resolve_sdk(s["sdk"]))
                if s.get("cli"):
                    name = s["cli"].replace("-", "_")
                    self.assertIn(f"def cmd_{name.split()[0]}(", CLI)
                if s.get("mcp"):
                    self.assertIn(f'"name": "{s["mcp"]}"', MCP)
                if s.get("dashboard"):
                    head = s["dashboard"].split("/")[0]
                    self.assertIn(f'"{head}"', SERVER)

    def test_the_generated_page_is_current(self) -> None:
        done = subprocess.run([sys.executable, str(ROOT / "tools" / "gen_capabilities.py"),
                               "--check"], capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stdout)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
