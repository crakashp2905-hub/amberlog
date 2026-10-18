"""M2 -- reflective rulebooks: does an agent improve its own rules from outcomes, and does it stay improved?

Real local models, on M1's ObjectiveWorld, except that **nobody tells the agent
the objective**. It starts with an empty rulebook. Each round:

1. it answers a batch of 8 training tasks, with its rulebook in the prompt;
2. the environment reveals the correct value for each, which is a verified
   outcome and not the agent's own judgement;
3. it reflects on its misses, with the notes it saw (and their metadata),
   its answer and the correct one, and writes a revision.

Every world in a seed works at the same plant, so rules about fields
generalise from round to round. The test set is a fixed, separate world,
asked after every round, including round 0, before any rule exists.

A rulebook is applied the way M1's `both` arm applies an objective: as a
retrieval filter (never one that admits nothing, `objective.sanity`) and as
rules in the prompt. The dev pilot showed why. With prompt-only rules, an
arm beat the hand-written "oracle" rulebook, so that was not a ceiling
(AGENTS.md 8b). Applied as a filter, perfect rules show only the relevant note.

Arms (same retrieval, k = 5, same model, temperature 0):
  no_rulebook       never any rules
  reflexion_append  each round's reflection is a free-text lesson appended to the prompt,
                    kept forever, never checked (Reflexion-style)
  ungated_rewrite   each round the agent rewrites its rules (validated JSON), always adopted
  gated_rewrite     the same proposals, adopted only if they beat the incumbent on a held-out
                    validation batch scored by the environment (`rulebook.Rulebook.adopt`)
  oracle_rulebook   the hand-written rules from round 0

    python -m experiments.m2_rulebook --split dev --model qwen2.5:3b --cache c.json
"""

from __future__ import annotations

import argparse
import json
import random
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Sequence

from experiments.m1_objective import FIELDS, K, SYSTEM, ask, gold, render, world

ARMS = ("no_rulebook", "reflexion_append", "ungated_rewrite", "gated_rewrite", "oracle_rulebook")
ROUNDS = 4
BATCH = 8
SPLITS = {"dev": range(300, 301), "test": range(200, 205)}
REFLECT = ("You maintain a rulebook that decides which notes to trust when answering plant staff. "
           "Notes carry metadata fields:\n{fields}\n"
           "Below are questions you answered with your current rules, the notes you saw, your "
           "answer and the correct answer. Revise the rules so the correct note is the one "
           "trusted. Return JSON: include is a list of alternatives, each a list of conditions "
           "that must all hold; exclude is a list of conditions any one of which rules a note "
           "out. Operators: eq, neq, in, not_in, gte, lte.")
LESSON = ("Below are questions you answered, the notes you saw, your answer and the correct "
          "answer. Write one or two sentences of advice to yourself for next time.")


def worlds_at(plant: str, start: int, count: int) -> list[dict[str, Any]]:
    """`count` ObjectiveWorlds at this plant, from seeds at or after `start`."""
    out, s = [], start
    while len(out) < count:
        w = world(s)
        if w["plant"] == plant:
            out.append(w)
        s += 1
    return out


class Store:
    """One world's memories in a fresh store, for retrieval."""

    def __init__(self, w: dict[str, Any]) -> None:
        from memory_fabric import MemoryFabric

        self.fab = MemoryFabric(":memory:", auto_activate=True)
        self.w = w
        for m in w["memories"]:
            self.fab.remember("staff", m["text"], scope="team", context=m["context"])

    def notes(self, question: str, objective: Any = None) -> list[Any]:
        from memory_fabric.objective import sanity

        if objective is not None and (not (objective.include or objective.exclude) or sanity(
                objective, [m["context"] for m in self.w["memories"]])):
            objective = None
        return self.fab.retrieve("agent", question, k=K, group_by_source_root=False,
                                 expand_lineage=0, objective=objective).exposed

    def close(self) -> None:
        self.fab.close()


def answer(client: Any, model: str, cache: Any, rules_text: str, store: Store,
           task: dict[str, Any], objective: Any = None) -> dict[str, Any]:
    question = task["questions"][0]
    notes = store.notes(question, objective)
    system = SYSTEM + ("\n\n" + rules_text if rules_text else "")
    text = ("Notes:\n" + "\n".join(f"- {render(m)}" for m in notes)
            + f"\n\nQuestion: {question}\nAnswer with the number only.")
    reply = ask(client, model, cache, system, text)
    match = re.search(r"-?\d+", reply.replace(",", ""))
    value = int(match.group()) if match else None
    return {"question": question, "notes": [render(m) for m in notes], "answer": value,
            "correct_value": task["answer"], "correct": int(value == task["answer"])}


