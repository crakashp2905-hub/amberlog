"""Benchmark harness: registry, run manifests, statistics, cost ledger, scoreboard.

Masterplan §7A. Standard library only, like the core. Nothing here claims a
result: a suite is RUN only when a manifest under
`research/results/bench_runs/` records it, and a vendor's number is kept as
theirs, never assigned to Amberlog.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
