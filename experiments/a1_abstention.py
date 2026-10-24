"""A1 — answerability verdicts and abstention policies with a real model.

Registered in `research/prereg/a1-answerability-abstention.md` before this file
existed. One governed store per seed, 30 questions, seven arms (§3).

    python -m experiments.a1_abstention --check          # structural verdicts, no calls
    python -m experiments.a1_abstention --seeds 1 2 3 4 5
"""

from __future__ import annotations

import argparse
import json
import random
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from experiments import stats
from experiments.d1_downstream import ask
from memory_fabric import MemoryFabric
from memory_fabric.answerability import INSUFFICIENT

ROOT = Path(__file__).resolve().parent.parent
KINDS = ("pump", "compressor", "hoist", "generator", "conveyor", "chiller")
PARAMS = (("relief pressure", "bar", 6, 48, "blow-off setting"),
          ("torque setting", "Nm", 20, 98, "fastening tightness"),
          ("coolant flow", "l/min", 10, 90, "cooling water rate"),
          ("trip current", "A", 11, 95, "overload cut-out point"))
FAMILIES = (("answerable", 15), ("paraphrased", 3), ("missing_unit", 3),
            ("missing_parameter", 3), ("transposed_id", 3), ("withdrawn_only", 3))
UNANSWERABLE = {"missing_unit", "missing_parameter", "transposed_id", "withdrawn_only"}
ARMS = ("answer_always", "instructed", "structural_gate", "judge_gate",
        "structural_then_judge", "oracle", "abstain_all")
INSTRUCTED = ("The evidence may be outdated, withdrawn or wrong. Reply with only the value "
              "(with its unit), or UNKNOWN if the evidence does not establish it.")
ALWAYS = "Reply with only the value (with its unit)."
JUDGE = ("Does the evidence above state the value this question asks for, for this exact "
         "unit? Reply YES or NO only.")


def make_code(rng: random.Random, used: set[str]) -> tuple[str, str, int]:
    while True:
        letter = rng.choice("BCDFGHKLMPRSTV")
        a, b = rng.sample(range(1, 10), 2)
        fmt = rng.choice(("{L}-{n}", "{L}/{n}", "{L}_00{n}"))
        code, swapped = fmt.format(L=letter, n=f"{a}{b}"), fmt.format(L=letter, n=f"{b}{a}")
        if code.lower() not in used and swapped.lower() not in used:
            used.update({code.lower(), swapped.lower()})
            return code, swapped, 0


def build(seed: int) -> tuple[MemoryFabric, list[dict[str, Any]]]:
    rng = random.Random(f"a1/{seed}")
    fabric = MemoryFabric(auto_activate=True)
    used: set[str] = set()
    units = []
    for _ in range(14):
        kind = rng.choice(KINDS)
        code, swapped, _ = make_code(rng, used)
        params = rng.sample(PARAMS, 2)
        values = {}
        for p in params:
            v = rng.randrange(p[2], p[3])
            values[p[0]] = v
            fabric.remember(rng.choice(("ag_tech_1", "ag_tech_2", "ag_tech_3")),
                            f"{kind.title()} {code}: the {p[0]} is {v} {p[1]}.", scope="team")
        units.append({"kind": kind, "code": code, "swapped": swapped, "params": params,
                      "values": values})
    questions: list[dict[str, Any]] = []
    pool = [(u, p) for u in units for p in u["params"]]
    rng.shuffle(pool)
    for family, n in FAMILIES:
        for _ in range(n):
            if family in ("answerable", "paraphrased"):
                u, p = pool.pop()
                name = p[4] if family == "paraphrased" else p[0]
                q = {"q": f"What is the {name} of {u['kind']} {u['code']}?",
                     "answer": str(u["values"][p[0]])}
            elif family == "missing_unit":
                u = rng.choice(units)
                code, _, _ = make_code(rng, used)
                p = rng.choice(u["params"])
                q = {"q": f"What is the {p[0]} of {u['kind']} {code}?", "answer": None}
            elif family == "missing_parameter":
                u = rng.choice(units)
                p = rng.choice([x for x in PARAMS if x not in u["params"]])
                q = {"q": f"What is the {p[0]} of {u['kind']} {u['code']}?", "answer": None}
            elif family == "transposed_id":
                u = rng.choice(units)
                p = rng.choice(u["params"])
                q = {"q": f"What is the {p[0]} of {u['kind']} {u['swapped']}?", "answer": None}
            else:  # withdrawn_only
                kind = rng.choice(KINDS)
                code, _, _ = make_code(rng, used)
                p = rng.choice(PARAMS)
                mid = fabric.remember("ag_tech_4", f"{kind.title()} {code}: the {p[0]} is "
                                      f"{rng.randrange(p[2], p[3])} {p[1]}.", scope="team")
                fabric.quarantine(mid, reason="survey was wrong", actor="reviewer",
                                  basis="contradicted")
                q = {"q": f"What is the {p[0]} of {kind} {code}?", "answer": None}
            q["family"] = family
            questions.append(q)
    return fabric, questions


