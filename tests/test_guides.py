"""Framework guides: their code parses, and the memory side of it runs."""

from __future__ import annotations

import ast
import re
import unittest
from pathlib import Path

from memory_fabric import MemoryFabric
from memory_fabric.actions import ActionGate, ActionPolicy, ToolRule
from memory_fabric.integrations.tools import FabricTools
from memory_fabric.sdk import agent

GUIDES = Path(__file__).resolve().parents[1] / "docs" / "guides"


class TestGuides(unittest.TestCase):
    def test_python_blocks_parse(self):
        blocks = 0
        for guide in sorted(GUIDES.glob("*.md")):
            for code in re.findall(r"```python\n(.*?)```", guide.read_text(), re.S):
                ast.parse(code, filename=str(guide))
                blocks += 1
        self.assertGreaterEqual(blocks, 4)

    def test_guarded_runs_then_blocks_with_a_reason(self):
        f = MemoryFabric(":memory:", auto_activate=True)
        self.addCleanup(f.close)
        fact = f.remember("insp", "Pump P-14 relief valve is set to 12 bar.", scope="team")
        mem = FabricTools(agent(f, "ops"))
        gate = ActionGate(f, ActionPolicy(tools={"set_relief": ToolRule("set_relief")},
                                          grants={"ops": frozenset({"set_relief"})}))
        calls = []
        ok = mem.guarded(gate, "set_relief", [fact], lambda k: calls.append(k) or "set",
                         key="p14:12")
        self.assertEqual(ok, {"ran": True, "result": "set"})
        f.quarantine(fact, reason="vendor said 10 bar", actor="lead", basis="contradicted")
        no = mem.guarded(gate, "set_relief", [fact], lambda k: calls.append(k), key="p14:12b")
        self.assertTrue(no["blocked"])
        self.assertIn("withdrawn by lead", no["why"][0])
        self.assertEqual(calls, ["p14:12"])


if __name__ == "__main__":
    unittest.main()
