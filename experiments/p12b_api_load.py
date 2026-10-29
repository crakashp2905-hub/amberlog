"""P12b: many agents through one `agent-api` process.

P12 measured agents as separate processes, each opening the store, and found
throughput collapses (214 → 4 ops/s from 1 to 100 agents). Its recommendation
was to serve many agents from one process, but that was not measured. This
measures it. One `amberlog agent-api` server runs in its own process. N
agents, each with its own credential, are client threads in another process.
They wait at a barrier, then each runs the same mix over HTTP:

- 30% `remember`;
- 50% `recall`;
- 20% `fetch` then `verify` of a recalled memory (the action-time check).

Rate limiting is turned off (`--rate-limit 0`), because the question is what
the store can do, not what the limiter allows. Latency is per request, as the
client sees it.

    python -m experiments.p12b_api_load            # writes the result
    python -m experiments.p12b_api_load --quick    # 10 agents, prints only

Not pre-registered: an operational measurement on this machine, like P12.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import random
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from experiments.p12_load import SEED_MEMORIES, _pct

ROOT = Path(__file__).resolve().parent.parent
CLI = [sys.executable, "-m", "amberlog"]
AGENT_COUNTS = (1, 10, 50, 100)
OPS_PER_AGENT = 20
TOPICS = ("pump", "valve", "hoist", "compressor", "conveyor", "generator")


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def post(port: int, op: str, body: dict, bearer: str) -> tuple[int, dict]:
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/v1/{op}", data=json.dumps(body).encode(), method="POST",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {bearer}"})
    try:
        with urllib.request.urlopen(request, timeout=600) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read() or b"{}")
    except OSError as exc:              # a dropped connection is an error, not a crash
        return 0, {"error": type(exc).__name__}


def agent_loop(port: int, bearer: str, seed: int, barrier: threading.Barrier,
               out: list[tuple[str, float, int]]) -> None:
    rng = random.Random(seed)
    barrier.wait()
    seen: list[str] = []
    for i in range(OPS_PER_AGENT):
        roll = rng.random()
        topic = rng.choice(TOPICS)
        started = time.perf_counter()
        if roll < 0.3:
            op = "remember"
            status, _ = post(port, "remember", {
                "content": f"{topic} unit {rng.randrange(100)} at site {seed}: "
                           f"observation {i} on the {topic} seal"}, bearer)
        elif roll < 0.8 or not seen:
            op = "recall"
            status, body = post(port, "recall", {"query": f"{topic} seal site", "k": 5}, bearer)
            seen += [m["memory_id"] for m in body.get("memories", [])]
        else:
            op = "fetch+verify"
            memory_id = rng.choice(seen)
            status, _ = post(port, "fetch", {"memory_id": memory_id}, bearer)
            if status == 200:
                status, _ = post(port, "verify", {"memory_id": memory_id}, bearer)
        out.append((op, (time.perf_counter() - started) * 1000.0, status))


def run_one(agents: int) -> dict[str, Any]:
    from amberlog import Amberlog

    with tempfile.TemporaryDirectory() as tmp:
        db = os.path.join(tmp, "load.db")
        seed = Amberlog(db, auto_activate=True)
        rng = random.Random(0)
        for i in range(SEED_MEMORIES):
            topic = rng.choice(TOPICS)
            seed.remember("ag_seed", f"{topic} unit {i} at site {i % 17}: the {topic} seal "
                                     f"was replaced on visit {i}")
        seed.close()
        agents_file = os.path.join(tmp, "agents")
        with open(agents_file, "w") as fh:
            for n in range(agents):
                fh.write(f"ag_{n}:tn_default:{os.urandom(32).hex()}\n")
        port = free_port()
        server = subprocess.Popen(CLI + ["--db", db, "agent-api", "--agents-file", agents_file,
                                         "--port", str(port), "--rate-limit", "0"],
                                  cwd=ROOT, stdout=subprocess.DEVNULL, stderr=open(os.environ.get("P12B_LOG", os.devnull), "w"))
        try:
            deadline = time.time() + 30
            while time.time() < deadline:
                try:
                    urllib.request.urlopen(f"http://127.0.0.1:{port}/v1/health", timeout=1)
                    break
                except Exception:  # noqa: BLE001 - polling a server that is starting
                    time.sleep(0.2)
            bearers = []
            for n in range(agents):
                bearers.append(subprocess.run(
                    CLI + ["--db", db, "agent-api-issue", "--agents-file", agents_file,
                           "--agent", f"ag_{n}", "--ttl", "3600"],
                    capture_output=True, text=True, cwd=ROOT).stdout.strip().splitlines()[-1])
            barrier = threading.Barrier(agents + 1)
            records: list[tuple[str, float, int]] = []
            threads = [threading.Thread(target=agent_loop,
                                        args=(port, bearers[n], n, barrier, records))
                       for n in range(agents)]
            for t in threads:
                t.start()
            barrier.wait()
            started = time.perf_counter()
            for t in threads:
                t.join()
            wall = time.perf_counter() - started
        finally:
            server.terminate()
            server.wait(timeout=30)

    def lat(op: str | None) -> list[float]:
        return [r[1] for r in records if op is None or r[0] == op]

    errors: dict[str, int] = {}
    for op, _, status in records:
        if status != 200:
            errors[f"{op}:{status}"] = errors.get(f"{op}:{status}", 0) + 1
    ok = sum(1 for r in records if r[2] == 200)
    return {
        "agents": agents, "ops": len(records), "ok": ok, "wall_s": wall,
        "ops_per_s": ok / wall if wall else 0.0, "errors": errors,
        "latency_ms": {name: {"p50": _pct(lat(op), 0.5), "p95": _pct(lat(op), 0.95),
                              "p99": _pct(lat(op), 0.99)}
                       for name, op in (("all", None), ("remember", "remember"),
                                        ("recall", "recall"), ("fetch+verify", "fetch+verify"))},
    }


def to_markdown(results: list[dict[str, Any]], commit: str, machine: str) -> str:
    def cell(d: dict[str, float]) -> str:
        return f"{d['p50']:.1f} / {d['p95']:.1f} / {d['p99']:.1f}"

    rows = "\n".join(
        f"| {r['agents']} | {r['ok']}/{r['ops']} | {r['ops_per_s']:.0f} | {cell(r['latency_ms']['all'])} "
        f"| {cell(r['latency_ms']['remember'])} | {cell(r['latency_ms']['recall'])} "
        f"| {cell(r['latency_ms']['fetch+verify'])} | {r['errors'] or 'none'} |" for r in results)
    return f"""# P12b — many agents through one agent-api process

