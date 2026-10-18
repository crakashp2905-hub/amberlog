"""M1 -- ObjectiveWorld: does stating the session's objective first make agents use the right memory?

Real local models. Per seed, the session works at one plant, and its objective
is stated in words before anything is asked:

    "This session supports the night shift at Brook. Relevant: approved
    procedures for Brook from the 2026 revision, and plant-wide safety rules.
    Irrelevant: drafts, procedures for other plants, anything from the 2025
    revision, and vendor material."

Per seed there are 16 plant procedures and 6 plant-wide rules.

- Each **procedure** has one relevant memory and four near-identical
  distractors: the same procedure at another plant, a draft, the 2025 version,
  and a vendor claim. Each asserts a different value.
- Each **plant-wide rule** is relevant despite naming no plant. A filter that
  keeps "this plant only" drops it.

Every memory carries its metadata (plant, status, revision, source) and every
arm renders the same notes with it. Each question names the plant, so the
plain baseline knows which plant it is at. What it does not know is the rest
of the objective. Each task is asked in two phrasings.

Arms (same retrieval, same k = 5, same model, temperature 0):
  plain         no objective
  prompt_only   the objective's statement and rules in the system prompt
  filter_only   retrieval restricted by the model-compiled objective (retrieve(objective=))
  both          compiled filter + objective in the prompt
  filter_gold   retrieval restricted by hand-written rules (exploratory: the
                filter route without compilation loss)
  oracle        only the relevant memory is retrievable; plain prompt

    python -m experiments.m1_objective --split dev --model qwen2.5:3b --cache c.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Sequence

PLANTS = ("ashby", "brook", "carr")
ARMS = ("plain", "prompt_only", "filter_only", "both", "filter_gold", "oracle")
SPLITS = {"dev": range(100, 102), "test": range(0, 10)}
K = 5
EQUIPMENT = [("pump", "restart pressure", "bar", 2, 9), ("compressor", "discharge limit", "bar", 6, 15),
             ("chiller", "setpoint", "C", 2, 12), ("boiler", "purge time", "s", 30, 120),
             ("conveyor", "belt speed", "m/min", 10, 60), ("mixer", "batch time", "min", 5, 45),
             ("valve", "opening torque", "Nm", 20, 90), ("fan", "trip current", "A", 5, 40)]
RULES = [("flange bolt", "torque limit", "Nm", 30, 80), ("hot work permit", "gas test interval", "min", 15, 60),
         ("lockout", "verification wait", "s", 10, 90), ("confined space", "gas alarm threshold", "ppm", 10, 50),
         ("forklift", "speed limit", "km/h", 5, 15), ("eyewash", "flush time", "min", 10, 20)]
SYSTEM = ("You answer questions for plant staff using the notes provided. "
          "Reply with the number only.")


def statement(plant: str) -> str:
    p = plant.title()
    return (f"This session supports the night shift at {p}. Relevant: approved procedures for "
            f"{p} from the 2026 revision, and plant-wide safety rules. Irrelevant: drafts, "
            f"procedures for other plants, anything from the 2025 revision, and vendor material.")


def gold(plant: str) -> Any:
    from memory_fabric.objective import MemoryObjective, Rule

    return MemoryObjective(statement(plant), include=(
        (Rule("plant", "eq", plant), Rule("status", "eq", "approved"),
         Rule("revision", "eq", 2026), Rule("source", "eq", "staff")),
        (Rule("plant", "eq", "all"), Rule("status", "eq", "approved"),
         Rule("revision", "eq", 2026), Rule("source", "eq", "staff"))))


FIELDS = {"plant": [*PLANTS, "all"], "status": ["approved", "draft"], "revision": [2025, 2026],
          "source": ["staff", "vendor"]}


def world(seed: int) -> dict[str, Any]:
    rng = random.Random(seed)
    plant = rng.choice(PLANTS)
    others = [p for p in PLANTS if p != plant]
    memories, tasks = [], []
    names = rng.sample(range(10, 99), 16)
    for n in range(16):
        kind, param, unit, lo, hi = EQUIPMENT[n % len(EQUIPMENT)]
        equip = f"{kind} {kind[0].upper()}{names[n]}"
        values = rng.sample(range(lo, hi + 1), 5)
        variants = [(plant, "approved", 2026, "staff"), (rng.choice(others), "approved", 2026, "staff"),
                    (plant, "draft", 2026, "staff"), (plant, "approved", 2025, "staff"),
                    (plant, "approved", 2026, "vendor")]
        for v, (pl, status, rev, src) in zip(values, variants):
            memories.append({"text": f"The {param} for the {equip} at {pl.title()} is {v} {unit}.",
                             "context": {"plant": pl, "status": status, "revision": rev, "source": src},
                             "relevant": (pl, status, rev, src) == variants[0], "task": n})
        tasks.append({"task": n, "kind": "procedure", "answer": values[0], "wrong": values[1:],
                      "questions": [f"What is the {param} for the {equip} at {plant.title()}?",
                                    f"At {plant.title()}, what {param} should the {equip} use?"]})
    for n, (thing, param, unit, lo, hi) in enumerate(RULES):
        t = 16 + n
        values = rng.sample(range(lo, hi + 1), 4)
        variants = [("all", "approved", 2026, "staff"), ("all", "draft", 2026, "staff"),
                    ("all", "approved", 2025, "staff"), ("all", "approved", 2026, "vendor")]
        for v, (pl, status, rev, src) in zip(values, variants):
            memories.append({"text": f"Plant-wide safety rule: the {thing} {param} is {v} {unit}.",
                             "context": {"plant": pl, "status": status, "revision": rev, "source": src},
                             "relevant": (pl, status, rev, src) == variants[0], "task": t})
        tasks.append({"task": t, "kind": "plant_wide", "answer": values[0], "wrong": values[1:],
                      "questions": [f"What is the {thing} {param} at {plant.title()}?",
                                    f"At {plant.title()}, what {param} applies to the {thing}?"]})
    rng.shuffle(memories)
    return {"plant": plant, "memories": memories, "tasks": tasks}


def render(memory: Any) -> str:
    c = memory.context
    return (f"[plant: {c['plant']} | status: {c['status']} | revision: {c['revision']} | "
            f"source: {c['source']}] {memory.content}")


def ask(client: Any, model: str, cache: Any, system: str, text: str) -> str:
    key = hashlib.sha256(f"{model}\n{system}\n{text}".encode()).hexdigest()
    hit = cache.get(key)
    if hit is not None:
        return str(hit)
    result = client.chat(model=model, messages=[{"role": "system", "content": system},
                                                {"role": "user", "content": text}],
                         temperature=0.0, num_predict=16)
    answer = (result.get("message") or {}).get("content", "") or ""
    cache.put(key, answer)
    return str(answer)


def compiled(client: Any, model: str, cache: Any, plant: str) -> Any:
    from memory_fabric.objective import MemoryObjective, compile_objective

    key = hashlib.sha256(f"compile\n{model}\n{statement(plant)}".encode()).hexdigest()
    hit = cache.get(key)
    if hit is not None:
        return MemoryObjective.from_json(json.loads(hit))
    objective = compile_objective(statement(plant), FIELDS, client, model)
    cache.put(key, json.dumps(objective.to_json()))
    return objective


def run_seed(seed: int, client: Any, model: str, cache: Any) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    from memory_fabric import MemoryFabric

    w = world(seed)
    fab = MemoryFabric(":memory:", auto_activate=True)
    truth: dict[str, bool] = {}
    for m in w["memories"]:
        mid = fab.remember("staff", m["text"], scope="team", context=m["context"])
        truth[mid] = m["relevant"]
    objective = compiled(client, model, cache, w["plant"])
    gold_objective = gold(w["plant"])
    admitted = {mid for mid in truth if objective.admits(fab.state.memories[mid].context)}
    relevant = {mid for mid, r in truth.items() if r}
    compile_quality = {
        "admission_precision": round(len(admitted & relevant) / len(admitted), 4) if admitted else 0.0,
        "admission_recall": round(len(admitted & relevant) / len(relevant), 4),
        "rules": objective.to_json(),
    }
    oracle_ids = relevant
    rows = []
    for task in w["tasks"]:
        for q, question in enumerate(task["questions"]):
            for arm in ARMS:
                system = SYSTEM
                filt = None
                if arm in ("prompt_only", "both"):
                    system = SYSTEM + "\n\n" + objective.prompt()
                if arm in ("filter_only", "both"):
                    filt = objective
                if arm == "filter_gold":
                    filt = gold_objective
                result = fab.retrieve("agent", question, k=K, objective=filt,
                                      group_by_source_root=False, expand_lineage=0)
                notes = result.exposed
                if arm == "oracle":
                    pool = fab.retrieve("agent", question, k=50, group_by_source_root=False,
                                        expand_lineage=0).exposed
                    notes = [m for m in pool if m.id in oracle_ids][:K]
                text = ("Notes:\n" + "\n".join(f"- {render(m)}" for m in notes) if notes
                        else "Notes:\n(no notes)") + f"\n\nQuestion: {question}\nAnswer with the number only."
                answer = ask(client, model, cache, system, text)
                match = re.search(r"-?\d+", answer.replace(",", ""))
                value = int(match.group()) if match else None
                rows.append({"seed": seed, "task": task["task"], "kind": task["kind"], "q": q,
                             "arm": arm, "answer": value, "correct": int(value == task["answer"]),
                             "irrelevant": int(value in task["wrong"]),
                             "relevant_shown": int(any(truth.get(m.id) for m in notes))})
    fab.close()
    return rows, compile_quality


def analyse(rows: list[dict[str, Any]], seeds: int) -> dict[str, Any]:
    from memeval import Registration, stats

    arms: dict[str, Any] = {}
    for arm in ARMS:
        mine = [r for r in rows if r["arm"] == arm]
        arms[arm] = {"accuracy": round(sum(r["correct"] for r in mine) / len(mine), 4),
                     "used_irrelevant": round(sum(r["irrelevant"] for r in mine) / len(mine), 4),
                     "relevant_shown": round(sum(r["relevant_shown"] for r in mine) / len(mine), 4),
                     "by_kind": {k: round(sum(r["correct"] for r in mine if r["kind"] == k)
                                          / max(1, sum(r["kind"] == k for r in mine)), 4)
                                 for k in ("procedure", "plant_wide")}}
    key = lambda r: (r["seed"], r["task"], r["q"])  # noqa: E731
    by = {arm: {key(r): r["correct"] for r in rows if r["arm"] == arm} for arm in ARMS}
    units = sorted(by["plain"])
    interval, discordance = stats.paired_difference([by["both"][u] for u in units],
                                                    [by["plain"][u] for u in units])
    verdict = Registration(hypothesis="M1", metric="accuracy", mechanism="both",
                           baselines=["plain"], ceiling="oracle", seeds_required=10).evaluate(
        arms, seeds=seeds, n_pairs=len(units), discordance=discordance)
    return {"arms": arms,
            "both_minus_plain": {"mean": round(interval.point, 4),
                                 "ci95": [round(interval.low, 4), round(interval.high, 4)],
                                 "discordance": round(discordance, 4), "pairs": len(units)},
            "no_arm_beats_the_oracle": all(arms[a]["accuracy"] <= arms["oracle"]["accuracy"]
                                           for a in ARMS),
            "verdict": verdict.to_json()}


def main(argv: Sequence[str] | None = None) -> int:
    from experiments.g4_labnet import Cache
    from memory_fabric.adapters.ollama import OllamaClient

    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--split", choices=sorted(SPLITS), default="dev")
    parser.add_argument("--model", default="qwen2.5:3b")
    parser.add_argument("--arms", default=",".join(ARMS))
    parser.add_argument("--cache")
    parser.add_argument("--out")
    args = parser.parse_args(argv)
    client, cache = OllamaClient(), Cache(args.cache)
    started = time.perf_counter()
    rows, compiles = [], []
    for seed in SPLITS[args.split]:
        seed_rows, quality = run_seed(seed, client, args.model, cache)
        rows += seed_rows
        compiles.append({"seed": seed, **quality})
        print(f"  seed {seed} done, {time.perf_counter() - started:.0f}s", file=sys.stderr, flush=True)
    cache.save()
    result = {"experiment": "m1-objective", "model": args.model, "split": args.split,
              "commit": subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                                       capture_output=True, text=True).stdout.strip(),
              "seeds": len(SPLITS[args.split]), "wall_s": round(time.perf_counter() - started, 1),
              "model_calls": len(client.calls), **analyse(rows, len(SPLITS[args.split])),
              "compiles": compiles}
    if args.out:
        Path(args.out).write_text(json.dumps({**result, "rows": rows}, indent=1) + "\n",
                                  encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "compiles"}, indent=2))
    print(json.dumps([{k: c[k] for k in ("seed", "admission_precision", "admission_recall")}
                      for c in compiles]))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
