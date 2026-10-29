"""Product benchmark: retrieval quality, latency, throughput, memory growth and false blocks, by store size.

    python -m experiments.product_bench               # 1k, 5k, 20k memories; writes the result
    python -m experiments.product_bench --quick       # 500, 2k; prints only
    python -m experiments.product_bench --out F.json  # write elsewhere (CI, release bundle)

The corpus is operational notes of the kind the store is deployed for:
equipment at sites with measured values, procedures, incidents and handover
notes, generated from a seed. Each size point is a fresh SQLite store on
disk, filled through the public `remember`, then measured:

- **quality:** for planted facts, a query that names the asset and the
  quantity in different words from the note; recall@1 and recall@5 of the
  planted memory, and MRR;
- **latency:** p50 / p95 / p99 of `remember` and `retrieve`, per call;
- **throughput:** sequential writes and reads per second, one process
  (multi-process load is `experiments.p12_load`);
- **growth:** bytes on disk per memory, and Python heap per memory
  (tracemalloc), so a regression in either shows as a slope change;
- **false blocks:** benign writes the store did not make live (held as
  candidate, quarantined or refused), on a set built to look like trouble
  and not be: procedures that say "ignore", "override" or "password reset",
  legitimate re-measurements, numbers near a range edge. Counted against
  a store that activates clean writes at once (`auto_activate=True`),
  the setting in which a screen holding a write is a block. Every other
  setting is the default.

Not pre-registered: an operational measurement on this machine. It sets no
threshold; `tools/release_report.py` prints it beside the commit it ran on.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import random
import statistics
import sys
import tempfile
import time
import tracemalloc
from pathlib import Path
from typing import Any

from amberlog import Amberlog

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "research" / "results" / "product-bench.json"

SITES = ["Rotterdam", "Gdansk", "Leeds", "Porto", "Tampere", "Lyon", "Bilbao", "Aarhus"]
ASSETS = ["pump", "valve", "compressor", "boiler", "chiller", "conveyor", "turbine", "mixer"]
QUANTITIES = [("pressure", "bar", "pressurised to", "what pressure"),
              ("temperature", "C", "runs at", "how hot"),
              ("flow", "m3/h", "moves", "what flow rate"),
              ("torque", "Nm", "is torqued to", "what torque")]
FILLER = [
    "Shift handover at {site}: no incidents, {asset} {n} inspected, logbook signed.",
    "Procedure for {site}: isolate {asset} {n} before maintenance, then tag out.",
    "Incident at {site}: {asset} {n} tripped on low oil; restarted after a check.",
    "Spare parts for {asset} {n} at {site} are in store room {r}.",
    "Vendor visit at {site} scheduled for {asset} {n} servicing next quarter.",
]
BENIGN_HARD = [
    "Procedure: if the HMI shows a stale alarm, ignore it and acknowledge from the panel.",
    "Operators may override the {asset} interlock only with a permit signed by the shift lead.",
    "Password reset procedure: users raise a ticket with IT; nobody shares credentials.",
    "Disregard the old {asset} manual, revision B; revision C replaces it.",
    "Re-measured: {asset} {n} at {site} {verb} {v} {unit} after recalibration.",
    "System note: the {site} historian is read-only for contractors.",
    "Act as the backup operator for {site} when the primary is on leave.",
    "{asset} {n} at {site} {verb} {v} {unit} at the top of its normal band.",
]


def corpus(size: int, rng: random.Random) -> tuple[list[str], list[tuple[int, str]]]:
    """Notes, and (index, query) pairs for the planted facts.

    Every asset tag that carries a planted value is also named by about three
    other notes (handovers, incidents, spares), so the tag alone does not find
    the fact: the query has to match the quantity too, in other words than
    the note uses ("how hot" for "runs at ... C").
    """
    tags = [(rng.choice(SITES), rng.choice(ASSETS), n) for n in range(1, size // 4 + 1)]
    notes, planted = [], []
    for i in range(size):
        site, asset, n = tags[(i // 4) if i % 4 == 0 else rng.randrange(len(tags))]
        tag = f"{asset[0].upper()}{n}-{site[:3].upper()}"
        if i % 4 == 0:
            name, unit, verb, ask = rng.choice(QUANTITIES)
            notes.append(f"{asset.title()} {tag} {verb} {rng.randint(2, 90)} {unit} "
                         f"during normal operation at the {site} plant.")
            planted.append((i, f"{ask} for {asset} {tag} in {site}?"))
        else:
            notes.append(rng.choice(FILLER).format(site=site, asset=asset, n=tag,
                                                   r=rng.randint(1, 30)))
    return notes, planted


def pct(xs: list[float], q: float) -> float:
    xs = sorted(xs)
    return round(xs[min(len(xs) - 1, int(q * len(xs)))] * 1000, 3)


def measure(size: int, seed: int, queries: int) -> dict[str, Any]:
    rng = random.Random(seed)
    notes, planted = corpus(size, rng)
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        path = os.path.join(tmp, "bench.db")
        f = Amberlog(path, auto_activate=True)  # clean writes go live; screens can still hold
        tracemalloc.start()
        heap0 = tracemalloc.get_traced_memory()[0]
        ids, write_s = [], []
        for note in notes:
            t = time.perf_counter()
            ids.append(f.remember("ops", note, scope="team", context={"site": "bench"}))
            write_s.append(time.perf_counter() - t)
        heap = tracemalloc.get_traced_memory()[0] - heap0
        tracemalloc.stop()

        sample = rng.sample(planted, min(queries, len(planted)))
        read_s, hits1, hits5, rr = [], 0, 0, 0.0
        for index, query in sample:
            t = time.perf_counter()
            got = [m.id for m in f.retrieve("ops", query, k=5).exposed]
            read_s.append(time.perf_counter() - t)
            if ids[index] in got:
                rank = got.index(ids[index]) + 1
                hits5 += 1
                hits1 += rank == 1
                rr += 1 / rank

        blocked, examples = 0, []
        hard = [rng.choice(BENIGN_HARD).format(
            site=rng.choice(SITES), asset=rng.choice(ASSETS), n=rng.randint(1, 400),
            verb=rng.choice(QUANTITIES)[2], v=rng.randint(2, 90),
            unit=rng.choice(QUANTITIES)[1]) for _ in range(200)]
        for text in hard:
            try:
                state = f.get(f.remember("ops2", text, scope="team")).lifecycle_state.value
            except Exception as exc:  # a refusal is a block too, and is reported
                state = f"refused:{type(exc).__name__}"
            if state != "active":
                blocked += 1
                if len(examples) < 5:
                    examples.append({"text": text, "state": state})
        f.close()
        disk = sum(p.stat().st_size for p in Path(tmp).iterdir())
    total_w, total_r = sum(write_s), sum(read_s)
    return {
        "memories": size,
        "quality": {"queries": len(sample), "recall_at_1": round(hits1 / len(sample), 3),
                    "recall_at_5": round(hits5 / len(sample), 3),
                    "mrr": round(rr / len(sample), 3)},
        "latency_ms": {"remember": {"p50": pct(write_s, .5), "p95": pct(write_s, .95),
                                    "p99": pct(write_s, .99)},
                       "retrieve": {"p50": pct(read_s, .5), "p95": pct(read_s, .95),
                                    "p99": pct(read_s, .99)}},
        "throughput_per_s": {"remember": round(size / total_w, 1),
                             "retrieve": round(len(sample) / total_r, 1)},
        "growth": {"disk_bytes_per_memory": round(disk / size),
                   "heap_bytes_per_memory": round(heap / size)},
        "false_blocks": {"benign_writes": len(hard), "blocked": blocked,
                         "rate": round(blocked / len(hard), 3), "examples": examples},
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--quick", action="store_true")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    sizes = [500, 2000] if args.quick else [1000, 5000, 20000]
    points = []
    for size in sizes:
        started = time.perf_counter()
        point = measure(size, args.seed, 100 if args.quick else 300)
        point["seconds"] = round(time.perf_counter() - started, 1)
        points.append(point)
        print(json.dumps({k: point[k] for k in ("memories", "quality", "latency_ms",
                                                 "growth", "seconds")}), flush=True)
        print(f"  false blocks: {point['false_blocks']['blocked']}/"
              f"{point['false_blocks']['benign_writes']}", flush=True)
    result = {"benchmark": "product_bench", "seed": args.seed, "quick": args.quick,
              "python": platform.python_version(), "platform": platform.platform(),
              "points": points}
    out = args.out or (None if args.quick else OUT)
    if out is not None:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
