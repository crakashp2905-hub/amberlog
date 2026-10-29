"""INT-03 / E1: exhaustive enumeration — typed filter vs search (research/prereg/e1-exhaustive-enumeration.md).

    python -m benchmarks.enumeration --arms lexical,nav          # baselines first (AGENTS.md 8c/8d)
    python -m benchmarks.enumeration                              # every arm, writes the result files

Deterministic, no model, no network. Seeds 1-5.
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
OUT_MD = ROOT / "research" / "results" / "e1-exhaustive-enumeration.md"
OUT_JSON = ROOT / "research" / "results" / "e1-exhaustive-enumeration.json"

KINDS = ["valve", "pump", "sensor", "door", "server"]
SITES = ["riverside", "hilltop", "harbour", "northfield", "eastgate", "lakeshore"]
STATUS = {"open": ["is open", "stands open", "was left open", "is not closed"],
          "closed": ["is closed", "is shut", "was sealed", "is not open"]}
YEARS = range(2015, 2026)
N_RECORDS, N_NOTES, UNTYPED, K = 1000, 60, 0.10, 50
SEEDS = (1, 2, 3, 4, 5)
ARMS = ("lexical", "nav", "typed", "typed+fallback", "oracle")


@dataclass
class Record:
    rid: str
    kind: str
    site: str
    status: str
    year: int
    typed: bool


def world(seed: int) -> tuple[list[Record], list[str], list[dict[str, Any]]]:
    rng = random.Random(seed)
    records = [Record(f"{k[0].upper()}-{i:04d}", k, rng.choice(SITES), rng.choice(list(STATUS)),
                      rng.choice(list(YEARS)), rng.random() >= UNTYPED)
               for i, k in enumerate(rng.choice(KINDS) for _ in range(N_RECORDS))]
    notes = [f"Inspection of {r.kind} {r.rid} is scheduled for next week by the {rng.choice(SITES)} crew."
             for r in rng.sample(records, N_NOTES)]
    queries: list[dict[str, Any]] = []
    while len(queries) < 60:
        broad = len(queries) >= 30
        q: dict[str, Any] = {"kind": rng.choice(KINDS)}
        extra = rng.sample(["site", "status"] if broad else ["site", "status", "year"], 1 if broad else 2)
        for key in extra:
            if key == "site":
                q["site"] = rng.choice(SITES)
            elif key == "status":
                q["status"] = rng.choice(list(STATUS))
            else:
                lo = rng.choice(list(YEARS)[:-2])
                q["year"] = (lo, lo + rng.randint(1, 4))
        gold = {r.rid for r in records if matches(r, q)}
        if gold:
            queries.append({"where": q, "gold": gold, "type": "broad" if broad else "narrow"})
    return records, notes, queries


def matches(r: Record, q: dict[str, Any]) -> bool:
    return (r.kind == q["kind"] and q.get("site", r.site) == r.site and q.get("status", r.status) == r.status
            and ("year" not in q or q["year"][0] <= r.year <= q["year"][1]))


def sentence(r: Record, rng: random.Random) -> str:
    return (f"{r.kind.capitalize()} {r.rid} at the {r.site.capitalize()} site {rng.choice(STATUS[r.status])}; "
            f"it was installed in {r.year}.")


def query_text(q: dict[str, Any]) -> str:
    parts = [q["kind"], q.get("site", ""), q.get("status", "")]
    if "year" in q:
        parts.append(" ".join(str(y) for y in range(q["year"][0], q["year"][1] + 1)))
    return " ".join(p for p in parts if p)


def text_filter(text: str, q: dict[str, Any]) -> bool:
    """The strongest text filter without a model: every condition read from the sentence."""
    t = text.lower()
    if not re.search(rf"\b{q['kind']}\b", t) or "installed in" not in t:
        return False
    if "site" in q and f"the {q['site']} site" not in t:
        return False
    if "status" in q:
        want = any(p in t for p in STATUS[q["status"]])
        other = any(p in t for s, ps in STATUS.items() if s != q["status"] for p in ps)
        if not want or other:
            return False
    if "year" in q:
        found = re.search(r"installed in (\d{4})", t)
        if not found or not q["year"][0] <= int(found[1]) <= q["year"][1]:
            return False
    return True


def where_of(q: dict[str, Any]) -> dict[str, Any]:
    w: dict[str, Any] = {"kind": q["kind"]}
    if "site" in q:
        w["site"] = q["site"]
    if "status" in q:
        w["status"] = q["status"]
    if "year" in q:
        w["year"] = {"$gte": q["year"][0], "$lte": q["year"][1]}
    return w


def run_seed(seed: int, arms: tuple[str, ...]) -> dict[str, Any]:
    from amberlog import Amberlog
    from amberlog.navigation import navigate
    from amberlog.typed_query import select

    records, notes, queries = world(seed)
    rng = random.Random(seed * 101)
    f = Amberlog(":memory:", auto_activate=True, encrypt_content=False, recognise_copies=False,
                     retrieval="lexical")
    rid_of: dict[str, str] = {}
    try:
        for r in records:
            mid = f.remember("inventory", sentence(r, rng), scope="team",
                             structured=({"kind": r.kind, "site": r.site, "status": r.status, "year": r.year}
                                         if r.typed else None))
            rid_of[mid] = r.rid
        for n in notes:
            f.remember("inventory", n, scope="team")
        content = {mid: f.state.memories[mid].content for mid in f.state.memories}

        def ids_to_rids(ids: list[str]) -> set[str]:
            return {rid_of[m] for m in ids if m in rid_of}

        arm_fns: dict[str, Callable[[dict[str, Any]], tuple[set[str], int, bool | None]]] = {}

        def lexical(q: dict[str, Any]) -> tuple[set[str], int, bool | None]:
            got = [m.id for m in f.retrieve("reader", query_text(q["where"]), k=K, min_relevance=0.0).exposed]
            return ids_to_rids([m for m in got if text_filter(content[m], q["where"])]), len(got), None

        def nav(q: dict[str, Any]) -> tuple[set[str], int, bool | None]:
            got = navigate(f, "reader", query_text(q["where"]), k=K)
            return ids_to_rids([m for m in got if text_filter(content[m], q["where"])]), len(got), None

        def typed(q: dict[str, Any]) -> tuple[set[str], int, bool | None]:
            sel = select(f, "reader", where_of(q["where"]))
            return ids_to_rids(sel.ids), len(sel.ids), sel.complete

        def typed_fallback(q: dict[str, Any]) -> tuple[set[str], int, bool | None]:
            sel = select(f, "reader", where_of(q["where"]))
            extra = [m for m in sel.unknown if text_filter(content[m], q["where"])]
            return ids_to_rids(sel.ids + extra), len(sel.ids) + len(sel.unknown), None

        arm_fns.update({"lexical": lexical, "nav": nav, "typed": typed, "typed+fallback": typed_fallback,
                        "oracle": lambda q: (set(q["gold"]), len(q["gold"]), True)})
        out: dict[str, Any] = {}
        for arm in arms:
            rows = []
            started = time.perf_counter()
            for q in queries:
                got, read, complete = arm_fns[arm](q)
                gold = q["gold"]
                rows.append({"type": q["type"], "exact": got == gold,
                             "recall": len(got & gold) / len(gold),
                             "precision": len(got & gold) / len(got) if got else (1.0 if not gold else 0.0),
                             "read": read, "complete": complete, "gold": len(gold)})
            out[arm] = {"rows": rows, "seconds": round(time.perf_counter() - started, 3)}
        return out
    finally:
        f.close()


def summarise(per_seed: dict[int, dict[str, Any]], arms: tuple[str, ...]) -> dict[str, Any]:
    def avg(xs: list[float]) -> float:
        return round(sum(xs) / len(xs), 4) if xs else 0.0

    table: dict[str, Any] = {}
    for arm in arms:
        rows = [r for s in per_seed.values() for r in s[arm]["rows"]]
        table[arm] = {
            "set_exact": avg([r["exact"] for r in rows]),
            "set_exact_narrow": avg([r["exact"] for r in rows if r["type"] == "narrow"]),
            "set_exact_broad": avg([r["exact"] for r in rows if r["type"] == "broad"]),
            "recall": avg([r["recall"] for r in rows]), "precision": avg([r["precision"] for r in rows]),
            "contents_read_per_query": avg([r["read"] for r in rows]),
            "per_seed_set_exact": {s: avg([r["exact"] for r in per_seed[s][arm]["rows"]]) for s in per_seed},
        }
        if arm == "typed":
            wrong = [r for r in rows if not r["exact"]]
            table[arm]["certificate_soundness"] = avg([r["complete"] is False for r in wrong]) if wrong else 1.0
            table[arm]["complete_share"] = avg([bool(r["complete"]) for r in rows])
    return table


def verdict(table: dict[str, Any]) -> dict[str, Any]:
    from benchmarks.checks import bar, sanity

    base_arm = max(("lexical", "nav"), key=lambda a: table[a]["set_exact"])
    b, o = table[base_arm]["set_exact"], table["oracle"]["set_exact"]
    threshold = bar(b, o, 0.40)
    t = table["typed"]
    wins = sum(t["per_seed_set_exact"][s] > table[base_arm]["per_seed_set_exact"][s] for s in t["per_seed_set_exact"])
    checks = sanity({a: v["set_exact"] for a, v in table.items()}, ["lexical", "nav"])
    invalid = bool(checks["baselines_at_ceiling"] or checks["arms_above_oracle"])
    e1a = t["set_exact"] >= threshold and wins >= 4
    e1b = t["certificate_soundness"] == 1.0
    return {"B_arm": base_arm, "B": b, "O": o, "bar_E1a": round(threshold, 4), "typed_seed_wins": wins,
            "E1a": e1a, "E1b": e1b, "sanity": checks,
            "decision": "INVALID" if invalid else ("PASS" if e1a and e1b else "FAIL")}


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--arms", default=",".join(ARMS))
    p.add_argument("--seeds", default=",".join(map(str, SEEDS)))
    args = p.parse_args(argv)
    arms = tuple(a for a in args.arms.split(",") if a)
    seeds = tuple(int(s) for s in args.seeds.split(","))
    per_seed = {s: run_seed(s, arms) for s in seeds}
    table = summarise(per_seed, arms)
    print(json.dumps(table, indent=1))
    if set(ARMS) <= set(arms) and seeds == SEEDS:
        write(table, verdict(table))
    return 0


def write(table: dict[str, Any], v: dict[str, Any]) -> None:
    from benchmarks.manifest import Manifest, head
    from benchmarks.manifest import write as write_manifest

    commit = head()[:12]
    OUT_JSON.write_text(json.dumps({"commit": commit, "seeds": list(SEEDS), "k": K, "records": N_RECORDS,
                                    "untyped_share": UNTYPED, "rows": table, "verdict": v},
                                   indent=1) + "\n", encoding="utf-8")
    write_manifest(Manifest(
        run_id="e1-exhaustive-enumeration", suite="INT-03", arm="all", decision=v["decision"],
        repo_commit=commit, prereg="research/prereg/e1-exhaustive-enumeration.md",
        dataset={"name": "generated", "generator": "benchmarks/enumeration.py", "seeds": list(SEEDS)},
        model={"provider": None, "id": None}, seeds=list(SEEDS),
        counts={"attempted": 60 * len(SEEDS), "completed": 60 * len(SEEDS),
                "solved": round(table["typed"]["set_exact"] * 60 * len(SEEDS)), "skipped": 0, "failed": 0},
        results={"primary_metric": "set_exact", "typed": table["typed"]["set_exact"],
                 v["B_arm"]: v["B"], "bar": v["bar_E1a"]},
        cost={"model_usd": 0.0, "model_calls": 0},
        verification={"baseline_registered": True, "oracle_sanity_passed": v["sanity"]["ok"],
                      "holdout_frozen": True, "independent_replicated": False}))
    rows = "\n".join(
        f"| {a} | {t['set_exact']:.3f} | {t['set_exact_narrow']:.3f} | {t['set_exact_broad']:.3f} | "
        f"{t['recall']:.3f} | {t['precision']:.3f} | {t['contents_read_per_query']:.1f} |"
        for a, t in table.items())
    OUT_MD.write_text(f"""# E1 — exhaustive enumeration: typed filter vs search (INT-03)

