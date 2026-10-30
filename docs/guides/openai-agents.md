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

## Reproduce the runtime contract without model spending

In a development virtual environment, from an editable checkout:

```bash
python -m pip install "openai-agents==0.24.0" "langgraph==1.2.11"
python -m unittest tests.test_framework_contracts -v
```

The Agents SDK test uses the real `Agent`, `FunctionTool` and `Runner` with
Amberlog's existing governed dispatcher. A local `Model` supplies deterministic
function calls. It checks successful retrieval, foreign-tenant refusal, a
positive verification control and refusal after correction. Tracing is disabled
and HTTP client sends raise an error, so the test cannot silently call a hosted
model. The separate `framework-contracts` CI job installs the pinned SDKs; core
tests skip these optional contracts when they are absent.

This is runtime/tool interoperability evidence, not evidence of model reasoning,
task success, streaming, handoffs or an external pilot. The example above still
needs a configured model and a real billing implementation before live use.
Host-owned side effects require the action fence and external idempotency
described in [failure policies](../FAILURE_POLICIES.md).

References: [official agent definitions](https://developers.openai.com/api/docs/guides/agents/define-agents)
and [models and providers](https://developers.openai.com/api/docs/guides/agents/models).