Produced by `python -m experiments.p12b_api_load` at commit `{commit}`; raw numbers
in [p12b-api-load.json](p12b-api-load.json). Machine: {machine}. One `agent-api`
server process on a SQLite store seeded with {SEED_MEMORIES} memories, rate limiting
off. N agents with their own credentials are client threads, {OPS_PER_AGENT} requests
each (30% remember, 50% recall, 20% fetch then verify). An operational measurement,
not pre-registered.

Latencies in ms as the client sees them, p50 / p95 / p99. Throughput is successful
operations per second of wall time (a fetch+verify counts once).

| agents | ok / ops | ops/s | all ops | remember | recall | fetch+verify | errors |
|---|---|---|---|---|---|---|---|
{rows}

Compare [P12](p12-load.md), where each agent was its own process opening the
store: 214 → 31 → 9 → 4 ops/s at 1, 10, 50 and 100 agents on SQLite.
"""


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--quick", action="store_true")
    p.add_argument("--agents", type=int, nargs="+", help="agent counts to run instead")
    p.add_argument("--out", default="p12b-api-load")
    args = p.parse_args(argv)
    counts = (10,) if args.quick else tuple(args.agents or AGENT_COUNTS)
    results = []
    for n in counts:
        r = run_one(n)
        results.append(r)
        print(f"{n:>4} agents: {r['ok']}/{r['ops']} ok, {r['ops_per_s']:.0f} ops/s, "
              f"p50 {r['latency_ms']['all']['p50']:.1f} ms, p99 {r['latency_ms']['all']['p99']:.1f} ms, "
              f"errors {r['errors'] or 'none'}", flush=True)
    if args.quick:
        return 0
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True,
                            text=True, cwd=ROOT).stdout.strip()
    machine = f"{platform.system()} {platform.machine()}, {os.cpu_count()} CPUs, Python {platform.python_version()}"
    out = ROOT / "research" / "results"
    (out / f"{args.out}.json").write_text(json.dumps(
        {"commit": commit, "machine": machine, "results": results}, indent=2) + "\n")
    (out / f"{args.out}.md").write_text(to_markdown(results, commit, machine))
    return 0


if __name__ == "__main__":
    sys.exit(main())
