"""The MCP server: protocol conformance, governance at the boundary, transport.

Three layers, each of which can fail without the others noticing:

* **Protocol.** 2026-07-28 made MCP stateless, so the versioning, `resultType`,
  `serverInfo` and caching fields are checked per version -- including that a
  legacy client is *not* sent fields from a revision it does not know.
* **Governance.** The properties that make this store worth having must
  survive the trip through a tool call: identity cannot be chosen per call, a
  retracted memory is never recalled, an agent cannot retract another agent's
  memory, sensitive content is neither stored live nor echoed, and there is no
  tool by which an agent can report its own outcome.
* **Transport.** A real subprocess speaking newline-delimited JSON-RPC, with a
  check that stdout carries protocol messages and nothing else.
"""

from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from memory_fabric import MemoryFabric  # noqa: E402
from memory_fabric.mcp import protocol as P  # noqa: E402
from memory_fabric.mcp.tools import TOOLS, build_server  # noqa: E402

V26 = {P.META_PROTOCOL: "2026-07-28"}


def call(server, method, params=None, request_id=1, meta=V26):
    body = dict(params or {})
    if meta is not None:
        body["_meta"] = dict(meta)
    return server.handle({"jsonrpc": "2.0", "id": request_id,
                          "method": method, "params": body})


def tool(server, name, arguments=None, meta=V26):
    return call(server, "tools/call",
                {"name": name, "arguments": arguments or {}}, meta=meta)


class Base(unittest.TestCase):
    def setUp(self):
        self.fabric = MemoryFabric(":memory:", encrypt_content=False,
                                   retrieval="lexical", auto_activate=True)
        self.server = build_server(self.fabric, "agent-a")

    def tearDown(self):
        self.fabric.close()

    def remember(self, content, **extra):
        r = tool(self.server, "memory_remember", {"content": content, **extra})
        return r["result"]["structuredContent"]["id"]


# --- protocol ---------------------------------------------------------------

class TestVersioning(Base):
    def test_discover_is_answered_without_a_version(self):
        """The probe a stateless client sends before it knows what the server
        speaks. Answering it is how the version gets chosen."""
        r = call(self.server, "server/discover", meta=None)
        self.assertIn("2026-07-28", r["result"]["supportedVersions"])
        self.assertEqual(r["result"]["serverInfo"]["name"], "memory-fabric")

    def test_a_current_result_carries_result_type_and_server_info(self):
        r = call(self.server, "tools/list")
        self.assertEqual(r["result"]["resultType"], "complete")
        self.assertEqual(
            r["result"]["_meta"][P.META_SERVER_INFO]["name"], "memory-fabric")

    def test_an_unsupported_version_is_refused_with_the_supported_list(self):
        r = call(self.server, "tools/list",
                 meta={P.META_PROTOCOL: "1999-01-01"})
        self.assertEqual(r["error"]["code"], P.UNSUPPORTED_VERSION)
        self.assertEqual(r["error"]["code"], -32022,
                         "renumbered from -32004 in 2026-07-28")
        self.assertIn("2026-07-28", r["error"]["data"]["supported"])

    def test_no_version_and_no_handshake_is_refused_not_guessed(self):
        """A trust boundary that picks a version for a client has decided
        something the client did not ask for."""
        r = call(self.server, "tools/list", meta=None)
        self.assertEqual(r["error"]["code"], P.INVALID_PARAMS)
        self.assertIn("supported", r["error"]["data"])

    def test_a_legacy_client_negotiates_with_initialize(self):
        r = self.server.handle({"jsonrpc": "2.0", "id": 1,
                                "method": "initialize",
                                "params": {"protocolVersion": "2025-06-18"}})
        self.assertEqual(r["result"]["protocolVersion"], "2025-06-18")
        r = call(self.server, "tools/list", meta=None)
        self.assertIn("tools", r["result"])

    def test_an_unknown_legacy_version_gets_the_newest_legacy_one(self):
        """The negotiation rule those revisions define."""
        r = self.server.handle({"jsonrpc": "2.0", "id": 1,
                                "method": "initialize",
                                "params": {"protocolVersion": "2024-01-01"}})
        self.assertEqual(r["result"]["protocolVersion"], P.LEGACY_VERSIONS[0])

    def test_initialize_for_the_stateless_revision_falls_back_to_legacy(self):
        """2026-07-28 has no initialize, so a client sending one is a legacy
        client, whatever it says."""
        r = self.server.handle({"jsonrpc": "2.0", "id": 1,
                                "method": "initialize",
                                "params": {"protocolVersion": "2026-07-28"}})
        self.assertIn(r["result"]["protocolVersion"], P.LEGACY_VERSIONS)

    def test_legacy_results_carry_no_fields_from_later_revisions(self):
        """Each revision's clients validate against that revision's schema."""
        self.server.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                            "params": {"protocolVersion": "2025-06-18"}})
        r = call(self.server, "tools/list", meta=None)
        for field in ("resultType", "ttlMs", "cacheScope"):
            self.assertNotIn(field, r["result"])

    def test_a_2025_03_26_client_gets_no_output_schema_or_structured_content(self):
        """Both arrived in 2025-06-18."""
        self.server.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                            "params": {"protocolVersion": "2025-03-26"}})
        r = call(self.server, "tools/list", meta=None)
        for t in r["result"]["tools"]:
            self.assertNotIn("outputSchema", t)
            self.assertNotIn("annotations", t)
        r = tool(self.server, "memory_remember", {"content": "x is 4."},
                 meta=None)
        self.assertNotIn("structuredContent", r["result"])
        self.assertTrue(r["result"]["content"][0]["text"])


