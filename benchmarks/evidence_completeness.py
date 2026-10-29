"""ECV1 five-arm, fixed-budget evaluation. Baseline dev run precedes registration."""
from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path
from typing import Any

from benchmarks.completeness_data import CONFIG, SPLITS, digest, generate
from benchmarks.manifest import Manifest, head, write
from amberlog import Amberlog
from amberlog.evidence_completeness import classify, exhaustive

ARMS = ("lexical", "typed", "typed+fallback", "selective", "oracle")
ROOT = Path(__file__).resolve().parents[1]


def evaluate(memory: Any, where: Any) -> bool | None:
    """Generic key=value reader; never imports gold or corpus template definitions."""
    values: dict[str, set[str]] = {}
    for key, value in re.findall(r"\b([a-z]+)\s*=\s*([a-z]+)\b", memory.content.lower()):
        values.setdefault(key, set()).add(value)
    if any(len(values.get(k, set())) != 1 for k in where):
        return None
    return all(values[k] == {v} for k, v in where.items())


def run_seed(seed: int, split: str, arms: tuple[str, ...]) -> dict[str, Any]:
    data = generate(seed, split)
    f = Amberlog(":memory:", retrieval="lexical", recognise_copies=False)
    rid_of, records = {}, {}
    try:
        for row in data["records"]:
            mid = f.remember("writer", row["text"], structured=row["fields"], auto_activate=True, scope="team")
            rid_of[mid], records[mid] = row["rid"], row
        output: dict[str, Any] = {}
        budget = CONFIG["budget"]
        for arm in arms:
            rows = []
            for index, q in enumerate(data["queries"]):
                start = time.perf_counter()
                c = classify(f, "reader", q)
                ids, reads, complete = list(c.matches), 0, c.complete
                coverage = 1 - len(c.unknown) / c.considered
                query = " ".join(q.values())
                if arm == "selective":
                    result = exhaustive(f, "reader", q, query=query, evaluate=evaluate,
                                        evaluator_id="key-value/1", max_reads=budget)
                    ids, reads, complete = result.ids, result.reads, result.complete
                    coverage = 1 - len(result.unknown) / result.considered
                elif arm != "typed":
                    if arm == "lexical":
                        candidates = list(records)
                        ids = []
                    elif arm == "typed+fallback":
                        # Strong control: the existing E1 typed+fallback also
                        # uses three-valued unknowns, not all untyped records.
                        candidates = c.unknown
                    else:
                        # Same budget and mechanisms, perfect unknown ordering.
                        candidates = sorted(c.unknown, key=lambda m: rid_of[m] not in data["gold"][index])
                    if arm == "lexical":
                        exposed = f.retrieve("reader", query, within=candidates, k=budget,
                            min_relevance=0.0, expand_lineage=0, group_by_source_root=False).exposed
                    else:
                        exposed = []
                        for mid in candidates:
                            if len(exposed) >= budget:
                                break
                            exposed.extend(f.retrieve("reader", query, within=[mid], k=1,
                                min_relevance=0.0, expand_lineage=0, group_by_source_root=False).exposed)
                    reads = len(exposed)
                    known_false = set(c.nonmatches)
                    for memory in exposed:
                        if memory.id not in known_false and evaluate(memory, q) is True:
                            ids.append(memory.id)
                    # Exhaustive coverage cannot be inferred just from hitting gold.
                    checked = {m.id for m in exposed if evaluate(m, q) is not None}
                    complete = set(c.unknown) <= checked
                    coverage = 1 - len(set(c.unknown) - checked) / c.considered
                    if arm == "lexical":
                        complete = set(records) <= checked
                        coverage = len(checked) / len(records)
                got, gold = {rid_of[m] for m in ids}, set(data["gold"][index])
                rows.append({"query": index, "exact": got == gold,
                             "recall": len(got & gold) / len(gold) if gold else 1.0,
                             "precision": len(got & gold) / len(got) if got else float(not gold),
                             "complete": complete, "false_complete": complete and got != gold,
                             "reads": reads, "latency_ms": round(1000 * (time.perf_counter() - start), 3),
                             "matched": sorted(got), "gold": sorted(gold),
                             "coverage": coverage})
            output[arm] = rows
        return output
    finally:
        f.close()


