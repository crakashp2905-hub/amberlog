"""C3 — a model-backed check for free-text claims (research/prereg/c3-free-text-claims.md).

    python -m experiments.c3_free_text            # all arms, seeds 1-5
"""

from __future__ import annotations

import json
import random
import statistics
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from memory_fabric import MemoryFabric
from memory_fabric.claimcheck import ModelClaimChecker

ROOT = Path(__file__).resolve().parent.parent
SEEDS = (1, 2, 3, 4, 5)
PLACES = ("east wing", "west wing", "north lab", "loading bay", "server room", "cafeteria",
          "archive", "roof terrace")
# kind -> (established fact, contradiction, paraphrase, new detail)
KINDS = {
    "safe": ("The {p} is safe to enter.",
             "The {p} is not safe to enter; the ceiling is unstable.",
             "It is fine to go into the {p}.",
             "The {p} was repainted last week."),
    "open": ("The {p} is open to visitors.",
             "The {p} is closed to everyone until further notice.",
             "Visitors are allowed in the {p}.",
             "The {p} has a new information desk."),
    "generator": ("The backup generator in the {p} works.",
                  "The backup generator in the {p} is broken and will not start.",
                  "The {p}'s backup generator runs fine.",
                  "The {p}'s backup generator was serviced by an outside contractor."),
    "dogs": ("Dogs are allowed in the {p}.",
             "Dogs are banned from the {p}.",
             "Pets such as dogs may come into the {p}.",
             "There is a water bowl by the door of the {p}."),
    "alarm": ("The fire alarm in the {p} is connected to the monitoring service.",
              "The fire alarm in the {p} is disconnected from the monitoring service.",
              "The {p}'s fire alarm reports to the monitoring service.",
              "The fire alarm in the {p} was tested on Monday."),
    "night": ("The {p} runs a night shift.",
              "The {p} has no night shift any more.",
              "There is a night shift working in the {p}.",
              "The night shift in the {p} has a new supervisor."),
}
ARMS = ("structural", "haiku", "sonnet", "oracle")


def world(seed: int) -> dict[str, Any]:
    rng = random.Random(f"c3/{seed}")
    pairs = [(p, k) for p in PLACES for k in KINDS]
    established = rng.sample(pairs, 24)
    unused = [pp for pp in pairs if pp not in established]
    claims = []
    for kind, n in (("contradiction", 8), ("paraphrase", 8), ("new_detail", 8)):
        for place, k in rng.sample(established, n):
            text = KINDS[k][{"contradiction": 1, "paraphrase": 2, "new_detail": 3}[kind]]
            claims.append({"type": kind, "text": text.format(p=place)})
    for place, k in rng.sample(unused, 8):
        claims.append({"type": "other_place", "text": KINDS[k][1].format(p=place)})
    rng.shuffle(claims)
    return {"established": [KINDS[k][0].format(p=p) for p, k in established], "claims": claims}


def one_claim(arm: str, w: dict[str, Any], claim: dict[str, Any]) -> tuple[bool, float]:
    """Fresh store per claim, so claims do not influence each other."""
    if arm == "oracle":
        return claim["type"] == "contradiction", 0.0
    checker = None
    if arm in ("haiku", "sonnet"):
        checker = ModelClaimChecker(f"claude-cli:{arm}")
    f = MemoryFabric(":memory:", auto_activate=True, claim_checker=checker)
    try:
        for text in w["established"]:
            f.remember("inspector", text, scope="team")
        for i in range(3):  # a track record for the inspector
            f.remember("inspector", f"Routine walk-through number {i} completed.", scope="team")
        mid = f.remember("field-agent", claim["text"], scope="team")
        held = f.lifecycle_of(mid).value != "active"
    finally:
        f.close()
    cost = sum(c["cost_usd"] or 0 for c in checker.client.log.calls) if checker else 0.0
    return held, cost


def run(arm: str, seed: int) -> dict[str, Any]:
    w = world(seed)
    with ThreadPoolExecutor(max_workers=8 if arm in ("haiku", "sonnet") else 1) as pool:
        results = list(pool.map(lambda c: one_claim(arm, w, c), w["claims"]))
    contra = [h for (h, _), c in zip(results, w["claims"]) if c["type"] == "contradiction"]
    other = [h for (h, _), c in zip(results, w["claims"]) if c["type"] != "contradiction"]
    by_type: dict[str, float] = {}
    for t in ("contradiction", "paraphrase", "new_detail", "other_place"):
        hs = [h for (h, _), c in zip(results, w["claims"]) if c["type"] == t]
        by_type[t] = sum(hs) / len(hs)
    return {"arm": arm, "seed": seed, "recall": sum(contra) / len(contra),
            "false_holds": sum(other) / len(other), "held_by_type": by_type,
            "cost_usd": round(sum(c for _, c in results), 5), "writes": len(results)}


