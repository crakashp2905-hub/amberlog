"""P12-open — latency under open-loop load: requests arrive on a schedule, not when the last one finished.

P12 (`p12_load.py`) is closed-loop: each agent waits for its previous
operation, so a slow store slows the arrivals and hides its own queueing
(coordinated omission). Here arrivals follow a seeded Poisson process at a
fixed offered rate, and latency is measured from the **scheduled** arrival
to completion, so time spent waiting in the queue counts.

The mix is P12's: 30% `remember`, 50% `retrieve`, 20% `certify` +
`ActionGate.authorize`, on one on-disk SQLite store with store limits off, one connection shared by
a pool of threads under the store lock, as `serve` and `agent-api` run it.
Each rate runs for `--seconds`. The knee is the highest offered rate whose
achieved rate is within 5% of offered and whose p99 stays under one second.

    python -m experiments.p12_openloop                # writes research/results/p12-openloop.json
    python -m experiments.p12_openloop --quick        # two rates, prints only

Not pre-registered: an operational measurement on one machine. It sets the
documented performance limits (docs/OPERATIONS.md) and supports no claim
beyond them.
"""

from __future__ import annotations

import argparse
import json
import platform
import random
import statistics
import subprocess
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from amberlog import Amberlog
from amberlog.actions import ActionGate, ActionPolicy, ToolRule

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "research" / "results" / "p12-openloop.json"


def pct(values: list[float], q: float) -> float:
    if not values:
        return float("nan")
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(q * len(ordered)))]


def run_rate(rate: float, seconds: float, seed: int, workers: int) -> dict[str, object]:
    tmp = tempfile.mkdtemp()
    fabric = Amberlog(str(Path(tmp) / "load.db"), auto_activate=True, seed=seed)
    gate = ActionGate(fabric, ActionPolicy(tools={"act": ToolRule("act")},
                                           grants={"agent": frozenset({"act"})}))
    for i in range(200):
        fabric.remember("seed", f"Pump P{i} purge time is {10 + i % 50} seconds at site {i % 7}.",
                        scope="team")
    rng = random.Random(seed)
    lock = threading.Lock()
    latencies: dict[str, list[float]] = {"remember": [], "retrieve": [], "action": []}
    errors: dict[str, int] = {}
    counter = [0]

    def op(kind: str, scheduled: float) -> None:
        try:
            with lock:
                counter[0] += 1
                n = counter[0]
            # One store connection serves every thread, so each call holds the
            # store's lock, exactly as the servers do (`transport._store_lock`).
            # Queueing for it is part of the latency being measured.
            with fabric.lock:
                if kind == "remember":
                    fabric.remember("agent", f"Observation {n}: pump P{n % 200} ran {n % 90} s.",
                                    scope="team")
                elif kind == "retrieve":
                    fabric.retrieve("agent", f"pump P{n % 200} purge time", k=5)
                else:
                    hits = fabric.retrieve("agent", f"pump P{n % 200} purge", k=1).exposed
                    if hits:
                        gate.authorize("act", "agent",
                                       fabric.certify(f"c{n}", [hits[0].id], "agent"))
            done = time.perf_counter()
            with lock:
                latencies[kind].append(done - scheduled)
        except Exception as exc:  # noqa: BLE001 - counted, never dropped
            with lock:
                errors[type(exc).__name__] = errors.get(type(exc).__name__, 0) + 1

    arrivals: list[tuple[float, str]] = []
    t = 0.0
    while t < seconds:
        t += rng.expovariate(rate)
        r = rng.random()
        arrivals.append((t, "remember" if r < 0.3 else "retrieve" if r < 0.8 else "action"))
    start = time.perf_counter()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for offset, kind in arrivals:
            scheduled = start + offset
            delay = scheduled - time.perf_counter()
            if delay > 0:
                time.sleep(delay)
            pool.submit(op, kind, scheduled)
    wall = time.perf_counter() - start
    fabric.close()
    every = [x for v in latencies.values() for x in v]
    completed = len(every)
    return {
        "offered_per_s": rate, "arrivals": len(arrivals), "completed": completed,
        "achieved_per_s": round(completed / wall, 1), "wall_s": round(wall, 2),
        "p50_ms": round(pct(every, 0.50) * 1000, 1), "p95_ms": round(pct(every, 0.95) * 1000, 1),
        "p99_ms": round(pct(every, 0.99) * 1000, 1),
        "mean_ms": round(statistics.fmean(every) * 1000, 1) if every else None,
        "by_op_p99_ms": {k: round(pct(v, 0.99) * 1000, 1) for k, v in latencies.items()},
        "errors": errors,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--rates", default="25,50,100,200,400")
    parser.add_argument("--seconds", type=float, default=8.0)
    parser.add_argument("--workers", type=int, default=16)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--quick", action="store_true")
    args = parser.parse_args(argv)
    rates = [25.0, 100.0] if args.quick else [float(r) for r in args.rates.split(",")]
    rows = []
    for rate in rates:
        row = run_rate(rate, 3.0 if args.quick else args.seconds, args.seed, args.workers)
        rows.append(row)
        print(json.dumps(row))
    sustained = [r for r in rows if r["achieved_per_s"] >= 0.95 * r["offered_per_s"]
                 and r["p99_ms"] < 1000 and not r["errors"]]
    knee = max((r["offered_per_s"] for r in sustained), default=None)
    print(f"highest sustained offered rate: {knee} ops/s")
    if not args.quick:
        commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True,
                                text=True, cwd=ROOT).stdout.strip()
        OUT.write_text(json.dumps({"commit": commit, "machine": platform.platform(),
                                   "python": platform.python_version(),
                                   "config": vars(args), "rows": rows,
                                   "highest_sustained_per_s": knee}, indent=2),
                       encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