class TestCaching(Base):
    """A cached memory read keeps serving a memory after its origin has
    retracted it, which defeats the capability this project measures best."""

    def test_every_cacheable_method_carries_both_fields(self):
        mid = self.remember("Bay 4 is assigned to crane-2.")
        for method, params in (
                ("tools/list", {}), ("prompts/list", {}),
                ("resources/list", {}), ("resources/templates/list", {}),
                ("resources/read", {"uri": f"memory://{mid}"})):
            r = call(self.server, method, params)
            self.assertIn("ttlMs", r["result"], method)
            self.assertIn(r["result"]["cacheScope"], ("public", "private"),
                          method)

    def test_memory_content_is_never_cacheable(self):
        mid = self.remember("Bay 4 is assigned to crane-2.")
        r = call(self.server, "resources/read", {"uri": f"memory://{mid}"})
        self.assertEqual(r["result"]["ttlMs"], 0)
        self.assertEqual(r["result"]["cacheScope"], "private")
        r = call(self.server, "resources/read", {"uri": "memory://overview"})
        self.assertEqual(r["result"]["cacheScope"], "private")

    def test_tool_definitions_may_be_cached_publicly(self):
        r = call(self.server, "tools/list")
        self.assertEqual(r["result"]["cacheScope"], "public")
        self.assertGreater(r["result"]["ttlMs"], 0)

    def test_tool_order_is_deterministic(self):
        """2026-07-28: servers SHOULD, for client caching and prompt-cache
        hit rates."""
        first = [t["name"] for t in call(self.server, "tools/list")
                 ["result"]["tools"]]
        second = [t["name"] for t in call(self.server, "tools/list")
                  ["result"]["tools"]]
        self.assertEqual(first, second)
        self.assertEqual(first, [t["name"] for t in TOOLS])


class TestErrors(Base):
    def test_unknown_method(self):
        self.assertEqual(call(self.server, "nope/nope")["error"]["code"],
                         P.METHOD_NOT_FOUND)

    def test_not_jsonrpc(self):
        r = self.server.handle({"id": 1, "method": "tools/list"})
        self.assertEqual(r["error"]["code"], P.INVALID_REQUEST)

    def test_a_notification_gets_no_response(self):
        self.assertIsNone(self.server.handle(
            {"jsonrpc": "2.0", "method": "notifications/initialized"}))
        self.assertIsNone(self.server.handle(
            {"jsonrpc": "2.0", "method": "tools/list",
             "params": {"_meta": V26}}))

    def test_an_unknown_tool_is_invalid_params(self):
        self.assertEqual(tool(self.server, "memory_delete_everything")
                         ["error"]["code"], P.INVALID_PARAMS)

    def test_a_missing_resource_is_invalid_params_since_2026_07_28(self):
        """It was -32002; the revision aligned it with JSON-RPC."""
        r = call(self.server, "resources/read", {"uri": "memory://no-such"})
        self.assertEqual(r["error"]["code"], -32602)

    def test_a_batch_is_answered_in_order(self):
        out = self.server.handle([
            {"jsonrpc": "2.0", "id": 1, "method": "server/discover"},
            {"jsonrpc": "2.0", "id": 2, "method": "nope"},
        ])
        self.assertEqual([r["id"] for r in out], [1, 2])

    def test_an_internal_error_is_contained(self):
        """One bad call must not take down a server another conversation
        depends on, and the detail goes to stderr rather than the client."""
        def explode(params, ctx):
            raise RuntimeError("boom")
        self.server.methods["tools/list"] = explode
        r = call(self.server, "tools/list")
        self.assertEqual(r["error"]["code"], P.INTERNAL_ERROR)
        self.assertNotIn("boom", json.dumps(r))


