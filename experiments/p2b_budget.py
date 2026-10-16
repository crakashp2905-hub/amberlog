"""P2b — sufficiency at a fixed 400-token budget.

Registered in `research/prereg/p2b-sufficiency-at-budget.md` (§5 thresholds,
Amendment 1 for the arm under test and the split). Arms, all capped at the
same budget except `full_context`, which is reported and non-compliant:

- `top_k@400`: the shared ranking, filled to the budget. The baseline.
- `random@400`: the gated pool in a seeded random order, filled; seeds 0–4.
- `sufficiency_aware@400`: P2's selector, unchanged, truncated to the budget.
- `chain@400`: `reconstruct` steps first, then the ranking, to the budget.
- `oracle_evidence@400`: the labelled satisfiers, same gates, same budget.

    python -m research.bench.relevance_v2.build   # dev/test, if not built
    python -m experiments.p2b_budget
"""

from __future__ import annotations

import json
import random
import subprocess
import sys
from pathlib import Path
from typing import Any, Sequence

from experiments import p1_chains as p1
from experiments import p2_budget_sweep as sweep
from experiments import p2_sufficiency as p2
from experiments import relevance_bench as rb
from experiments import stats

ROOT = Path(__file__).resolve().parent.parent
BUDGET = 400
HOLDOUT = "holdout_p2b"
HOLDOUT_INDICES = range(400, 406)
RANDOM_SEEDS = (0, 1, 2, 3, 4)
FAMILIES = ("direct", "facet_trap", "multi_hop_3", "multi_hop_4", "superseded_rev",
            "unanswerable", "conflicting", "gated", "shared_root", "independent_support",
            "budget_pressure")


def build_holdout() -> int:
    from research.bench.relevance_v2 import build as B

    cases = [B.BUILDERS[f](i) for f in FAMILIES for i in HOLDOUT_INDICES]
    B.shuffle_corpora(cases)
    path = ROOT / "research" / "bench" / "relevance_v2" / f"{HOLDOUT}.json"
    path.write_text(json.dumps({"benchmark": "relevance_v2", "split": HOLDOUT,
                                "cases": cases}) + "\n", encoding="utf-8")
    return len(cases)


def chain_ids(case, ctx: p2.Context) -> list[str]:
    chain = ctx.fabric.reconstruct(
        agent_id=case["task"]["agent_id"], query=rb.query_text(case), k=p1.DEFAULT_K,
        tenant_id=case["task"].get("tenant_id", "tn_default"), as_of=rb._as_of(case))
    return [ctx.bench_id[s.memory_id] for s in chain.steps]


def assemble(case, order: Sequence[str], ctx) -> p2.Assembly:
    return sweep.fill_to_budget(case, list(dict.fromkeys(order)), ctx, BUDGET)


def run(split: str) -> dict[str, Any]:
    arms = ["top_k", "sufficiency_aware", "chain", "oracle_evidence", "full_context"]
    outcomes: dict[str, list[p2.Outcome]] = {a: [] for a in arms}
    rand: dict[int, list[p2.Outcome]] = {s: [] for s in RANDOM_SEEDS}
    for case in rb.load(split, "relevance_v2"):
        ctx = p2.build_context(case)
        try:
            ranked = p2.base_ranking(ctx)
            allowed = list(rb.apply_gates(case, ranked)[0])
            chain = [m for m in rb.apply_gates(case, chain_ids(case, ctx))[0]]
            picks = {
                "top_k": assemble(case, allowed, ctx),
                "sufficiency_aware": assemble(
                    case, p2.arm_sufficiency_aware(case, allowed, ctx, 50).selected, ctx),
                "chain": assemble(case, chain + allowed, ctx),
                "oracle_evidence": sweep.oracle_to_budget(case, allowed, ctx, BUDGET),
                "full_context": p2.arm_full_context(case, allowed, ctx, 0),
            }
            for name, a in picks.items():
                outcomes[name].append(p2.score(case, a, 0.0))
            for s in RANDOM_SEEDS:
                order = list(allowed)
                random.Random(f"p2b/{s}/{case['case_id']}").shuffle(order)
                rand[s].append(p2.score(case, assemble(case, order, ctx), 0.0))
        finally:
            ctx.fabric.close()

    def summary(rows: list[p2.Outcome]) -> dict[str, Any]:
        graded = [o for o in rows if o.sufficient is not None]
        abst = [o for o in rows if o.expect_abstain]
        answerable = [o for o in rows if not o.expect_abstain]
        return {
            "sufficient": sum(o.sufficient for o in graded) / len(graded),
            "mean_tokens": sum(o.prompt_tokens for o in rows) / len(rows),
            "abstention_precision": (sum(o.abstained for o in abst) / len(abst)) if abst else None,
            "false_abstention": sum(o.abstained for o in answerable) / len(answerable),
            "must_not_expose": sum(bool(o.exposed_forbidden) for o in rows) / len(rows),
            "by_family": {f: (lambda g: sum(o.sufficient for o in g) / len(g) if g else None)(
                [o for o in graded if o.family == f]) for f in FAMILIES},
        }

    out: dict[str, Any] = {"split": split, "cases": len(outcomes["top_k"]),
                           "arms": {a: summary(outcomes[a]) for a in arms}}
    per_seed = [summary(rand[s]) for s in RANDOM_SEEDS]
    out["arms"]["random"] = {
        "sufficient": stats.mean([p["sufficient"] for p in per_seed]),
        "sufficient_by_seed": [p["sufficient"] for p in per_seed],
        "mean_tokens": stats.mean([p["mean_tokens"] for p in per_seed]),
        "abstention_precision": per_seed[0]["abstention_precision"],
        "false_abstention": 0.0,
        "must_not_expose": max(p["must_not_expose"] for p in per_seed),
        "by_family": {f: stats.mean([p["by_family"][f] for p in per_seed
                                     if p["by_family"][f] is not None]) for f in FAMILIES},
    }
    return out


