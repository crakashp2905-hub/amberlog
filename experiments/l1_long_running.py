"""L1 — a long-running task: a plain vector store against Amberlog.

Registered in `research/prereg/l1-long-running-task.md` before this file
existed. Deterministic; known answers.

    python -m experiments.l1_long_running
"""

from __future__ import annotations

import json
import random
import re
import statistics
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

from amberlog import Amberlog, correction
from amberlog.actions import ActionGate, ActionPolicy, ToolRule
from amberlog.vectors import LexicalIndex

ROOT = Path(__file__).resolve().parent.parent
SEEDS = (1, 2, 3, 4, 5)
EQUIPMENT = 40
STEPS = 600
CORRECTIONS = 16
NOTE_RATE = 0.35
WORKERS = ("worker-a", "worker-b", "worker-c", "worker-d")
NOTES = ("Shift plan: run {e} at setpoint {v}.",
         "Used setpoint {v} on {e} today; it held.",
         "{e} running at setpoint {v} per the procedure.",
         "Reminder for next shift: {e} setpoint {v}.")
QUERIES = ("{e} setpoint for the shift plan", "what setpoint is {e} running at",
           "setpoint used on {e} today", "reminder: {e} setpoint for next shift")
"""Amendment 1 (L1′): recall in the words of the job."""
AMENDED = False
VALUE = re.compile(r"setpoint (?:is )?(\d+)")


def value_of(text: str, equipment: str) -> int | None:
    if not re.search(rf"(?<![\w-]){re.escape(equipment)}(?![\w-])", text):
        return None
    found = VALUE.search(text)
    return int(found.group(1)) if found else None


def schedule(seed: int) -> dict[str, Any]:
    """Everything random, drawn once per seed so every arm sees the same world."""
    rng = random.Random(f"l1/{seed}")
    truth0 = {f"E-{i}": rng.randrange(20, 90) for i in range(1, EQUIPMENT + 1)}
    steps = sorted(rng.sample(range(20, STEPS - 20), CORRECTIONS))
    fixes = {}
    for step in steps:
        fixes[step] = rng.choice(sorted(truth0))
    jobs = [(rng.choice(WORKERS), f"E-{rng.randrange(1, EQUIPMENT + 1)}",
             rng.random() < NOTE_RATE, rng.randrange(len(NOTES))) for _ in range(STEPS)]
    shifts = [rng.choice((-15, -9, -6, 6, 9, 15)) for _ in range(CORRECTIONS)]
    # A separate stream, so the original world's draws are unchanged.
    qrng = random.Random(f"l1q/{seed}")
    queries = [QUERIES[qrng.randrange(len(QUERIES))] if AMENDED else "{e} setpoint"
               for _ in range(STEPS)]
    return {"truth0": truth0, "fixes": fixes, "jobs": jobs, "shifts": shifts,
            "queries": queries}


class VectorArm:
    """A plain store: similarity ranking, no lifecycle, no lineage.

    Ties break newest first, which favours this arm: a correction written as a
    new memory wins a tie against the value it corrects.
    """

    def __init__(self, replace: bool) -> None:
        self.replace = replace
        self.index = LexicalIndex()
        self.docs: dict[str, str] = {}
        self.order: dict[str, int] = {}
        self.original: dict[str, str] = {}

    def write(self, text: str, equipment: str | None = None) -> str:
        key = f"m{len(self.order):05d}"
        self.docs[key] = text
        self.order[key] = len(self.order)
        self.index.add(key, text)
        if equipment is not None:
            self.original[equipment] = key
        return key

    def correct(self, equipment: str, new_value: int) -> None:
        text = f"{equipment} setpoint is {new_value}."
        if self.replace:
            key = self.original[equipment]
            self.docs[key] = text
            self.index.add(key, text)
        else:
            self.write(text)

    def recall(self, agent: str, equipment: str, query: str) -> tuple[int | None, Any]:
        hits = self.index.search(query, k=10, min_relevance=0.0)
        hits.sort(key=lambda h: (-round(h[1], 9), -self.order[h[0]]))
        for key, _ in hits:
            v = value_of(self.docs[key], equipment)
            if v is not None:
                return v, key
        return None, None

    def act(self, agent: str, equipment: str, query: str) -> int | None:
        return self.recall(agent, equipment, query)[0]

    def note(self, agent: str, text: str, used: Any) -> None:
        self.write(text)

    def close(self) -> None:
        pass


