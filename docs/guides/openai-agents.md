# OpenAI Agents SDK

```bash
pip install openai-agents
```

```python
from agents import Agent, Runner, function_tool

from amberlog import Amberlog
from amberlog.actions import ActionGate, ActionPolicy, ToolRule
from amberlog.integrations.tools import FabricTools
from amberlog.sdk import agent

fabric = Amberlog("memory/store.db")
mem = FabricTools(agent(fabric, "support-bot"))
gate = ActionGate(fabric, ActionPolicy(tools={"issue_refund": ToolRule("issue_refund")},
                                       grants={"support-bot": frozenset({"issue_refund"})}))


@function_tool
def recall(query: str) -> dict:
    """Recall what is known. Each memory comes with a trust summary."""
    return mem.call("recall", {"query": query})


@function_tool
def remember(content: str) -> dict:
    """Record a durable fact. Reviewed before other agents see it."""
    return mem.call("remember", {"content": content})


@function_tool
def issue_refund(order_id: str, amount: float, evidence: list[str]) -> dict:
    """Refund an order. `evidence`: the memory ids that justify it."""
    return mem.guarded(gate, "issue_refund", evidence,
                       lambda key: billing.refund(order_id, amount, idempotency_key=key),
                       key=f"refund:{order_id}")


bot = Agent(name="support", instructions="Recall before acting; cite memory ids as evidence.",
            tools=[recall, remember, issue_refund])
result = Runner.run_sync(bot, "Customer 1182 says the refund policy changed. What now?")
```

Without the Agents SDK, `mem.specs("openai")` gives the four memory tools as
Chat Completions function definitions and `mem.call(name, arguments)` runs a
tool call (the JSON string a model returns is accepted as is).