Registered in [e1-exhaustive-enumeration.md](../prereg/e1-exhaustive-enumeration.md). Produced by
`python -m benchmarks.enumeration` at commit `{commit}`; seeds {', '.join(map(str, SEEDS))}; {N_RECORDS} records,
{int(UNTYPED * 100)}% written untyped, k = {K} for the search arms. No model. Raw numbers:
[e1-exhaustive-enumeration.json](e1-exhaustive-enumeration.json).

| arm | set-exact | narrow | broad | recall | precision | memories read / query |
|---|---|---|---|---|---|---|
{rows}

| B ({v['B_arm']}) | bar E1a | typed | typed > B in seeds | E1a | E1b certificate soundness | 8b/8c sanity | decision |
|---|---|---|---|---|---|---|---|
| {v['B']:.3f} | {v['bar_E1a']:.3f} | {table['typed']['set_exact']:.3f} | {v['typed_seed_wins']}/5 | {'pass' if v['E1a'] else 'fail'} | {table['typed']['certificate_soundness']:.2f} ({'pass' if v['E1b'] else 'fail'}) | {'ok' if v['sanity']['ok'] else v['sanity']} | **{v['decision']}** |

`typed` called its answer complete on {table['typed']['complete_share']:.0%} of queries: a visible
memory without typed fields makes every answer incomplete, and the certificate says so rather than
treating unknown as no.
""", encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
