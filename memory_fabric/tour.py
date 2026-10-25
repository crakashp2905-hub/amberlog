"""`memory-fabric tour`: the whole idea in about sixty seconds, in a terminal.

One fact, four agents, one correction. An inspector records a pump setting;
a planner builds on it; an operator is allowed to act on it; the setting
turns out to be wrong and is withdrawn; the same action is then blocked, in
plain words, and the fact's story is told from the log.

Everything runs in an in-memory store: nothing is written to disk, nothing
is downloaded, and no model is called. `pause` slows it to reading speed;
`memory-fabric tour --fast` prints it at once.
"""

from __future__ import annotations

__stability__ = "beta"

import sys
import time
from typing import TextIO

from .actions import ActionGate, ActionPolicy, ToolRule
from .fabric import MemoryFabric
from .observability.control import timeline
from .reasons import badge, describe

BOLD, DIM, GREEN, RED, RESET = "\033[1m", "\033[2m", "\033[32m", "\033[31m", "\033[0m"


def run(out: TextIO | None = None, pause: float = 0.8, color: bool | None = None) -> dict[str, object]:
    """Tell the story. Returns what happened, for tests."""
    stream = out or sys.stdout
    use_color = stream.isatty() if color is None else color

    def c(code: str, text: str) -> str:
        return f"{code}{text}{RESET}" if use_color else text

    def say(text: str = "", wait: float = 1.0) -> None:
        print(text, file=stream, flush=True)
        if pause and text:
            time.sleep(pause * wait)

    def step(n: int, title: str) -> None:
        say()
        say(c(BOLD, f"{n}. {title}"), 0.5)

    f = MemoryFabric(":memory:", auto_activate=True)
    try:
        gate = ActionGate(f, ActionPolicy(
            tools={"set_relief_valve": ToolRule("set_relief_valve")},
            grants={"ops-agent": frozenset({"set_relief_valve"})}))

        say(c(BOLD, "Memory Fabric — a sixty-second tour"))
        say(c(DIM, "One fact, four agents, one correction. Nothing leaves this terminal."), 0.5)

        step(1, "An inspection agent records what it saw")
        fact = f.remember("inspector-agent", "Pump P-14 relief valve is set to 12 bar.",
                          scope="team")
        say("   “Pump P-14 relief valve is set to 12 bar.”")
        say(c(DIM, f"   trust: {badge(f, fact)['summary']}"))

        step(2, "A planning agent recalls it and builds on it")
        recalled = f.retrieve("planner-agent", "P-14 relief valve setting", k=3).exposed
        plan = f.derive("planner-agent", "After the seal job, restore P-14 relief to 12 bar.",
                        [fact], scope="team")
        say(f"   recalled: “{recalled[0].content}”")
        say("   plan:     “After the seal job, restore P-14 relief to 12 bar.”")
        say(c(DIM, "   the plan records what it was built from"))

        step(3, "An operations agent asks to act on it")
        cert = f.certify("P-14 relief should be 12 bar", [fact], "ops-agent")
        first = gate.authorize("set_relief_valve", "ops-agent", cert)
        say("   " + c(GREEN, "ALLOWED") + ": set_relief_valve, on evidence checked just now")

        step(4, "The vendor says 12 bar was wrong")
        f.quarantine(fact, reason="vendor re-specified the setting as 10 bar",
                     actor="shift-lead", basis="contradicted")
        say("   shift-lead withdraws the fact, once, in one place")
        after = [m.content for m in f.retrieve("planner-agent", "P-14 relief valve setting",
                                               k=3).exposed]
        say(f"   recall now returns: {after or 'nothing'}")
        say(f"   the plan built on it is now: {f.lifecycle_of(plan).value}")

        step(5, "The same action, a minute later")
        second = gate.authorize("set_relief_valve", "ops-agent", cert)
        say("   " + c(RED, "BLOCKED"))
        for line in describe(f, second):
            say(f"   {line}", 0.6)

        step(6, "The story of that fact, from the log")
        story = timeline(f, fact)
        for s in story["steps"]:
            say(c(DIM, "   • ") + s["text"], 0.4)

        say()
        say(c(BOLD, "That is the product:") + " every memory knows where it came from, a "
            "correction reaches everything built on it, and nothing acts on evidence that no "
            "longer holds.", 0.5)
        say(c(DIM, "Next: `memory-fabric sandbox` to explore a store like this in the dashboard."), 0)
        return {"first_allowed": first.allowed, "second_allowed": second.allowed,
                "recall_after": after, "plan_state": f.lifecycle_of(plan).value,
                "steps": [s["kind"] for s in story["steps"]]}
    finally:
        f.close()

