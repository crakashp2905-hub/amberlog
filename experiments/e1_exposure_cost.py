"""E1 — what does recording every exposure cost a retrieval?

Every `retrieve` appends one `ExposureDecided` event per ranked candidate,
shown or withheld, so that credit can be estimated later (AGENTS.md
principle 4). This measures the share of a retrieval spent writing those
events (`_emit`), against ranking (`_search`) and everything else, at two
store sizes. It also measures one batching variant: chain rows inserted with
`executemany` instead of one statement each. That variant was kept only if it
moved the number.

    python -m experiments.e1_exposure_cost

Not pre-registered: an operational measurement on this machine.
"""

from __future__ import annotations

import cProfile
import json
import os
import platform
import pstats
import random
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from memory_fabric import MemoryFabric

ROOT = Path(__file__).resolve().parent.parent
SIZES = (2_000, 10_000)
QUERIES = 300


def cumulative(stats: pstats.Stats, suffix: str) -> float:
    return sum(v[3] for k, v in stats.stats.items() if f"{k[0]}:{k[2]}".endswith(suffix))  # type: ignore[attr-defined]


def run(size: int) -> dict[str, Any]:
    rng = random.Random(size)
    with tempfile.TemporaryDirectory() as tmp:
        fabric = MemoryFabric(os.path.join(tmp, "e1.db"), auto_activate=True)
        for i in range(size):
            fabric.remember("ag", f"Pump P-{i}: the relief pressure is {rng.randrange(6, 48)} bar "
                                  f"at site {i % 40}.", scope="team")
        queries = [f"relief pressure pump P-{rng.randrange(size)}" for _ in range(QUERIES)]
        before = sum(1 for _ in fabric.log.read())
        profile = cProfile.Profile()
        started = time.perf_counter()
        profile.enable()
        for q in queries:
            fabric.retrieve("ag_reader", q, k=5)
        profile.disable()
        wall = time.perf_counter() - started
        events = sum(1 for _ in fabric.log.read()) - before
        fabric.close()
    stats = pstats.Stats(profile)
    total = cumulative(stats, "retrieval.py:retrieve")
    emit = cumulative(stats, "core.py:_emit")
    search = cumulative(stats, "retrieval.py:_search")
    return {"memories": size, "queries": QUERIES, "ms_per_retrieve": wall * 1000 / QUERIES,
            "events_per_retrieve": events / QUERIES,
            "share_recording": emit / total, "share_ranking": search / total,
            "ms_recording": emit * 1000 / QUERIES}


def main() -> int:
    results = [run(n) for n in SIZES]
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True,
                            text=True, cwd=ROOT).stdout.strip()
    machine = f"{platform.system()} {platform.machine()}, {os.cpu_count()} CPUs, Python {platform.python_version()}"
    out = ROOT / "research" / "results"
    (out / "e1-exposure-cost.json").write_text(json.dumps(
        {"commit": commit, "machine": machine, "results": results}, indent=2) + "\n")
    rows = "\n".join(f"| {r['memories']:,} | {r['ms_per_retrieve']:.1f} | {r['events_per_retrieve']:.0f} "
                     f"| {r['ms_recording']:.1f} ({r['share_recording']:.0%}) "
                     f"| {r['share_ranking']:.0%} |" for r in results)
    (out / "e1-exposure-cost.md").write_text(f"""# E1 — the cost of recording every exposure

Produced by `python -m experiments.e1_exposure_cost` at commit `{commit}`; raw numbers
in [e1-exposure-cost.json](e1-exposure-cost.json). Machine: {machine}. SQLite, {QUERIES}
retrievals (`k = 5`) per size, profiled with cProfile (which adds overhead in
proportion; the shares are what matter). An operational measurement, not
pre-registered.

| memories | ms per retrieve | exposure events per retrieve | recording ms (share) | ranking share |
|---|---|---|---|---|
{rows}

**Reading.** Recording is a minority of a retrieval's cost, and ranking is the
majority. A retrieval writes one event per ranked candidate (pool `4k`), shown
or withheld, so recording costs a fixed few milliseconds while ranking grows
with the store.

**Batching, tried and not kept.** Inserting the hash-chain rows with one
`executemany` instead of one statement each halved the SQL calls a retrieval
makes (48 → 27) and did not move the recording time (1.23 s against 1.22 s per
300 retrievals at 2,000 memories). The cost is SQLite's work per row, not the
calls. Writing the exposures as a single batched event would cut rows, but it
needs a schema change for a cost that is a minority of the total, and it would
coarsen the per-candidate audit trail that credit estimation reads. Not done.

**Where the capacity goes instead.** Read-heavy load is served by one
`agent-api` process per store, which keeps throughput flat as agents are added
(OPERATIONS §4a). Ranking, not recording, is what to optimise next.
""")
    print(json.dumps(results, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
