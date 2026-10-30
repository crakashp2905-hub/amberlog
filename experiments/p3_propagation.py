"""P3 — correction propagation: five rules over one ranking.

Registered in `research/prereg/p3-correction-propagation.md` before this file
existed. The question: a conclusion has four apparent supports, all four derive
from one survey, and the survey is retracted. What should reach the context?

## Why the arms share a base ranking

Every arm applies its rule to **the same ranking from the same retrieval**, so
the only thing that varies is the propagation rule. Measuring five end-to-end
configurations instead would have confounded the rule with whatever else
differs between them, which is how `store_temporal` and `store_all` once came
to print identical numbers and read as temporal filtering doing all the work.

The grouping arm calls the product's own `_group_by_root` and `source_root`
rather than a reimplementation, so this experiment cannot quietly diverge from
what ships. The other three rules are implemented here because they are
baselines the product deliberately does not have.

## The trap the benchmark is built around

`shared_root` and `independent_support` have identical surface -- the same
retracted survey, the same three derived restatements -- and differ only in
whether one further measurement descends from it. So **the conservative answer
is wrong half the time**: blanket invalidation gets `shared_root` right and
`independent_support` wrong, by discarding a standing load-cell trial and
abstaining when the answer was there. A method cannot win here by withholding
more, which is why two primary metrics are registered and neither may be
traded for the other.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Sequence

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from experiments import relevance_bench as rb  # noqa: E402

DEFAULT_K = 5

# Which families carry provenance structure, per fixture. Named rather than
# inferred: a family without a retracted ancestor contributes a 0.000 to every
# arm and would dilute the comparison identically for all of them, which looks
# like agreement between rules that have never been asked to differ.
PROVENANCE_FAMILIES = {
    "relevance_v2": ("shared_root", "independent_support"),
    "propagation_v1": ("retracted_intermediate", "deep_chain", "copied_document",
                       "independent_reconfirmation"),
}
BENCHMARK = "propagation_v1"
FAMILIES = PROVENANCE_FAMILIES[BENCHMARK]

# The registered thresholds. Here so the code and the pre-registration cannot
# drift, and so the verdict is computed rather than argued.
STALE_SHARE = 0.40
ABANDON_IF_HEADROOM_BELOW = 0.25


# --- the propagation rules --------------------------------------------------
#
# Each takes the ranking, the corpus and the fabric handles, and returns the
# ranking it would allow. None of them may look at `labels` except the oracle,
# which is the ceiling and says so.


Rule = Callable[..., list[str]]


def rule_no_propagation(ranked: list[str], ctx: "Context") -> list[str]:
    """Retraction affects only the retracted memory itself."""
    return ranked


def rule_blanket_invalidation(ranked: list[str], ctx: "Context") -> list[str]:
    """Withhold anything sharing a source root with a retracted memory.

    The conservative baseline, and the one the matched pair exists to catch: it
    cannot distinguish "derives from the retracted survey" from "happens to
    share its root", and on `independent_support` it discards nothing wrongly
    only because the standing trial has a different root. Where it fails is the
    reverse case, and the metric for that is `unnecessary_invalidation`.
    """
    return [m for m in ranked if ctx.root_of(m) not in ctx.retracted_roots]


def rule_graph_traversal(ranked: list[str], ctx: "Context") -> list[str]:
    """Withhold anything reachable from a retracted memory through parents.

    Distinct from blanket invalidation in principle: it follows edges rather
    than root identity, so a memory sharing a root without descending from the
    retracted one survives. On these families every derived memory is one hop
    from the root, so the two mostly coincide -- which prediction 2 of the
    registration says in advance, and which makes a deeper chain the next
    benchmark change rather than a ranker.
    """
    return [m for m in ranked if not ctx.has_retracted_ancestor(m)]


def rule_source_root_grouping(ranked: list[str], ctx: "Context") -> list[str]:
    """The product. Keep the best-ranked memory per source root, sparing a
    premise of something already kept.

    Not a propagation rule at all, strictly: it reduces copies rather than
    reasoning about standing support. That is the substance of prediction 3 --
    on `shared_root` the best-ranked derived memory is still stale, so grouping
    cuts how much stale evidence arrives and cannot cut it to zero.
    """
    scored = [(m, 1.0 - i * 1e-6) for i, m in enumerate(ranked)]
    kept = ctx.fabric._group_by_root(
        [(ctx.store_id[m], s) for m, s in scored], limit=len(scored)
    )
    return [ctx.bench_id[sid] for sid, _ in kept]


def rule_oracle_propagation(ranked: list[str], ctx: "Context") -> list[str]:
    """Withhold exactly the labelled stale set.

    Scores 0.000 stale citations **by construction**, because it is told which
    memories are stale. It bounds the metric and is not a method, and every
    place this number appears must say so.
    """
    return [m for m in ranked if m not in ctx.stale]


RULES: dict[str, Rule] = {
    "no_propagation": rule_no_propagation,
    "blanket_invalidation": rule_blanket_invalidation,
    "graph_traversal": rule_graph_traversal,
    "source_root_grouping": rule_source_root_grouping,
    "oracle_propagation": rule_oracle_propagation,
}
BASELINES = ("no_propagation", "blanket_invalidation", "graph_traversal")
CEILING = "oracle_propagation"


# --- per-case context -------------------------------------------------------


@dataclass
class Context:
    """One case, written into a real store, with the lookups a rule needs."""

    case: Mapping[str, Any]
    fabric: Any
    store_id: dict[str, str]          # benchmark id -> store id
    bench_id: dict[str, str]          # store id -> benchmark id
    retracted: set[str]               # benchmark ids whose lifecycle is blocked
    stale: set[str]

    def root_of(self, bench: str) -> str:
        return self.bench_id[self.fabric.source_root(self.store_id[bench])]

    @property
    def retracted_roots(self) -> set[str]:
        return {self.root_of(m) for m in self.retracted}

    def has_retracted_ancestor(self, bench: str) -> bool:
        graph = self.fabric.lineage_graph
        ancestors = {
            self.bench_id[node.memory_id]
            for node in graph.ancestors(self.store_id[bench])
            if node.memory_id in self.bench_id
        }
        return bool(ancestors & self.retracted)


def build_context(case: Mapping[str, Any]) -> Context:
    from memory_fabric import MemoryFabric

    fabric = MemoryFabric(
        ":memory:", auto_activate=True, encrypt_content=False, retrieval="lexical"
    )
    store_id: dict[str, str] = {}
    bench_id: dict[str, str] = {}
    retracted: set[str] = set()
    # Dependency order, via the harness's own helper, so the two cannot drift.
    for memory in rb.insertion_order(case["corpus"]):
        parents = [
            (store_id[p[0]], 1) for p in (memory.get("parents") or []) if p[0] in store_id
        ]
        stored = fabric.remember(
            agent_id=case["task"]["agent_id"],
            content=memory["content"],
            tenant_id=memory.get("tenant_id", "tn_default"),
            parents=parents,
            method="consolidated" if parents else "observed",
            valid_from=memory.get("valid_from"),
            valid_to=memory.get("valid_to"), scope="team",
        )
        store_id[memory["id"]] = stored
        bench_id[stored] = memory["id"]
        if memory["lifecycle_state"] in rb.BLOCKED_LIFECYCLE:
            retracted.add(memory["id"])
    # Quarantine after every write, so `propagate=True` has descendants to
    # reach. Inside the loop it silently did nothing, which is what made the
    # first version of this experiment report a product with no propagation.
    for bench in retracted:
        fabric.quarantine(store_id[bench], reason="benchmark fixture",
                          actor="bench", basis="contradicted")
    return Context(
        case=case, fabric=fabric, store_id=store_id, bench_id=bench_id,
        retracted=retracted, stale=set(case["labels"].get("stale") or ()),
    )


def base_ranking(ctx: Context) -> list[str]:
    """One retrieval, shared by every arm.

    `k` is the whole corpus so each rule sees the same full ordering and the
    truncation to k happens after the rule -- otherwise a rule that withholds
    anything would be compared against a shorter list than one that does not.
    """
    result = ctx.fabric.retrieve(
        agent_id=ctx.case["task"]["agent_id"],
        query=rb.query_text(ctx.case),
        k=len(ctx.case["corpus"]),
        tenant_id=ctx.case["task"].get("tenant_id", "tn_default"),
        min_relevance=0.0,
        group_by_source_root=False,
        expand_lineage=0,
    )
    return [ctx.bench_id[m.id] for m in result.exposed]


# --- metrics ----------------------------------------------------------------


@dataclass
class CaseOutcome:
    case_id: str
    family: str
    returned: tuple[str, ...]
    stale_cited: int
    cited_any_stale: bool
    standing_support_lost: bool | None
    sufficient: bool | None
    abstained: bool
    expect_abstain: bool
    exposed_forbidden: tuple[str, ...]


def score(case: Mapping[str, Any], returned: Sequence[str], k: int) -> CaseOutcome:
    labels = case["labels"]
    stale = set(labels.get("stale") or ())
    forbidden = set(labels["must_not_expose"])
    top = list(returned[:k])
    visible = set(top) - forbidden

    # `unnecessary_invalidation`, the metric that stops a rule winning by
    # withholding everything. On `independent_support` a standing measurement
    # exists and does not descend from the retracted survey; losing it is the
    # failure blanket invalidation is expected to commit.
    standing: set[str] = set()
    for req in labels["requirements"]:
        if req.get("critical"):
            standing |= set(req["satisfied_by"]) - forbidden
    standing_lost = (not (standing & visible)) if standing else None

    critical_reqs = [r for r in labels["requirements"] if r.get("critical")]
    met = [r for r in critical_reqs if set(r["satisfied_by"]) & visible]
    return CaseOutcome(
        case_id=case["case_id"],
        family=case["family"],
        returned=tuple(top),
        stale_cited=len([m for m in top if m in stale]),
        cited_any_stale=any(m in stale for m in top),
        standing_support_lost=standing_lost,
        sufficient=(len(met) == len(critical_reqs)) if critical_reqs else None,
        abstained=not top,
        expect_abstain=bool(labels["expect_abstain"]),
        exposed_forbidden=tuple(m for m in top if m in forbidden),
    )


@dataclass
class ArmReport:
    arm: str
    outcomes: list[CaseOutcome] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        n = len(self.outcomes)
        staleful = [o for o in self.outcomes if o.family in FAMILIES]
        indep = [o for o in self.outcomes if o.standing_support_lost is not None]
        suff = [o for o in self.outcomes if o.sufficient is not None]
        unans = [o for o in self.outcomes if o.expect_abstain]
        mean = lambda xs: round(sum(xs) / len(xs), 4) if xs else None  # noqa: E731
        return {
            "arm": self.arm,
            "cases": n,
            # Primary 1
            "stale_citations_mean": mean([float(o.stale_cited) for o in staleful]),
            "stale_citation_rate": mean([float(o.cited_any_stale) for o in staleful]),
            # Primary 2
            "unnecessary_invalidation": mean(
                [float(o.standing_support_lost) for o in indep]),
            "sufficient": mean([float(bool(o.sufficient)) for o in suff]),
            "abstention_precision": mean([float(o.abstained) for o in unans]),
            "must_not_expose_rate": mean(
                [float(bool(o.exposed_forbidden)) for o in self.outcomes]),
            "n_stale_cases": len(staleful),
            "n_independent_cases": len(indep),
        }

    def by_family(self) -> dict[str, dict[str, Any]]:
        """Where the residual sits, which the aggregate cannot show.

        Every arm leaves the same stale citations behind on `copied_document`
        and none on the others, so an aggregate makes the rules look closer
        than they are and hides that the remainder is one family nothing solves.
        """
        families: dict[str, list[CaseOutcome]] = {}
        for o in self.outcomes:
            families.setdefault(o.family, []).append(o)
        mean = lambda xs: round(sum(xs) / len(xs), 4) if xs else None  # noqa: E731
        return {
            family: {
                "cases": len(rows),
                "stale_cited": mean([float(r.stale_cited) for r in rows]),
                "unnecessary_invalidation": mean(
                    [float(r.standing_support_lost) for r in rows
                     if r.standing_support_lost is not None]),
                "sufficient": mean([float(bool(r.sufficient)) for r in rows
                                    if r.sufficient is not None]),
            }
            for family, rows in sorted(families.items())
        }


def run(split: str, k: int = DEFAULT_K, families: Sequence[str] | None = None,
        benchmark: str = BENCHMARK) -> dict[str, Any]:
    cases = [
        c for c in rb.load(split, benchmark)
        if families is None or c["family"] in families
    ]
    reports = {name: ArmReport(arm=name) for name in RULES}
    for case in cases:
        ctx = build_context(case)
        try:
            ranked = base_ranking(ctx)
            for name, rule in RULES.items():
                allowed, _refused = rb.apply_gates(case, rule(list(ranked), ctx))
                reports[name].outcomes.append(score(case, allowed, k))
        finally:
            ctx.fabric.close()
    return {
        "experiment": "p3-correction-propagation",
        "benchmark": benchmark,
        "split": split,
        "k": k,
        "cases": len(cases),
        "arms": {name: report.summary() for name, report in reports.items()},
        "by_family": {name: report.by_family() for name, report in reports.items()},
    }


# --- the registered verdict, computed rather than argued --------------------


def verdict(result: Mapping[str, Any]) -> dict[str, Any]:
    arms = result["arms"]
    base = min(arms[a]["stale_citations_mean"] for a in BASELINES)
    ceiling = arms[CEILING]["stale_citations_mean"]
    headroom = base - ceiling
    best_base_invalidation = min(
        arms[a]["unnecessary_invalidation"] for a in BASELINES)
    product = arms["source_root_grouping"]

    out = {
        "best_baseline_stale": base,
        "ceiling_stale": ceiling,
        "headroom": round(headroom, 4),
        "threshold": round(base - STALE_SHARE * headroom, 4),
        "product_stale": product["stale_citations_mean"],
        "baseline_unnecessary_invalidation": best_base_invalidation,
        "product_unnecessary_invalidation": product["unnecessary_invalidation"],
    }
    if headroom <= ABANDON_IF_HEADROOM_BELOW:
        out["verdict"] = "ABANDONED"
        out["why"] = (
            f"headroom {headroom:+.3f} <= {ABANDON_IF_HEADROOM_BELOW} citations a "
            f"case. Too little stale evidence reaches the context for a "
            f"propagation rule to show anything; the registration says abandoned, "
            f"not reinterpreted."
        )
        return out
    meets_stale = product["stale_citations_mean"] <= out["threshold"]
    keeps_support = (
        product["unnecessary_invalidation"] <= best_base_invalidation + 1e-9)
    if meets_stale and keeps_support:
        out["verdict"] = "SUPPORTED"
    elif not keeps_support:
        out["verdict"] = "FAILED — traded unnecessary invalidation for stale citations"
    else:
        closed = (base - product["stale_citations_mean"]) / headroom if headroom else 0.0
        out["verdict"] = "NOT SUPPORTED"
        out["why"] = (
            f"closed {closed:.0%} of the headroom against a registered "
            f"{STALE_SHARE:.0%}")
    return out


def to_markdown(result: Mapping[str, Any], v: Mapping[str, Any]) -> str:
    lines = [
        f"# P3 — correction propagation · {result['split']} split",
        "",
        f"- **Benchmark:** {result['benchmark']}, {result['cases']} cases, k={result['k']}",
        "- **One retrieval per case**, five rules over the same ranking.",
        "",
        "| arm | stale cited / case | stale rate | unnecessary invalidation | "
        "sufficient | abstention precision | must-not-expose |",
        "|---|---|---|---|---|---|---|",
    ]
    fmt = lambda x: "—" if x is None else f"{x:.3f}"  # noqa: E731
    for name, row in result["arms"].items():
        lines.append(
            f"| `{name}` | {fmt(row['stale_citations_mean'])} | "
            f"{fmt(row['stale_citation_rate'])} | "
            f"{fmt(row['unnecessary_invalidation'])} | {fmt(row['sufficient'])} | "
            f"{fmt(row['abstention_precision'])} | "
            f"**{fmt(row['must_not_expose_rate'])}** |"
        )
    any_row = next(iter(result["arms"].values()))
    lines += [
        "",
        f"Counts: {any_row['n_stale_cases']} cases carry a stale set, "
        f"{any_row['n_independent_cases']} carry a standing independent source. "
        f"Every rate above is over those counts, not over all {result['cases']}.",
        "",
        "## Verdict, applied as registered",
        "",
        "```",
        f"best baseline        B = {v['best_baseline_stale']:.3f}",
        f"ceiling              C = {v['ceiling_stale']:.3f}   (oracle, 0 by construction)",
        f"headroom                 {v['headroom']:+.3f}",
        f"threshold            B - {STALE_SHARE:.2f} x headroom = {v['threshold']:.3f}",
        f"source_root_grouping     {v['product_stale']:.3f}",
        "",
        f"unnecessary invalidation: product {v['product_unnecessary_invalidation']:.3f} "
        f"vs best baseline {v['baseline_unnecessary_invalidation']:.3f}",
        f"VERDICT: {v['verdict']}",
        "```",
    ]
    if v.get("why"):
        lines += ["", v["why"]]

    families = sorted(next(iter(result["by_family"].values())))
    lines += [
        "",
        "## Stale citations by family",
        "",
        "| arm | " + " | ".join(f"`{f}`" for f in families) + " |",
        "|---|" + "---|" * len(families),
    ]
    for name, rows in result["by_family"].items():
        cells = [fmt(rows[f]["stale_cited"]) for f in families]
        lines.append(f"| `{name}` | " + " | ".join(cells) + " |")
    lines += [
        "",
        "## Unnecessary invalidation by family",
        "",
        "| arm | " + " | ".join(f"`{f}`" for f in families) + " |",
        "|---|" + "---|" * len(families),
    ]
    for name, rows in result["by_family"].items():
        cells = [fmt(rows[f]["unnecessary_invalidation"]) for f in families]
        lines.append(f"| `{name}` | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--split", default="dev", choices=["dev", "test"])
    parser.add_argument("--benchmark", default=BENCHMARK,
                        choices=sorted(PROVENANCE_FAMILIES))
    parser.add_argument("--k", type=int, default=DEFAULT_K)
    parser.add_argument(
        "--all-families", action="store_true",
        help="score every family, not only those carrying provenance structure",
    )
    parser.add_argument("--out")
    parser.add_argument("--json", dest="as_json", action="store_true")
    args = parser.parse_args(argv)

    result = run(
        args.split, k=args.k, benchmark=args.benchmark,
        families=None if args.all_families else PROVENANCE_FAMILIES[args.benchmark],
    )
    v = verdict(result)
    if args.as_json:
        print(json.dumps({"result": result, "verdict": v}, indent=2))
    else:
        print(to_markdown(result, v))

    violations = {
        n: r["must_not_expose_rate"] for n, r in result["arms"].items()
        if (r["must_not_expose_rate"] or 0) > 0
    }
    if violations:
        print("\n  GATE VIOLATIONS (a failure regardless of every other metric):")
        for name, rate in violations.items():
            print(f"    {name}: {rate:.3f}")

    if args.out:
        pathlib.Path(args.out).write_text(
            to_markdown(result, v) + "\n", encoding="utf-8")
        print(f"\n  wrote {args.out}")
    return 0 if not violations else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
