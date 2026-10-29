"""Federation reach: how many stores, how deep, and does a retraction still land?

Model-free and deterministic in outcome (timings vary by machine). For each
topology, a memory is written at an origin, travels by the real `offer` path
(each recipient re-sharing what it imported), and is then retracted at the
origin. Every store's dispatcher is drained until nothing moves. Measured:

- **reach**: stores that received a copy;
- **converged**: stores whose copy is no longer exposable after draining;
- **rounds**: dispatcher passes over all stores until quiet;
- **hop-limit rejections**: retractions stopped by `MAX_HOPS` (recorded, not dropped);
- wall time to build and to converge.

Topologies: a chain of N stores; a star (origin → N); a random mesh of N
stores where each store re-shares to `fanout` others (seeded), with cycles,
which `offer` refuses on the provenance chain.

    python -m experiments.fed_scale            # writes research/results/fed-scale.json
"""

from __future__ import annotations

import json
import platform
import random
import subprocess
import time
from pathlib import Path

from amberlog import Amberlog
from amberlog.dispatcher import Dispatcher
from amberlog.events import EventType
from amberlog.federation import offer
from amberlog.governance.firewall import (Firewall, rule_capabilities_must_be_granted,
                                               rule_must_be_active, rule_restricted_stays_private)
from amberlog.model import EXPOSABLE_STATES
from amberlog.protocol import MAX_HOPS
from amberlog.transport import InProcessTransport

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "research" / "results" / "fed-scale.json"


def store() -> Amberlog:
    return Amberlog(":memory:", firewall=Firewall(rules=(
        rule_must_be_active, rule_restricted_stays_private, rule_capabilities_must_be_granted)))


def run(name: str, n: int, edges_of: "callable", seed: int = 7) -> dict:  # type: ignore[valid-type]
    stores = [store() for _ in range(n)]
    by_id = {s.store_id: s for s in stores}
    started = time.perf_counter()
    origin = stores[0].remember("a", "valve 7 is upstream of the pump", auto_activate=True)
    held = {0: origin}
    frontier = [0]
    rng = random.Random(seed)
    while frontier:
        nxt = []
        for i in frontier:
            for j in edges_of(i, n, rng):
                if j in held:
                    continue
                result = offer(stores[i], held[i], stores[j], f"agent{j}", activate=True)
                if result.imported_memory_id:
                    held[j] = result.imported_memory_id
                    nxt.append(j)
        frontier = nxt
    built = time.perf_counter() - started
    # A correction, not a bare quarantine: `quarantine` withdraws locally and
    # owes nothing, so the first run of this harness moved no retraction at
    # all and reported every copy still live.
    from amberlog import correction

    correction.apply(stores[0], origin, reason="wrong", actor="op")
    transport = InProcessTransport(by_id)
    t0, rounds = time.perf_counter(), 0
    while rounds < 200:
        rounds += 1
        moved = sum(Dispatcher(s, transport).drain().attempted for s in stores)
        if moved == 0:
            break
    converge = time.perf_counter() - t0
    live = [j for j, mid in held.items()
            if stores[j].get(mid).lifecycle_state in EXPOSABLE_STATES]
    rejections = sum(1 for s in stores for e in s.log.read()
                     if '"hop_limit"' in json.dumps(e.payload, default=str))
    for s in stores:
        s.close()
    return {"topology": name, "stores": n, "reach": len(held), "still_exposable": len(live),
            "deepest_live": sorted(live)[:5], "rounds": rounds,
            "hop_limit_rejections": rejections, "build_s": round(built, 2),
            "converge_s": round(converge, 2)}


def chain(i: int, n: int, rng: random.Random) -> list[int]:
    return [i + 1] if i + 1 < n else []


def star(i: int, n: int, rng: random.Random) -> list[int]:
    return list(range(1, n)) if i == 0 else []


def mesh(fanout: int):  # noqa: ANN201
    def edges(i: int, n: int, rng: random.Random) -> list[int]:
        return rng.sample([j for j in range(n) if j != i], min(fanout, n - 1))
    return edges


def main() -> int:
    rows = []
    for n in (2, 5, 10, 16, 17, 20):
        rows.append(run("chain", n, chain))
        print(json.dumps(rows[-1]), flush=True)
    for n in (10, 50, 100):
        rows.append(run("star", n, star))
        print(json.dumps(rows[-1]), flush=True)
    for n in (25, 50, 100):
        rows.append(run("mesh_fanout3", n, mesh(3)))
        print(json.dumps(rows[-1]), flush=True)
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True,
                            text=True, cwd=ROOT).stdout.strip()
    OUT.write_text(json.dumps({"commit": commit, "machine": platform.platform(),
                               "max_hops": MAX_HOPS, "rows": rows}, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