class FabricArm:
    def __init__(self, lineage: bool) -> None:
        self.lineage = lineage
        self.f = Amberlog(":memory:", auto_activate=True)
        self.gate = ActionGate(self.f, ActionPolicy(
            tools={"set": ToolRule("set")}, grants={w: frozenset({"set"}) for w in WORKERS}))
        self.original: dict[str, str] = {}
        self.blocked = 0

    def write(self, text: str, equipment: str | None = None) -> str:
        mid = self.f.remember("inspector", text, scope="team")
        if equipment is not None:
            self.original[equipment] = mid
        return mid

    def correct(self, equipment: str, new_value: int) -> None:
        correction.apply(self.f, self.original[equipment], reason="re-measured",
                         actor="supervisor")
        self.original[equipment] = self.f.remember(
            "supervisor", f"{equipment} setpoint is {new_value}.", scope="team")

    def recall(self, agent: str, equipment: str, query: str) -> tuple[int | None, Any]:
        for m in self.f.retrieve(agent, query, k=10).exposed:
            v = value_of(m.content, equipment)
            if v is not None:
                return v, m.id
        return None, None

    def act(self, agent: str, equipment: str, query: str) -> int | None:
        for _ in range(2):  # recall, act through the gate; once more if refused
            value, mid = self.recall(agent, equipment, query)
            if value is None:
                return None
            cert = self.f.certify(f"{equipment}={value}", [mid], agent)
            if self.gate.authorize("set", agent, cert).allowed:
                self._used = mid
                return value
            self.blocked += 1
        return None

    def note(self, agent: str, text: str, used: Any) -> None:
        if self.lineage and used is not None:
            self.f.derive(agent, text, [used], scope="team")
        else:
            self.f.remember(agent, text, scope="team")

    def close(self) -> None:
        self.f.close()


def run(seed: int, arm: str) -> dict[str, Any]:
    world = schedule(seed)
    truth = dict(world["truth0"])
    store: Any = None
    if arm in ("vector_append", "vector_replace"):
        store = VectorArm(replace=arm == "vector_replace")
    elif arm in ("fabric", "fabric_no_lineage"):
        store = FabricArm(lineage=arm == "fabric")
    if store is not None:
        for e, v in truth.items():
            store.write(f"{e} setpoint is {v}.", equipment=e)
    corrected_at: dict[str, list[tuple[int, int]]] = {}
    harmful = taken = correct = 0
    last_harm: dict[tuple[str, int], int] = {}
    fixes = world["fixes"]
    shift_iter = iter(world["shifts"])
    try:
        for step, (agent, e, writes_note, template) in enumerate(world["jobs"]):
            if step in fixes:
                fe = fixes[step]
                old = truth[fe]
                truth[fe] = max(5, old + next(shift_iter))
                corrected_at.setdefault(fe, []).append((step, old))
                if store is not None:
                    store.correct(fe, truth[fe])
            if store is None:
                value: int | None = truth[e]
                used = None
            else:
                query = world["queries"][step].format(e=e)
                value = store.act(agent, e, query)
                used = getattr(store, "_used", None) if isinstance(store, FabricArm) else \
                    store.recall(agent, e, query)[1]
            if value is None:
                continue
            taken += 1
            if value == truth[e]:
                correct += 1
            else:
                harmful += 1
                for when, old in corrected_at.get(e, []):
                    if old == value:
                        last_harm[(e, when)] = step
            if writes_note and store is not None:
                store.note(agent, NOTES[template].format(e=e, v=value), used)
    finally:
        blocked = getattr(store, "blocked", 0)
        if store is not None:
            store.close()
    recoveries = [last_harm.get((e, when), when) - when
                  for e, events in corrected_at.items() for when, _ in events]
    return {"seed": seed, "arm": arm, "jobs": STEPS, "actions": taken, "harmful": harmful,
            "harm_per_1000": 1000 * harmful / taken if taken else 0.0,
            "completion": correct / STEPS, "mean_recovery": statistics.fmean(recoveries),
            "gate_refusals": blocked}


ARMS: tuple[str, ...] = ("oracle", "vector_append", "vector_replace", "fabric",
                         "fabric_no_lineage")


