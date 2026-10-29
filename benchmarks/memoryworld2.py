"""INT-01: MemoryWorld 2, changing knowledge — "true at t" vs "believed at τ" (RQ3). Descriptive, no claim.

    python -m benchmarks.memoryworld2

Facts change value over valid time; some are recorded late, and some are
recorded wrong and corrected later. Two kinds of question:

- **valid-at-t**: what was the value at time t, as known now?
- **believed-at-τ**: what would the store have said about time t at log
  position τ, before later recordings and corrections?

Arms: `overwrite` (the latest recorded value, ignoring both times), `valid_time`
(`retrieve(as_of=t)`, the product path), `bitemporal` (the projection replayed to τ
with `incident.replay_until`, then filtered at t), `oracle`. Deterministic, no model.

The point is functional: the store can answer both questions and they differ.
The product has `as_of` for valid time but no `retrieve(known_at=τ)`; the
bitemporal arm goes through the replay helper, which is the gap RQ3 names.
"""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OUT_MD = ROOT / "research" / "results" / "int01-memoryworld2.md"
OUT_JSON = ROOT / "research" / "results" / "int01-memoryworld2.json"
SEEDS = (1, 2, 3, 4, 5)
KEYS, PERIODS, WRONG_SHARE = 20, ((0, 100), (100, 200), (200, None)), 0.3


def run_seed(seed: int) -> dict[str, Any]:
    from amberlog import Amberlog
    from amberlog.incident import replay_until
    from amberlog.model import EXPOSABLE_STATES

    rng = random.Random(seed)
    f = Amberlog(":memory:", auto_activate=True, recognise_copies=False, retrieval="lexical",
                     encrypt_content=False)
    truth: dict[tuple[str, int], int] = {}
    # Writes in a shuffled recording order: (key, period index, value, correct?)
    plan = []
    for k in range(KEYS):
        for p in range(len(PERIODS)):
            value = rng.randint(10, 99)
            truth[(f"rate-{k}", p)] = value
            if rng.random() < WRONG_SHARE:
                plan.append((f"rate-{k}", p, value + rng.randint(1, 9), "wrong"))
                plan.append((f"rate-{k}", p, value, "fix"))
            else:
                plan.append((f"rate-{k}", p, value, "right"))
    rng.shuffle(plan)
    # A correction must come after the wrong value it corrects.
    plan.sort(key=lambda w: (w[0], w[1], w[3] == "fix"))
    rng.shuffle(plan)
    seen_wrong: set[tuple[str, int]] = set()
    ordered, pending = [], []
    for w in plan:
        if w[3] == "fix" and (w[0], w[1]) not in seen_wrong:
            pending.append(w)
            continue
        ordered.append(w)
        if w[3] == "wrong":
            seen_wrong.add((w[0], w[1]))
            ordered += [x for x in pending if (x[0], x[1]) == (w[0], w[1])]
            pending = [x for x in pending if (x[0], x[1]) != (w[0], w[1])]
    ordered += pending
    believed: list[tuple[int, dict[tuple[str, int], int]]] = []
    standing: dict[tuple[str, int], tuple[str, int]] = {}
    try:
        for key, p, value, kind in ordered:
            lo, hi = PERIODS[p]
            if kind == "fix" and (key, p) in standing:
                f.quarantine(standing[(key, p)][0], reason="recorded wrong", actor="auditor",
                             basis="contradicted")
            mid = f.remember("recorder", f"The {key} for period {p} is {value} per cent.", scope="team",
                             structured={"key": key, "period": p, "value": value},
                             valid_from=lo, valid_to=hi)
            standing[(key, p)] = (mid, value)
            believed.append((f.log.head_seq, {kp: v for kp, (_, v) in standing.items()}))

        def period_at(t: int) -> int:
            return next(i for i, (lo, hi) in enumerate(PERIODS) if lo <= t and (hi is None or t < hi))

        def value_from(memories: Any, key: str, t: int) -> int | None:
            best = None
            for m in memories:
                s = m.structured or {}
                if s.get("key") == key and m.lifecycle_state in EXPOSABLE_STATES and m.applies_at(t):
                    if best is None or m.created_at >= best.created_at:
                        best = m
            return best.structured["value"] if best else None

        rows: dict[str, list[bool]] = {f"{q}:{a}": [] for q in ("valid", "believed")
                                       for a in ("overwrite", "valid_time", "bitemporal", "oracle")}
        latest = {}
        for key, p, value, kind in ordered:
            latest[key] = value
        for _ in range(60):
            key, t = f"rate-{rng.randrange(KEYS)}", rng.randrange(0, 300)
            gold_now = truth[(key, period_at(t))]
            got_valid = [m for m in f.retrieve("reader", f"The {key} for period", k=20, min_relevance=0.0,
                                              as_of=t).exposed]
            answers_now = {"overwrite": latest[key], "valid_time": value_from(got_valid, key, t),
                           "bitemporal": value_from(f.state.memories.values(), key, t), "oracle": gold_now}
            for arm, a in answers_now.items():
                rows[f"valid:{arm}"].append(a == gold_now)
            seq, snapshot = rng.choice(believed)
            gold_then = snapshot.get((key, period_at(t)))
            replayed = replay_until(f, seq)
            answers_then = {"overwrite": latest[key], "valid_time": value_from(got_valid, key, t),
                            "bitemporal": value_from(replayed.memories.values(), key, t), "oracle": gold_then}
            for arm, a in answers_then.items():
                rows[f"believed:{arm}"].append(a == gold_then)
    finally:
        f.close()
    return {k: sum(v) / len(v) for k, v in rows.items()}


