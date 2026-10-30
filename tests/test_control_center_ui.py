"""The Control Center's graph and agents views, and that its script parses."""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from memory_fabric import MemoryFabric
from memory_fabric.observability.control import agents, graph, knowledge_map
from memory_fabric.observability.server import Api

HTML = Path(__file__).resolve().parents[1] / "src" / "memory_fabric" / "observability" / "static" / "dashboard.html"


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
        self.assertIn("topics", api.handle("/api/map", {"per_topic": ["2"]}))
        self.assertTrue(api.handle("/api/agents", {}))


class TestKnowledgeMap(unittest.TestCase):
    """Topics a person can read without zooming: few, named, with what matters picked out."""

    def setUp(self):
        self.f = MemoryFabric(":memory:", auto_activate=True)
        self.addCleanup(self.f.close)
        self.wrong = self.f.remember("ag_one", "Pump P-14 relief valve opens at 12 bar.", scope="team")
        self.f.remember("ag_two", "Pump P-14 relief valve was replaced in May.", scope="team")
        self.f.remember("ag_two", "Pump P-14 relief valve has a new gasket.", scope="team")
        self.f.remember("ag_one", "Chiller C-2 setpoint is 7 C for the server room.", scope="team")
        self.f.remember("ag_one", "Chiller C-2 alarms page the night shift.", scope="team")
        self.f.remember("ag_one", "To deploy, export AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE now.", scope="team")
        self.f.quarantine(self.wrong, reason="it opens at 10 bar", actor="op")

    def test_groups_by_a_shared_word_and_names_the_topic(self):
        m = knowledge_map(self.f)
        pump = next(t for t in m["topics"] if t["label"].startswith(("Pump", "Relief", "Valve")))
        self.assertEqual(pump["size"], 3)
        self.assertTrue(any(t["label"].startswith("Chiller") for t in m["topics"]))
        self.assertEqual(m["total"], 6)

    def test_puts_the_withdrawn_memory_first_and_says_so(self):
        pump = next(t for t in knowledge_map(self.f)["topics"] if t["size"] == 3)
        self.assertEqual(pump["highlights"][0]["id"], self.wrong)
        self.assertEqual(pump["highlights"][0]["why"], "withdrawn")
        self.assertEqual(pump["states"].get("quarantined"), 1)
        self.assertTrue(any("withdrawn" in line for line in knowledge_map(self.f)["summary"]))

    def test_stays_small_and_masks_secrets(self):
        m = knowledge_map(self.f, max_topics=1, per_topic=1)
        self.assertLessEqual(len([t for t in m["topics"] if t["id"] != "_other"]), 1)
        self.assertTrue(all(len(t["highlights"]) <= 1 for t in m["topics"]))
        self.assertNotIn("AKIAIOSFODNN7EXAMPLE", repr(knowledge_map(self.f)))

    def test_an_empty_store_has_no_topics(self):
        empty = MemoryFabric(":memory:")
        self.addCleanup(empty.close)
        m = knowledge_map(empty)
        self.assertEqual((m["topics"], m["total"]), ([], 0))


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
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as fh:
            fh.write(script)
        result = subprocess.run(["node", "--check", fh.name], capture_output=True, text=True)
        Path(fh.name).unlink()
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
