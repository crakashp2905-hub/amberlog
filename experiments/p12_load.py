"""P12 — latency and throughput at 10, 50 and 100 simulated agents (plan Task 12).

Each agent is its own **process** with its own `MemoryFabric` on one shared
store, which is the deployment the cross-process freshness work supports. All
agents open the store, wait at a barrier, then run the same mix of operations:

- 30% `remember` (a write, screened);
- 50% `retrieve` (a read, which logs exposure events, so it also writes);
- 20% gated action: `certify` one retrieved memory, then `ActionGate.authorize`
  (re-verifies it and appends an `ActionGated` event).

Latency is per operation, measured inside the agent, and excludes opening the
store. Throughput is operations over the wall time from the barrier to the
last agent finishing. Errors are counted and their kinds reported, never
dropped.

    python -m experiments.p12_load                    # SQLite; writes the result
    MF_BENCH_POSTGRES_URL=postgresql://... python -m experiments.p12_load
    python -m experiments.p12_load --quick            # 10 agents, prints only

Not pre-registered: an operational measurement. It sets no threshold and
supports no scaling claim beyond the numbers it prints on this machine.
"""

from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import os
import platform
import random
import statistics
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any, Sequence

AGENT_COUNTS = (1, 10, 50, 100)  # 1 is the uncontended reference
OPS_PER_AGENT = 20
SEED_MEMORIES = 200


def _pct(values: Sequence[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round(q * (len(ordered) - 1)))))
    return ordered[index]


def _worker(url: str, agent: str, ops: int, seed: int, barrier: Any, out: Any) -> None:
    from memory_fabric import MemoryFabric
    from memory_fabric.actions import ActionGate, ActionPolicy, ToolRule

    rng = random.Random(seed)
    records: list[tuple[str, float, str]] = []
    try:
        fabric = MemoryFabric(url, auto_activate=True, busy_timeout_ms=30_000)
        gate = ActionGate(fabric, ActionPolicy(tools={"act": ToolRule("act")},
                                               grants={agent: frozenset({"act"})}))
    except Exception as exc:  # noqa: BLE001 - reported, not hidden
        barrier.wait()
        out.put([("open", 0.0, type(exc).__name__)])
        return
    barrier.wait()
    for i in range(ops):
        roll = rng.random()
        start = time.perf_counter()
        op, error = "", ""
        try:
            if roll < 0.3:
                op = "remember"
                fabric.remember(agent, f"{agent} reading {i}: unit {rng.randint(1, 50)} at "
                                       f"{rng.randint(1, 9)} bar")
            elif roll < 0.8:
                op = "retrieve"
                fabric.retrieve(agent, f"unit {rng.randint(1, 50)} bar", k=5)
            else:
                op = "gated_action"
                hits = fabric.retrieve(agent, f"unit {rng.randint(1, 50)} bar", k=1).exposed
                if hits:
                    cert = fabric.certify("c", [hits[0].id], agent)
                    gate.authorize("act", agent, cert)
        except Exception as exc:  # noqa: BLE001 - reported, not hidden
            error = type(exc).__name__ + ": " + str(exc)[:80]
        records.append((op, (time.perf_counter() - start) * 1000, error))
    fabric.close()
    out.put(records)


def _prepare(backend: str, base_url: str | None) -> tuple[str, Any]:
    from memory_fabric import MemoryFabric

    if backend == "sqlite":
        tmp = tempfile.TemporaryDirectory()
        url = str(Path(tmp.name) / "load.db")
        cleanup: Any = tmp
    else:
        import psycopg

        name = f"mf_load_{uuid.uuid4().hex[:10]}"
        with psycopg.connect(base_url, autocommit=True) as conn:
            conn.execute(f"CREATE DATABASE {name}")
        url = base_url.rpartition("/")[0] + "/" + name
        cleanup = (base_url, name)
    fabric = MemoryFabric(url, auto_activate=True)
    rng = random.Random(0)
    for i in range(SEED_MEMORIES):
        fabric.remember(f"seed{i % 7}", f"unit {rng.randint(1, 50)} runs at {rng.randint(1, 9)} bar, "
                                        f"logged {i}")
    fabric.close()
    return url, cleanup


def _cleanup(backend: str, cleanup: Any) -> None:
    if backend == "sqlite":
        cleanup.cleanup()
        return
    import psycopg

    base_url, name = cleanup
    with psycopg.connect(base_url, autocommit=True) as conn:
        conn.execute(f"DROP DATABASE IF EXISTS {name} WITH (FORCE)")


