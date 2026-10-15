"""Memory Fabric as a Model Context Protocol server.

Exposes the governed store to any MCP host -- Claude Code, Claude Desktop,
Cursor and the rest -- so adopting it means adding a server rather than
rewriting a memory layer.

Three modules, separated by what can be tested without a process:

* `protocol` -- JSON-RPC 2.0 and MCP version negotiation, transport-agnostic.
* `tools` -- the memory tools, resources and prompts, bound to one agent.
* `stdio` -- the newline-delimited stdio transport and the entry point.

Read `protocol`'s docstring before changing anything: the current
specification (2026-07-28) made MCP **stateless**, and a server built from the
older initialize-first tutorials is wrong for current clients.
"""

from .protocol import (  # noqa: F401
    CURRENT_VERSION, LEGACY_VERSIONS, SUPPORTED_VERSIONS, McpError, Server,
)
