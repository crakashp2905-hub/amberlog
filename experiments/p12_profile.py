"""Where P12's latency goes: one agent profiled among N contending agents.

    python -m experiments.p12_profile --agents 10 [--out p12-profile.json]

P12 measured the collapse and said its cause was "observed, not isolated".
This isolates it. It runs P12's workload unchanged (`p12_load._worker`) in
N-1 processes and, in one more, the same workload under `cProfile`. The report
attributes that agent's operation time to the functions that dominate it, plus
two counters read directly: how many full log replays it ran, and how many
events those replays re-read.
"""

from __future__ import annotations

import argparse
import cProfile
import io
import json
import multiprocessing as mp
import pstats
import sys
import time
from pathlib import Path
from typing import Any

from experiments import p12_load as P


def _profiled(url: str, agent: str, ops: int, seed: int, barrier: Any, out: Any) -> None:
    from memory_fabric import fabric as F

    counters = {"replays": 0, "replay_events": 0, "catch_ups": 0, "catch_up_events": 0}
    original_replay = F.MemoryFabric._replay

    def counted_replay(self: Any) -> None:
        counters["replays"] += 1
        counters["replay_events"] += self.log.head_seq
        original_replay(self)

    F.MemoryFabric._replay = counted_replay  # type: ignore[method-assign]
    original_catch_up = getattr(F.MemoryFabric, "_catch_up", None)
    if original_catch_up is not None:
        def counted_catch_up(self: Any) -> int:
            n = original_catch_up(self)
            counters["catch_ups"] += 1
            counters["catch_up_events"] += n
            return n
        F.MemoryFabric._catch_up = counted_catch_up  # type: ignore[method-assign]

    inner: Any = mp.Queue() if False else _ListQueue()
    profile = cProfile.Profile()
    started = time.perf_counter()
    profile.enable()
    P._worker(url, agent, ops, seed, barrier, inner)
    profile.disable()
    wall = time.perf_counter() - started
    stream = io.StringIO()
    stats = pstats.Stats(profile, stream=stream).sort_stats("cumulative")
    rows = []
    for (filename, line, name), (cc, nc, tt, ct, _callers) in stats.stats.items():  # type: ignore[attr-defined]
        if "memory_fabric" in filename or name in ("execute", "fetchone", "fetchall"):
            rows.append({"function": f"{Path(filename).name}:{line}:{name}",
                         "calls": nc, "cumulative_s": round(ct, 4), "own_s": round(tt, 4)})
    rows.sort(key=lambda r: -r["cumulative_s"])
    records = inner.items[0] if inner.items else []
    out.put({"records": records, "counters": counters, "wall_s": wall, "top": rows[:25]})


class _ListQueue:
    def __init__(self) -> None:
        self.items: list[Any] = []

    def put(self, item: Any) -> None:
        self.items.append(item)


def run(agents: int, ops: int = P.OPS_PER_AGENT) -> dict[str, Any]:
    url, cleanup = P._prepare("sqlite", None)
    ctx = mp.get_context("spawn")
    barrier = ctx.Barrier(agents + 1)
    out = ctx.Queue()
    procs = [ctx.Process(target=P._worker, args=(url, f"ag{i}", ops, i, barrier, out))
             for i in range(agents - 1)]
    procs.append(ctx.Process(target=_profiled,
                             args=(url, f"ag{agents - 1}", ops, agents - 1, barrier, out)))
    for p in procs:
        p.start()
    barrier.wait()
    profiled: dict[str, Any] = {}
    for _ in procs:
        item = out.get(timeout=1800)
        if isinstance(item, dict):
            profiled = item
    for p in procs:
        p.join(timeout=60)
    P._cleanup("sqlite", cleanup)
    op_ms = sum(ms for _, ms, _ in profiled.get("records", []))
    return {"experiment": "p12-profile", "agents": agents, "ops": ops,
            "profiled_op_ms_total": round(op_ms, 1), **profiled}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--agents", type=int, default=10)
    parser.add_argument("--out")
    args = parser.parse_args(argv)
    result = run(args.agents)
    text = json.dumps(result, indent=2)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
