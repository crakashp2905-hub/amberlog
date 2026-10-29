"""P2 — context sufficiency: does the assembled set support a decision?

Registered in `research/prereg/p2-context-sufficiency.md`, which fixed the
arms, the primary metric and the threshold before this selector existed.

## The selector, and why each part of it is here rather than guessed

`sufficiency_aware` is three mechanisms, and none of them reads the labels.

**1. Withhold anything with a retracted ancestor.** Not a design choice —
[P3](../research/results/p3-correction-propagation.md) measured this rule as
exactly optimal on three families of four, against the product's source-root
grouping closing −150% of the headroom. It is here because it won a
pre-registered comparison, which is the only reason a mechanism should be in a
second experiment.

**2. Bridged conjunctive coverage.** Top-k ranks each candidate against the
query independently, which is why a 4-hop chain scores 0.519 on relevance_v2:
hop 2 names a vehicle the query never mentions, so nothing ranks it. This
assembles instead — take the best candidate, then repeatedly add whichever
candidate covers the most *uncovered* query terms, subject to sharing a token
with what is already selected. Coverage of the query's content terms is the
objective rather than per-candidate score.

**3. Abstain when coverage cannot be completed.** The gap relevance_v2 found is
that **no arm abstains even once** on the cases where abstention is the only
correct answer. Here abstention is the stopping condition rather than a special
case: if the content terms of the query are still not covered when no admissible
candidate remains, the corpus does not answer the question.

**This mechanism does not work, and the result says so rather than this module
being quietly adjusted until it did.** Demanding coverage of every content term
abstains on 79% of the answerable cases; demanding coverage of only the terms
the corpus contains abstains on none. Token presence is not evidence about a
conjunction — on an `unanswerable` case every term of the absent tuple appears
somewhere, in sentences about something else — and no setting between those two
is a signal about the asked question. See
`research/results/p2-context-sufficiency.md` section 5.

## The restatement test, which does two jobs

A bridge is admissible only if the new memory is **not a restatement** of one
already selected — Jaccard overlap of their tokens below `RESTATEMENT`. Without
it, `unanswerable` is answered wrongly: the asked facet tuple is absent, but its
neighbours jointly cover every query term, so a bridge from "crane-5, coastal,
summer" to "crane-5, inland, winter" completes coverage out of two memories that
contradict each other.

The same test, inverted, surfaces conflicts. After coverage is complete, any
candidate achieving the **same** coverage as a selected memory while asserting
something different is added — which is what `conflicting` requires, where the
defensible answer needs both sides and a context holding one looks complete.

`RESTATEMENT = 0.6` is not tuned on the metric, and the gap it sits in is not
as clean as the first version of this docstring claimed. Measured on dev:
near-identical pairs mean **0.797**, everything else means **0.396** — but the
second group reaches **0.727**, above the threshold, so some legitimate bridges
are blocked by a rule written for near-misses. The means are far apart and the
distributions overlap. Every run prints the distribution so that is visible
rather than taken on trust.

(It is not what makes the selector fail. See the result: the bridge is rejected
on marginal coverage gain before the restatement test is ever consulted.)
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

BENCHMARK = "relevance_v2"
DEFAULT_K = 5
RESTATEMENT = 0.6
MAX_SELECTED = 6          # the 4-hop chain plus a conflicting pair
SUFFICIENCY_SHARE = 0.40
ABANDON_IF_HEADROOM_BELOW = 0.05


# --- tokens -----------------------------------------------------------------


def terms(text: str) -> set[str]:
    return set(rb.tokens(text))


def content_terms(case: Mapping[str, Any]) -> set[str]:
    """The query's content terms, which are what must be covered.

    Entities declared on the task are included even when the task text phrases
    them differently, because a facet the caller named is part of the question
    whether or not the sentence repeats it.
    """
    out = terms(case["task"]["task_text"])
    for entity in case["task"].get("entities") or ():
        out |= terms(entity)
    return out


def jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


# --- the arms ---------------------------------------------------------------


@dataclass
class Assembly:
    """What an arm returned, and what it cost."""

    selected: list[str]
    abstained: bool
    prompt_tokens: int
    coverage: float


def _tokens_of(case: Mapping[str, Any], ids: Sequence[str]) -> int:
    by_id = {m["id"]: m for m in case["corpus"]}
    body = " ".join(by_id[i]["content"] for i in ids)
    return len(body.split()) if body else 0


def arm_top_k(case, ranked, ctx, k: int) -> Assembly:
    chosen = list(ranked[:k])
    return Assembly(chosen, not chosen, _tokens_of(case, chosen),
                    _coverage(case, chosen, ctx))


def arm_full_context(case, ranked, ctx, k: int) -> Assembly:
    """Every reachable memory. The thing retrieval must justify itself against.

    R6 could use this as a free baseline because its corpora were 19 memories
    and 294 tokens. Here it is ~495 memories and ~6,600 tokens, and ~25,000 on
    `budget_pressure`, so it is a cost rather than a control.
    """
    chosen = list(ranked)
    return Assembly(chosen, not chosen, _tokens_of(case, chosen),
                    _coverage(case, chosen, ctx))


def reachable_terms(case, ctx: "Context", pool: Sequence[str]) -> set[str]:
    """Query terms that some candidate actually contains.

    Coverage over *all* content terms is unachievable by construction, which is
    the second reason the first run was invalid: "How often is the X cable
    swapped at Y?" asks for "often" and "swapped", and the corpus says "swap
    ... every 90 days". Neither token appears anywhere, so coverage could never
    reach 1.0 and the selector abstained on 79% of the answerable cases.

    Filtering to terms with a document frequency of at least one is label-free
    and removes interrogatives and morphological variants together, without a
    stop-list to maintain or a stemmer to tune.
    """
    need = content_terms(case) - rb._STOP
    present: set[str] = set()
    for i in pool:
        present |= ctx.terms[i]
    return need & present


def _coverage(case, ids: Sequence[str], ctx: "Context",
              need: set[str] | None = None) -> float:
    if need is None:
        need = content_terms(case) - rb._STOP
    if not need:
        return 1.0
    have: set[str] = set()
    for i in ids:
        have |= ctx.terms[i]
    return len(need & have) / len(need)


def arm_sufficiency_aware(case, ranked, ctx, k: int) -> Assembly:
    # Mechanism 1: P3's measured winner.
    pool = [m for m in ranked if not ctx.has_retracted_ancestor(m)]
    if not pool:
        return Assembly([], True, 0, 0.0)
    need = reachable_terms(case, ctx, pool)
    if not need:
        return Assembly([], True, 0, 0.0)

    # Mechanism 2: bridged conjunctive coverage.
    #
    # **Measured not to work on multi-hop, which is what it was built for.**
    # The objective is marginal coverage of uncovered *query* terms, and a
    # chain's middle hop covers none of them: in a `multi_hop_3` case the query
    # names a bay, a site and a season, while hop 2 says "tug-3 was re-fitted
    # with the heavy axle set" and contains no query term at all. Its whole
    # value is connecting hop 1 to hop 3, so its gain is zero and the loop below
    # can never select it. `multi_hop_3` and `multi_hop_4` score 0.000 here,
    # identical to budget-matched top-k.
    #
    # Valuing a connector needs assembly treated as path-finding over an entity
    # graph, where a node with no query overlap is worth adding when it joins
    # two that have it. A different algorithm, not a parameter.
    selected: list[str] = [pool[0]]
    covered = set(ctx.terms[pool[0]]) & need
    while len(selected) < MAX_SELECTED and covered != need:
        best, best_gain = None, 0
        for candidate in pool:
            if candidate in selected:
                continue
            gain = len((ctx.terms[candidate] & need) - covered)
            if gain <= best_gain:
                continue
            connected = any(ctx.terms[candidate] & ctx.terms[s] for s in selected)
            if not connected:
                continue
            # The restatement test: a near-miss of something already selected
            # completes coverage while contradicting it.
            if any(jaccard(ctx.terms[candidate], ctx.terms[s]) >= RESTATEMENT
                   for s in selected):
                continue
            best, best_gain = candidate, gain
        if best is None:
            break
        selected.append(best)
        covered |= ctx.terms[best] & need

    coverage = len(covered) / len(need)

    # Mechanism 3: abstain when the conjunction was never reached.
    if coverage < 1.0:
        return Assembly([], True, 0, coverage)

    # The restatement test inverted: a candidate matching the selected answer's
    # coverage while saying something else is a conflict, not a distractor.
    answer = selected[0]
    answer_cover = ctx.terms[answer] & need
    for candidate in pool:
        if candidate in selected or len(selected) >= MAX_SELECTED:
            continue
        if (ctx.terms[candidate] & need) == answer_cover and \
                ctx.terms[candidate] != ctx.terms[answer]:
            selected.append(candidate)
    return Assembly(selected, False, _tokens_of(case, selected), coverage)


def arm_oracle_evidence(case, ranked, ctx, k: int) -> Assembly:
    """The labelled satisfiers, through the same gates at the same k.

    Capped at 0.800 sufficiency on dev and that is correct: `gated` and
    `shared_root` are built so the only satisfier of their critical requirement
    is a memory the gates refuse. An arm above the oracle has exposed something
    it may not.
    """
    wanted: list[str] = []
    for req in case["labels"]["requirements"]:
        for satisfier in req["satisfied_by"]:
            if satisfier not in wanted:
                wanted.append(satisfier)
    chosen = [m for m in ranked if m in wanted][:max(k, MAX_SELECTED)]
    return Assembly(chosen, not chosen, _tokens_of(case, chosen),
                    _coverage(case, chosen, ctx))


ARMS = {
    "top_k": arm_top_k,
    "full_context": arm_full_context,
    "sufficiency_aware": arm_sufficiency_aware,
    "oracle_evidence": arm_oracle_evidence,
}
BASELINES = ("top_k", "full_context", "budget_matched_top_k")
CEILING = "oracle_evidence"


# --- per-case context -------------------------------------------------------


@dataclass
class Context:
    case: Mapping[str, Any]
    fabric: Any
    store_id: dict[str, str]
    bench_id: dict[str, str]
    retracted: set[str]
    terms: dict[str, set[str]]

    def has_retracted_ancestor(self, bench: str) -> bool:
        if not self.retracted:
            return False
        graph = self.fabric.lineage_graph
        return any(
            self.bench_id.get(node.memory_id) in self.retracted
            for node in graph.ancestors(self.store_id[bench])
        )


def build_context(case: Mapping[str, Any]) -> Context:
    from amberlog import Amberlog

    fabric = Amberlog(":memory:", auto_activate=True, encrypt_content=False,
                          retrieval="lexical")
    store_id, bench_id, retracted = {}, {}, set()
    for memory in rb.insertion_order(case["corpus"]):
        parents = [(store_id[p[0]], 1) for p in (memory.get("parents") or ())]
        stored = fabric.remember(
            agent_id=case["task"]["agent_id"], content=memory["content"],
            tenant_id=memory.get("tenant_id", "tn_default"), parents=parents,
            method="consolidated" if parents else "observed",
            valid_from=memory.get("valid_from"), valid_to=memory.get("valid_to"), scope="team",
        )
        store_id[memory["id"]] = stored
        bench_id[stored] = memory["id"]
        if memory["lifecycle_state"] in rb.BLOCKED_LIFECYCLE:
            retracted.add(memory["id"])
    # After every write: see p3_propagation.build_context.
    for bench in retracted:
        fabric.quarantine(store_id[bench], reason="benchmark fixture",
                          actor="bench", basis="contradicted")
    return Context(
        case=case, fabric=fabric, store_id=store_id, bench_id=bench_id,
        retracted=retracted,
        terms={m["id"]: terms(m["content"]) for m in case["corpus"]},
    )


def base_ranking(ctx: Context) -> list[str]:
    """An ordering of the whole corpus, not only the part the index scored.

    The first run of this experiment scored `oracle_evidence` at **0.000 on
    both multi-hop families**, which is impossible for an arm handed the
    answers -- and under principle 8b an impossible oracle means the ceiling is
    wrong, not that the families are hard.

    The cause: `retrieve` returns what the lexical index scored, and hop 2 of a
    chain ("tug-3 was re-fitted with the heavy axle set") shares no term with
    the query, so it was never a candidate for *any* arm. A chain whose middle
    link cannot be retrieved is not a retrieval problem, it is an absent
    candidate -- and bridging to exactly that link is the mechanism under test.

    So retrieval supplies the order and the corpus supplies the pool. Memories
    the index did not score keep their corpus order behind those it did, which
    is the honest representation of "no evidence either way about this one".
    """
    result = ctx.fabric.retrieve(
        agent_id=ctx.case["task"]["agent_id"], query=rb.query_text(ctx.case),
        k=len(ctx.case["corpus"]),
        tenant_id=ctx.case["task"].get("tenant_id", "tn_default"),
        min_relevance=0.0, group_by_source_root=True, expand_lineage=1,
    )
    scored = [ctx.bench_id[m.id] for m in result.exposed]
    seen = set(scored)
    # The tail is what the **store** considers exposable and the index merely
    # did not score. Filtering it by the benchmark's own `lifecycle_state`
    # instead re-admitted memories the store had excluded: quarantining a
    # memory contests its descendants, so they are CONTESTED in the store while
    # the fixture still calls them active, and the first version of this
    # function put them back. `full_context` then reported 3.500 stale
    # citations a case that the product does not make.
    exposable = ctx.fabric._eligible_ids(
        include_contested=False,
        tenant_id=ctx.case["task"].get("tenant_id", "tn_default"),
    )
    tail = [
        m["id"] for m in ctx.case["corpus"]
        if m["id"] not in seen and ctx.store_id[m["id"]] in exposable
    ]
    return scored + tail


# --- scoring ----------------------------------------------------------------


@dataclass
class Outcome:
    case_id: str
    family: str
    sufficient: bool | None
    requirements_met: int
    requirements_total: int
    abstained: bool
    expect_abstain: bool
    exposed_forbidden: tuple[str, ...]
    prompt_tokens: int
    latency_ms: float
    stale_cited: int
    stale_declared: int


def score(case, assembly: Assembly, latency_ms: float) -> Outcome:
    labels = case["labels"]
    forbidden = set(labels["must_not_expose"])
    stale = set(labels.get("stale") or ())
    visible = set(assembly.selected) - forbidden
    critical = [r for r in labels["requirements"] if r.get("critical")]
    met = [r for r in labels["requirements"] if set(r["satisfied_by"]) & visible]
    met_critical = [r for r in critical if set(r["satisfied_by"]) & visible]
    return Outcome(
        case_id=case["case_id"], family=case["family"],
        sufficient=(len(met_critical) == len(critical)) if critical else None,
        requirements_met=len(met), requirements_total=len(labels["requirements"]),
        abstained=assembly.abstained, expect_abstain=bool(labels["expect_abstain"]),
        exposed_forbidden=tuple(m for m in assembly.selected if m in forbidden),
        prompt_tokens=assembly.prompt_tokens, latency_ms=latency_ms,
        stale_cited=len([m for m in assembly.selected if m in stale]),
        stale_declared=len(stale),
    )


@dataclass
class ArmReport:
    arm: str
    outcomes: list[Outcome] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        mean = lambda xs: round(sum(xs) / len(xs), 4) if xs else None  # noqa: E731
        suff = [o for o in self.outcomes if o.sufficient is not None]
        answerable = [o for o in self.outcomes if not o.expect_abstain]
        unanswerable = [o for o in self.outcomes if o.expect_abstain]
        staleful = [o for o in self.outcomes if o.stale_declared]
        return {
            "arm": self.arm,
            "cases": len(self.outcomes),
            "sufficient": mean([float(bool(o.sufficient)) for o in suff]),
            "requirement_recall": mean([
                o.requirements_met / o.requirements_total
                for o in self.outcomes if o.requirements_total]),
            "abstention_precision": mean(
                [float(o.abstained) for o in unanswerable]),
            "false_abstention": mean([float(o.abstained) for o in answerable]),
            "stale_citations_mean": mean([float(o.stale_cited) for o in staleful]),
            "must_not_expose_rate": mean(
                [float(bool(o.exposed_forbidden)) for o in self.outcomes]),
            "prompt_tokens": round(
                sum(o.prompt_tokens for o in self.outcomes) / len(self.outcomes), 1)
            if self.outcomes else 0.0,
        }

    def timing(self) -> dict[str, float]:
        if not self.outcomes:
            return {"latency_ms": 0.0}
        return {"latency_ms": round(
            sum(o.latency_ms for o in self.outcomes) / len(self.outcomes), 3)}

    def by_family(self) -> dict[str, dict[str, Any]]:
        fams: dict[str, list[Outcome]] = {}
        for o in self.outcomes:
            fams.setdefault(o.family, []).append(o)
        mean = lambda xs: round(sum(xs) / len(xs), 4) if xs else None  # noqa: E731
        return {
            f: {
                "cases": len(rows),
                "sufficient": mean([float(bool(r.sufficient)) for r in rows
                                    if r.sufficient is not None]),
                "abstained": len([r for r in rows if r.abstained]),
                "expect_abstain": len([r for r in rows if r.expect_abstain]),
            }
            for f, rows in sorted(fams.items())
        }


def run(split: str, k: int = DEFAULT_K, benchmark: str = BENCHMARK) -> dict[str, Any]:
    cases = rb.load(split, benchmark)
    reports = {name: ArmReport(arm=name) for name in ARMS}
    reports["budget_matched_top_k"] = ArmReport(arm="budget_matched_top_k")
    overlaps: dict[str, list[float]] = {"restatement": [], "bridge": []}

    for case in cases:
        ctx = build_context(case)
        try:
            ranked = base_ranking(ctx)
            allowed, _ = rb.apply_gates(case, ranked)
            assemblies: dict[str, Assembly] = {}
            for name, arm in ARMS.items():
                started = time.perf_counter()
                assembly = arm(case, list(allowed), ctx, k)
                elapsed = (time.perf_counter() - started) * 1000.0
                assemblies[name] = assembly
                reports[name].outcomes.append(score(case, assembly, elapsed))

            # Equal-budget control: top-k spending what the selector spent, so
            # the selector cannot win by being allowed more context.
            target = assemblies["sufficiency_aware"].prompt_tokens
            matched: list[str] = []
            spent = 0
            for memory in allowed:
                cost = _tokens_of(case, [memory])
                if matched and spent + cost > target:
                    break
                matched.append(memory)
                spent += cost
            reports["budget_matched_top_k"].outcomes.append(score(
                case, Assembly(matched, not matched, spent,
                               _coverage(case, matched, ctx)), 0.0))

            # The overlap distribution behind RESTATEMENT, collected rather
            # than asserted.
            top = allowed[:12]
            for i, a in enumerate(top):
                for b in top[i + 1:]:
                    bucket = ("restatement"
                              if ctx.terms[a] and ctx.terms[b] and
                              len(ctx.terms[a] ^ ctx.terms[b]) <= 2
                              else "bridge")
                    overlaps[bucket].append(jaccard(ctx.terms[a], ctx.terms[b]))
        finally:
            ctx.fabric.close()

    return {
        "experiment": "p2-context-sufficiency",
        "benchmark": benchmark, "split": split, "k": k, "cases": len(cases),
        "arms": {n: r.summary() for n, r in reports.items()},
        "timing": {n: r.timing() for n, r in reports.items()},
        "by_family": {n: r.by_family() for n, r in reports.items()},
        "overlaps": {
            name: {
                "n": len(values),
                "mean": round(sum(values) / len(values), 4) if values else None,
                "max": round(max(values), 4) if values else None,
            }
            for name, values in overlaps.items()
        },
    }


def verdict(result: Mapping[str, Any]) -> dict[str, Any]:
    arms = result["arms"]
    base = max(arms[a]["sufficient"] for a in BASELINES)
    ceiling = arms[CEILING]["sufficient"]
    headroom = ceiling - base
    product = arms["sufficiency_aware"]["sufficient"]
    out = {
        "best_baseline": base, "ceiling": ceiling, "headroom": round(headroom, 4),
        "threshold": round(base + SUFFICIENCY_SHARE * headroom, 4),
        "sufficiency_aware": product,
    }
    if headroom <= ABANDON_IF_HEADROOM_BELOW:
        out["verdict"] = "ABANDONED"
        out["why"] = (
            f"headroom {headroom:+.3f} <= {ABANDON_IF_HEADROOM_BELOW}. No "
            f"quantity to divide, so the registration says abandoned rather "
            f"than reinterpreted.")
        return out
    if product > ceiling + 1e-9:
        out["verdict"] = "CEILING BREACHED — the ceiling is wrong, not the arm"
        return out
    closed = (product - base) / headroom if headroom else 0.0
    out["closed_share"] = round(closed, 4)
    out["verdict"] = (
        "SUPPORTED" if product >= out["threshold"] else
        ("NOT SUPPORTED" if product > base else "KILLED — below every baseline"))
    return out


def to_markdown(result: Mapping[str, Any], v: Mapping[str, Any]) -> str:
    fmt = lambda x: "—" if x is None else f"{x:.3f}"  # noqa: E731
    order = ["top_k", "budget_matched_top_k", "full_context",
             "sufficiency_aware", "oracle_evidence"]
    lines = [
        f"# P2 — context sufficiency · {result['split']} split",
        "",
        f"- **Benchmark:** {result['benchmark']}, {result['cases']} cases, k={result['k']}",
        "",
        "| arm | sufficient | requirement recall | abstention precision | "
        "false abstention | stale cited | prompt tokens | must-not-expose |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for name in order:
        row = result["arms"][name]
        lines.append(
            f"| `{name}` | {fmt(row['sufficient'])} | "
            f"{fmt(row['requirement_recall'])} | "
            f"{fmt(row['abstention_precision'])} | "
            f"{fmt(row['false_abstention'])} | "
            f"{fmt(row['stale_citations_mean'])} | "
            f"{row['prompt_tokens']:.0f} | **{fmt(row['must_not_expose_rate'])}** |"
        )
    lines += [
        "",
        "## Verdict, applied as registered",
        "",
        "```",
        f"best baseline        B = {v['best_baseline']:.3f}",
        f"ceiling              C = {v['ceiling']:.3f}",
        f"headroom                 {v['headroom']:+.3f}",
        f"threshold            B + {SUFFICIENCY_SHARE:.2f} x headroom = {v['threshold']:.3f}",
        f"sufficiency_aware        {v['sufficiency_aware']:.3f}",
        f"VERDICT: {v['verdict']}",
        "```",
    ]
    if v.get("why"):
        lines += ["", v["why"]]
    if "closed_share" in v:
        lines += ["", f"Closed **{v['closed_share']:.0%}** of the headroom against "
                      f"a registered {SUFFICIENCY_SHARE:.0%}."]

    families = sorted(next(iter(result["by_family"].values())))
    lines += ["", "## Sufficiency by family", "",
              "| arm | " + " | ".join(f"`{f}`" for f in families) + " |",
              "|---|" + "---|" * len(families)]
    for name in order:
        cells = [fmt(result["by_family"][name][f]["sufficient"]) for f in families]
        lines.append(f"| `{name}` | " + " | ".join(cells) + " |")

    lines += ["", "## Abstention by family (abstained / cases where it is correct)",
              "", "| arm | " + " | ".join(f"`{f}`" for f in families) + " |",
              "|---|" + "---|" * len(families)]
    for name in order:
        cells = []
        for f in families:
            row = result["by_family"][name][f]
            cells.append(f"{row['abstained']}/{row['expect_abstain']}")
        lines.append(f"| `{name}` | " + " | ".join(cells) + " |")

    ov = result["overlaps"]
    lines += [
        "", "## The restatement threshold, checked rather than asserted", "",
        f"`RESTATEMENT = {RESTATEMENT}`. Token-overlap Jaccard among the top 12 "
        f"candidates, split by whether the pair differs by at most two tokens:",
        "",
        "| pair kind | n | mean | max |",
        "|---|---|---|---|",
        f"| near-identical (restatements) | {ov['restatement']['n']} | "
        f"{fmt(ov['restatement']['mean'])} | {fmt(ov['restatement']['max'])} |",
        f"| everything else | {ov['bridge']['n']} | {fmt(ov['bridge']['mean'])} | "
        f"{fmt(ov['bridge']['max'])} |",
    ]
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--split", default="dev", choices=["dev", "test"])
    parser.add_argument("--k", type=int, default=DEFAULT_K)
    parser.add_argument("--out")
    parser.add_argument("--json", dest="as_json", action="store_true")
    args = parser.parse_args(argv)

    result = run(args.split, k=args.k)
    v = verdict(result)
    print(json.dumps({"result": result, "verdict": v}, indent=2)
          if args.as_json else to_markdown(result, v))

    violations = {n: r["must_not_expose_rate"] for n, r in result["arms"].items()
                  if (r["must_not_expose_rate"] or 0) > 0}
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
