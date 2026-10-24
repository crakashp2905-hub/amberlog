"""C2 — which decisions genuinely depended on a corrected memory?

Registered in `research/prereg/c2-decision-dependence.md` before this file
and `memory_fabric/dependence.py` existed. Deterministic, known answers.

    python -m experiments.c2_dependence
"""

from __future__ import annotations

import json
import random
import subprocess
import sys
from pathlib import Path
from typing import Any

from experiments import stats
from memory_fabric import MemoryFabric
from memory_fabric.actions import ActionGate, ActionPolicy, ToolRule
from memory_fabric.dependence import decisions_depending_on

ROOT = Path(__file__).resolve().parent.parent
SEEDS = (1, 2, 3, 4, 5)


def run_seed(seed: int) -> dict[str, Any]:
    rng = random.Random(f"c2/{seed}")
    fabric = MemoryFabric(auto_activate=True, hold_suspicious=False)
    try:
        root_of: dict[str, int] = {}
        group: dict[int, list[str]] = {}
        for i in range(40):
            mid = fabric.remember(f"ag_src_{i}", f"Unit U-{100 + i}: the trip current is "
                                                 f"{rng.randrange(11, 95)} A.", scope="team")
            root_of[mid], group[i] = i, [mid]
        for i in rng.sample(range(40), 12):  # copies: same text by another agent, same root
            text = fabric.get(group[i][0]).content
            copy = fabric.remember(f"ag_copier_{i}", text, scope="team")
            root_of[copy] = i
            group[i].append(copy)
        for i in rng.sample(range(40), 12):  # conclusions derived from a fact
            d = fabric.derive(f"ag_analyst_{i}", f"Unit U-{100 + i} needs a breaker rated above "
                                                 f"its trip current.", [group[i][0]])
            root_of[d] = i
            group[i].append(d)
        pool = list(root_of)
        gate = ActionGate(fabric, ActionPolicy(tools={"act": ToolRule("act")},
                                               grants={"ag_ops": frozenset({"act"})}))
        actions: list[dict[str, Any]] = []
        while len(actions) < 60:
            evidence = rng.sample(pool, rng.choice((1, 2, 2, 3)))
            roots = {root_of[e] for e in evidence}
            need = 2 if len(roots) >= 2 and rng.random() < 0.4 else 1
            claim = f"action-{len(actions)}"
            cert = fabric.certify(claim, evidence, "ag_ops", min_independent_sources=need)
            if not gate.authorize("act", "ag_ops", cert).allowed:
                continue
            actions.append({"claim": claim, "evidence": evidence, "roots": roots, "need": need})
        usage = {i: sum(1 for a in actions if i in a["roots"]) for i in range(40)}
        target = max(usage, key=lambda i: (usage[i], len(group[i]), -i))
        corrected = group[target][0]
        fabric.quarantine(corrected, reason="re-measured", actor="lead", basis="contradicted")

        truth = {a["claim"] for a in actions
                 if target in a["roots"] and len(a["roots"] - {target}) < a["need"]}
        result = decisions_depending_on(fabric, corrected)
        flagged_cf = {d["claim_id"] for d in result["depended"]}
        flagged_graph = flagged_cf | {d["claim_id"] for d in result["would_stand"]}
    finally:
        fabric.close()

    def scores(flagged: set[str]) -> dict[str, float]:
        tp = len(flagged & truth)
        return {"flagged": len(flagged), "recall": tp / len(truth) if truth else 1.0,
                "precision": tp / len(flagged) if flagged else 1.0}

    return {"seed": seed, "affected": len(flagged_graph), "depended_truth": len(truth),
            "graph": scores(flagged_graph), "counterfactual": scores(flagged_cf),
            "oracle": scores(truth)}


def main() -> int:
    rows = [run_seed(s) for s in SEEDS]
    graph_p = stats.mean([r["graph"]["precision"] for r in rows])
    print(f"8c: graph precision {graph_p:.3f}; depended share of affected "
          f"{sum(r['depended_truth'] for r in rows) / max(1, sum(r['affected'] for r in rows)):.3f}")
    cf_p = stats.mean([r["counterfactual"]["precision"] for r in rows])
    bar = graph_p + 0.4 * (1 - graph_p)
    v = {"C2a": "SUPPORTED" if all(r["counterfactual"]["recall"] == 1.0 for r in rows)
         else "NOT SUPPORTED",
         "C2b": ("ABANDONED (graph precision >= 0.95)" if graph_p >= 0.95 else
                 "SUPPORTED" if cf_p >= bar else "NOT SUPPORTED"),
         "graph_precision": graph_p, "counterfactual_precision": cf_p, "bar": bar}
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True,
                            text=True, cwd=ROOT).stdout.strip()
    out = ROOT / "research" / "results"
    (out / "c2-dependence.json").write_text(json.dumps({"commit": commit, "rows": rows,
                                                        "verdict": v}, indent=2) + "\n")
    table = "\n".join(
        f"| {r['seed']} | {r['affected']} | {r['depended_truth']} "
        f"| {r['graph']['flagged']} · {r['graph']['precision']:.2f} · {r['graph']['recall']:.2f} "
        f"| {r['counterfactual']['flagged']} · {r['counterfactual']['precision']:.2f} · "
        f"{r['counterfactual']['recall']:.2f} |" for r in rows)
    (out / "c2-dependence.md").write_text(f"""# C2 — which decisions genuinely depended on a corrected memory?

Registered in [c2-decision-dependence.md](../prereg/c2-decision-dependence.md) before the
mechanism existed. Produced by `python -m experiments.c2_dependence` at commit `{commit}`;
raw numbers in [c2-dependence.json](c2-dependence.json). Deterministic, seeds 1–5,
60 allowed actions a seed, 40 facts with copies and derived conclusions; the most-used
fact is corrected.

**C2a (no dependent action missed): {v['C2a']}. C2b (review load): {v['C2b']}** —
counterfactual precision {cf_p:.3f} against graph {graph_p:.3f} (bar {bar:.3f}).

| seed | actions touched | truly depended | graph: flagged · precision · recall | counterfactual: flagged · precision · recall |
|---|---|---|---|---|
{table}
""")
    print(json.dumps(v, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