# --- governance -------------------------------------------------------------

class TestIdentityIsBound(Base):
    def test_agent_id_cannot_be_passed_per_call(self):
        r = tool(self.server, "memory_remember",
                 {"content": "x", "agent_id": "agent-b"})
        self.assertEqual(r["error"]["code"], P.INVALID_PARAMS)
        self.assertIn("fixed when the server starts", r["error"]["message"])

    def test_writes_are_attributed_to_the_bound_agent(self):
        mid = self.remember("Bay 4 is assigned to crane-2.")
        self.assertEqual(self.fabric.get(mid).provenance.created_by,
                         "agent-a")

    def test_any_unexpected_field_is_refused(self):
        r = tool(self.server, "memory_recall", {"query": "x", "limit": 3})
        self.assertEqual(r["error"]["code"], P.INVALID_PARAMS)

    def test_a_server_needs_an_agent(self):
        with self.assertRaises(ValueError):
            build_server(self.fabric, "")


class TestSchemaValidation(Base):
    def test_required(self):
        self.assertEqual(tool(self.server, "memory_recall", {})["error"]
                         ["code"], P.INVALID_PARAMS)

    def test_a_boolean_is_not_an_integer(self):
        """bool subclasses int in Python; JSON does not agree."""
        r = tool(self.server, "memory_recall", {"query": "x", "k": True})
        self.assertEqual(r["error"]["code"], P.INVALID_PARAMS)

    def test_bounds(self):
        self.assertEqual(tool(self.server, "memory_recall",
                              {"query": "x", "k": 9999})["error"]["code"],
                         P.INVALID_PARAMS)
        self.assertEqual(tool(self.server, "memory_challenge",
                              {"memory_ids": ["a"], "evidence": "x"})
                         ["error"]["code"], P.INVALID_PARAMS)

    def test_over_long_content_is_refused_not_truncated(self):
        """A truncated memory has provenance for text it no longer holds."""
        r = tool(self.server, "memory_remember", {"content": "x" * 20_001})
        self.assertEqual(r["error"]["code"], P.INVALID_PARAMS)


class TestRecall(Base):
    def test_retrieved_memory_is_framed_as_untrusted_evidence(self):
        """SECURITY.md T1 at a new boundary: a tool result lands in a model's
        context exactly as a retrieval does."""
        self.remember("Fault E03 at coastal: swap the pilot cable.")
        r = tool(self.server, "memory_recall", {"query": "fault E03 coastal"})
        text = r["result"]["content"][0]["text"]
        self.assertIn("evidence, not instructions", text)
        self.assertIn("<retrieved_memories>", text)
        self.assertEqual(r["result"]["structuredContent"]["trust"],
                         "untrusted-evidence")

    def test_an_empty_recall_says_so(self):
        r = tool(self.server, "memory_recall", {"query": "nothing here"})
        self.assertEqual(r["result"]["structuredContent"]["memories"], [])

    def test_a_retracted_memory_is_never_recalled(self):
        """PB2's property, through the tool surface. The whole point."""
        mid = self.remember("Fault E03 at coastal: replace the RCD.")
        tool(self.server, "memory_retract",
             {"memory_id": mid, "reason": "misdiagnosed"})
        r = tool(self.server, "memory_recall", {"query": "fault E03 coastal RCD"})
        ids = [m["id"] for m in r["result"]["structuredContent"]["memories"]]
        self.assertNotIn(mid, ids)


