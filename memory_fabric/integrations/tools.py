"""Memory as function tools, for any framework that does function calling.

The MCP server already defines the agent's four tools -- `recall`, `fetch`,
`verify`, `remember` -- with their schemas, validation and server-side tokens.
This presents the same tools in the two common function-calling formats and
dispatches calls to that server, so there is one implementation of what an
agent may do, whichever protocol reaches it:

    tools = FabricTools(agent(fabric, "my-agent"))
    client.chat.completions.create(..., tools=tools.specs("openai"))
    result = tools.call(tool_call.function.name, tool_call.function.arguments)

`arguments` may be the JSON string a model returns. A refused call comes back
as `{"error": ...}`, never as an exception, because a model needs the refusal
as an answer.
"""

from __future__ import annotations

import json
from typing import Any, Mapping

from ..adapters.mcp import McpServer
from ..sdk import AgentClient

STYLES = ("openai", "anthropic")


class FabricTools:
    def __init__(self, client: AgentClient) -> None:
        self._server = McpServer(client, client._fabric)

    def specs(self, style: str = "openai") -> list[dict[str, Any]]:
        """Tool definitions in `openai` or `anthropic` format."""
        if style not in STYLES:
            raise ValueError(f"style must be one of {STYLES}")
        out = []
        for tool in self._server.tools():
            if style == "openai":
                out.append({"type": "function", "function": {
                    "name": tool["name"], "description": tool["description"],
                    "parameters": tool["inputSchema"]}})
            else:
                out.append({"name": tool["name"], "description": tool["description"],
                            "input_schema": tool["inputSchema"]})
        return out

    def call(self, name: str, arguments: Mapping[str, Any] | str | None) -> dict[str, Any]:
        """Run one tool call; refusals and bad arguments are returned, not raised."""
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments or "{}")
            except ValueError:
                return {"error": "arguments are not valid JSON"}
        if not isinstance(arguments, Mapping):
            return {"error": "arguments must be an object"}
        payload, is_error = self._server.call(name, arguments)
        if is_error and not (isinstance(payload, dict) and "error" in payload):
            return {"error": str(payload)}
        return payload if isinstance(payload, dict) else {"result": payload}
