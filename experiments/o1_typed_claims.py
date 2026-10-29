"""O1 — typed claims catch free-text contradictions without a model (research/prereg/o1-typed-claims.md).

    python -m experiments.o1_typed_claims
"""

from __future__ import annotations

import json
import random
import statistics
import subprocess
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from experiments import c3_free_text as c3  # noqa: E402
from amberlog import Amberlog  # noqa: E402
from amberlog.typedclaims import TypedClaimChecker  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SEEDS = (1, 2, 3, 4, 5)
# The held-out world, exactly as registered.
H_SUBJECTS = ("north gate", "pump house", "main lift", "lab freezer F2", "staff canteen",
              "visitor car park", "rear fire exit", "courier desk")
H_KINDS = {
    "locked": ("The {p} is locked overnight.", "The {p} is never locked overnight.",
               "Overnight, the {p} gets locked.", "The {p} was fitted with a new handle."),
    "staffed": ("The {p} is staffed on weekends.", "The {p} is not staffed on weekends.",
                "On weekends there is staff at the {p}.", "The {p} got a new rota system."),
    "accessible": ("The {p} is wheelchair accessible.", "The {p} is not wheelchair accessible.",
                   "Wheelchair users can reach the {p}.", "The {p} has a ramp near the entrance."),
    "monitored": ("The {p} is covered by CCTV.", "The {p} has no CCTV coverage.",
                  "CCTV covers the {p}.", "The {p} cameras were cleaned last month."),
    "heated": ("The {p} is heated in winter.", "The {p} is unheated in winter.",
               "In winter the {p} has heating.", "The {p} heater is a gas model."),
    "smoking": ("Smoking is permitted at the {p}.", "Smoking is prohibited at the {p}.",
                "People may smoke at the {p}.", "The {p} has a new bin by the door."),
}
WORLDS = {"c3": (c3.PLACES, c3.KINDS), "heldout": (H_SUBJECTS, H_KINDS)}
ARMS = ("structural", "typed", "oracle")


def world(places: tuple[str, ...], kinds: dict[str, tuple[str, ...]], seed: int, tag: str) -> dict[str, Any]:
    """C3's sampling, on any template set."""
    rng = random.Random(f"o1/{tag}/{seed}")
    pairs = [(p, k) for p in places for k in kinds]
    established = rng.sample(pairs, 24)
    unused = [pp for pp in pairs if pp not in established]
    claims = []
    for kind, n in (("contradiction", 8), ("paraphrase", 8), ("new_detail", 8)):
        for place, k in rng.sample(established, n):
            text = kinds[k][{"contradiction": 1, "paraphrase": 2, "new_detail": 3}[kind]]
            claims.append({"type": kind, "text": text.format(p=place)})
    for place, k in rng.sample(unused, 8):
        claims.append({"type": "other_place", "text": kinds[k][1].format(p=place)})
    rng.shuffle(claims)
    return {"established": [kinds[k][0].format(p=p) for p, k in established], "claims": claims}


def held(arm: str, w: dict[str, Any], claim: dict[str, Any]) -> bool:
    if arm == "oracle":
        return claim["type"] == "contradiction"
    f = Amberlog(":memory:", auto_activate=True,
                     claim_checker=TypedClaimChecker() if arm == "typed" else None)
    try:
        for text in w["established"]:
            f.remember("inspector", text, scope="team")
        for i in range(3):
            f.remember("inspector", f"Routine walk-through number {i} completed.", scope="team")
        mid = f.remember("field-agent", claim["text"], scope="team")
        return f.lifecycle_of(mid).value != "active"
    finally:
        f.close()


def run(arm: str, w: dict[str, Any], seed: int) -> dict[str, Any]:
    flags = [held(arm, w, c) for c in w["claims"]]
    by = {t: [f for f, c in zip(flags, w["claims"]) if c["type"] == t]
          for t in ("contradiction", "paraphrase", "new_detail", "other_place")}
    contra = by["contradiction"]
    other = by["paraphrase"] + by["new_detail"] + by["other_place"]
    return {"seed": seed, "recall": sum(contra) / len(contra), "false_holds": sum(other) / len(other),
            "held_by_type": {t: sum(v) / len(v) for t, v in by.items()}}


def main() -> int:
    rows: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for name, (places, kinds) in WORLDS.items():
        rows[name] = {a: [run(a, world(places, kinds, s, name), s) for s in SEEDS] for a in ARMS}
    h = rows["heldout"]
    base = statistics.fmean(r["recall"] for r in h["structural"])
    bar = base + 0.5 * (1 - base)
    rec = statistics.fmean(r["recall"] for r in h["typed"])
    fh = statistics.fmean(r["false_holds"] for r in h["typed"])
    per = sum(r["recall"] >= bar and r["false_holds"] <= 0.10 for r in h["typed"])
    verdict = {"structural_recall": base, "bar": bar, "typed_recall": rec, "typed_false_holds": fh,
               "O1a": rec >= bar, "O1b": fh <= 0.10, "O1c": per >= 4,
               "ceiling_ok": all(r["recall"] <= 1 and r["false_holds"] >= 0
                                 for w in rows.values() for a in w.values() for r in a)}
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True,
                            cwd=ROOT).stdout.strip()
    (ROOT / "research" / "results" / "o1-typed-claims.json").write_text(
        json.dumps({"commit": commit, "rows": rows, "verdict": verdict}, indent=2) + "\n")

    def line(world_rows: dict[str, list[dict[str, Any]]], arm: str) -> str:
        rs = world_rows[arm]
        t = {k: statistics.fmean(r["held_by_type"][k] for r in rs)
             for k in ("contradiction", "paraphrase", "new_detail", "other_place")}
        return (f"| `{arm}` | {t['contradiction']:.2f} | {t['paraphrase']:.2f} | {t['new_detail']:.2f} | "
                f"{t['other_place']:.2f} |")
    table = lambda wr: "\n".join(line(wr, a) for a in ARMS)  # noqa: E731
    mark = lambda k: "pass" if verdict[k] else "fail"  # noqa: E731
    (ROOT / "research" / "results" / "o1-typed-claims.md").write_text(f"""# O1 — typed claims catch free-text contradictions without a model

Registered in [o1-typed-claims.md](../prereg/o1-typed-claims.md) with the held-out templates fixed
before the extractor existed. Produced by `python -m experiments.o1_typed_claims` at commit `{commit}`;
raw numbers in [o1-typed-claims.json](o1-typed-claims.json). Seeds {SEEDS}; 32 new claims a seed, each
written to a fresh store holding 24 established facts. No model call anywhere.

Share of each kind of new claim **held for review** (contradictions should be; nothing else should be):

**Held-out world (the thresholds):**

| arm | contradiction | paraphrase | new detail | other subject |
|---|---|---|---|---|
{table(rows["heldout"])}

| O1a recall ≥ structural + 50% of headroom ({bar:.2f}) | O1b false holds ≤ 0.10 | O1c both, ≥ 4 of 5 seeds |
|---|---|---|---|
| {mark("O1a")} ({rec:.2f}) | {mark("O1b")} ({fh:.3f}) | {mark("O1c")} ({per}/5) |

**C3's world (reported, not a threshold: the author had seen these templates):**

| arm | contradiction | paraphrase | new detail | other subject |
|---|---|---|---|---|
{table(rows["c3"])}

For comparison, C3 measured model checkers on its own world: Haiku and Sonnet each held 1.00 of
contradictions with 0.067 and 0.058 false holds, at a model call per checked write.
""")
    print(json.dumps(verdict, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