def accuracy(results: list[dict[str, Any]]) -> float:
    return sum(r["correct"] for r in results) / len(results) if results else 0.0


def misses_text(results: list[dict[str, Any]]) -> str:
    misses = [r for r in results if not r["correct"]] or results[:2]
    return "\n\n".join(f"Question: {r['question']}\nNotes:\n" + "\n".join(f"- {n}" for n in r["notes"])
                       + f"\nYour answer: {r['answer']}\nCorrect answer: {r['correct_value']}"
                       for r in misses[:6])


def reflect_rules(client: Any, model: str, cache: Any, current: Any,
                  results: list[dict[str, Any]]) -> Any:
    from memory_fabric.objective import SCHEMA, MemoryObjective, validate

    described = "\n".join(f"- {k}: one of {sorted(map(str, v))}" for k, v in sorted(FIELDS.items()))
    system = REFLECT.format(fields=described)
    user = (f"Current rules: {json.dumps({'include': current.to_json()['include'], 'exclude': current.to_json()['exclude']})}\n\n"
            + misses_text(results))
    key = json.dumps(["reflect", model, system, user])
    hit = cache.get(key)
    if hit is None:
        reply = client.chat(model, [{"role": "system", "content": system},
                                    {"role": "user", "content": user}],
                            temperature=0.0, num_predict=512, schema=SCHEMA)
        hit = (reply.get("message") or {}).get("content", "") or ""
        cache.put(key, hit)
    try:
        raw = json.loads(hit)
    except json.JSONDecodeError:
        return MemoryObjective("Rules learned from outcomes", dropped=("unparseable reflection",))
    return validate(raw if isinstance(raw, dict) else {}, FIELDS, "Rules learned from outcomes")


def reflect_lesson(client: Any, model: str, cache: Any, results: list[dict[str, Any]]) -> str:
    user = misses_text(results)
    key = json.dumps(["lesson", model, user])
    hit = cache.get(key)
    if hit is None:
        reply = client.chat(model, [{"role": "system", "content": LESSON},
                                    {"role": "user", "content": user}],
                            temperature=0.0, num_predict=120)
        hit = ((reply.get("message") or {}).get("content", "") or "").strip()
        cache.put(key, hit)
    return str(hit)


def rules_prompt(objective: Any) -> str:
    if not objective.include and not objective.exclude:
        return ""
    return objective.prompt()


def run_seed(seed: int, client: Any, model: str, cache: Any) -> dict[str, Any]:
    from memory_fabric import MemoryFabric
    from memory_fabric.rulebook import Rulebook

    rng = random.Random(seed)
    test_world = world(seed)
    plant = test_world["plant"]
    train = worlds_at(plant, seed * 1000 + 1, ROUNDS)
    val = worlds_at(plant, seed * 1000 + 501, ROUNDS)
    test_store = Store(test_world)
    books = MemoryFabric(":memory:", auto_activate=True)
    gated = Rulebook(books, "gated", "agent", statement="Rules learned from outcomes")
    state: dict[str, Any] = {"ungated": gated.current(), "lessons": []}
    gold_rules = gold(plant)
    gold_text = gold_rules.prompt()
    log: dict[str, Any] = {"seed": seed, "plant": plant, "rounds": [], "decisions": []}

    def prompts() -> dict[str, str]:
        lessons = state["lessons"]
        return {"no_rulebook": "", "oracle_rulebook": gold_text,
                "reflexion_append": ("Advice from your past mistakes:\n" + "\n".join(f"- {x}" for x in lessons))
                if lessons else "",
                "ungated_rewrite": rules_prompt(state["ungated"]),
                "gated_rewrite": rules_prompt(gated.current())}

    def filters() -> dict[str, Any]:
        return {"no_rulebook": None, "reflexion_append": None, "oracle_rulebook": gold_rules,
                "ungated_rewrite": state["ungated"], "gated_rewrite": gated.current()}

    def test_round(r: int) -> None:
        current, filt = prompts(), filters()
        scores = {}
        for arm in ARMS:
            results = [answer(client, model, cache, current[arm], test_store, t, filt[arm])
                       for t in test_world["tasks"]]
            scores[arm] = round(accuracy(results), 4)
        log["rounds"].append({"round": r, "test_accuracy": scores,
                              "gated_version": gated.version,
                              "ungated_rules": state["ungated"].to_json(),
                              "gated_rules": gated.current().to_json(),
                              "lessons": list(state["lessons"])})

    test_round(0)
    for r in range(1, ROUNDS + 1):
        train_store, val_store = Store(train[r - 1]), Store(val[r - 1])
        batch = rng.sample(train[r - 1]["tasks"], BATCH)
        vbatch = rng.sample(val[r - 1]["tasks"], BATCH)
        current, filt = prompts(), filters()
        # reflexion: a lesson from its own training misses
        res = [answer(client, model, cache, current["reflexion_append"], train_store, t) for t in batch]
        state["lessons"].append(reflect_lesson(client, model, cache, res))
        # ungated: rewrite and adopt
        res = [answer(client, model, cache, current["ungated_rewrite"], train_store, t,
                      filt["ungated_rewrite"]) for t in batch]
        proposal = reflect_rules(client, model, cache, state["ungated"], res)
        state["ungated"] = proposal  # always adopted; an empty filter is not applied (Store.notes)
        # gated: rewrite, then adopt only on held-out, environment-scored evidence
        res = [answer(client, model, cache, current["gated_rewrite"], train_store, t,
                      filt["gated_rewrite"]) for t in batch]
        proposal = reflect_rules(client, model, cache, gated.current(), res)
        candidate = gated.propose(proposal, f"round {r}: {sum(1 - x['correct'] for x in res)} misses")
        incumbent = accuracy([answer(client, model, cache, current["gated_rewrite"], val_store, t,
                                     filt["gated_rewrite"]) for t in vbatch])
        challenger = accuracy([answer(client, model, cache, rules_prompt(proposal), val_store, t,
                                      proposal) for t in vbatch])
        decision = gated.adopt(candidate, incumbent_score=incumbent, candidate_score=challenger,
                               n=len(vbatch), verifier="env")
        log["decisions"].append({"round": r, "adopted": decision.adopted,
                                 "incumbent": round(incumbent, 4), "candidate": round(challenger, 4)})
        train_store.close()
        val_store.close()
        test_round(r)
    log["gated_history"] = gated.history()
    test_store.close()
    books.close()
    return log


