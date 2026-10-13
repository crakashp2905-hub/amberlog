"""X1 — extraction at ingest, on the two families nothing else reaches.

Registered in `research/prereg/x1-extraction-at-ingest.md`.

`multi_hop_4` scores **0.000 sufficiency for every arm measured** at k=3, 5 and
10 on both splits: similarity cannot express what one memory *modifies*.
Declared relations take it to 1.000, so the question is whether a model can
supply the declarations.

The registration pooled a second family, `implied_by_default`, and **it is
abandoned** — its 0.000 was nDCG at k=3, and on the registered metric
(sufficiency at k=5) a plain lexical baseline reaches 1.000 on dev, so
`C - B = 0` and the registration's abandonment clause applies. `FAMILIES` still
loads it so the applicability path keeps a runnable arm, and `--family
multi_hop_4` selects the primary. See the registration's section 8.

## The arms, and which one is the ceiling

| arm | what it is |
|---|---|
`baseline` | the product as it ships, chain reconstruction included
`extraction` | **the mechanism**: one model call per memory, relations and defaults inferred structurally from the records
`declared` | fixture-supplied relations — the ceiling from `relations-ceiling.md`, and the thing `extraction` has to recover a share of
`oracle` | the labelled relevant set

Beating 0.000 while recovering a tenth of a known ceiling is a weak result
dressed as a strong one, which is why `declared` is reported beside
`extraction` rather than only the baselines.

## Cost, and the reduced store it forces

Extraction is cached **by content**, because a benchmark writes the same filler
into hundreds of corpora and without the cache the cost would be the
measurement. Even so, the five cases of these two families hold **1,374 unique
statements on dev**, and the models that extract correctly cost 19-133 seconds
each on this hardware — 7 to 50 hours for one split of one arm. The models run
on CPU here (`/api/ps` reports 0 MB VRAM), so neither batching nor concurrency
changes that: it is compute-bound, not round-trip-bound.

`--max-corpus N` therefore measures the registered primary on a **reduced
store**: every labelled memory is kept and the fillers are sampled down to N,
with a seeded RNG. Three things make it a fair comparison rather than a
convenience:

* **Every arm sees the same reduced corpus** — baseline, declared and the
  oracle are all recomputed on it, so B and C are measured where `extraction`
  is measured and the headroom is the headroom that actually exists there
  (principle 8b: same budget, same k, same mechanisms).
* **The sampling never consults the labels to decide what is interesting.** It
  keeps the labelled set because dropping a critical memory would make the case
  unanswerable for every arm including the oracle, and it drops fillers at
  random.
* **It is reported as what it is.** A 60-memory store is an easier store, and
  the honest effect is that the *baseline* may rank a memory it misses at full
  size — which raises B and shrinks the headroom rather than flattering the
  mechanism. Full-size numbers are not claimed from it.

Every call goes through `OllamaClient`, so model, prompt hash and token counts
are recorded, and the totals are reported as a first-class metric — prediction
4 is that the cost is what decides whether this belongs on the write path.

The cache is also written to disk when `--cache` is given, because a run of
this length that loses its extractions to a crash cannot be afforded twice.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import random
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from experiments import relevance_bench as rb  # noqa: E402
from memory_fabric import extraction as extracting  # noqa: E402
from memory_fabric.relations import RelationKind  # noqa: E402

FAMILIES = {
    "relevance_v2": ("multi_hop_4",),
    "facet_v1": ("implied_by_default",),
}
# The fixture-declared relations, for the `declared` ceiling only.
DECLARED = {"multi_hop_4": [("h4", "h3")]}
ARMS = ("baseline", "extraction", "declared", "oracle")


@dataclass
class Outcome:
    case_id: str
    family: str
    arm: str
    result: rb.CaseResult
    inferred: tuple[tuple[str, str], ...] = ()
    defaults_found: int = 0
    latency_ms: float = 0.0


@dataclass
class Cost:
    calls: int = 0
    tokens: int = 0
    wall_s: float = 0.0
    unique_statements: int = 0
    reused_from_cache: int = 0


def build_extractor(model: str, cache: str | None = None,
                    trace: str | None = None,
                    constrained: bool = False) -> tuple[Any, Cost]:
    from memory_fabric.adapters.ollama import OllamaClient

    client = OllamaClient()
    if trace:
        from memory_fabric.adapters.tracing import JsonlSink

        client.add_sink(JsonlSink(trace))
    extractor = extracting.ModelExtractor(
        client=client, model=model, constrained=constrained)
    if cache:
        load_cache(extractor, pathlib.Path(cache))
    return extractor, Cost()


def load_cache(extractor: Any, path: pathlib.Path) -> int:
    """Re-use extractions from an earlier run of the same model and mode.

    Keyed on model, **decoding mode** and content. A cache shared between
    models would make the result a property of whichever ran first, and the
    mode belongs in the key for the same reason: schema-constrained and
    free-form decoding produce different records from the same statement, as
    the two measurements in `research/results/x1-extraction.md` sections 2 and
    8 show directly. A mixed cache is a mixed arm.
    """
    if not path.exists():
        return 0
    stored = json.loads(path.read_text(encoding="utf-8"))
    if stored.get("model") != extractor.model:
        return 0
    if bool(stored.get("constrained")) != bool(
            getattr(extractor, "constrained", True)):
        return 0
    for content, fields in stored.get("records", {}).items():
        # JSON has no tuples. Without this coercion a resumed run holds lists
        # where a fresh run holds tuples on a frozen dataclass declared
        # `tuple[str, ...]` -- the records compare unequal and hash
        # differently, so "resume the cache" would quietly stop being the same
        # measurement as "run it again".
        fields = {key: tuple(value) if key in ("scope", "excepts")
                  and isinstance(value, list) else value
                  for key, value in fields.items()}
        extractor._cache[content] = extracting.Extracted(**fields)
    return len(extractor._cache)


def save_cache(extractor: Any, path: pathlib.Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "model": extractor.model,
        "constrained": bool(getattr(extractor, "constrained", True)),
        "records": {content: record.__dict__
                    for content, record in extractor._cache.items()},
    }, indent=1), encoding="utf-8")


def reduce_case(case: Mapping[str, Any], limit: int,
                seed: int = 1) -> Mapping[str, Any]:
    """Keep every labelled memory, sample the fillers down to `limit`.

    The module docstring says why this is a fair comparison and what it does
    not license. The RNG is seeded per case, so the two arms of one run and the
    two runs of one config all see the same store.
    """
    corpus = case["corpus"]
    if limit <= 0 or len(corpus) <= limit:
        return case
    labelled = set(case["labels"].get("relevant") or ())
    for key in ("must_not_expose", "stale", "critical"):
        labelled |= set(case["labels"].get(key) or ())
    keep = [m for m in corpus if m["id"] in labelled]
    fillers = [m for m in corpus if m["id"] not in labelled]
    room = max(0, limit - len(keep))
    chosen = random.Random(f"{seed}:{case['case_id']}").sample(
        fillers, min(room, len(fillers)))
    kept = {m["id"] for m in keep} | {m["id"] for m in chosen}
    # Original corpus order, so insertion order -- and therefore any temporal
    # mechanism -- is unchanged by the sampling.
    return {**case, "corpus": [m for m in corpus if m["id"] in kept]}


def run_case(case: Mapping[str, Any], arm: str, k: int,
             extractor: Any | None) -> Outcome:
    fabric, ids = rb._build_fabric(case, "lexical")
    local = {bench: store for store, bench in ids.items()}
    started = time.perf_counter()
    inferred: list[tuple[str, str]] = []
    defaults = 0
    try:
        if arm == "declared":
            for subject, obj in DECLARED.get(case["family"], ()):
                if subject in local and obj in local:
                    fabric.relate(local[subject], RelationKind.QUALIFIES,
                                  local[obj], actor="fixture")
        elif arm == "extraction":
            # Every memory, with no reference to the labels. The cache is on
            # the extractor, so a statement seen in an earlier case costs
            # nothing here.
            records = []
            for store_id, bench_id in ids.items():
                record = extractor.extract(
                    store_id, fabric.state.memories[store_id].content)
                records.append(record)
                fabric.index_extraction(record)
            for subject, kind, obj in extracting.infer_relations(records):
                inferred.append((ids[subject], ids[obj]))
                fabric.relate(subject, kind, obj, actor="extraction")
            defaults = sum(1 for r in records if r.is_default)

        use = arm in ("declared", "extraction")
        if arm == "oracle":
            returned = list(case["labels"]["relevant"])[:k]
        else:
            chain = fabric.reconstruct(
                agent_id=case["task"]["agent_id"], query=rb.query_text(case),
                k=k, tenant_id=case["task"].get("tenant_id", "tn_default"),
                as_of=rb._as_of(case), follow_relations=use)
            returned = [ids[s.memory_id] for s in chain.steps]
            if arm == "extraction":
                # The defaults mechanism lives on `retrieve`, so a family whose
                # answer is a default rule needs that path as well as the
                # chain. Union, because the two mechanisms address different
                # families and an arm that had to pick one would measure the
                # choice.
                result = fabric.retrieve(
                    agent_id=case["task"]["agent_id"],
                    query=rb.query_text(case), k=k,
                    tenant_id=case["task"].get("tenant_id", "tn_default"),
                    min_relevance=0.0, as_of=rb._as_of(case),
                    entities=list(case["task"].get("entities") or ()),
                    use_extraction=True, follow_relations=True,
                )
                for memory in result.exposed:
                    bench_id = ids[memory.id]
                    if bench_id not in returned:
                        returned.append(bench_id)
                returned = returned[:k]
        elapsed = (time.perf_counter() - started) * 1000.0
    finally:
        fabric.close()
    allowed, refused = rb.apply_gates(case, returned)
    return Outcome(
        case_id=case["case_id"], family=case["family"], arm=arm,
        result=rb.score_case(case, allowed, refused, k),
        inferred=tuple(inferred), defaults_found=defaults, latency_ms=elapsed,
    )


def run(split: str, k: int = 5, model: str = "gemma2:latest",
        arms: Sequence[str] = ARMS, max_corpus: int = 0,
        cache: str | None = None,
        families: Sequence[str] | None = None,
        trace: str | None = None,
        constrained: bool = False) -> dict[str, Any]:
    extractor, cost = (
        build_extractor(model, cache, trace, constrained)
        if "extraction" in arms else (None, Cost()))
    reused = len(extractor._cache) if extractor is not None else 0
    cases: list[tuple[str, Mapping[str, Any]]] = []
    wanted = set(families) if families else None
    for benchmark, benchmark_families in FAMILIES.items():
        for case in rb.load(split, benchmark):
            if case["family"] not in benchmark_families:
                continue
            if wanted is not None and case["family"] not in wanted:
                continue
            cases.append((benchmark, reduce_case(case, max_corpus)))

    started = time.perf_counter()
    outcomes: list[Outcome] = []
    for arm in arms:
        for _benchmark, case in cases:
            outcomes.append(run_case(case, arm, k, extractor))
            if cache and extractor is not None:
                save_cache(extractor, pathlib.Path(cache))
        print(f"  {arm}: {time.perf_counter() - started:.0f}s elapsed, "
              f"{len(extractor._cache) if extractor else 0} extracted",
              file=sys.stderr)
    if extractor is not None:
        cost.wall_s = time.perf_counter() - started
        cost.unique_statements = len(extractor._cache)
        calls = getattr(extractor.client, "calls", [])
        cost.calls = len(calls)
        cost.tokens = sum(getattr(c, "tokens", 0) or 0 for c in calls)
        cost.reused_from_cache = reused

    def summarise(rows: Sequence[Outcome]) -> dict[str, Any]:
        if not rows:
            return {}
        mean = lambda f: round(sum(f(r) for r in rows) / len(rows), 4)  # noqa: E731
        return {
            "cases": len(rows),
            "sufficient": mean(lambda r: float(bool(r.result.sufficient))),
            "ndcg": mean(lambda r: r.result.ndcg),
            "critical_recall": mean(lambda r: r.result.critical_recall),
            "latency_ms": mean(lambda r: r.latency_ms),
            # Registered in section 5 as a gate rather than a metric: any
            # non-zero value fails the run. It was missing from this summary
            # for the first dev run, which is recorded in the result -- a
            # registered pass/fail condition that is not printed is not
            # checked, whatever the gate pipeline guarantees structurally.
            "must_not_expose_rate": mean(
                lambda r: float(bool(r.result.exposed_forbidden))),
        }

    out: dict[str, Any] = {
        "experiment": "x1-extraction-at-ingest",
        "split": split, "k": k, "model": model,
        "constrained": constrained,
        "max_corpus": max_corpus,
        "families": sorted({c["family"] for _b, c in cases}),
        "corpus_sizes": sorted(len(c["corpus"]) for _b, c in cases),
        "cases": len(cases),
        "cost": cost.__dict__,
        "arms": {}, "by_family": {},
    }
    for arm in arms:
        rows = [o for o in outcomes if o.arm == arm]
        out["arms"][arm] = summarise(rows)
        out["by_family"][arm] = {
            family: summarise([o for o in rows if o.family == family])
            for family in sorted({o.family for o in rows})
        }
    # Extraction quality against the declarations, where ground truth exists.
    extracted = [o for o in outcomes if o.arm == "extraction"]
    hits = total = found = 0
    for o in extracted:
        want = {tuple(pair) for pair in DECLARED.get(o.family, ())}
        got = set(o.inferred)
        total += len(want)
        found += len(got)
        hits += len(want & got)
    out["relation_quality"] = {
        "declared": total, "inferred": found, "correct": hits,
        "recall": round(hits / total, 4) if total else None,
        "precision": round(hits / found, 4) if found else None,
        "defaults_found": sum(o.defaults_found for o in extracted),
    }
    return out


def to_markdown(result: Mapping[str, Any]) -> str:
    fmt = lambda x: "—" if x is None else f"{x:.3f}"  # noqa: E731
    families = sorted({f for arm in result["by_family"].values() for f in arm})
    lines = [
        f"# X1 — extraction at ingest · {result['split']} split",
        "",
        f"- **Model:** `{result['model']}` · {result['cases']} cases · k={result['k']}",
        "- `declared` is the fixture-supplied ceiling, not a method. "
        "`extraction` has to recover a share of it.",
        "",
        "| arm | sufficient | nDCG | critical recall | latency ms |",
        "|---|---|---|---|---|",
    ]
    for arm, row in result["arms"].items():
        if not row:
            continue
        lines.append(
            f"| `{arm}` | **{fmt(row['sufficient'])}** | {fmt(row['ndcg'])} | "
            f"{fmt(row['critical_recall'])} | {row['latency_ms']:.0f} |")

    lines += ["", "## Sufficiency by family", "",
              "| arm | " + " | ".join(f"`{f}`" for f in families) + " |",
              "|---|" + "---|" * len(families)]
    for arm, rows in result["by_family"].items():
        cells = [fmt((rows.get(f) or {}).get("sufficient")) for f in families]
        lines.append(f"| `{arm}` | " + " | ".join(cells) + " |")

    q = result["relation_quality"]
    cost = result["cost"]
    lines += [
        "", "## Extraction quality and cost", "",
        f"- **Relations:** {q['correct']} correct of {q['inferred']} inferred, "
        f"against {q['declared']} declared — precision {fmt(q['precision'])}, "
        f"recall {fmt(q['recall'])}",
        f"- **Defaults recognised:** {q['defaults_found']}",
        f"- **Cost:** {cost['calls']} model calls, {cost['tokens']} tokens, "
        f"{cost['unique_statements']} unique statements, "
        f"{cost['wall_s']:.0f} s wall",
    ]
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--split", default="dev", choices=["dev", "test"])
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument("--model", default="gemma2:latest")
    parser.add_argument("--arms", nargs="*", default=list(ARMS))
    parser.add_argument("--max-corpus", type=int, default=0,
                        help="sample fillers down to this many memories per "
                             "case, keeping every labelled one; 0 = full store")
    parser.add_argument("--cache", help="path to a resumable extraction cache")
    parser.add_argument("--trace",
                        help="append one JSON object per model call to this "
                             "file (metadata only, no content)")
    parser.add_argument("--constrained", action="store_true",
                        help="constrain decoding to the JSON schema. Measured "
                             "to improve nothing and to cost gemma2 58% more "
                             "wall time (result section 10), so free-form is "
                             "the default here")
    parser.add_argument("--family", nargs="*",
                        help="restrict to these families. The registration "
                             "pooled two; `implied_by_default` is abandoned on "
                             "dev under its own abandonment clause, because a "
                             "plain lexical baseline reaches 1.000 sufficiency "
                             "there at k=5 (0.000 only at k=3, which is the "
                             "metric the registered B was copied from).")
    parser.add_argument("--out")
    parser.add_argument("--json", dest="as_json", action="store_true")
    args = parser.parse_args(argv)
    result = run(args.split, args.k, args.model, args.arms,
                 max_corpus=args.max_corpus, cache=args.cache,
                 families=args.family, trace=args.trace,
                 constrained=args.constrained)
    text = json.dumps(result, indent=2) if args.as_json else to_markdown(result)
    print(text)
    if args.out:
        pathlib.Path(args.out).write_text(
            to_markdown(result) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
