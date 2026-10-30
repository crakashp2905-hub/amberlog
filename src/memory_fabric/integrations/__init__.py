"""Integrations with agent frameworks, each at the agent-facing policy boundary.

Every integration here is built on `sdk.AgentClient` (or the MCP server built
on it), never on `MemoryFabric` directly, so a framework gets exactly what an
agent may have: enforced reads, a governed write path, an action-time check,
and nothing that bypasses them. None of them imports a framework at module
import time; the core stays dependency-free.

- `tools`: framework-neutral function tools (`recall`, `fetch`, `verify`,
  `remember`) in OpenAI or Anthropic tool format, with a dispatcher.
- `langchain`: a LangChain retriever, when `langchain_core` is installed.
"""

__stability__ = "beta"
