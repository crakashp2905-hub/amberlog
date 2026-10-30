"""INT-04: compaction with reversible drill-down (masterplan §7A.6). Descriptive, no claim.

    python -m benchmarks.compaction

A long task log is compacted into one governed summary (`compaction.compact_session`).
Under a fixed context budget, does the critical detail a question needs reach
the context — from the raw log, from the summary alone, or from the summary
plus a drill-down into the memories it was built from? And do the invariants
hold: a withdrawn source is never brought back by drilling down, and an erased
one comes back as nothing, not as text?

Deterministic, no model. Budgets are in words; the tokenizer of any particular
model would change the absolute numbers, not the comparison.
"""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OUT_MD = ROOT / "research" / "results" / "int04-compaction-drilldown.md"
OUT_JSON = ROOT / "research" / "results" / "int04-compaction-drilldown.json"
SEEDS = (1, 2, 3, 4, 5)
TASKS, STEPS, BUDGETS = 8, 30, (40, 80, 160)
COMPONENTS = ["feed pump", "relief valve", "chiller", "boiler", "compressor", "filter bank",
              "heat exchanger", "dosing unit", "intake fan", "drain line"]


def words(text: str) -> list[str]:
    return text.split()


def fit(texts: list[str], budget: int) -> str:
    out: list[str] = []
    for t in texts:
        room = budget - len(out)
        if room <= 0:
            break
        out += words(t)[:room]
    return " ".join(out)


def task_log(rng: random.Random, task: int) -> list[tuple[str, str, str]]:
    """(sentence, question, critical detail) per step."""
    rows = []
    for step in range(STEPS):
        comp = rng.choice(COMPONENTS)
        tag = f"U{task}{step:02d}"
        kind = rng.choice(["limit", "negation", "date"])
        if kind == "limit":
            v = rng.randint(3, 95)
            rows.append((f"Step {step}: unit {tag} {comp} limit set to {v} bar after test.",
                         f"What limit was set on unit {tag}?", f"{v} bar"))
        elif kind == "negation":
            rows.append((f"Step {step}: unit {tag} {comp} must not be restarted before inspection.",
                         f"Can unit {tag} be restarted?", "must not be restarted"))
        else:
            d = f"2026-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}"
            rows.append((f"Step {step}: unit {tag} {comp} next service due {d}.",
                         f"When is unit {tag} due for service?", d))
    return rows


