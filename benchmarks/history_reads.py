"""Descriptive seeded qualification of historical reads against independent latent truth."""
from __future__ import annotations

import json
from pathlib import Path
import random

from benchmarks.manifest import head
from amberlog import Amberlog
from amberlog.identity import DEFAULT_TENANT
from amberlog.history_query import query

SEEDS = (401, 409, 419, 421, 431)
ROOT = Path(__file__).resolve().parents[1]


def run_seed(seed: int) -> dict:
    rng = random.Random(seed)
    f = Amberlog(":memory:", recognise_copies=False)
    records = []
    try:
        for i in range(20):
            state = ("active", "revised", "retracted", "erased", "foreign", "private")[i % 6]
            value = rng.randint(3, 80)
            text = f"Record {i} threshold is {value} bar."
            mid = f.remember("writer", text, auto_activate=True,
                scope="private" if state == "private" else "team",
                tenant_id="foreign" if state == "foreign" else DEFAULT_TENANT,
                valid_from=100, valid_to=200)
            records.append((mid, text, value, state))
        # Derive expected answers from hidden scenario assignments, not a replay filter.
        expected = {mid: text for mid, text, _, state in records if state in {"active", "revised"}}
        snapshot = f.log.head_seq
        for mid, _, value, state in reversed(records):
            if state == "revised":
                f.revise(mid, f"Corrected threshold is {value + 1} bar.", agent_id="writer", reason="late correction")
            elif state == "retracted":
                f.quarantine(mid, reason="source correction", actor="reviewer")
            elif state == "erased":
                f.erase_content(mid, reason="fixture request")
        ids = [mid for mid, *_ in records]
        receipt = query(f, "reader", ids, known_at=snapshot, valid_at=150)
        got = {row.memory_id: row.content for row in receipt.rows}
        out_of_window = query(f, "reader", ids, known_at=snapshot, valid_at=250)
        return {"seed": seed, "expected_rows": len(expected), "returned_rows": len(got),
                "exact": got == expected, "out_of_window_empty": not out_of_window.rows,
                "events_replayed": receipt.events_replayed, "latency_ms": receipt.elapsed_ms,
                "archival_labels": all(row.archival_only for row in receipt.rows)}
    finally:
        f.close()


def main() -> int:
    rows = [run_seed(seed) for seed in SEEDS]
    failures = [r for r in rows if not (r["exact"] and r["out_of_window_empty"] and r["archival_labels"])]
    result = {"commit": head(), "seeds": SEEDS, "rows": rows,
              "decision": "FAIL" if failures else "DESCRIPTIVE", "failures": len(failures),
              "scope": "scripted functional qualification, not a model or performance-improvement claim",
              "cost": {"model_calls": 0, "model_usd": 0, "hardware_usd": None}}
    output = ROOT / "research/results/historical-read-qualification.json"
    output.write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=1))
    return bool(failures)


if __name__ == "__main__":
    raise SystemExit(main())
