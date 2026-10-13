"""Which models actually produce the `QUALIFIES` edge the primary needs?

The quality harness scores a statement's **class**. The primary needs something
stricter: `infer_relations` must match the modifier's extracted `modifies`
against another memory's extracted `predicate`, so **both sides come from the
model** and a target that reads well to a human may still never meet anything.

Judging that by eye was wrong twice in one session. `'axle-set figure'` looks
like the right answer and is **not** contained in
`'tyre pressure for the axle set'` either way round; `'tyre pressure'` looks
vaguer and **is**. And the fixture's hand-written predicate is not what the
pipeline sees -- the predicate is whatever the model extracts from the other
memory. So this runs the real inference over the real pair and reports whether
the edge appears.

Two statements per model, which is cheap enough to run for every candidate:

* `h4`, the modifier -- *"At the depot-12 site, add 0.35 bar to the axle-set figure as a salt-corrosion margin."*
* `h3`, what it modifies -- *"Vehicles with the standard axle set run 4.0 bar in summer."*

A model passes only if `infer_relations` returns the `h4 QUALIFIES h3` edge
from its own two records. `research/results/relations-ceiling.md` measured that
this edge takes `multi_hop_4` from 0.000 to 1.000, so a model that cannot
produce it cannot move the primary at all, whatever it scores on class.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time
from typing import Any, Mapping, Sequence

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from experiments import relevance_bench as rb  # noqa: E402
from memory_fabric import extraction as extracting  # noqa: E402
from memory_fabric.relations import RelationKind  # noqa: E402


def pair(split: str = "dev") -> tuple[str, str]:
    """(h4, h3) from the first `multi_hop_4` case, by id rather than by text."""
    for case in rb.load(split, "relevance_v2"):
        if case["family"] != "multi_hop_4":
            continue
        by_id = {m["id"]: m["content"] for m in case["corpus"]}
        return by_id["h4"], by_id["h3"]
    raise SystemExit("no multi_hop_4 case found")


def check(model: str, modifier: str, stated: str, constrained: bool = True,
          think: bool | None = False) -> dict[str, Any]:
    from memory_fabric.adapters.ollama import OllamaClient

    extractor = extracting.ModelExtractor(
        client=OllamaClient(), model=model, constrained=constrained,
        think=think)
    # Warm, so the first statement does not carry a 20-35s cold load.
    try:
        extractor.extract("warm", "Bay 1 is assigned to unit-1.")
        extractor._cache.clear()
    except Exception as exc:  # pragma: no cover - environment
        return {"model": model, "error": f"{type(exc).__name__}: {exc}"[:90]}

    started = time.perf_counter()
    try:
        h4 = extractor.extract("h4", modifier)
        h3 = extractor.extract("h3", stated)
    except Exception as exc:  # pragma: no cover - environment
        return {"model": model, "error": f"{type(exc).__name__}: {exc}"[:90]}
    elapsed = time.perf_counter() - started

    edges = extracting.infer_relations([h3, h4])
    wanted = ("h4", RelationKind.QUALIFIES, "h3")
    return {
        "model": model,
        "constrained": constrained,
        "edge": wanted in edges,
        "edges": [[s, k.value if hasattr(k, "value") else str(k), o]
                  for s, k, o in edges],
        "h4_target": h4.modify_target,
        "h4_is_modifier": h4.is_modifier,
        "h4_parsed": h4.parsed,
        "h3_predicate": h3.predicate,
        "h3_asserts": h3.asserts,
        "h3_parsed": h3.parsed,
        "seconds": round(elapsed, 1),
    }


def run(models: Sequence[str], split: str = "dev",
        constrained: bool = True) -> dict[str, Any]:
    modifier, stated = pair(split)
    rows = []
    for model in models:
        row = check(model, modifier, stated, constrained)
        rows.append(row)
        print(f"  {model}: edge={row.get('edge')} "
              f"target={row.get('h4_target')!r} "
              f"predicate={row.get('h3_predicate')!r} "
              f"{row.get('seconds', 0)}s", file=sys.stderr)
    return {
        "experiment": "x1-edge-check",
        "split": split,
        "constrained": constrained,
        "modifier": modifier,
        "stated": stated,
        "rows": rows,
    }


def to_markdown(result: Mapping[str, Any]) -> str:
    lines = [
        "# X1 — which models produce the edge the primary needs?",
        "",
        f"- `{result['split']}` split, "
        f"{'schema-constrained' if result['constrained'] else 'free-form'}, "
        f"no reasoning trace, models warmed",
        "- Both sides of the match are model-extracted; see the module docstring",
        "",
        "| model | edge formed | `modifies` (from h4) | `predicate` (from h3) | seconds |",
        "|---|---|---|---|---|",
    ]
    for row in result["rows"]:
        if row.get("error"):
            lines.append(f"| `{row['model']}` | — | error: {row['error']} | | |")
            continue
        lines.append(
            f"| `{row['model']}` | {'**YES**' if row['edge'] else 'no'} | "
            f"`{row['h4_target']!r}` | `{row['h3_predicate']!r}` | "
            f"{row['seconds']} s |")
    lines += [
        "",
        "A model that cannot produce this edge cannot move `multi_hop_4` at "
        "all, whatever it scores on classification: "
        "`research/results/relations-ceiling.md` measured that this one edge "
        "takes the family from 0.000 to 1.000.",
    ]
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--models", nargs="*", default=[
        "qwen2.5:1.5b", "qwen2.5:3b", "qwen3:1.7b", "gemma3:4b",
        "llama3.2:3b", "qwen2.5:7b", "gemma2:latest"])
    parser.add_argument("--split", default="dev", choices=["dev", "test"])
    parser.add_argument("--unconstrained", action="store_true")
    parser.add_argument("--out")
    parser.add_argument("--json", dest="as_json", action="store_true")
    args = parser.parse_args(argv)
    result = run(args.models, args.split, not args.unconstrained)
    print(json.dumps(result, indent=2) if args.as_json
          else to_markdown(result))
    if args.out:
        pathlib.Path(args.out).write_text(
            json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