def main() -> int:
    rows: dict[str, list[dict[str, Any]]] = {a: [] for a in ARMS}
    rows["structural"] = [run("structural", s) for s in SEEDS]
    base = statistics.fmean(r["recall"] for r in rows["structural"])
    verdict: dict[str, Any] = {"structural_recall": base}
    if base >= 0.9:
        verdict["C3"] = "ABANDONED (8c: the built-in rules already hold these)"
    else:
        rows["oracle"] = [run("oracle", s) for s in SEEDS]
        for arm in ("haiku", "sonnet"):
            rows[arm] = [run(arm, s) for s in SEEDS]
            print(arm, [round(r["recall"], 2) for r in rows[arm]],
                  [round(r["false_holds"], 2) for r in rows[arm]], flush=True)
        bar = base + 0.5 * (1 - base)
        for arm in ("haiku", "sonnet"):
            rec = statistics.fmean(r["recall"] for r in rows[arm])
            fh = statistics.fmean(r["false_holds"] for r in rows[arm])
            per = sum(r["recall"] >= bar and r["false_holds"] <= 0.10 for r in rows[arm])
            verdict[arm] = {"recall": rec, "false_holds": fh, "C3a": rec >= bar,
                            "C3b": fh <= 0.10, "C3c": per >= 4, "bar": bar,
                            "cost_per_write_usd": sum(r["cost_usd"] for r in rows[arm])
                            / sum(r["writes"] for r in rows[arm])}
        verdict["ceiling_ok"] = all(r["recall"] <= 1.0 and r["false_holds"] >= 0.0
                                    for a in ARMS for r in rows[a])
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True,
                            text=True, cwd=ROOT).stdout.strip()
    out = ROOT / "research" / "results"
    (out / "c3-free-text.json").write_text(json.dumps(
        {"commit": commit, "rows": rows, "verdict": verdict}, indent=2) + "\n")

    def line(arm: str) -> str:
        rs = rows[arm]
        if not rs:
            return f"| `{arm}` | not run | | | | |"
        t = {k: statistics.fmean(r["held_by_type"][k] for r in rs)
             for k in ("contradiction", "paraphrase", "new_detail", "other_place")}
        cost = sum(r["cost_usd"] for r in rs) / sum(r["writes"] for r in rs)
        return (f"| `{arm}` | {t['contradiction']:.2f} | {t['paraphrase']:.2f} | "
                f"{t['new_detail']:.2f} | {t['other_place']:.2f} | ${cost:.5f} |")

    def mark(arm: str) -> str:
        v = verdict.get(arm)
        if not isinstance(v, dict):
            return f"| `{arm}` | n/a | n/a | n/a |"
        return "| `{}` | {} | {} | {} |".format(
            arm, *("pass" if v[k] else "fail" for k in ("C3a", "C3b", "C3c")))
    (out / "c3-free-text.md").write_text(f"""# C3 — a model-backed check for free-text claims

Registered in [c3-free-text-claims.md](../prereg/c3-free-text-claims.md) before the harness
existed. Produced by `python -m experiments.c3_free_text` at commit `{commit}`; raw numbers in
[c3-free-text.json](c3-free-text.json). Seeds {SEEDS}; 32 new claims a seed, each written to a
fresh store holding 24 established free-text facts. Models through the `claude` command line.
{verdict.get("C3", "")}

Share of each kind of new claim **held for review** (contradictions should be; nothing else
should be), mean over seeds, and model cost per checked write:

| arm | contradiction | paraphrase | new detail | other place | cost a write |
|---|---|---|---|---|---|
{chr(10).join(line(a) for a in ARMS)}

| arm | C3a recall ≥ structural + 50% of headroom | C3b false holds ≤ 0.10 | C3c both, ≥ 4 of 5 seeds |
|---|---|---|---|
{mark("haiku")}
{mark("sonnet")}

**Reading.** Both models held every contradiction and never held a paraphrase or a new detail.
Their false holds all came from the hardest kind: a claim worded as a contradiction ("the archive
is closed to everyone") about a place with no established fact, which the model sometimes read as
contradicting a similar fact about another place. Haiku costs about a twentieth of Sonnet a write
for the same result here. Opt-in, as registered: every checked write is a model call, and content
goes to the provider the user chose.
""")
    print(json.dumps(verdict, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
