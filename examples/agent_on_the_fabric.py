"""P3: running an agent on the fabric.

    python examples/agent_on_the_fabric.py

Uses a scripted stand-in for Claude so it runs with no API key and no network.
The fabric-side path — session scoping, retrieval, prompt assembly, the
`remember` tool, governance on the write — is the real one; only the model is
faked. The same code runs against the live API by dropping the `client=`
argument, once `pip install anthropic` and credentials are in place.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Windows consoles default to a legacy code page that cannot encode the
# punctuation below; this reconfigures stdout the way the CLI does.
from memory_fabric.cli import configure_output

configure_output()

from memory_fabric.sdk import operator
from memory_fabric import MemoryFabric
from memory_fabric.adapters import ingest_transcript
from memory_fabric.adapters.claude import ClaudeMemoryAgent


# --- a scripted stand-in for the model --------------------------------------


@dataclass
class Block:
    type: str
    text: str = ""
    id: str = ""
    name: str = ""
    input: dict = field(default_factory=dict)


@dataclass
class Usage:
    input_tokens: int = 1200
    output_tokens: int = 180
    cache_read_input_tokens: int = 0


@dataclass
class Response:
    content: list
    stop_reason: str = "end_turn"
    stop_details: Any = None
    usage: Usage = field(default_factory=Usage)


class ScriptedMessages:
    def __init__(self, owner):
        self.owner = owner

    def create(self, **params):
        self.owner.calls.append(params)
        return self.owner.script.pop(0)


class ScriptedClient:
    def __init__(self, script):
        self.script = list(script)
        self.calls = []
        self.messages = ScriptedMessages(self)
        self.beta = type("B", (), {"messages": ScriptedMessages(self)})()


def rule(title: str) -> None:
    print(f"\n{'=' * 74}\n{title}\n{'=' * 74}")


def main() -> None:
    fabric = MemoryFabric(seed=0)  # candidates stay candidates until reviewed

    rule("1. Seed the store from an existing transcript")

    imported = ingest_transcript(
        fabric,
        agent_id="support-agent",
        task_id="ticket-4471",
        turns=[
            {"role": "user", "content": "The depot charger trips the breaker on cold mornings."},
            {"role": "assistant", "content": "Check the earth bond before the RCD; a damp bond trips on the first high-current draw."},
        ],
        context={"domain": "ev"},
        outcome=1.0,
        verifier_id="ticket-system",
    )
    print(f"  episode {imported['episode_id']}")
    print(f"  memory  {imported['memory_id']} ({imported['lifecycle_state']})")

    # A reviewer promotes it, which is what makes it retrievable at all.
    fabric.validate(imported["memory_id"], actor="reviewer")
    print("  reviewed and validated")

    rule("2. An agent runs a task, with memory retrieved into its prompt")

    client = ScriptedClient([
        Response(
            content=[Block(type="tool_use", id="t1", name="remember", input={
                "content": "On cold mornings, check the earth bond before the RCD: "
                           "a damp bond trips on the first high-current draw.",
                "type": "procedural",
            })],
            stop_reason="tool_use",
        ),
        Response(content=[Block(
            type="text",
            text="Check the earth bond first — a damp bond trips on the first "
                 "high-current draw. I've recorded the procedure.",
        )]),
    ])

    agent = ClaudeMemoryAgent(fabric, agent_id="depot-agent", client=client)
    run = agent.run(
        task_id="ticket-4482",
        prompt="A different depot charger trips the breaker. Where do I start?",
        context={"domain": "ev"},
    )

    print(f"  recalled:   {run.recalled}")
    print(f"  answer:     {run.text}")
    print(f"  turns:      {run.turns}   tokens in/out: {run.input_tokens}/{run.output_tokens}")

    rule("3. What the model was actually shown")

    print(client.calls[0]["messages"][0]["content"])

    rule("4. What the agent wrote, and what governance did with it")

    # Through the operator client, not `fabric.get()`. This section is an
    # operator view — it deliberately shows withdrawn memories — and an
    # example is the thing adapter authors copy. `operator(...).inspect()`
    # says "I mean the unenforced read" out loud; `fabric.get()` says nothing
    # and is shorter to type.
    reviewer = operator(fabric, actor="reviewer")
    for memory_id in run.remembered:
        memory = reviewer.inspect(memory_id)
        print(f"  {memory_id}")
        print(f"    state:   {memory.lifecycle_state.value}")
        print(f"    by:      {memory.provenance.created_by}")
        print(f"    from:    episode {memory.provenance.source_episodes[0]}")
        print(f"    content: {memory.content[:70]}...")
    print(
        "\n  It is a candidate, not active: an agent writing something down does\n"
        "  not by itself make it retrievable by anyone else."
    )

    rule("5. The outcome is recorded by someone other than the agent")

    fabric.record_outcome(run.episode_id, outcome=1.0, verifier_id="ticket-system")
    print("  recorded by ticket-system")
    try:
        fabric.record_outcome(run.episode_id, 1.0, verifier_id="depot-agent")
    except Exception as exc:
        print(f"  refused for the agent itself: {exc}")

    rule("6. Store health")

    health = fabric.health()
    print(f"  memories {health.total}  by state {health.by_state}")
    print(f"  episodes {health.episodes} ({health.episodes_with_outcome} with a verified outcome)")
    print(f"\n  memory-fabric --db <path> attention   # to review the candidate")

    fabric.close()
    print()


if __name__ == "__main__":
    main()