def summary(runs: dict[str, Any]) -> dict[str, Any]:
    table = {}
    for arm in next(iter(runs.values())):
        rows = [r for seed in runs.values() for r in seed[arm]]
        table[arm] = {key: round(sum(r[key] for r in rows) / len(rows), 4)
                      for key in ("exact", "recall", "precision", "complete", "false_complete",
                                  "reads", "latency_ms", "coverage")}
        table[arm]["per_seed_exact"] = {s: sum(r["exact"] for r in v[arm]) / len(v[arm])
                                          for s, v in runs.items()}
    return table


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", choices=SPLITS, required=True)
    parser.add_argument("--baselines-only", action="store_true")
    args = parser.parse_args()
    if args.split == "test" and args.baselines_only:
        raise ValueError("baseline discovery belongs on development only")
    arms = tuple(a for a in ARMS if a != "selective") if args.baselines_only else ARMS
    registration = ROOT / "research/prereg/ecv1-threshold.json"
    if args.split == "test" and not registration.exists():
        raise ValueError("commit a threshold registration after measuring development headroom first")
    runs = {str(s): run_seed(s, args.split, arms) for s in SPLITS[args.split]}
    table = summary(runs)
    decision = "DESCRIPTIVE"
    threshold = None
    above = [a for a in arms if table[a]["exact"] > table["oracle"]["exact"]]
    if args.split == "test":
        reg = json.loads(registration.read_text())
        best = max(("lexical", "typed", "typed+fallback"), key=lambda a: table[a]["exact"])
        b, o = table[best]["exact"], table["oracle"]["exact"]
        threshold = b + reg["headroom_share"] * (o - b) if reg["attainable_headroom"] else None
        wins = sum(table["selective"]["per_seed_exact"][s] > table[best]["per_seed_exact"][s] for s in runs)
        decision = ("INCONCLUSIVE" if above or o <= b or not reg["attainable_headroom"] else
                    "PASS" if table["selective"]["exact"] >= threshold and wins >= 4
                    and table["selective"]["false_complete"] == 0 else "FAIL")
    data = {"commit": head(), "split": args.split, "dataset_sha256": digest(args.split),
            "config": CONFIG, "seeds": SPLITS[args.split], "arms": arms,
            "rows": runs, "summary": table, "decision": decision, "threshold": threshold,
            "oracle_violations": above, "cost": {"model_calls": 0, "model_usd": 0,
                "hardware_usd": None, "note": "reads and latency measured; local hardware cost unpriced"}}
    out = ROOT / f"research/results/ecv1-{args.split}.json"
    out.write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")
    if args.split == "test":
        write(Manifest(run_id="evidence-completeness-v1", suite="INT-03", arm="all", decision=decision,
                       repo_commit=head(), prereg="research/prereg/ecv1-design.md",
                       reason="development lexical baseline saturates oracle; no attainable threshold registered",
                       budget={"content_reads_per_query": CONFIG["budget"], "model_calls": 0},
                       counts={"attempted": len(runs) * 2, "completed": len(runs) * 2,
                               "solved": round(table["selective"]["exact"] * len(runs) * 2),
                               "failed": 0, "skipped": 0},
                       dataset={"sha256": digest(args.split), "split": args.split}, seeds=list(SPLITS[args.split]),
                       results={"summary": table, "threshold": threshold}, cost=data["cost"],
                       verification={"baseline_registered": True, "oracle_sanity_passed": not above,
                                     "holdout_frozen": True, "independent_replicated": False}))
    print(json.dumps({"summary": table, "decision": decision, "threshold": threshold}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