def run_seed(seed: int) -> dict[str, Any]:
    from memory_fabric import MemoryFabric
    from memory_fabric.compaction import compact_session

    rng = random.Random(seed)
    f = MemoryFabric(":memory:", auto_activate=True, recognise_copies=False, retrieval="lexical")
    results: dict[str, Any] = {str(b): {a: [] for a in ("raw", "summary", "summary+drill", "oracle")}
                               for b in BUDGETS}
    invariants = {"withdrawn_resurrected": 0, "erased_returned_text": 0, "summary_still_exposable": 0,
                  "checks": 0}
    summary_words, raw_words = [], []
    try:
        for task in range(TASKS):
            ep = f.start_episode("worker", f"task-{task}")
            log = task_log(rng, task)
            ids = [f.remember("worker", s, source_episodes=[ep.id], scope="team") for s, _, _ in log]
            report = compact_session(f, ep.id, "worker")
            summary = f.state.memories[report.summary_id].content
            summary_words.append(len(words(summary)))
            raw_words.append(sum(len(words(s)) for s, _, _ in log))
            for (sentence, question, detail), mid in zip(log, ids):
                for b in BUDGETS:
                    raw = [m.content for m in f.retrieve("reader", question, k=5, min_relevance=0.0).exposed]
                    drill = [m.content for m in f.retrieve("reader", question, k=5, min_relevance=0.0,
                                                           within=report.inputs).exposed]
                    contexts = {"raw": fit(raw, b), "summary": fit([summary], b),
                                "summary+drill": fit([fit([summary], b // 2)] + drill, b),
                                "oracle": fit([sentence], b)}
                    for arm, ctx in contexts.items():
                        results[str(b)][arm].append(detail in ctx)
            # Invariants: withdraw one source and erase another, then drill down for them.
            gone, erased = ids[0], ids[1]
            f.quarantine(gone, reason="source wrong", actor="reviewer", basis="contradicted")
            f.erase_content(erased, reason="erasure request")
            for (_, question, _), mid in ((log[0], gone), (log[1], erased)):
                got = f.retrieve("reader", question, k=5, min_relevance=0.0, within=report.inputs).exposed
                invariants["checks"] += 1
                if mid == gone and any(m.id == gone for m in got):
                    invariants["withdrawn_resurrected"] += 1
                if mid == erased and any(m.id == erased and m.content for m in got):
                    invariants["erased_returned_text"] += 1
            from memory_fabric.model import EXPOSABLE_STATES

            invariants["checks"] += 1
            if f.state.memories[report.summary_id].lifecycle_state in EXPOSABLE_STATES:
                invariants["summary_still_exposable"] += 1
    finally:
        f.close()
    return {"recovered": {b: {a: sum(v) / len(v) for a, v in arms.items()} for b, arms in results.items()},
            "invariants": invariants, "summary_words": sum(summary_words) / len(summary_words),
            "raw_words": sum(raw_words) / len(raw_words)}


def main(argv: list[str]) -> int:
    from benchmarks.manifest import Manifest, head
    from benchmarks.manifest import write as write_manifest

    per_seed = {s: run_seed(s) for s in SEEDS}
    arms = ("raw", "summary", "summary+drill", "oracle")
    table = {str(b): {a: round(sum(per_seed[s]["recovered"][str(b)][a] for s in SEEDS) / len(SEEDS), 3)
                      for a in arms} for b in BUDGETS}
    inv = {k: sum(per_seed[s]["invariants"][k] for s in SEEDS) for k in per_seed[SEEDS[0]]["invariants"]}
    sw = round(sum(per_seed[s]["summary_words"] for s in SEEDS) / len(SEEDS), 1)
    rw = round(sum(per_seed[s]["raw_words"] for s in SEEDS) / len(SEEDS), 1)
    commit = head()[:12]
    data = {"commit": commit, "seeds": list(SEEDS), "tasks": TASKS, "steps": STEPS, "budgets_words": list(BUDGETS),
            "recovered": table, "invariants": inv, "summary_words": sw, "raw_words": rw}
    print(json.dumps(data, indent=1))
    if "--no-write" in argv:
        return 0
    OUT_JSON.write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")
    ok = inv["withdrawn_resurrected"] == 0 and inv["erased_returned_text"] == 0 and inv["summary_still_exposable"] == 0
    write_manifest(Manifest(
        run_id="int04-compaction-drilldown", suite="INT-04", arm="all", decision="DESCRIPTIVE",
        repo_commit=commit, reason="descriptive: no improvement claim registered",
        dataset={"name": "generated", "generator": "benchmarks/compaction.py"}, seeds=list(SEEDS),
        results={"recovered_by_budget": table, "invariants": inv}, cost={"model_usd": 0.0, "model_calls": 0},
        verification={"baseline_registered": True, "oracle_sanity_passed": all(
            table[b]["oracle"] >= max(table[b].values()) for b in table),
            "holdout_frozen": False, "independent_replicated": False}))
    rows = "\n".join(f"| {b} | " + " | ".join(f"{table[b][a]:.3f}" for a in arms) + " |" for b in table)
    OUT_MD.write_text(f"""# INT-04 — compaction with reversible drill-down (descriptive)

Produced by `python -m benchmarks.compaction` at commit `{commit}`; seeds {', '.join(map(str, SEEDS))}; {TASKS} task
logs of {STEPS} steps each, every step carrying one critical detail (a limit with its unit, a
prohibition, or a date). No model; no improvement claim is registered, so this is a description.
Raw numbers: [int04-compaction-drilldown.json](int04-compaction-drilldown.json).

Share of questions whose critical detail is in the context, by budget (words):

| budget | raw (search top-5) | summary only | summary + drill-down | oracle |
|---|---|---|---|---|
{rows}

A summary averages {sw} words against {rw} for the raw log it replaces.

| invariant | violations | checks |
|---|---|---|
| a withdrawn source is never returned by drilling down | {inv['withdrawn_resurrected']} | {inv['checks']} |
| an erased source never returns text | {inv['erased_returned_text']} | |
| a summary built on a withdrawn source is no longer exposable | {inv['summary_still_exposable']} | |

Invariants: **{'all held' if ok else 'VIOLATED'}**. Zero violations in these checks bounds the rate,
it does not prove impossibility; the deterministic tests in `tests/test_gov_conformance.py` are the
standing check.
""", encoding="utf-8")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