def analyse(seeds: list[dict[str, Any]]) -> dict[str, Any]:
    from memeval import Registration

    final = {a: round(sum(s["rounds"][-1]["test_accuracy"][a] for s in seeds) / len(seeds), 4)
             for a in ARMS}
    trajectory = {a: [round(sum(s["rounds"][r]["test_accuracy"][a] for s in seeds) / len(seeds), 4)
                      for r in range(ROUNDS + 1)] for a in ARMS}
    regressions = {a: sum(1 for s in seeds for r in range(1, ROUNDS + 1)
                          if s["rounds"][r]["test_accuracy"][a] < s["rounds"][r - 1]["test_accuracy"][a])
                   for a in ARMS}
    arms = {a: {"final_test_accuracy": final[a], "trajectory": trajectory[a],
                "test_regressions": regressions[a]} for a in ARMS}
    baselines = ["no_rulebook", "reflexion_append", "ungated_rewrite"]
    verdict = Registration(hypothesis="M2a", metric="final_test_accuracy",
                           mechanism="gated_rewrite", baselines=baselines,
                           ceiling="oracle_rulebook", seeds_required=5).evaluate(arms, seeds=len(seeds))
    adopted = sum(d["adopted"] for s in seeds for d in s["decisions"])
    return {"arms": arms, "verdict": verdict.to_json(),
            "no_arm_beats_the_oracle": all(final[a] <= final["oracle_rulebook"] for a in ARMS),
            "gated_adoptions": f"{adopted}/{sum(len(s['decisions']) for s in seeds)}"}


def main(argv: Sequence[str] | None = None) -> int:
    from experiments.g4_labnet import Cache
    from memory_fabric.adapters.ollama import OllamaClient

    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--split", choices=sorted(SPLITS), default="dev")
    parser.add_argument("--model", default="qwen2.5:3b")
    parser.add_argument("--cache")
    parser.add_argument("--out")
    args = parser.parse_args(argv)
    client, cache = OllamaClient(), Cache(args.cache)
    started = time.perf_counter()
    seeds = []
    for seed in SPLITS[args.split]:
        seeds.append(run_seed(seed, client, args.model, cache))
        print(f"  seed {seed} done, {time.perf_counter() - started:.0f}s", file=sys.stderr, flush=True)
    cache.save()
    result = {"experiment": "m2-rulebook", "model": args.model, "split": args.split,
              "commit": subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                                       capture_output=True, text=True).stdout.strip(),
              "seeds": len(seeds), "wall_s": round(time.perf_counter() - started, 1),
              "model_calls": len(client.calls), **analyse(seeds)}
    if args.out:
        Path(args.out).write_text(json.dumps({**result, "per_seed": seeds}, indent=1) + "\n",
                                  encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
