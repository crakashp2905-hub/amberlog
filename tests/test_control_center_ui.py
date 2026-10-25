"""The Control Center's graph and agents views, and that its script parses."""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from memory_fabric import MemoryFabric
from memory_fabric.observability.control import agents, graph
from memory_fabric.observability.server import Api

HTML = Path(__file__).resolve().parents[1] / "memory_fabric" / "observability" / "static" / "dashboard.html"


class TestViews(unittest.TestCase):
    def setUp(self):
        self.f = MemoryFabric(":memory:", auto_activate=True)
        self.addCleanup(self.f.close)
        self.a = self.f.remember("ag_one", "Pump P-14 relief valve is set to 12 bar.", scope="team")
        self.b = self.f.derive("ag_two", "Restore P-14 relief after seal work.", [self.a])
        self.f.remember("ag_one", "To deploy, export AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE now.",
                        scope="team")
        self.f.retrieve("ag_two", "P-14 relief", k=3)

    def test_graph_has_lineage_and_masks_secrets(self):
        g = graph(self.f)
        self.assertIn({"from": self.a, "to": self.b, "kind": "derived"}, g["edges"])
        self.assertFalse(any("AKIAIOSFODNN7EXAMPLE" in n["label"] for n in g["nodes"]))
        self.assertEqual(g["total"], 3)
        self.assertLessEqual(graph(self.f, limit=1)["shown"], 1)

    def test_agents_counts(self):
        rows = {r["agent_id"]: r for r in agents(self.f)}
        self.assertEqual(rows["ag_one"]["writes"], 2)
        self.assertGreaterEqual(rows["ag_two"]["recalls"], 1)

    def test_routes(self):
        api = Api(self.f)
        self.assertIn("nodes", api.handle("/api/graph", {}))
        self.assertTrue(api.handle("/api/agents", {}))


class TestPage(unittest.TestCase):
    def test_every_tab_has_a_section_and_a_loader(self):
        html = HTML.read_text(encoding="utf-8")
        tabs = set(re.findall(r'data-tab="([a-z]+)"', html))
        for t in tabs:
            self.assertIn(f'id="tab-{t}"', html, t)
        listed = re.search(r"const TABS = \[(.*?)\];", html, re.S).group(1)
        self.assertEqual(tabs, set(re.findall(r'"([a-z]+)"', listed)))

    @unittest.skipUnless(shutil.which("node"), "node is not installed")
    def test_script_parses(self):
        html = HTML.read_text(encoding="utf-8")
        script = html[html.index("<script>") + 8: html.rindex("</script>")]
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as fh:
            fh.write(script)
        result = subprocess.run(["node", "--check", fh.name], capture_output=True, text=True)
        Path(fh.name).unlink()
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