def evidence_for(fabric: MemoryFabric, q: dict[str, Any]) -> tuple[str, str]:
    result = fabric.retrieve("ag_reader", q["q"], k=5)
    q["verdict"] = result.answerability(q["q"]).verdict
    lines = "\n".join(f"- {m.content}" for m in result.exposed) or "(none)"
    return lines, q["verdict"]


def prompt(lines: str, question: str, tail: str) -> str:
    return f"Evidence from the maintenance memory store:\n{lines}\n\nQuestion: {question}\n{tail}"


def abstained(reply: str) -> bool:
    return "UNKNOWN" in reply.upper()


def says(value: str, reply: str) -> bool:
    return re.search(rf"(?<![\d.]){re.escape(value)}(?![\d.])", reply) is not None


def run_seed(seed: int, model: str, cache: dict[str, Any], workers: int) -> list[dict[str, Any]]:
    fabric, questions = build(seed)
    try:
        for q in questions:
            q["lines"], _ = evidence_for(fabric, q)
    finally:
        fabric.close()
    prompts: list[str] = []
    for q in questions:
        for tail in (ALWAYS, INSTRUCTED, JUDGE):
            prompts.append(prompt(q["lines"], q["q"], tail))

    def work(p: str) -> None:
        key = f"{model}|{p}"
        if key not in cache:
            reply, cost, served = ask(p, model)
            cache[key] = {"reply": reply, "cost": cost, "served": served}

    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(work, list(dict.fromkeys(prompts))))

    def reply(q: dict[str, Any], tail: str) -> str:
        return cache[f"{model}|{prompt(q['lines'], q['q'], tail)}"]["reply"]

    rows = []
    for q in questions:
        judge_yes = reply(q, JUDGE).strip().upper().startswith("YES")
        instructed = reply(q, INSTRUCTED)
        outs = {
            "answer_always": reply(q, ALWAYS),
            "instructed": instructed,
            "structural_gate": "UNKNOWN" if q["verdict"] == INSUFFICIENT else instructed,
            "judge_gate": instructed if judge_yes else "UNKNOWN",
            "structural_then_judge": (instructed if q["verdict"] != INSUFFICIENT or judge_yes
                                      else "UNKNOWN"),
            "oracle": "UNKNOWN" if q["family"] in UNANSWERABLE else instructed,
            "abstain_all": "UNKNOWN",
        }
        for arm, out in outs.items():
            gave_up = abstained(out)
            if q["answer"] is None:
                correct = gave_up
            else:
                correct = not gave_up and says(q["answer"], out)
            rows.append({"seed": seed, "family": q["family"], "arm": arm, "question": q["q"],
                         "verdict": q["verdict"], "judge_yes": judge_yes, "reply": out,
                         "abstained": gave_up, "correct": correct})
    return rows


