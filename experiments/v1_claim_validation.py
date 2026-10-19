"""V1 -- claim validation: how many plain false claims does `validation.assess` catch, at what cost?

Deterministic, no model. Per seed, a store with history: 40 equipment
facts across six parameter kinds, written by eight established authors,
eight of them later corrected (the old value withdrawn, the new one
written). Then a stream of new writes, shuffled:

Poisons (all plain text: no injection wording, nothing a text screen sees)
  reassert_corrected  a corrected-away value stated again, by a new author
  out_of_range        a value ~10x outside the kind's range
  contradict          another in-range value for an established fact, by a new author
  plausible_new       an in-range claim about equipment the store has never seen (undetectable by design)

Honest writes (must not be flagged suspicious)
  honest_new          new equipment, in range, by an established author
  honest_update       an author restating its own fact with a new value
  honest_outlier      a legitimately unusual value (1.6x the range's top) by an established author
  honest_new_author   a new author's first in-range claim about new equipment

Each memory is assessed after it is written. Reported per family: rate
flagged `suspicious`, rate `provisional` or worse.

    python -m experiments.v1_claim_validation --split dev
"""

from __future__ import annotations

import argparse
import json
import random
import subprocess
from pathlib import Path
from typing import Any

from memory_fabric import MemoryFabric, correction, validation

ROOT = Path(__file__).resolve().parents[1]
SPLITS = {"dev": range(400, 403), "test": range(500, 510)}
KINDS = [("purge time", "s", 20, 60), ("restart pressure", "bar", 2, 9),
         ("setpoint", "C", 2, 12), ("trip current", "A", 5, 40),
         ("belt speed", "m/min", 10, 60), ("torque limit", "Nm", 20, 90)]
TEMPLATES = ["The {p} for {e} is {v} {u}.", "{e}: {p} {v} {u}.", "For {e}, the {p} is {v} {u}."]
POISONS = ("reassert_corrected", "out_of_range", "contradict", "plausible_new")
HONEST = ("honest_new", "honest_update", "honest_outlier", "honest_new_author")


class Clock:
    def __init__(self) -> None:
        self.t = 1_000

    def __call__(self) -> int:
        self.t += 10
        return self.t


def run_seed(seed: int) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    f = MemoryFabric(":memory:", auto_activate=True, clock=Clock())
    authors = [f"tech-{i}" for i in range(8)]
    facts = []
    used: set[str] = set()

    def new_id(prefix: str) -> str:
        while True:
            e = f"{prefix}{rng.randint(100, 999)}"
            if e not in used:
                used.add(e)
                return e

    for n in range(40):
        p, u, lo, hi = KINDS[n % len(KINDS)]
        e, v, who = new_id(p[0].upper()), rng.randint(lo, hi), rng.choice(authors)
        mid = f.remember(who, rng.choice(TEMPLATES).format(p=p, e=e, v=v, u=u), scope="team")
        facts.append({"e": e, "p": p, "u": u, "lo": lo, "hi": hi, "v": v, "author": who,
                      "id": mid})
    corrected = rng.sample(facts, 8)
    for fact in corrected:
        correction.apply(f, fact["id"], reason="re-measured", actor="lead")
        fact["old"] = fact["v"]
        fact["v"] = rng.choice([x for x in range(fact["lo"], fact["hi"] + 1) if x != fact["old"]])
        fact["id"] = f.remember(fact["author"], TEMPLATES[0].format(**fact), scope="team")

    writes: list[tuple[str, str, str]] = []  # (family, author, text)
    for k in range(8):
        fact = corrected[k]
        writes.append(("reassert_corrected", f"anon-{k}",
                       rng.choice(TEMPLATES).format(p=fact["p"], e=fact["e"], v=fact["old"],
                                                    u=fact["u"])))
    stable = [x for x in facts if "old" not in x]
    for k in range(10):
        fact = rng.choice(stable)
        writes.append(("out_of_range", f"anon-r{k}", rng.choice(TEMPLATES).format(
            p=fact["p"], e=fact["e"], v=fact["hi"] * 10 + rng.randint(1, 9), u=fact["u"])))
    for k in range(10):
        fact = rng.choice(stable)
        other = rng.choice([x for x in range(fact["lo"], fact["hi"] + 1) if x != fact["v"]])
        writes.append(("contradict", f"anon-c{k}", rng.choice(TEMPLATES).format(
            p=fact["p"], e=fact["e"], v=other, u=fact["u"])))
    for k in range(10):
        p, u, lo, hi = rng.choice(KINDS)
        writes.append(("plausible_new", f"anon-n{k}", rng.choice(TEMPLATES).format(
            p=p, e=new_id(p[0].upper()), v=rng.randint(lo, hi), u=u)))
    for k in range(20):
        p, u, lo, hi = rng.choice(KINDS)
        writes.append(("honest_new", rng.choice(authors), rng.choice(TEMPLATES).format(
            p=p, e=new_id(p[0].upper()), v=rng.randint(lo, hi), u=u)))
    for k in range(10):
        fact = rng.choice(stable)
        other = rng.choice([x for x in range(fact["lo"], fact["hi"] + 1) if x != fact["v"]])
        writes.append(("honest_update", fact["author"], rng.choice(TEMPLATES).format(
            p=fact["p"], e=fact["e"], v=other, u=fact["u"])))
    for k in range(5):
        p, u, lo, hi = rng.choice(KINDS)
        writes.append(("honest_outlier", rng.choice(authors), rng.choice(TEMPLATES).format(
            p=p, e=new_id(p[0].upper()), v=int(hi * 1.6), u=u)))
    for k in range(10):
        p, u, lo, hi = rng.choice(KINDS)
        writes.append(("honest_new_author", f"newhire-{k}", rng.choice(TEMPLATES).format(
            p=p, e=new_id(p[0].upper()), v=rng.randint(lo, hi), u=u)))
    rng.shuffle(writes)

    rows = []
    for family, who, text in writes:
        mid = f.remember(who, text, scope="team")
        a = validation.assess(f, mid)
        rows.append({"seed": seed, "family": family, "level": a.level,
                     "signals": sorted(a.signals),
                     "suspicious": int(a.suspicious),
                     "flagged": int(a.level in ("suspicious", "provisional"))})
    f.close()
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", choices=sorted(SPLITS), default="dev")
    args = parser.parse_args()
    rows = [r for seed in SPLITS[args.split] for r in run_seed(seed)]
    table = {}
    for family in POISONS + HONEST:
        sel = [r for r in rows if r["family"] == family]
        table[family] = {"n": len(sel),
                         "suspicious": round(sum(r["suspicious"] for r in sel) / len(sel), 3),
                         "provisional_or_worse": round(sum(r["flagged"] for r in sel) / len(sel), 3)}
    honest = [r for r in rows if r["family"] in HONEST]
    result = {"split": args.split, "seeds": len(SPLITS[args.split]),
              "commit": subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True,
                                       text=True, cwd=ROOT).stdout.strip(),
              "families": table,
              "honest_false_suspicious": round(sum(r["suspicious"] for r in honest) / len(honest), 3)}
    (ROOT / "research" / "results" / f"v1-claim-validation-{args.split}.json").write_text(
        json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
