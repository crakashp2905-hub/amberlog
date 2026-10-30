"""What would declared relations be worth, given perfect declarations?

A **ceiling**, not a method, and labelled as one everywhere. Nothing discovers
typed relations yet; the question is whether discovering them would pay, and
principle 8a says measure the ceiling before registering a threshold.

The declarations come from the fixture, which is why this is a ceiling: a
pattern extractor fitted to text this project's own generators wrote would pass
by construction and measure its own phrasing. So the honest first measurement
is "if a perfect extractor existed, this much".

## What is covered, and what is not

`multi_hop_4` is covered. Its missing memory is *"at the depot-12 site, add
0.35 bar to the axle-set figure"* — it **qualifies** the axle-set rule, and
`QUALIFIES` is exactly a memory-to-memory relation.

**`implied_by_default` is not**, and that is worth stating rather than quietly
omitting. Its answer is *"all yard vehicles run 3.9 bar in winter, except at
the harbour and quarry sites"*, and the exception names **sites**, not
memories. `EXCEPTS` as defined relates two memories, and there are no memories
for the excepted sites to relate it to. Deciding that a default applies to a
query needs entity-scoped applicability — a rule's scope checked against the
query's entities — which is a different mechanism and is not built.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
from typing import Any, Mapping, Sequence

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from experiments import relevance_bench as rb  # noqa: E402
from memory_fabric.relations import RelationKind  # noqa: E402

# Which memory qualifies which, per family. Read from the fixture, which is
# what makes this a ceiling.
DECLARED: dict[str, list[tuple[str, str]]] = {
    # the site margin qualifies the axle-set rule
    "multi_hop_4": [("h4", "h3")],
}
FAMILIES = tuple(DECLARED)


def run_case(case: Mapping[str, Any], k: int, declare: bool,
             use_chain: bool) -> rb.CaseResult:
    fabric, ids = rb._build_fabric(case, "lexical")
    local = {bench: store for store, bench in ids.items()}
    try:
        if declare:
            for subject, obj in DECLARED.get(case["family"], ()):
                if subject in local and obj in local:
                    fabric.relate(local[subject], RelationKind.QUALIFIES,
                                  local[obj], actor="fixture")
        if use_chain:
            chain = fabric.reconstruct(
                agent_id=case["task"]["agent_id"], query=rb.query_text(case),
                k=k, tenant_id=case["task"].get("tenant_id", "tn_default"),
                as_of=rb._as_of(case), follow_relations=declare)
            returned = [ids[s.memory_id] for s in chain.steps]
        else:
            result = fabric.retrieve(
                agent_id=case["task"]["agent_id"], query=rb.query_text(case),
                k=k, tenant_id=case["task"].get("tenant_id", "tn_default"),
                min_relevance=0.0, as_of=rb._as_of(case),
                follow_relations=declare)
            returned = [ids[m.id] for m in result.exposed]
    finally:
        fabric.close()
    allowed, refused = rb.apply_gates(case, returned)
    return rb.score_case(case, allowed, refused, k)


def run(split: str, k: int = 5) -> dict[str, Any]:
    cases = [c for c in rb.load(split, "relevance_v2") if c["family"] in FAMILIES]
    arms = {
        "retrieve": (False, False),
        "retrieve + declared relations": (True, False),
        "chain": (False, True),
        "chain + declared relations": (True, True),
    }
    out: dict[str, Any] = {"split": split, "k": k, "cases": len(cases),
                           "families": list(FAMILIES), "arms": {}}
    for name, (declare, use_chain) in arms.items():
        results = [run_case(c, k, declare, use_chain) for c in cases]
        mean = lambda attr: round(  # noqa: E731
            sum(getattr(r, attr) for r in results) / len(results), 4)
        out["arms"][name] = {
            "ndcg": mean("ndcg"),
            "critical_recall": mean("critical_recall"),
            "sufficient": round(
                sum(1 for r in results if r.sufficient) / len(results), 4),
            "returned": round(
                sum(len(r.returned) for r in results) / len(results), 2),
        }
    return out


def to_markdown(result: Mapping[str, Any]) -> str:
    lines = [
        f"# Declared relations — a ceiling · {result['split']} split",
        "",
        f"- **Families:** {', '.join(result['families'])} · "
        f"{result['cases']} cases · k={result['k']}",
        "- **The declarations come from the fixture.** This is what a perfect "
        "extractor would be worth, not what any mechanism achieves.",
        "",
        "| arm | nDCG@5 | critical recall | sufficient | returned |",
        "|---|---|---|---|---|",
    ]
    for name, row in result["arms"].items():
        lines.append(
            f"| {name} | {row['ndcg']:.3f} | {row['critical_recall']:.3f} | "
            f"{row['sufficient']:.3f} | {row['returned']:.2f} |")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--split", default="dev", choices=["dev", "test"])
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument("--json", dest="as_json", action="store_true")
    args = parser.parse_args(argv)
    result = run(args.split, args.k)
    print(json.dumps(result, indent=2) if args.as_json else to_markdown(result))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