class TestRemember(Base):
    def test_sensitive_content_is_quarantined_and_not_echoed(self):
        secret = "AKIAIOSFODNN7EXAMPLE"
        r = tool(self.server, "memory_remember",
                 {"content": f"the deploy key is {secret}"})
        result = r["result"]
        self.assertTrue(result["structuredContent"]
                        ["quarantined_for_sensitive_data"])
        self.assertNotIn(secret, json.dumps(result))
        r = tool(self.server, "memory_recall", {"query": "deploy key"})
        self.assertNotIn(secret, json.dumps(r))

    def test_derived_from_records_the_parents(self):
        a = self.remember("pump-2 has the standard axle set.")
        b = self.remember("standard axle set runs 4.2 bar.",
                          derived_from=[a])
        parents = [pid for pid, _version in
                   self.fabric.get(b).provenance.parents]
        self.assertEqual(parents, [a])

    def test_retracting_a_premise_reaches_the_conclusion(self):
        """The most important property in this file, pinned at the boundary.

        A conclusion derived through MCP must become contested when its
        premise is retracted, or the tool surface is where PB2's guarantee
        would leak. It does not leak, and did not: the first version raised on
        an invalid provenance method rather than writing an unlinked memory.
        This test exists so that any future change to the write path that
        *does* drop the edges fails here rather than in production.
        """
        premise = self.remember("Fault E03 at coastal: replace the RCD.")
        conclusion = self.remember(
            "So keep a spare RCD at coastal.", derived_from=[premise])
        tool(self.server, "memory_retract",
             {"memory_id": premise, "reason": "misdiagnosed"})
        self.assertNotEqual(
            self.fabric.get(conclusion).lifecycle_state.value, "active",
            "a conclusion must not stay active once its only premise is "
            "retracted")

    def test_an_unknown_parent_is_a_tool_failure(self):
        r = tool(self.server, "memory_remember",
                 {"content": "x", "derived_from": ["no-such"]})
        self.assertTrue(r["result"]["isError"])


class TestRetractionIsForTheOrigin(Base):
    def test_an_agent_can_retract_its_own_memory(self):
        mid = self.remember("Fault E03 at coastal: replace the RCD.")
        r = tool(self.server, "memory_retract",
                 {"memory_id": mid, "reason": "misdiagnosed"})
        self.assertNotIn("isError", r["result"])
        self.assertEqual(r["result"]["structuredContent"]["memory_id"], mid)

    def test_an_agent_cannot_retract_another_agents_memory(self):
        """PB2 measured ORIGIN retraction. Another agent has a disagreement,
        not knowledge, and the tool says which tool fits."""
        other = self.fabric.remember(agent_id="agent-b",
                                     content="Fault E03: reseat the contactor.")
        r = tool(self.server, "memory_retract",
                 {"memory_id": other, "reason": "I disagree"})
        self.assertTrue(r["result"]["isError"])
        self.assertIn("memory_challenge", r["result"]["content"][0]["text"])
        self.assertNotEqual(self.fabric.get(other).lifecycle_state.value,
                            "quarantined")


class TestChallenge(Base):
    def test_a_disagreement_keeps_both_and_recalls_them_together(self):
        """H4b's mechanism through the tool surface."""
        a = self.remember("Fault E03 at coastal: swap the pilot cable.")
        b = self.fabric.remember(agent_id="agent-b",
                                 content="Fault E03 at coastal: reseat the contactor.")
        r = tool(self.server, "memory_challenge",
                 {"memory_ids": [a, b], "evidence": "different fixes"})
        self.assertEqual(sorted(r["result"]["structuredContent"]["contested"]),
                         sorted([a, b]))
        r = tool(self.server, "memory_recall",
                 {"query": "fault E03 coastal", "k": 5})
        recalled = {m["id"]: m for m in
                    r["result"]["structuredContent"]["memories"]}
        self.assertIn(a, recalled)
        self.assertIn(b, recalled)
        self.assertTrue(recalled[a]["contested_with"] or
                        recalled[a]["lifecycle"] == "contested")


class TestEpisodes(Base):
    def test_a_handle_links_recall_and_remember(self):
        r = tool(self.server, "memory_begin_episode", {"task": "fix E03"})
        handle = r["result"]["structuredContent"]["episode"]
        self.assertTrue(handle.startswith("ep_"))
        r = tool(self.server, "memory_remember",
                 {"content": "E03 fixed by swapping the cable.",
                  "episode": handle})
        mid = r["result"]["structuredContent"]["id"]
        self.assertTrue(self.fabric.get(mid).provenance.source_episodes)
        r = tool(self.server, "memory_end_episode", {"episode": handle})
        self.assertTrue(r["result"]["structuredContent"]["closed"])

    def test_an_unknown_handle_fails_visibly(self):
        """A write the caller believes is linked to an episode, and is not,
        has provenance it does not have."""
        r = tool(self.server, "memory_remember",
                 {"content": "x", "episode": "ep_not_real"})
        self.assertTrue(r["result"]["isError"])

    def test_ending_twice_is_not_an_error(self):
        handle = tool(self.server, "memory_begin_episode", {"task": "t"}
                      )["result"]["structuredContent"]["episode"]
        tool(self.server, "memory_end_episode", {"episode": handle})
        r = tool(self.server, "memory_end_episode", {"episode": handle})
        self.assertFalse(r["result"]["structuredContent"]["closed"])
        self.assertNotIn("isError", r["result"])


