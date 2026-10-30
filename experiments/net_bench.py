"""Networked deployment: latency, a partition, an outage and concurrent corrections.

Three `memory_fabric federate` servers, each with its own database, talking
only over HTTP through TCP proxies (`experiments/multihost.py`). At each
latency the run covers:
- correction propagation A → B → C;
- an outage of C;
- a partition of B–C with both servers up;
- two corrections at once at different stores.

    python -m experiments.net_bench

Separate processes on one machine, not several physical machines. Not
pre-registered: an operational measurement.
"""

from __future__ import annotations

import json
import platform
import subprocess
import sys
from pathlib import Path

from experiments.multihost import run

ROOT = Path(__file__).resolve().parent.parent
LATENCIES = (0, 50, 200)


def main() -> int:
    results = [run(3, ms, network=True) for ms in LATENCIES]
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True,
                            text=True, cwd=ROOT).stdout.strip()
    out = ROOT / "research" / "results"
    (out / "net-bench.json").write_text(json.dumps(
        {"commit": commit, "machine": platform.platform(), "results": results}, indent=2) + "\n")

    def cell(v: object) -> str:
        return "—" if v is None else str(v)

    rows = "\n".join(
        f"| {r['latency_ms_per_hop']:g} | {cell(r['correction_reached_last_store_s'])} "
        f"| {r['last_store_while_offline']} / {cell(r['converged_after_restart_s'])} "
        f"| {r['partition_mid_withdrawn']} · {r['partition_last_while_cut']} "
        f"/ {cell(r['partition_converged_after_heal_s'])} "
        f"| {cell(r['concurrent_converged_s'])} "
        f"| {all(v for k, v in r.items() if k.startswith('chain_verifies'))} |" for r in results)
    (out / "net-bench.md").write_text(f"""# Networked deployment: latency, partition, outage, concurrent corrections

Produced by `python -m experiments.net_bench` at commit `{commit}`; raw numbers in
[net-bench.json](net-bench.json). Three `federate` servers, each with its own
database, connected only over HTTP through TCP proxies that add latency per
hop and can cut a link. A → B → C share chain, background managers deliver
retractions every second. Separate processes on one machine, not several
physical machines. Not pre-registered.

| latency per hop (ms) | correction reached C (s) | C during outage / converged after restart (s) | partition: B withdrawn · C while cut / converged after heal (s) | two concurrent corrections converged at C (s) | every chain verifies |
|---|---|---|---|---|---|
{rows}
""")
    print(json.dumps(results, indent=2))
    ok = all(r["correction_reached_last_store_s"] is not None
             and r["partition_converged_after_heal_s"] is not None
             and r["concurrent_converged_s"] is not None for r in results)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
