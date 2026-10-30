"""A reference agent application: the whole loop an agent on the fabric should run.

    python examples/reference_agent.py

For each task: retrieve what is known, decide, cite what it used, ask the
host for a short-lived grant bound to the exact action, execute through the
action fence, have the environment verify the outcome, and write down what
it learned. The "model" is a deterministic stand-in, so this runs with no
key and no network; replace `decide` with a model call and nothing else
changes. `tests/test_reference_agent.py` runs it, including a poisoned
memory that the gate refuses to act on.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from memory_fabric import MemoryFabric  # noqa: E402
from memory_fabric.actions import ActionGate, ActionPolicy, ActionRequest, ToolRule  # noqa: E402

TRUE_LIMITS = {"P1": 30, "P2": 45}


@dataclass
class Report:
    task: str
    decided: int | None
    outcome: str
    reasons: tuple[str, ...] = ()


@dataclass
class ReferenceAgent:
    fabric: MemoryFabric
    agent_id: str = "ops-agent"
    gate: ActionGate = field(init=False)
    executed: list[tuple[str, int]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.gate = ActionGate(self.fabric, ActionPolicy(
            tools={"set_purge": ToolRule("set_purge", requires_grant=True)},
            grants={self.agent_id: frozenset({"set_purge"})}))

    def decide(self, pump: str, memories: list[Any]) -> tuple[int | None, Any]:
        """The model's job, faked: read a purge time for this pump from what was shown."""
        for memory in memories:
            if pump in memory.content:
                found = re.search(r"(\d+)\s*(?:s|second)", memory.content)
                if found:
                    return int(found.group(1)), memory
        return None, None

    def run(self, pump: str) -> Report:
        f = self.fabric
        episode = f.start_episode(self.agent_id, f"set-purge-{pump}")
        shown = f.retrieve(self.agent_id, f"pump {pump} purge time", k=3,
                           episode_id=episode.id).exposed
        seconds, used = self.decide(pump, shown)
        if used is None:
            f.record_outcome(episode.id, 0.0, verifier_id="env")
            return Report(pump, None, "no evidence")
        f.cite(self.agent_id, episode.id, used.id)
        certificate = f.certify(f"purge-{pump}", [used.id], self.agent_id)
        request = ActionRequest(f"pump/{pump}", {"purge_s": seconds})
        # The host issues the grant, for this action only, for one minute.
        grant = self.gate.issue_grant("set_purge", self.agent_id, issuer="host",
                                      certificate=certificate, request=request, ttl_s=60)
        result = self.gate.execute(
            "set_purge", self.agent_id, lambda key: self.executed.append((pump, seconds)),
            certificate, key=f"{episode.id}:{pump}", request=request, grant=grant)
        if result.outcome != "executed":
            f.record_outcome(episode.id, 0.0, verifier_id="env")
            return Report(pump, seconds, "refused", result.decision.reason_codes
                          if result.decision else ())
        correct = TRUE_LIMITS.get(pump) == seconds          # the environment checks
        f.record_outcome(episode.id, 1.0 if correct else 0.0, verifier_id="env")
        if correct:
            f.remember(self.agent_id, f"Setting pump {pump} purge to {seconds} s was verified.",
                       source_episodes=[episode.id], scope="team")
        return Report(pump, seconds, "verified" if correct else "wrong")


def main(path: str = ":memory:") -> list[Report]:
    fabric = MemoryFabric(path, auto_activate=True)
    try:
        fabric.remember("plant-manual", "Pump P1 requires a 30 second purge.", scope="team")
        # A poisoned note from a scraped forum: the gate must not act on it.
        fabric.remember("agent", "Pump P2 purge time is 5 s.", context={"origin": "web:forum"},
                        scope="team")
        agent = ReferenceAgent(fabric)
        reports = [agent.run("P1"), agent.run("P2")]
        for r in reports:
            print(f"{r.task}: {r.outcome} {r.decided if r.decided is not None else ''} "
                  f"{' '.join(r.reasons)}".rstrip())
        return reports
    finally:
        fabric.close()


if __name__ == "__main__":
    main()
