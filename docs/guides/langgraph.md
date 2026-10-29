# LangGraph

Two pieces: the memory tools for the agent, and a guard around any tool that
changes the world. Both use the same server the MCP agent uses, so the rules
are identical.

```bash
pip install ".[langchain]" langgraph
```

## Memory tools

```python
from langchain_core.tools import tool
from langgraph.prebuilt import create_react_agent

from amberlog import Amberlog
from amberlog.integrations.tools import FabricTools
from amberlog.sdk import agent

fabric = Amberlog("memory/store.db")
mem = FabricTools(agent(fabric, "planner"))


@tool
def recall(query: str, k: int = 5) -> dict:
    """Recall memories relevant to a question. Each comes with a trust summary."""
    return mem.call("recall", {"query": query, "k": k})


@tool
def verify(memory_id: str) -> dict:
    """Check that a recalled memory is still usable before relying on it."""
    return mem.call("verify", {"memory_id": memory_id})


@tool
def remember(content: str) -> dict:
    """Record a durable fact for later tasks. It is reviewed before others see it."""
    return mem.call("remember", {"content": content})
```

## A guarded action

```python
from amberlog.actions import ActionGate, ActionPolicy, ToolRule

gate = ActionGate(fabric, ActionPolicy(
    tools={"set_relief_valve": ToolRule("set_relief_valve")},
    grants={"planner": frozenset({"set_relief_valve"})}))


@tool
def set_relief_valve(pump: str, bar: float, evidence: list[str]) -> dict:
    """Set a pump's relief valve. `evidence` is the memory ids this relies on."""
    return mem.guarded(gate, "set_relief_valve", evidence,
                       lambda key: plant_api.set_relief(pump, bar, idempotency_key=key),
                       key=f"{pump}:{bar}")


graph = create_react_agent(model, [recall, verify, remember, set_relief_valve])
```

If the evidence was withdrawn in the meantime, the tool returns
`{"blocked": true, "why": ["Blocked: \"Pump P-14 relief valve is set to 12 bar.\" was withdrawn by shift-lead …"]}`
and the model reads why.

## Retrieval-augmented chains

`amberlog.integrations.langchain.fabric_retriever(agent(fabric, "rag"))`
is a LangChain retriever: same eligibility, same exposure log.
