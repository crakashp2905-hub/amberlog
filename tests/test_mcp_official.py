"""Official MCP SDK over real stdio: negotiation, isolation and late withdrawal."""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

from memory_fabric import MemoryFabric

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(importlib.util.find_spec("mcp"), "official MCP SDK is optional; run mcp-contract CI")
class OfficialClient(unittest.IsolatedAsyncioTestCase):
    async def test_negotiation_isolation_and_correction_through_official_client(self):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        with tempfile.TemporaryDirectory() as tmp:
            database = str(Path(tmp) / "store.db")
            with MemoryFabric(database, recognise_copies=False) as store:
                evidence = store.remember("observer", "Dispatch requires a reviewed valve check.",
                                          scope="team", tenant_id="tn_client", auto_activate=True)
                foreign = store.remember("observer", "FOREIGN_ONLY_MARKER", scope="team",
                                         tenant_id="tn_other", auto_activate=True)
            params = StdioServerParameters(
                command=sys.executable,
                args=["-m", "memory_fabric", "--db", database, "mcp", "--agent", "client",
                      "--tenant", "tn_client"],
                env=dict(os.environ, PYTHONPATH=str(ROOT / "src")), cwd=str(ROOT))
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write, read_timeout_seconds=timedelta(seconds=30)) as session:
                    initialized = await session.initialize()
                    self.assertEqual(initialized.serverInfo.name, "memory-fabric")
                    self.assertIn(initialized.protocolVersion,
                                  ("2025-06-18", "2025-03-26", "2024-11-05"))
                    tools = await session.list_tools()
                    self.assertEqual({tool.name for tool in tools.tools},
                                     {"recall", "fetch", "verify", "remember"})
                    fetched = await session.call_tool("fetch", {"memory_id": evidence})
                    self.assertFalse(fetched.isError)
                    self.assertIn("reviewed valve", fetched.content[0].text)
                    hidden = await session.call_tool("fetch", {"memory_id": foreign})
                    self.assertTrue(hidden.isError)
                    self.assertNotIn("FOREIGN_ONLY_MARKER", str(hidden.content))
                    before = await session.call_tool("verify", {"memory_id": evidence})
                    self.assertTrue(json.loads(before.content[0].text)["usable"])
                    with MemoryFabric(database, recognise_copies=False) as operator:
                        operator.quarantine(evidence, actor="reviewer", reason="source corrected",
                                            basis="contradicted")
                    after = await session.call_tool("verify", {"memory_id": evidence})
                    self.assertFalse(json.loads(after.content[0].text)["usable"])
                    withdrawn = await session.call_tool("fetch", {"memory_id": evidence})
                    self.assertTrue(withdrawn.isError)