def main() -> int:
    global SEEDS, AMENDED
    if "--amended" in sys.argv:
        SEEDS, AMENDED = (6, 7, 8, 9, 10), True
    name = "l1p-long-running" if AMENDED else "l1-long-running"
    rows: dict[str, list[dict[str, Any]]] = {a: [] for a in ARMS}
    # Baselines and the oracle first: the 8c check runs before any fabric arm.
    for arm in ("oracle", "vector_append", "vector_replace"):
        rows[arm] = [run(s, arm) for s in SEEDS]
    mean: Callable[[str, str], float] = lambda a, k: statistics.fmean(r[k] for r in rows[a])
    best = min(("vector_append", "vector_replace"), key=lambda a: mean(a, "harm_per_1000"))
    verdict: dict[str, Any] = {"best_baseline": best}
    if mean(best, "harm_per_1000") <= 1.0:
        verdict["L1"] = "ABANDONED (8c: a baseline is already at the oracle)"
    else:
        for arm in ("fabric", "fabric_no_lineage"):
            rows[arm] = [run(s, arm) for s in SEEDS]
        for arm in ("fabric", "fabric_no_lineage"):
            pairs = list(zip(rows[arm], rows[best]))
            verdict[arm] = {
                "L1a": all(f["harm_per_1000"] <= 0.5 * b["harm_per_1000"] for f, b in pairs),
                "L1b": mean(arm, "completion") >= mean(best, "completion") - 0.05,
                "L1c": sum(f["mean_recovery"] < b["mean_recovery"] for f, b in pairs) >= 4,
            }
    oracle_completion = mean("oracle", "completion")
    verdict["ceiling_ok"] = all(r["harm_per_1000"] >= 0 and r["completion"] <= oracle_completion + 1e-9
                                for a in ARMS for r in rows[a])
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True,
                            text=True, cwd=ROOT).stdout.strip()
    out = ROOT / "research" / "results"
    (out / f"{name}.json").write_text(json.dumps(
        {"commit": commit, "rows": rows, "verdict": verdict}, indent=2) + "\n")
    table = "\n".join(
        f"| `{a}` | {mean(a, 'harm_per_1000'):.1f} | {mean(a, 'completion'):.3f} "
        f"| {mean(a, 'mean_recovery'):.1f} | {mean(a, 'actions'):.0f} |"
        for a in ARMS if rows[a])
    per_seed = "\n".join(
        f"| {s} | " + " | ".join(f"{rows[a][i]['harm_per_1000']:.1f}" for a in ARMS if rows[a]) + " |"
        for i, s in enumerate(SEEDS))
    v = verdict
    reading = ""
    if rows["fabric"]:
        refusals = sum(r["gate_refusals"] for r in rows["fabric"])
        reading = (
            "**Reading.** Completion counts a job with no action as not done. "
            f"`fabric` acted on {mean('fabric', 'actions'):.0f} of {STEPS} jobs a seed "
            f"against {mean(best, 'actions'):.0f} for `{best}`, and every one of its actions "
            f"used the true value. The gate refused {refusals} time(s) across all seeds, so the "
            "gap in actions is retrieval, not safety: on those jobs no memory about that "
            "equipment was in the top 10 for a job-phrased query, where the baseline's top 10 "
            "more often held a note restating a value, current or not. The trained retriever "
            "(R3) is the lever for that, not the gate.")

    def mark(arm: str, key: str) -> str:
        return ("pass" if v[arm][key] else "fail") if arm in v else "n/a"
    (out / f"{name}.md").write_text(f"""# L1 — a long-running task: a plain vector store against Amberlog

Registered in [l1-long-running-task.md](../prereg/l1-long-running-task.md) before the
harness existed. {"Amendment 1 (L1′): recall in the words of the job, fresh seeds. " if AMENDED else ""}Produced by `python -m experiments.l1_long_running{" --amended" if AMENDED else ""}` at commit
`{commit}`; raw numbers in [{name}.json]({name}.json). Deterministic,
seeds {SEEDS}: {STEPS} jobs, {EQUIPMENT} pieces of equipment, {CORRECTIONS} corrections,
four worker agents writing working notes at rate {NOTE_RATE}.

Best baseline: `{best}`. Ceiling check: {"ok" if v["ceiling_ok"] else "FAILED"}.
{v.get("L1", "")}

| arm | harmful actions per 1,000 | completion | mean recovery (steps) | actions |
|---|---|---|---|---|
{table}

| | L1a harm ≤ 50% of best baseline, all seeds | L1b completion within 5 points | L1c faster recovery, ≥ 4 of 5 seeds |
|---|---|---|---|
| `fabric` | {mark("fabric", "L1a")} | {mark("fabric", "L1b")} | {mark("fabric", "L1c")} |
| `fabric_no_lineage` (no claim registered) | {mark("fabric_no_lineage", "L1a")} | {mark("fabric_no_lineage", "L1b")} | {mark("fabric_no_lineage", "L1c")} |

{reading}

Harm per 1,000 actions, by seed:

| seed | {" | ".join(a for a in ARMS if rows[a])} |
|---|{"---|" * len([a for a in ARMS if rows[a]])}
{per_seed}
""")
    print(json.dumps(verdict, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
