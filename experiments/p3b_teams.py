"""P3b — four memory systems, one agent team, identical task sequences.

Registered in `research/prereg/p3b-agent-teams.md`. The world and the backends
are in `teamworld.py`; this is the execution loop, the six metrics the question
asked for, and the verdict.

**The agent is deterministic.** It answers with whatever value its retrieved
context states, so every difference between arms is a property of the memory
system. R6 measured the other half — whether a model uses good evidence well —
and its dev finding did not replicate, which is why that half is not mixed in
here. Nothing in this file is evidence about model behaviour.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import statistics
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from experiments.teamworld import (  # noqa: E402
    BACKENDS, Fact, World, build_memory, build_world,
)

SEEDS = (1, 2, 3, 4, 5)
BASELINES = ("local", "shared", "shared_blanket")
CEILING = "oracle"
SHARE = 0.40
ABANDON_IF_HEADROOM_BELOW = 0.05
K = 5

_VALUE = re.compile(r"\b\d+\.\d+ m\b")


def extract(contents: Sequence[str], fact: Fact) -> str | None:
    """The agent's whole cognition: the value from the first statement that is
    about what it was asked.

    Deliberately the dullest possible reader -- it takes the **first** matching
    statement, so the memory system's ranking decides the answer and the agent
    adds nothing. But it does check the subject, and that check is not a
    nicety: without it the agent answered from any statement mentioning
    "clearance" and "site", so an isolated agent that had never learned the
    fact confidently returned another unit's figure instead of noticing it did
    not know. Every arm then showed exactly the 5 scheduled duplicate
    discoveries and the metric could not discriminate.

    Subject matching only -- unit, site and the attribute's own wording. It
    does not look at the value, at validity, or at anything the memory system
    is responsible for.
    """
    marker = "clearance" if fact.attribute == "clearance" else "access gap"
    for content in contents:
        lowered = content.lower()
        if fact.unit not in lowered or fact.site not in lowered:
            continue
        if marker not in lowered:
            continue
        found = _VALUE.search(content)
        if found:
            return found.group(0)
    return None


@dataclass
class TaskOutcome:
    agent: str
    key: tuple[str, str, str]
    answered: str | None
    correct_value: str | None
    correct: bool
    abstained: bool
    rediscovered: bool
    had_correct_evidence: bool
    acted_on_withdrawn: bool
    valid_evidence_withheld: bool
    context_tokens: int
    latency_ms: float


@dataclass
class RunResult:
    arm: str
    seed: int
    tasks: list[TaskOutcome] = field(default_factory=list)
    duplicate_discoveries: int = 0
    discovery_actions: int = 0
    model_calls: int = 0
    rounds: int = 0
    wall_ms: float = 0.0

    def summary(self) -> dict[str, Any]:
        n = len(self.tasks)
        mean = lambda xs: (sum(xs) / len(xs)) if xs else 0.0  # noqa: E731
        answerable = [t for t in self.tasks if t.correct_value is not None]
        return {
            "tasks": n,
            "task_success": round(mean([float(t.correct) for t in answerable]), 4),
            "correct_evidence_rate": round(
                mean([float(t.had_correct_evidence) for t in answerable]), 4),
            "stale_action_rate": round(
                mean([float(t.acted_on_withdrawn) for t in self.tasks]), 4),
            "wrong_invalidation_rate": round(
                mean([float(t.valid_evidence_withheld) for t in self.tasks]), 4),
            "abstention_rate": round(
                mean([float(t.abstained) for t in self.tasks]), 4),
            "rediscovery_rate": round(
                mean([float(t.rediscovered) for t in self.tasks]), 4),
            # The registered metric without the deadline, reported so the
            # difference the deadline makes stays visible.
            "answered_correctly_eventually": round(
                mean([float(bool(t.answered and t.answered == t.correct_value))
                      for t in answerable]), 4),
            "duplicate_discoveries": self.duplicate_discoveries,
            "discovery_actions": self.discovery_actions,
            "model_calls": self.model_calls,
            "context_tokens": round(
                mean([float(t.context_tokens) for t in self.tasks]), 1),
            "latency_ms": round(mean([t.latency_ms for t in self.tasks]), 3),
            "rounds": self.rounds,
            "wall_ms": round(self.wall_ms, 1),
        }


def run_one(arm: str, seed: int, agents: int, rounds: int) -> RunResult:
    world = build_world(seed, agents=agents, rounds=rounds)
    memory = build_memory(arm, world)
    result = RunResult(arm=arm, seed=seed, rounds=rounds)
    started = time.perf_counter()
    # What the team is known to hold, for the duplicate-discovery count. Kept
    # outside the memory backend on purpose: it is a property of the *team's*
    # behaviour, and charging it to the backend would let an arm look efficient
    # by forgetting things.
    team_knows: set[tuple[str, str, str]] = set()
    superseded: dict[tuple[str, str, str], str] = {}

    try:
        for event in world.schedule:
            if event.kind in ("discover", "duplicate", "contradict"):
                if event.kind == "duplicate" and event.fact.key in team_knows:
                    result.duplicate_discoveries += 1
                result.discovery_actions += 1
                memory.write(event.agent, event.fact.statement(), event.fact.key)
                if event.kind == "discover":
                    world.current[event.fact.key] = event.fact
                    team_knows.add(event.fact.key)

            elif event.kind == "correct":
                old = world.current.get(event.fact.key)
                if old is not None:
                    superseded[event.fact.key] = old.value
                memory.withdraw(
                    event.agent, event.fact.key, "re-measured after the move")
                # The corrected value is then written as a new discovery.
                memory.write(event.agent, event.fact.statement(), event.fact.key)
                world.current[event.fact.key] = event.fact

            elif event.kind == "task":
                truth = world.truth(event.fact.key)
                question = event.fact.question()
                t0 = time.perf_counter()
                rows = memory.read(event.agent, question, k=K)
                elapsed = (time.perf_counter() - t0) * 1000.0
                result.model_calls += 1
                contents = [c for _, c in rows]
                answer = extract(contents, event.fact)

                # An agent with nothing may rediscover -- but only where the
                # fact can still be re-measured. Half of them cannot be, and
                # that is what makes memory load-bearing: with rediscovery
                # free for everything, an isolated agent re-measures its way to
                # the ceiling and the primary metric cannot see what that cost.
                rediscovered = False
                if (answer is None and truth is not None
                        and event.fact.key in world.reproducible):
                    rediscovered = True
                    result.duplicate_discoveries += 1
                    result.discovery_actions += 1
                    memory.write(event.agent, truth.statement(), truth.key)
                    rows = memory.read(event.agent, question, k=K)
                    contents = [c for _, c in rows]
                    answer = extract(contents, event.fact)

                stale = superseded.get(event.fact.key)
                correct_value = truth.value if truth else None
                had_correct = bool(
                    truth and any(truth.value in c for c in contents))
                result.tasks.append(TaskOutcome(
                    agent=event.agent,
                    key=event.fact.key,
                    answered=answer,
                    correct_value=correct_value,
                    # A task the agent could only answer by going out and
                    # re-measuring is not a success for the memory system.
                    #
                    # This is the third correction to this world and the reason
                    # principle 8c's check exists. With rediscovery free and
                    # unpenalised, suppression plus rediscovery equalled
                    # repair: `shared_blanket` destroyed knowledge that was
                    # never in question, re-measured it, and scored 0.980 task
                    # success -- above the fabric -- while paying twice the
                    # duplicate discoveries. A real task has a deadline, and
                    # the field crew's work is not the store's achievement.
                    correct=bool(answer and answer == correct_value
                                 and not rediscovered),
                    rediscovered=rediscovered,
                    abstained=answer is None,
                    had_correct_evidence=had_correct,
                    acted_on_withdrawn=bool(stale and answer == stale),
                    # Valid evidence withheld: the backend holds a current
                    # statement this agent could reach, and did not return it.
                    #
                    # Asked of the backend rather than of the team. The first
                    # version asked whether the *team* knew the fact, which
                    # scored `local` at 0.510 -- but an agent that never
                    # learned something has not had it invalidated. Isolation
                    # and wrongful suppression are different failures and were
                    # being added together.
                    valid_evidence_withheld=bool(
                        truth and not had_correct
                        and memory.holds(event.agent, truth.value)),
                    context_tokens=sum(len(c.split()) for c in contents),
                    latency_ms=elapsed,
                ))
    finally:
        memory.close()
    result.wall_ms = (time.perf_counter() - started) * 1000.0
    return result


def run(arms: Sequence[str] = BACKENDS, seeds: Sequence[int] = SEEDS,
        agents: int = 10, rounds: int = 60) -> dict[str, Any]:
    per_arm: dict[str, list[dict[str, Any]]] = {}
    for arm in arms:
        per_arm[arm] = [
            run_one(arm, seed, agents, rounds).summary() for seed in seeds
        ]

    def agg(arm: str, metric: str) -> dict[str, float]:
        values = [row[metric] for row in per_arm[arm]]
        return {
            "mean": round(statistics.fmean(values), 4),
            "min": round(min(values), 4),
            "max": round(max(values), 4),
            "sd": round(statistics.pstdev(values), 4) if len(values) > 1 else 0.0,
        }

    metrics = [m for m in per_arm[arms[0]][0] if m != "tasks"]
    return {
        "experiment": "p3b-agent-teams",
        "agents": agents, "rounds": rounds, "seeds": list(seeds),
        "tasks_per_seed": per_arm[arms[0]][0]["tasks"],
        "arms": {arm: {m: agg(arm, m) for m in metrics} for arm in arms},
    }


def verdict(result: Mapping[str, Any]) -> dict[str, Any]:
    arms = result["arms"]
    present = [a for a in BASELINES if a in arms]
    base = max(arms[a]["task_success"]["mean"] for a in present)
    ceiling = arms[CEILING]["task_success"]["mean"]
    headroom = ceiling - base
    fabric = arms["fabric"]["task_success"]["mean"]
    out = {
        "best_baseline": base, "ceiling": ceiling,
        "headroom": round(headroom, 4),
        "threshold": round(base + SHARE * headroom, 4),
        "fabric": fabric,
        # Principle 8c: a primary metric a baseline maxes is the wrong metric.
        "baseline_reaches_ceiling": bool(headroom <= 1e-9),
    }
    if headroom <= ABANDON_IF_HEADROOM_BELOW:
        out["verdict"] = "ABANDONED"
        out["why"] = (
            f"headroom {headroom:+.3f} <= {ABANDON_IF_HEADROOM_BELOW}. A "
            f"baseline is at the ceiling, so the world is too easy and the fix "
            f"is more injection, not a different threshold (principle 8c).")
        return out
    if fabric > ceiling + 1e-9:
        out["verdict"] = "CEILING BREACHED — the ceiling is wrong, not the arm"
        return out
    out["closed_share"] = round((fabric - base) / headroom, 4)
    out["verdict"] = (
        "SUPPORTED" if fabric >= out["threshold"]
        else ("NOT SUPPORTED" if fabric > base else "KILLED — at or below every baseline"))
    return out


METRIC_LABELS = [
    ("task_success", "task success"),
    ("correct_evidence_rate", "correct evidence"),
    ("stale_action_rate", "acted on withdrawn"),
    ("wrong_invalidation_rate", "valid evidence withheld"),
    ("abstention_rate", "abstained"),
    ("rediscovery_rate", "had to re-measure"),
    ("answered_correctly_eventually", "correct eventually"),
    ("duplicate_discoveries", "duplicate discoveries"),
    ("model_calls", "model calls"),
    ("context_tokens", "context tokens"),
    ("latency_ms", "latency ms"),
]


def to_markdown(result: Mapping[str, Any], v: Mapping[str, Any]) -> str:
    arms = list(result["arms"])
    lines = [
        f"# P3b — agent teams · {result['agents']} agents",
        "",
        f"- **Seeds:** {len(result['seeds'])} · **rounds:** {result['rounds']} · "
        f"**tasks a seed:** {result['tasks_per_seed']}",
        "- **The agent is deterministic.** It answers with the value its top "
        "retrieved statement contains, so every difference below is a property "
        "of the memory system and none of it is evidence about model behaviour.",
        "",
        "| metric | " + " | ".join(f"`{a}`" for a in arms) + " |",
        "|---|" + "---|" * len(arms),
    ]
    for key, label in METRIC_LABELS:
        cells = []
        for arm in arms:
            row = result["arms"][arm][key]
            if key in ("duplicate_discoveries", "model_calls"):
                cells.append(f"{row['mean']:.1f}")
            elif key in ("context_tokens", "latency_ms"):
                cells.append(f"{row['mean']:.1f}")
            else:
                cells.append(f"{row['mean']:.3f}")
        lines.append(f"| {label} | " + " | ".join(cells) + " |")

    lines += [
        "",
        "Spread across seeds (min–max) for the primary metric:",
        "",
        "| arm | task success | sd |",
        "|---|---|---|",
    ]
    for arm in arms:
        row = result["arms"][arm]["task_success"]
        lines.append(f"| `{arm}` | {row['min']:.3f}–{row['max']:.3f} | {row['sd']:.4f} |")

    lines += [
        "",
        "## Verdict, applied as registered",
        "",
        "```",
        f"best baseline        B = {v['best_baseline']:.3f}",
        f"ceiling              C = {v['ceiling']:.3f}",
        f"headroom                 {v['headroom']:+.3f}",
        f"threshold            B + {SHARE:.2f} x headroom = {v['threshold']:.3f}",
        f"fabric                   {v['fabric']:.3f}",
        f"VERDICT: {v['verdict']}",
        "```",
    ]
    if v.get("why"):
        lines += ["", v["why"]]
    if "closed_share" in v:
        lines += ["", f"Closed **{v['closed_share']:.0%}** of the headroom against "
                      f"a registered {SHARE:.0%}."]
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--agents", type=int, default=10)
    parser.add_argument("--rounds", type=int, default=60)
    parser.add_argument("--seeds", type=int, nargs="*", default=list(SEEDS))
    parser.add_argument("--arms", nargs="*", default=list(BACKENDS))
    parser.add_argument("--json", dest="as_json", action="store_true")
    parser.add_argument("--out")
    args = parser.parse_args(argv)

    result = run(arms=args.arms, seeds=args.seeds, agents=args.agents,
                 rounds=args.rounds)
    v = verdict(result) if {"fabric", CEILING} <= set(args.arms) else {}
    print(json.dumps({"result": result, "verdict": v}, indent=2)
          if args.as_json else to_markdown(result, v))
    if args.out:
        pathlib.Path(args.out).write_text(
            to_markdown(result, v) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