def verdict(r: dict[str, Any]) -> dict[str, Any]:
    a = r["arms"]
    compliant = {n: v for n, v in a.items() if v["mean_tokens"] <= BUDGET}
    B = max(compliant[n]["sufficient"] for n in ("top_k", "random") if n in compliant)
    C = a["oracle_evidence"]["sufficient"]
    S = a["chain"]["sufficient"]
    v: dict[str, Any] = {"B": B, "C": C, "S": S, "threshold": B + 0.4 * (C - B),
                         "non_compliant": sorted(set(a) - set(compliant)),
                         "above_ceiling": stats.check_ceiling(
                             {n: x["sufficient"] for n, x in compliant.items()},
                             "oracle_evidence"),
                         "must_not_expose_any": {n: x["must_not_expose"] for n, x in a.items()
                                                 if x["must_not_expose"] > 0}}
    if v["must_not_expose_any"]:
        v["verdict"] = "FAILED (must_not_expose non-zero)"
    elif C - B <= 0.05:
        v["verdict"] = "ABANDONED (headroom <= 0.05)"
    elif "chain" not in compliant:
        v["verdict"] = "NOT SUPPORTED (arm over budget)"
    else:
        v["verdict"] = "SUPPORTED" if S >= v["threshold"] else "NOT SUPPORTED"
    v["closed_share"] = (S - B) / (C - B) if C > B else None
    return v


def to_markdown(r: dict[str, Any]) -> str:
    v = r["verdict"]
    names = ["top_k", "random", "sufficiency_aware", "chain", "oracle_evidence", "full_context"]

    def table(split: dict[str, Any]) -> str:
        rows = []
        for n in names:
            x = split["arms"][n]
            ap = "—" if x["abstention_precision"] is None else f"{x['abstention_precision']:.3f}"
            rows.append(f"| `{n}` | {x['sufficient']:.3f} | {x['mean_tokens']:.0f} | {ap} "
                        f"| {x['false_abstention']:.3f} | {x['must_not_expose']:.3f} |")
        return ("| arm | sufficient | mean tokens | abstention precision | false abstention "
                "| must-not-expose |\n|---|---|---|---|---|---|\n" + "\n".join(rows))

    fam = "\n".join(
        f"| {f} | " + " | ".join(
            "—" if r["holdout"]["arms"][n]["by_family"][f] is None
            else f"{r['holdout']['arms'][n]['by_family'][f]:.2f}" for n in names) + " |"
        for f in FAMILIES)
    closed = "—" if v["closed_share"] is None else f"{v['closed_share']:.0%}"
    rnd = ", ".join(f"{x:.3f}" for x in r["holdout"]["arms"]["random"]["sufficient_by_seed"])
    return f"""# P2b — sufficiency at a fixed 400-token budget

Registered in [p2b-sufficiency-at-budget.md](../prereg/p2b-sufficiency-at-budget.md)
(Amendment 1 names the arm and the split). Produced by
`python -m experiments.p2b_budget` at commit `{r['commit']}`; raw numbers in
[p2b-budget.json](p2b-budget.json).

**{v['verdict']}.** On the fresh holdout ({r['holdout']['cases']} cases), `chain@400`
reaches {v['S']:.3f} against B = {v['B']:.3f} (best of `top_k@400` and `random@400`)
and the oracle's {v['C']:.3f}: threshold {v['threshold']:.3f}, {closed} of the headroom
closed. Arms above the ceiling: {v['above_ceiling'] or 'none'}. Non-compliant
(over budget, excluded from B): {', '.join(v['non_compliant']) or 'none'}.
Must-not-expose: {v['must_not_expose_any'] or 'zero for every arm'}.

## Holdout (evaluation)

{table(r['holdout'])}

`random@400` by seed: {rnd}.

Sufficiency by family on the holdout:

| family | {' | '.join(names)} |
|---|{'---|' * len(names)}
{fam}

## dev (for comparison)

{table(r['dev'])}

## test, *contaminated* (not evidence)

{table(r['test'])}

P1 inspected the test split when the chain was designed, so it is printed only
so it is not hidden.

**What this does not establish.** The holdout is new cases from the same
templates, not a new distribution. Sufficiency is defined by requirement slots
written by this project. Nothing here is downstream: whether a sufficient
context changes a model's answer is D1's and R6's question.
"""


def main(argv: list[str] | None = None) -> int:
    print(f"{HOLDOUT}: {build_holdout()} cases built")
    r: dict[str, Any] = {}
    for split in (HOLDOUT, "dev", "test"):
        r["holdout" if split == HOLDOUT else split] = run(split)
        print(split, {n: round(x["sufficient"], 3)
                      for n, x in r["holdout" if split == HOLDOUT else split]["arms"].items()},
              flush=True)
    r["verdict"] = verdict(r["holdout"])
    r["commit"] = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True,
                                 text=True, cwd=ROOT).stdout.strip()
    print(json.dumps(r["verdict"], indent=2))
    out = ROOT / "research" / "results"
    (out / "p2b-budget.json").write_text(json.dumps(r, indent=2) + "\n")
    (out / "p2b-budget.md").write_text(to_markdown(r))
    return 0


if __name__ == "__main__":
    sys.exit(main())
