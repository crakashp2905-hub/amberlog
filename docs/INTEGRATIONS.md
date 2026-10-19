# Supported integrations

Each row is tested in CI by the test named, with no network access and no
API key. An integration that is not listed here is not supported.

| surface | how | install | tested by | stability |
|---|---|---|---|---|
| Python library | `MemoryFabric`, `sdk.operator` / `sdk.agent` | `pip install .` | the whole suite; `tests/test_sdk.py` | stable |
| CLI | `memory-fabric …` | `pip install .` | `tests/test_first_run.py`, `tests/test_doctor.py`, `tests/test_backup.py` | stable |
| MCP server (stdio) | `memory-fabric mcp --agent <id>` for Claude Code, Claude Desktop and IDE assistants | `pip install .` | `tests/test_mcp.py`, `tests/test_lifecycle_through_mcp.py` | stable |
| Agent HTTP API | `memory-fabric agent-api`, bearer tokens per agent, rate limits | `pip install .` | `tests/test_agent_api.py`, `experiments/e2e_validation.py` | stable |
| Federation (store to store) | `memory-fabric serve --peers …`, signed retractions and notices | `pip install .` | `tests/test_retraction_protocol.py`, `tests/test_source_notice.py` | stable |
| Claude API adapter | `adapters.claude.ClaudeMemoryAgent` | `pip install ".[claude]"` | `tests/test_claude_contract.py` | beta |
| Ollama adapter (local models) | `adapters.ollama` | none (HTTP over urllib) | `tests/test_ollama_adapter.py` | beta |
| Function-calling tools (OpenAI or Anthropic style) | `integrations.tools.FabricTools` | `pip install .` | `tests/test_integrations.py` | beta |
| LangChain retriever | `integrations.langchain` | `pip install ".[langchain]"` | `tests/test_integrations.py` (skipped without `langchain-core`) | beta |
| PostgreSQL backend | `--db postgresql://…` | `pip install ".[postgres]"` | `tests/test_postgres.py` (CI job `postgres`) | beta |

Stability tiers are defined in [STABILITY.md](../STABILITY.md).
Supported versions of Python, PostgreSQL and the optional packages are in
[VERSIONING.md](../VERSIONING.md#supported-versions).