def summarise(rows: list[dict[str, Any]], seeds: list[int]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for arm in ARMS:
        per = {"correct": [], "abstention_recall": [], "false_abstention": [], "wrong_answer": []}
        for s in seeds:
            rs = [r for r in rows if r["arm"] == arm and r["seed"] == s]
            un = [r for r in rs if r["family"] in UNANSWERABLE]
            an = [r for r in rs if r["family"] not in UNANSWERABLE]
            per["correct"].append(sum(r["correct"] for r in rs) / len(rs))
            per["abstention_recall"].append(sum(r["abstained"] for r in un) / len(un))
            per["false_abstention"].append(sum(r["abstained"] for r in an) / len(an))
            per["wrong_answer"].append(sum(not r["correct"] and not r["abstained"] for r in rs)
                                       / len(rs))
        out[arm] = per
    return out


def verdicts(ps: dict[str, Any]) -> dict[str, Any]:
    m = {a: {k: stats.mean(v) for k, v in d.items()} for a, d in ps.items()}
    b_arm = max(("answer_always", "instructed"), key=lambda a: m[a]["correct"])
    B, C = m[b_arm]["correct"], m["oracle"]["correct"]
    v: dict[str, Any] = {"B_arm": b_arm, "B": B, "C": C, "threshold": B + 0.4 * (C - B),
                         "fa_bar": m["instructed"]["false_abstention"] + 0.10,
                         "above_ceiling": stats.check_ceiling({a: m[a]["correct"] for a in ARMS},
                                                              "oracle")}
    for key, arm in (("A1a", "structural_gate"), ("A1b", "structural_then_judge")):
        if C - B <= 0.05:
            v[key] = "ABANDONED (headroom <= 0.05)"
            continue
        ok = m[arm]["correct"] >= v["threshold"] and m[arm]["false_abstention"] <= v["fa_bar"]
        v[key] = "SUPPORTED" if ok else "NOT SUPPORTED"
        v[f"{key}_closed"] = (m[arm]["correct"] - B) / (C - B)
    return v


def to_markdown(r: dict[str, Any]) -> str:
    ps, v = r["per_seed"], r["verdict"]
    rows = "\n".join(
        f"| `{a}` | {stats.fmt_ci(ps[a]['correct'])} | {stats.fmt_ci(ps[a]['abstention_recall'])} "
        f"| {stats.fmt_ci(ps[a]['false_abstention'])} | {stats.fmt_ci(ps[a]['wrong_answer'])} |"
        for a in ARMS)
    fams = [f for f, _ in FAMILIES]
    by = "\n".join(f"| `{a}` | " + " | ".join(f"{r['by_family'][a][f]:.2f}" for f in fams) + " |"
                   for a in ARMS)
    struct = ", ".join(f"{f}: {r['structural'][f]}" for f in fams)
    return f"""# A1 — answerability verdicts and abstention policies

Registered in [a1-answerability-abstention.md](../prereg/a1-answerability-abstention.md)
before the harness existed. Produced by `python -m experiments.a1_abstention` at commit
`{r['commit']}`; every reply in [{r['out']}.json]({r['out']}.json). Model `{r['model']}`
(served: {', '.join(r['served'])}), seeds {r['seeds']}, 30 questions a seed, k = 5. Mean over
seeds, 95% bootstrap CI over seeds. Cost ${r['cost_usd']:.2f}.

| arm | correct | abstention recall | false abstention | wrong answer |
|---|---|---|---|---|
{rows}

Correct by family (pooled):

| arm | {' | '.join(fams)} |
|---|{'---|' * len(fams)}
{by}

Structural verdict `insufficient` rate by family (before any model call): {struct}.

## Verdicts

- B = {v['B']:.3f} (`{v['B_arm']}`), C = {v['C']:.3f} (`oracle`), threshold {v['threshold']:.3f},
  false-abstention bar {v['fa_bar']:.3f}.
- **A1a (`structural_gate`): {v['A1a']}**{'' if 'A1a_closed' not in v else f" ({v['A1a_closed']:.0%} of headroom)"}
- **A1b (`structural_then_judge`): {v['A1b']}**{'' if 'A1b_closed' not in v else f" ({v['A1b_closed']:.0%} of headroom)"}
- Arms above the oracle: {v['above_ceiling'] or 'none'}.
"""


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--seeds", type=int, nargs="+", default=[1, 2, 3, 4, 5])
    p.add_argument("--model", default="sonnet")
    p.add_argument("--workers", type=int, default=8)
    p.add_argument("--check", action="store_true")
    p.add_argument("--cache", default=str(ROOT / ".a1-cache.json"))
    p.add_argument("--out", default="a1-abstention")
    args = p.parse_args(argv)

    structural: dict[str, Any] = {}
    for s in args.seeds:
        fabric, qs = build(s)
        try:
            for q in qs:
                evidence_for(fabric, q)
                structural.setdefault(q["family"], []).append(q["verdict"] == INSUFFICIENT)
        finally:
            fabric.close()
    structural = {f: round(sum(v) / len(v), 3) for f, v in structural.items()}
    print("structural insufficient rate by family (no calls):", json.dumps(structural))
    if args.check:
        return 0
    cache_path = Path(args.cache)
    cache = json.loads(cache_path.read_text()) if cache_path.exists() else {}
    rows: list[dict[str, Any]] = []
    try:
        for s in args.seeds:
            rows += run_seed(s, args.model, cache, args.workers)
            print(f"seed {s}: " + ", ".join(
                f"{a} {sum(r['correct'] for r in rows if r['seed'] == s and r['arm'] == a) / 30:.2f}"
                for a in ARMS), flush=True)
    finally:
        cache_path.write_text(json.dumps(cache))
    used = {c["served"] for k, c in cache.items() if k.startswith(f"{args.model}|")}
    r: dict[str, Any] = {"model": args.model, "seeds": args.seeds, "structural": structural,
                         "per_seed": summarise(rows, args.seeds), "rows": rows,
                         "served": sorted(u for u in used if not u.startswith("error"))}
    r["by_family"] = {a: {f: stats.mean([float(x["correct"]) for x in rows
                                         if x["arm"] == a and x["family"] == f])
                          for f, _ in FAMILIES} for a in ARMS}
    r["verdict"] = verdicts(r["per_seed"])
    r["cost_usd"] = sum(c["cost"] for k, c in cache.items() if k.startswith(f"{args.model}|"))
    r["commit"] = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True,
                                 text=True, cwd=ROOT).stdout.strip()
    out = ROOT / "research" / "results"
    r["out"] = args.out
    (out / f"{args.out}.json").write_text(json.dumps(r, indent=1) + "\n")
    (out / f"{args.out}.md").write_text(to_markdown(r))
    print(json.dumps(r["verdict"], indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