def main(argv: list[str]) -> int:
    from benchmarks.manifest import Manifest, head
    from benchmarks.manifest import write as write_manifest

    per_seed = {s: run_seed(s) for s in SEEDS}
    table = {k: round(sum(per_seed[s][k] for s in SEEDS) / len(SEEDS), 3) for k in per_seed[SEEDS[0]]}
    commit = head()[:12]
    data = {"commit": commit, "seeds": list(SEEDS), "keys": KEYS, "wrong_share": WRONG_SHARE, "accuracy": table}
    print(json.dumps(data, indent=1))
    if "--no-write" in argv:
        return 0
    OUT_JSON.write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")
    write_manifest(Manifest(
        run_id="int01-memoryworld2", suite="INT-01", arm="all", decision="DESCRIPTIVE", repo_commit=commit,
        reason="descriptive: functional check of bitemporal answers, no improvement claim",
        dataset={"name": "generated", "generator": "benchmarks/memoryworld2.py"}, seeds=list(SEEDS),
        results={"accuracy": table}, cost={"model_usd": 0.0, "model_calls": 0},
        verification={"baseline_registered": True,
                      "oracle_sanity_passed": table["valid:oracle"] == 1.0 and table["believed:oracle"] == 1.0,
                      "holdout_frozen": False, "independent_replicated": False}))
    arms = ("overwrite", "valid_time", "bitemporal", "oracle")
    OUT_MD.write_text(f"""# INT-01 — MemoryWorld 2: true at t vs believed at τ (descriptive)

Produced by `python -m benchmarks.memoryworld2` at commit `{commit}`; seeds {', '.join(map(str, SEEDS))};
{KEYS} facts × 3 validity periods, {int(WRONG_SHARE * 100)}% recorded wrong and corrected later, recordings
in shuffled order. 60 questions of each kind per seed. No model; no claim registered.
Raw numbers: [int01-memoryworld2.json](int01-memoryworld2.json).

| question | overwrite | valid time (`retrieve(as_of=t)`) | bitemporal (replay to τ, then at t) | oracle |
|---|---|---|---|---|
| value at t, as known now | {' | '.join(f"{table['valid:' + a]:.3f}" for a in arms)} |
| value at t, as believed at τ | {' | '.join(f"{table['believed:' + a]:.3f}" for a in arms)} |

## Reading

Valid-time retrieval answers "what was true at t" from the product path. "What did the store
believe at τ" needs the log replayed to τ, which only `incident.replay_until` does today; there is
no `retrieve(known_at=τ)`. That API is the open RQ3 work item, and this harness is its acceptance
test. Overwrite (one value per fact) is the baseline that loses both questions once facts change.
""", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
