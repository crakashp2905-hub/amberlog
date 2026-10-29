"""The opt-in MCP tools: context, provenance, correction preview, branches.

Off by default (the default surface is pinned in test_mcp.py). On, each tool
is limited to what the agent may read, and none can apply a merge or a
correction.
"""

from __future__ import annotations

import json
import unittest

from amberlog import Amberlog
from amberlog.adapters.mcp import EXTENDED_TOOLS, McpServer
from amberlog.branching import Branches
from amberlog.sdk import agent


class Extended(unittest.TestCase):
    def setUp(self) -> None:
        self.f = Amberlog(":memory:", auto_activate=True)
        self.addCleanup(self.f.close)
        self.p1 = self.f.remember("ag_mcp", "Pump P1 runs at 4 bar.", scope="team")
        self.child = self.f.derive("ag_mcp", "Line 1 is safe at 4 bar.", parents=[self.p1],
                                   scope="team")
        self.hidden = self.f.remember("other", "Pump P1 vendor note: 4 bar.", scope="private")
        self.server = McpServer(agent(self.f, "ag_mcp"), self.f, extended=True)

    def call(self, tool: str, **arguments: object) -> tuple[dict, bool]:
        r = self.server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                "params": {"name": tool, "arguments": arguments}})
        assert r is not None
        return json.loads(r["result"]["content"][0]["text"]), r["result"]["isError"]

    def test_off_by_default(self) -> None:
        plain = McpServer(agent(self.f, "ag_mcp"), self.f)
        names = {t["name"] for t in plain.tools()}
        self.assertFalse(names & {t["name"] for t in EXTENDED_TOOLS})
        self.assertEqual(len({t["name"] for t in self.server.tools()}), 4 + len(EXTENDED_TOOLS))

    def test_no_tool_applies_a_merge_or_a_correction(self) -> None:
        names = {t["name"] for t in self.server.tools()}
        self.assertFalse({n for n in names if "apply" in n or "withdraw" in n or "quarantine" in n})

    def test_build_and_explain_context(self) -> None:
        out, err = self.call("build_context", query="pump p1", mode="evidence-first")
        self.assertFalse(err, out)
        self.assertIn("Pump P1 runs at 4 bar.", out["context"])
        self.assertNotIn("vendor note", out["context"])
        explained, err = self.call("explain_context", receipt_id=out["receipt_id"])
        self.assertFalse(err)
        self.assertTrue(all(s["admissible_now"] for s in explained["selected"]))

    def test_another_agents_receipt_is_not_readable(self) -> None:
        from amberlog.context_receipt import build_context

        rid = build_context(self.f, "other", "pump").receipt["receipt_id"]
        out, err = self.call("explain_context", receipt_id=rid)
        self.assertTrue(err)

    def test_provenance_and_correction_preview_list_only_readable_memories(self) -> None:
        out, err = self.call("trace_provenance", memory_id=self.child)
        self.assertFalse(err, out)
        self.assertIn(self.p1, out["derived_from"])
        out, err = self.call("preview_correction", memory_id=self.p1)
        self.assertEqual(out["would_contest"], [self.child])
        for tool in ("trace_provenance", "preview_correction"):
            out, err = self.call(tool, memory_id=self.hidden)
            self.assertTrue(err)
            self.assertIn("not a memory you can read", out["error"])
            out2, _ = self.call(tool, memory_id="01M5DOESNOTEXIST000000000")
            self.assertEqual(out["error"].split(" is ")[1], out2["error"].split(" is ")[1])

    def test_branch_create_propose_and_preview(self) -> None:
        out, err = self.call("branch_create", name="idea", reviewers=["lead"])
        self.assertFalse(err, out)
        out, err = self.call("branch_propose", branch="idea", content="Pump P1 runs at 5 bar.",
                             revises=self.p1)
        self.assertFalse(err, out)
        self.assertEqual(out["state"], "candidate")
        self.assertEqual(self.f.get(self.p1).content, "Pump P1 runs at 4 bar.")
        out, err = self.call("merge_preview", branch="idea")
        self.assertFalse(err, out)
        self.assertEqual(out["changes"][0]["decision"], "allow_with_warning")

    def test_proposing_to_a_branch_the_agent_does_not_own_is_refused(self) -> None:
        Branches(self.f).create("theirs", owner="other")
        out, err = self.call("branch_propose", branch="theirs", content="Pump P9 runs at 1 bar.")
        self.assertTrue(err)

    def test_revising_an_unreadable_memory_is_refused(self) -> None:
        self.call("branch_create", name="idea")
        out, err = self.call("branch_propose", branch="idea", content="x 5 bar",
                             revises=self.hidden)
        self.assertTrue(err)



class DecayTools(unittest.TestCase):
    def setUp(self) -> None:
        self.f = Amberlog(":memory:", auto_activate=True)
        self.addCleanup(self.f.close)
        for i in range(30):
            self.f.remember("ag_mcp", f"Pump P{i} runs at {i + 10} bar.", scope="team")
        self.server = McpServer(agent(self.f, "ag_mcp"), self.f, extended=True)

    def call(self, tool: str, **arguments: object) -> tuple[dict, bool]:
        r = self.server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                "params": {"name": tool, "arguments": arguments}})
        assert r is not None
        return json.loads(r["result"]["content"][0]["text"]), r["result"]["isError"]

    def test_wake_nap_zoom(self) -> None:
        out, err = self.call("wake", budget=120)
        self.assertFalse(err, out)
        self.assertIn("<retrieved_memories>", out["memory"])
        pending, _ = self.call("nap", budget=120)
        node = pending["pending"][0]["node"]
        lo, hi = map(int, node.split("-"))
        nums = sorted(int(w) for r in pending["pending"][0]["records"] for w in r.split()
                      if w.isdigit())
        out, err = self.call("nap", node=node, summary=f"Pumps run {nums[0]} to {nums[-1]} bar.")
        self.assertFalse(err, out)
        bad, err = self.call("nap", node=node, summary="Pumps run at 999 bar.")
        self.assertTrue(err)
        out, err = self.call("zoom", node=node)
        self.assertFalse(err, out)
        out, err = self.call("zoom", node="nope")
        self.assertTrue(err)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
