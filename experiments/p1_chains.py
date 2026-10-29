"""P1 — evidence-chain reconstruction: the registered verdict and the
explanation's correctness.

Registered in `research/prereg/p1-evidence-chain-reconstruction.md` before the
mechanism existed. Ranking metrics come from `relevance_bench` so the `chain`
arm is scored by the same code as every other arm; this module measures the
three things that are specific to chains and computes the verdict.

**Necessity is the explanation's correctness, and it is not the primary
metric.** A mechanism could score perfectly on it by returning one-step chains,
which is why the registration made sufficiency primary and this secondary.
Necessity is checked against the labelled `critical` set, which the mechanism
never sees.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from experiments import relevance_bench as rb  # noqa: E402
from amberlog.relevance import ReasonCode  # noqa: E402

BENCHMARK = "relevance_v2"
CHAIN_FAMILIES = ("multi_hop_3", "multi_hop_4")
DEFAULT_K = 5
SUFFICIENCY_SHARE = 0.40
ABANDON_IF_HEADROOM_BELOW = 0.05
BASELINES = ("lexical", "real_vector", "real_hybrid")


@dataclass
class Outcome:
    case_id: str
    family: str
    returned: tuple[str, ...]
    complete: bool
    connected: bool
    missing: tuple[str, ...]
    steps: int
    connectors: int
    deepest_rank: int
    necessary_claimed: tuple[str, ...]
    critical: tuple[str, ...]
    sufficient: bool | None
    nodes_explored: int
    budget_exhausted: bool
    latency_ms: float


def run_chain(split: str, k: int = DEFAULT_K, families: Sequence[str] | None = None
              ) -> list[Outcome]:
    out: list[Outcome] = []
    for case in rb.load(split, BENCHMARK):
        if families is not None and case["family"] not in families:
            continue
        fabric, ids = rb._build_fabric(case, "lexical")
        try:
            started = time.perf_counter()
            chain = fabric.reconstruct(
                agent_id=case["task"]["agent_id"],
                query=rb.query_text(case), k=k,
                tenant_id=case["task"].get("tenant_id", "tn_default"),
                as_of=rb._as_of(case),
            )
            elapsed = (time.perf_counter() - started) * 1000.0
            returned = [ids[s.memory_id] for s in chain.steps]
            allowed, _ = rb.apply_gates(case, returned)
            scored = rb.score_case(case, allowed, {}, k)
            out.append(Outcome(
                case_id=case["case_id"], family=case["family"],
                returned=tuple(returned),
                complete=chain.complete, connected=chain.connected,
                missing=chain.missing, steps=len(chain.steps),
                connectors=len([s for s in chain.steps
                                if s.reason is ReasonCode.DEPENDENCY_REQUIRED]),
                deepest_rank=max((s.rank for s in chain.steps), default=-1),
                necessary_claimed=tuple(
                    ids[s.memory_id] for s in chain.steps if s.necessary),
                critical=tuple(case["labels"]["critical"]),
                sufficient=scored.sufficient,
                nodes_explored=chain.nodes_explored,
                budget_exhausted=chain.budget_exhausted,
                latency_ms=elapsed,
            ))
        finally:
            fabric.close()
    return out


def summarise(outcomes: Sequence[Outcome]) -> dict[str, Any]:
    mean = lambda xs: round(sum(xs) / len(xs), 4) if xs else None  # noqa: E731
    suff = [o for o in outcomes if o.sufficient is not None]
    # Necessity, pooled over the cases that declare a critical set. Precision
    # and recall are reported separately and never combined: a mechanism that
    # returns one memory scores 1.0 precision and near-zero recall, and an F1
    # would hide which of the two it was.
    claimed = sum(len(o.necessary_claimed) for o in outcomes)
    correct = sum(len(set(o.necessary_claimed) & set(o.critical)) for o in outcomes)
    criticals = sum(len(o.critical) for o in outcomes)
    recalled = correct
    return {
        "cases": len(outcomes),
        "sufficient": mean([float(bool(o.sufficient)) for o in suff]),
        "complete_rate": mean([float(o.complete) for o in outcomes]),
        "connected_rate": mean([float(o.connected) for o in outcomes]),
        "mean_steps": mean([float(o.steps) for o in outcomes]),
        "mean_connectors": mean([float(o.connectors) for o in outcomes]),
        "deepest_rank_used": max((o.deepest_rank for o in outcomes), default=-1),
        "necessity_precision": round(correct / claimed, 4) if claimed else None,
        "necessity_recall": round(recalled / criticals, 4) if criticals else None,
        "nodes_explored": mean([float(o.nodes_explored) for o in outcomes]),
        "budget_exhausted_rate": mean(
            [float(o.budget_exhausted) for o in outcomes]),
        "latency_ms": mean([o.latency_ms for o in outcomes]),
    }


def by_family(outcomes: Sequence[Outcome]) -> dict[str, dict[str, Any]]:
    groups: dict[str, list[Outcome]] = {}
    for o in outcomes:
        groups.setdefault(o.family, []).append(o)
    return {f: summarise(rows) for f, rows in sorted(groups.items())}


def verdict(chain_sufficient: float | None, baseline: float, ceiling: float
            ) -> dict[str, Any]:
    headroom = ceiling - baseline
    out = {
        "best_baseline": baseline, "ceiling": ceiling,
        "headroom": round(headroom, 4),
        "threshold": round(baseline + SUFFICIENCY_SHARE * headroom, 4),
        "chain": chain_sufficient,
    }
    if headroom <= ABANDON_IF_HEADROOM_BELOW:
        out["verdict"] = "ABANDONED"
        return out
    if chain_sufficient is None:
        out["verdict"] = "NO DATA"
        return out
    if chain_sufficient > ceiling + 1e-9:
        out["verdict"] = "CEILING BREACHED — the ceiling is wrong, not the arm"
        return out
    out["closed_share"] = round(
        (chain_sufficient - baseline) / headroom, 4) if headroom else 0.0
    out["verdict"] = (
        "SUPPORTED" if chain_sufficient >= out["threshold"]
        else ("NOT SUPPORTED" if chain_sufficient > baseline
              else "KILLED — at or below every baseline"))
    return out


def baseline_sufficiency(split: str, k: int) -> tuple[float, float]:
    """The registered baselines and the ceiling, on the chain families only.

    Taken from `relevance_bench` rather than recomputed, so the chain arm and
    the arms it is compared against are scored by one implementation.
    """
    result = rb.run(split, k=k, benchmark=BENCHMARK,
                    arms=list(BASELINES) + ["oracle"])
    def pooled(arm: str) -> float:
        rows = [
            r for r in result["_reports"][arm].cases
            if r.family in CHAIN_FAMILIES and r.sufficient is not None
        ]
        return (sum(1 for r in rows if r.sufficient) / len(rows)) if rows else 0.0
    return max(pooled(a) for a in BASELINES), pooled("oracle")


def to_markdown(result: Mapping[str, Any]) -> str:
    fmt = lambda x: "—" if x is None else f"{x:.3f}"  # noqa: E731
    v = result["verdict"]
    lines = [
        f"# P1 — evidence-chain reconstruction · {result['split']} split",
        "",
        f"- **Benchmark:** {result['benchmark']}, {result['all']['cases']} cases, k={result['k']}",
        f"- **Primary:** sufficiency pooled over {', '.join(CHAIN_FAMILIES)}",
        "",
        "## Verdict, applied as registered",
        "",
        "```",
        f"best baseline        B = {v['best_baseline']:.3f}",
        f"ceiling              C = {v['ceiling']:.3f}",
        f"headroom                 {v['headroom']:+.3f}",
        f"threshold            B + {SUFFICIENCY_SHARE:.2f} x headroom = {v['threshold']:.3f}",
        f"chain                    {fmt(v['chain'])}",
        f"VERDICT: {v['verdict']}",
        "```",
    ]
    if "closed_share" in v:
        lines += ["", f"Closed **{v['closed_share']:.0%}** of the headroom against "
                      f"a registered {SUFFICIENCY_SHARE:.0%}."]
    lines += [
        "",
        "## Chain shape, explanation and cost",
        "",
        "| scope | sufficient | complete | connected | steps | connectors | "
        "deepest rank | necessity P | necessity R | nodes | latency ms |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for label, row in [("all families", result["all"])] + [
        (f"`{f}`", result["by_family"][f]) for f in sorted(result["by_family"])
    ]:
        lines.append(
            f"| {label} | {fmt(row['sufficient'])} | {fmt(row['complete_rate'])} | "
            f"{fmt(row['connected_rate'])} | {fmt(row['mean_steps'])} | "
            f"{fmt(row['mean_connectors'])} | {row['deepest_rank_used']} | "
            f"{fmt(row['necessity_precision'])} | {fmt(row['necessity_recall'])} | "
            f"{fmt(row['nodes_explored'])} | {fmt(row['latency_ms'])} |"
        )
    lines += [
        "",
        "`deepest rank` is the position in the lexical ranking of the "
        "lowest-ranked memory the chain used. It is the quantitative form of "
        "*no single memory matches the query*: a connector sitting in the "
        "hundreds is one no top-k arm could ever return.",
        "",
        "`necessity P` is the share of steps called necessary that are in the "
        "labelled critical set; `necessity R` is the share of critical "
        "memories both returned and called necessary. Reported separately and "
        "never combined, because a one-step chain scores perfect precision.",
    ]
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--split", default="dev", choices=["dev", "test"])
    parser.add_argument("--k", type=int, default=DEFAULT_K)
    parser.add_argument("--json", dest="as_json", action="store_true")
    parser.add_argument("--out")
    args = parser.parse_args(argv)

    outcomes = run_chain(args.split, k=args.k)
    chain_pooled = summarise(
        [o for o in outcomes if o.family in CHAIN_FAMILIES])["sufficient"]
    base, ceiling = baseline_sufficiency(args.split, args.k)
    result = {
        "experiment": "p1-evidence-chain-reconstruction",
        "benchmark": BENCHMARK, "split": args.split, "k": args.k,
        "all": summarise(outcomes),
        "by_family": by_family(outcomes),
        "verdict": verdict(chain_pooled, base, ceiling),
    }
    print(json.dumps(result, indent=2) if args.as_json
          else to_markdown(result))
    if args.out:
        pathlib.Path(args.out).write_text(
            to_markdown(result) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
