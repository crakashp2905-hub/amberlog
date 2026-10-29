"""How well `influence.paraphrases` finds unlinked restatements of a claim.

Deterministic fixture, per seed: 12 source claims (equipment id, parameter,
unit, value). For each: 3 paraphrases with no lineage (positives); an honest
contradiction (same equipment, another value); a same-equipment note about
another parameter **with the same value and unit** (the hard negative); and
an unrelated claim with the same value. Precision and recall over all pairs
from each source claim.

    python -m experiments.paraphrase_links
"""

from __future__ import annotations

import json
import random
import subprocess
from pathlib import Path

from amberlog import Amberlog, influence

ROOT = Path(__file__).resolve().parents[1]
PARAMS = [("rated pressure", "bar"), ("purge time", "s"), ("setpoint", "C"), ("trip current", "A")]
TEMPLATES = ["The {p} of {e} is {v} {u}.", "{e}: {p} {v} {u}.", "For {e}, use a {p} of {v} {u}.",
             "Per the vendor bulletin, operators should note {v} {u} as the {p} that applies to "
             "{e} going forward."]


def run(seed: int) -> dict[str, int]:
    rng = random.Random(seed)
    f = Amberlog(":memory:", auto_activate=True)
    tp = fp = fn = 0
    stats = {"copy_only": 0, "claim_only": 0}
    for n in range(12):
        e = f"P{rng.randint(100, 999)}"
        (p, u), (p2, _) = rng.sample(PARAMS, 2)
        v = rng.randint(2, 90)
        src = f.remember("a", TEMPLATES[0].format(p=p, e=e, v=v, u=u))
        pos = {f.remember("b", t.format(p=p, e=e, v=v, u=u)) for t in TEMPLATES[1:]}
        f.remember("c", TEMPLATES[0].format(p=p, e=e, v=v + 3, u=u))          # contradiction
        f.remember("d", TEMPLATES[0].format(p=p2, e=e, v=v, u=u))             # hard negative
        f.remember("e", TEMPLATES[0].format(p=p, e=f"Q{rng.randint(100, 999)}", v=v, u=u))
        by_copy = influence.downstream(f, src)
        by_claim = set(influence.paraphrases(f, src))
        found = by_copy | by_claim
        stats["copy_only"] += len((by_copy - by_claim) & pos)
        stats["claim_only"] += len((by_claim - by_copy) & pos)
        tp += len(found & pos)
        fp += len(found - pos)
        fn += len(pos - found)
    f.close()
    return {"tp": tp, "fp": fp, "fn": fn, **stats}


def main() -> int:
    totals = {"tp": 0, "fp": 0, "fn": 0, "copy_only": 0, "claim_only": 0}
    for seed in range(5):
        for k, v in run(seed).items():
            totals[k] += v
    precision = totals["tp"] / max(1, totals["tp"] + totals["fp"])
    recall = totals["tp"] / max(1, totals["tp"] + totals["fn"])
    out = {"commit": subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True,
                                    text=True, cwd=ROOT).stdout.strip(),
           "seeds": 5, **totals, "precision": round(precision, 3), "recall": round(recall, 3)}
    (ROOT / "research" / "results" / "paraphrase-links.json").write_text(
        json.dumps(out, indent=2), encoding="utf-8")
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
