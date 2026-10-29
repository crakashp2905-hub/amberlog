"""P12 for the recommended deployment: many agents, one server process.

    python -m experiments.p12_http [--agents 1 10 50 100] [--out p12-http.json]

P12 measured one store *process per agent* and recommended the opposite
shape -- agents sharing one process through the agent HTTP API -- without
measuring it. This measures it. One `agent-api` server, in its own process,
serves one store; N agent processes each hold their own credential and run
P12's operation mix over HTTP:

- 30% `remember`; 50% `recall`; 20% `recall` then `verify` on the first hit,
  the action-time check (P12's gated action is `certify` + gate, which the
  HTTP surface does not expose; `verify` is its nearest equivalent there).

Latency is per request as the agent saw it, including HTTP. The server's
default rate limits are kept (20 requests a second per agent, burst 40); the
mix never reaches them, and a 429 would be counted as an error, not hidden.
Credentials are generated per run and never leave the temporary directory.
"""

from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import os
import platform
import random
import secrets
import statistics
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Sequence

from experiments.p12_load import OPS_PER_AGENT, SEED_MEMORIES, _pct

AGENT_COUNTS = (1, 10, 50, 100)


def _serve(path: str, agents_file: str, port_out: Any, issued_out: Any,
           agent_ids: list[str], stop: Any) -> None:
    import threading

    from amberlog import Amberlog
    from amberlog.agent_api import (AgentApi, build_agent_server, encode_credential,
                                         load_agents, register_all)
    from amberlog.service import MemoryService

    fabric = Amberlog(path, auto_activate=True)
    service = MemoryService(fabric=fabric)
    register_all(service, load_agents(agents_file))
    server = build_agent_server(AgentApi(service), port=0)
    issued_out.put({a: encode_credential(service.issue(a, ttl_seconds=3600)) for a in agent_ids})
    port_out.put(server.server_address[1])
    threading.Thread(target=server.serve_forever, daemon=True).start()
    stop.wait()
    server.shutdown()
    server.server_close()
    fabric.close()


def _post(port: int, op: str, body: dict[str, Any], token: str) -> dict[str, Any]:
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/v1/{op}", data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
        method="POST")
    with urllib.request.urlopen(req, timeout=600) as res:
        return json.loads(res.read())


def _agent(port: int, token: str, name: str, ops: int, seed: int, barrier: Any,
           out: Any) -> None:
    rng = random.Random(seed)
    records: list[tuple[str, float, str]] = []
    barrier.wait()
    for i in range(ops):
        roll = rng.random()
        start = time.perf_counter()
        op, error = "", ""
        try:
            if roll < 0.3:
                op = "remember"
                _post(port, "remember", {"content": f"{name} reading {i}: unit "
                                         f"{rng.randint(1, 50)} at {rng.randint(1, 9)} bar"}, token)
            elif roll < 0.8:
                op = "recall"
                _post(port, "recall", {"query": f"unit {rng.randint(1, 50)} bar", "k": 5}, token)
            else:
                op = "recall_verify"
                hits = _post(port, "recall", {"query": f"unit {rng.randint(1, 50)} bar",
                                              "k": 1}, token)["memories"]
                if hits:
                    _post(port, "verify", {"memory_id": hits[0]["memory_id"]}, token)
        except urllib.error.HTTPError as exc:
            error = f"HTTP {exc.code}"
        except Exception as exc:  # noqa: BLE001 - reported, not hidden
            error = type(exc).__name__ + ": " + str(exc)[:80]
        records.append((op, (time.perf_counter() - start) * 1000, error))
    out.put(records)


def run_one(agents: int, ops: int = OPS_PER_AGENT) -> dict[str, Any]:
    from amberlog import Amberlog
    from amberlog.sdk import agent as sdk_agent
    from amberlog.sdk import operator as sdk_operator

    with tempfile.TemporaryDirectory() as tmp:
        path = str(Path(tmp) / "http.db")
        seed = Amberlog(path, auto_activate=True)
        writer = sdk_agent(seed, "ag_seed", "tn_default")
        reviewer = sdk_operator(seed, "op")
        rng = random.Random(0)
        for i in range(SEED_MEMORIES):
            # An agent's write is private to it; sharing to the team is what
            # lets the other agents read the seed corpus, as P12's do.
            reviewer.share(writer.remember(
                f"unit {rng.randint(1, 50)} runs at {rng.randint(1, 9)} bar, logged {i}"), "team")
        seed.close()
        names = [f"ag{i}" for i in range(agents)]
        agents_file = str(Path(tmp) / "agents")
        with open(agents_file, "w", encoding="utf-8") as fh:
            for name in names:
                fh.write(f"{name}:tn_default:{secrets.token_hex(32)}\n")
        ctx = mp.get_context("spawn")
        port_q, issued_q, out = ctx.Queue(), ctx.Queue(), ctx.Queue()
        stop = ctx.Event()
        server = ctx.Process(target=_serve, args=(path, agents_file, port_q, issued_q, names, stop))
        server.start()
        issued = issued_q.get(timeout=120)
        port = port_q.get(timeout=120)
        barrier = ctx.Barrier(agents + 1)
        procs = [ctx.Process(target=_agent, args=(port, issued[n], n, ops, i, barrier, out))
                 for i, n in enumerate(names)]
        for p in procs:
            p.start()
        barrier.wait()
        started = time.perf_counter()
        records: list[tuple[str, float, str]] = []
        for _ in procs:
            records.extend(out.get(timeout=3600))
        wall = time.perf_counter() - started
        for p in procs:
            p.join(timeout=60)
        stop.set()
        server.join(timeout=60)

    ok = [r for r in records if not r[2]]
    errors: dict[str, int] = {}
    for _, _, e in records:
        if e:
            errors[e.split(":")[0]] = errors.get(e.split(":")[0], 0) + 1
    by_op = {}
    for op in ("remember", "recall", "recall_verify"):
        lat = [ms for o, ms, e in ok if o == op]
        by_op[op] = {"n": len(lat), "p50": _pct(lat, 0.5), "p95": _pct(lat, 0.95),
                     "p99": _pct(lat, 0.99)}
    lat = [ms for _, ms, _ in ok]
    return {"backend": "sqlite via agent-api", "agents": agents, "ops": len(records),
            "ok": len(ok), "errors": errors, "wall_s": wall,
            "throughput_ops_s": len(ok) / wall if wall else 0.0,
            "all": {"p50": _pct(lat, 0.5), "p95": _pct(lat, 0.95), "p99": _pct(lat, 0.99),
                    "mean": statistics.mean(lat) if lat else 0.0},
            "by_op": by_op}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--agents", type=int, nargs="*", default=list(AGENT_COUNTS))
    parser.add_argument("--out")
    args = parser.parse_args(argv)
    results = [run_one(n) for n in args.agents]
    import subprocess
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True,
                            text=True).stdout.strip() or "unknown"
    payload = {"experiment": "p12-http", "commit": commit,
               "machine": (f"{platform.system()} {platform.machine()}, {os.cpu_count()} CPUs, "
                           f"Python {platform.python_version()}"),
               "results": results}
    text = json.dumps(payload, indent=2)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