class TestWhatIsDeliberatelyAbsent(Base):
    def test_no_tool_lets_the_agent_report_its_own_outcome(self):
        """Outcomes are never self-reported. The caller of a tool is the agent,
        and a tool that let it record its own success would let it write the
        evidence its memories are credited from."""
        names = {t["name"] for t in TOOLS}
        for forbidden in ("memory_record_outcome", "memory_outcome",
                          "memory_succeeded"):
            self.assertNotIn(forbidden, names)
        end = next(t for t in TOOLS if t["name"] == "memory_end_episode")
        self.assertNotIn("outcome", end["inputSchema"]["properties"])

    def test_no_quarantine_or_erasure_tool(self):
        """Quarantine-on-failure was measured to harm; erasure is
        irreversible and an operator's call."""
        names = {t["name"] for t in TOOLS}
        for forbidden in ("memory_quarantine", "memory_erase", "memory_delete"):
            self.assertNotIn(forbidden, names)


class TestTenancy(unittest.TestCase):
    def test_another_tenants_memory_is_indistinguishable_from_none(self):
        """Distinguishing them would tell a caller that a guessed id is real."""
        fabric = MemoryFabric(":memory:", encrypt_content=False,
                              retrieval="lexical", auto_activate=True)
        try:
            theirs = fabric.remember(agent_id="b", content="secret plan",
                                     tenant_id="tn_other") \
                if "tenant_id" in fabric.remember.__code__.co_varnames else None
            if theirs is None:
                self.skipTest("remember has no tenant_id in this build")
            server = build_server(fabric, "a", tenant_id="tn_default")
            r = tool(server, "memory_explain", {"memory_id": theirs})
            r2 = tool(server, "memory_explain", {"memory_id": "nonexistent"})
            self.assertTrue(r["result"]["isError"])
            self.assertEqual(
                r["result"]["content"][0]["text"].replace(theirs, "ID"),
                r2["result"]["content"][0]["text"].replace("nonexistent", "ID"))
        finally:
            fabric.close()


# --- transport --------------------------------------------------------------

class TestStdioSubprocess(unittest.TestCase):
    """The server as a host runs it: a separate process, newline-delimited
    JSON-RPC on stdin and stdout."""

    def test_a_real_session_over_stdio(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = str(pathlib.Path(tmp) / "store.db")
            messages = [
                {"jsonrpc": "2.0", "id": 1, "method": "server/discover"},
                {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {
                    "_meta": V26, "name": "memory_remember",
                    "arguments": {"content": "Fault E03 at coastal: swap the cable."}}},
                {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {
                    "_meta": V26, "name": "memory_recall",
                    "arguments": {"query": "fault E03 coastal"}}},
                "this is not json",
                {"jsonrpc": "2.0", "method": "notifications/initialized"},
            ]
            stdin = "\n".join(m if isinstance(m, str) else json.dumps(m)
                              for m in messages) + "\n"
            env = dict(os.environ, PYTHONIOENCODING="utf-8")
            proc = subprocess.run(
                [sys.executable, "-m", "memory_fabric.mcp.stdio",
                 "--db", db, "--agent-id", "agent-a", "--create"],
                input=stdin, capture_output=True, text=True, timeout=120,
                cwd=str(ROOT), env=env)
            self.assertEqual(proc.returncode, 0, proc.stderr)

            lines = [l for l in proc.stdout.splitlines() if l.strip()]
            # stdout is the protocol and nothing else: every line parses.
            responses = [json.loads(l) for l in lines]
            self.assertEqual(len(responses), 4,
                             "three requests, one parse error, no reply to "
                             "the notification")
            by_id = {r.get("id"): r for r in responses}
            self.assertIn("supportedVersions", by_id[1]["result"])
            self.assertFalse(by_id[2]["result"].get("isError", False))
            recalled = by_id[3]["result"]["structuredContent"]["memories"]
            self.assertEqual(len(recalled), 1)
            parse_errors = [r for r in responses if r.get("id") is None]
            self.assertEqual(parse_errors[0]["error"]["code"], P.PARSE_ERROR)
            # The human-readable line went to stderr.
            self.assertIn("agent=agent-a", proc.stderr)

    def test_a_missing_store_is_refused_without_create(self):
        proc = subprocess.run(
            [sys.executable, "-m", "memory_fabric.mcp.stdio",
             "--db", "definitely-not-here.db", "--agent-id", "a"],
            input="", capture_output=True, text=True, timeout=60,
            cwd=str(ROOT))
        self.assertEqual(proc.returncode, 2)
        self.assertEqual(proc.stdout, "")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