def run_one(backend: str, agents: int, base_url: str | None = None,
            ops: int = OPS_PER_AGENT) -> dict[str, Any]:
    url, cleanup = _prepare(backend, base_url)
    ctx = mp.get_context("spawn")
    barrier = ctx.Barrier(agents + 1)
    out = ctx.Queue()
    procs = [ctx.Process(target=_worker, args=(url, f"ag{i}", ops, i, barrier, out))
             for i in range(agents)]
    for p in procs:
        p.start()
    barrier.wait()
    started = time.perf_counter()
    records: list[tuple[str, float, str]] = []
    for _ in procs:
        records.extend(out.get(timeout=1800))
    wall = time.perf_counter() - started
    for p in procs:
        p.join(timeout=60)
    _cleanup(backend, cleanup)

    ok = [r for r in records if not r[2]]
    errors: dict[str, int] = {}
    for _, _, e in records:
        if e:
            errors[e.split(":")[0]] = errors.get(e.split(":")[0], 0) + 1
    by_op: dict[str, Any] = {}
    for op in ("remember", "retrieve", "gated_action"):
        lat = [ms for o, ms, e in ok if o == op]
        by_op[op] = {"n": len(lat), "p50": _pct(lat, 0.5), "p95": _pct(lat, 0.95),
                     "p99": _pct(lat, 0.99)}
    lat = [ms for _, ms, _ in ok]
    return {
        "backend": backend, "agents": agents, "ops": len(records), "ok": len(ok),
        "errors": errors, "wall_s": wall, "throughput_ops_s": len(ok) / wall if wall else 0.0,
        "all": {"p50": _pct(lat, 0.5), "p95": _pct(lat, 0.95), "p99": _pct(lat, 0.99),
                "mean": statistics.mean(lat) if lat else 0.0},
        "by_op": by_op,
    }


def to_markdown(results: list[dict[str, Any]], commit: str, machine: str) -> str:
    rows = []
    for r in results:
        b = r["by_op"]
        rows.append(
            f"| {r['backend']} | {r['agents']} | {r['ok']}/{r['ops']} | {r['throughput_ops_s']:.0f} "
            f"| {r['all']['p50']:.1f} / {r['all']['p95']:.1f} / {r['all']['p99']:.1f} "
            f"| {b['remember']['p50']:.1f} / {b['remember']['p95']:.1f} / {b['remember']['p99']:.1f} "
            f"| {b['retrieve']['p50']:.1f} / {b['retrieve']['p95']:.1f} / {b['retrieve']['p99']:.1f} "
            f"| {b['gated_action']['p50']:.1f} / {b['gated_action']['p95']:.1f} / {b['gated_action']['p99']:.1f} "
            f"| {', '.join(f'{k}: {v}' for k, v in r['errors'].items()) or 'none'} |")
    return f"""# P12 — latency and throughput at 10, 50 and 100 agents

Produced by `python -m experiments.p12_load` at commit `{commit}`; raw numbers
in [p12-load.json](p12-load.json). Machine: {machine}. One process per agent,
{OPS_PER_AGENT} operations each, on one shared store holding {SEED_MEMORIES}
memories at the start. An operational measurement: no threshold, no
pre-registration.

Latencies in ms, shown as p50 / p95 / p99. Throughput is successful operations
per second of wall time.

| backend | agents | ok / ops | ops/s | all ops | remember | retrieve | gated action | errors |
|---|---|---|---|---|---|---|---|---|
{chr(10).join(rows)}

**How to read this.** Every write takes the store's single write lock: SQLite's
database lock, or Postgres's `LOCK TABLE events IN EXCLUSIVE MODE`, which keeps
`seq` gapless and the hash chain ordered. A retrieve also writes, because it
logs the exposure decisions value estimation depends on. So added agents queue
on that lock, and **throughput does not scale with agent count**. The tail
latencies show the queue. Nothing here supports a linear-scaling claim, and none
is made. More agents than cores (here {os.cpu_count()}) also measures CPU
contention, not only the store.

**Supported workload, stated from these numbers only:** tens of agents on one
store, with tail latency in the range shown. A workload needing higher write
throughput needs a store design without the single ordered log, and the
roadmap gates that on measured need.
"""


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--quick", action="store_true")
    args = parser.parse_args(argv)
    counts = (10,) if args.quick else AGENT_COUNTS
    backends = ["sqlite"]
    pg = os.environ.get("MF_BENCH_POSTGRES_URL")
    if pg:
        backends.append("postgres")
    results = [run_one(b, n, pg) for b in backends for n in counts]
    print(json.dumps(results, indent=2))
    if not args.quick:
        import subprocess
        commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True,
                                text=True).stdout.strip() or "unknown"
        machine = (f"{platform.system()} {platform.machine()}, {os.cpu_count()} CPUs, "
                   f"Python {platform.python_version()}")
        out = Path(__file__).resolve().parent.parent / "research" / "results"
        (out / "p12-load.json").write_text(json.dumps(
            {"commit": commit, "machine": machine, "results": results}, indent=2) + "\n")
        (out / "p12-load.md").write_text(to_markdown(results, commit, machine))
    return 0


if __name__ == "__main__":
    sys.exit(main())
