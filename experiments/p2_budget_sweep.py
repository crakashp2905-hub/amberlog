"""How does sufficiency move with the token budget?

P2 was abandoned because its registered primary metric, sufficiency, is
trivially maximised by `full_context`: hand over everything and you hold every
satisfier by definition. The repair is to make the metric **sufficiency at a
fixed budget** — but a repaired metric needs the same discipline the first one
skipped, so this sweep establishes two things before anything is re-registered:

1. **The ceiling at each budget** (principle 8a: a threshold is a share of
   measured headroom, never an absolute margin).
2. **That no baseline maxes the metric at the budget chosen** — the failure the
   first registration committed, and which no amount of care about thresholds
   would have caught, because the defect was in the metric rather than the bar.

relevance_v2 declares `token_budget: 400` on every task, written into the
benchmark before any of this was measured, so it is the one budget this project
can use without choosing it to produce a result.

Read-only: it runs existing arms and prints a table. Nothing here is a verdict.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
from typing import Any, Mapping, Sequence

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from experiments import p2_sufficiency as p2  # noqa: E402
from experiments import relevance_bench as rb  # noqa: E402

BUDGETS = (25, 50, 100, 200, 400, 800, 1600, 3200, 6400)
DECLARED = 400          # relevance_v2's own task.token_budget


def fill_to_budget(case, ranked: Sequence[str], ctx, budget: int) -> p2.Assembly:
    """Top-k by rank, stopping at the budget. The baseline to beat."""
    chosen: list[str] = []
    spent = 0
    for memory in ranked:
        cost = p2._tokens_of(case, [memory])
        if chosen and spent + cost > budget:
            break
        chosen.append(memory)
        spent += cost
    return p2.Assembly(chosen, not chosen, spent,
                       p2._coverage(case, chosen, ctx))


def oracle_to_budget(case, ranked: Sequence[str], ctx, budget: int) -> p2.Assembly:
    """The labelled satisfiers, under the same budget.

    Capped the same way as every other arm, because an oracle with a larger
    budget than the arms it bounds is the handicap principle 8b forbids -- in
    the direction that makes the ceiling unreachable rather than beatable.
    """
    wanted: list[str] = []
    for req in case["labels"]["requirements"]:
        for satisfier in req["satisfied_by"]:
            if satisfier not in wanted:
                wanted.append(satisfier)
    ordered = [m for m in ranked if m in wanted]
    return fill_to_budget(case, ordered, ctx, budget)


def run(split: str) -> dict[str, Any]:
    cases = rb.load(split, "relevance_v2")
    rows: dict[int, dict[str, Any]] = {}
    per_case: list[tuple[Any, list[str], Any]] = []
    for case in cases:
        ctx = p2.build_context(case)
        try:
            allowed, _ = rb.apply_gates(case, p2.base_ranking(ctx))
            # The context is needed after the fabric closes only for token
            # counts and term sets, both already materialised on it.
            per_case.append((case, list(allowed), ctx))
            for budget in BUDGETS:
                slot = rows.setdefault(budget, {"top_k": [], "oracle": [],
                                                "top_k_tokens": [],
                                                "top_k_memories": []})
                top = fill_to_budget(case, allowed, ctx, budget)
                orc = oracle_to_budget(case, allowed, ctx, budget)
                slot["top_k"].append(p2.score(case, top, 0.0))
                slot["oracle"].append(p2.score(case, orc, 0.0))
                slot["top_k_tokens"].append(top.prompt_tokens)
                slot["top_k_memories"].append(len(top.selected))
        finally:
            ctx.fabric.close()

    def suff(outcomes) -> float | None:
        vals = [float(bool(o.sufficient)) for o in outcomes
                if o.sufficient is not None]
        return round(sum(vals) / len(vals), 4) if vals else None

    out = {"split": split, "cases": len(cases), "declared_budget": DECLARED,
           "budgets": {}}
    for budget in BUDGETS:
        slot = rows[budget]
        base, ceiling = suff(slot["top_k"]), suff(slot["oracle"])
        out["budgets"][budget] = {
            "top_k": base,
            "oracle": ceiling,
            "headroom": round((ceiling or 0.0) - (base or 0.0), 4),
            "mean_tokens": round(sum(slot["top_k_tokens"]) / len(slot["top_k_tokens"]), 1),
            "mean_memories": round(
                sum(slot["top_k_memories"]) / len(slot["top_k_memories"]), 1),
        }
    return out


def to_markdown(result: Mapping[str, Any]) -> str:
    lines = [
        f"# P2 budget sweep · {result['split']} split",
        "",
        f"- **Benchmark:** relevance_v2, {result['cases']} cases",
        f"- **Declared budget:** {result['declared_budget']} tokens "
        f"(`task.token_budget`, written into the benchmark before this sweep)",
        "",
        "| budget (tokens) | top-k sufficiency | oracle | headroom | mean tokens used | mean memories |",
        "|---|---|---|---|---|---|",
    ]
    fmt = lambda x: "—" if x is None else f"{x:.3f}"  # noqa: E731
    for budget, row in result["budgets"].items():
        marker = " **<- declared**" if budget == result["declared_budget"] else ""
        lines.append(
            f"| {budget}{marker} | {fmt(row['top_k'])} | {fmt(row['oracle'])} | "
            f"**{row['headroom']:+.3f}** | {row['mean_tokens']:.0f} | "
            f"{row['mean_memories']:.1f} |"
        )
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--split", default="dev", choices=["dev", "test"])
    parser.add_argument("--json", dest="as_json", action="store_true")
    parser.add_argument("--out")
    args = parser.parse_args(argv)
    result = run(args.split)
    text = json.dumps(result, indent=2) if args.as_json else to_markdown(result)
    print(text)
    if args.out:
        pathlib.Path(args.out).write_text(
            to_markdown(result) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
