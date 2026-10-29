"""Scripted three-agent correction study; no model or real-workflow claim.

Run: python -m benchmarks.three_agent --out PATH
All arms receive the same initial evidence and zero refresh reads at action time.
The oracle differs only in knowing whether that cached evidence is still true.
"""
from __future__ import annotations

import argparse
import json
import random
import time
from pathlib import Path
from typing import Any

from benchmarks.manifest import head
from memory_fabric import MemoryFabric
from memory_fabric.actions import ActionGate, ActionPolicy, ToolRule

SEEDS = (601, 607, 613, 617, 619)
ARMS = ("shared_cached", "shared_recheck", "governed", "oracle")


def run(seed: int, arm: str) -> dict[str, Any]:
    if arm not in ARMS:
        raise ValueError("unknown arm")
    rng = random.Random(seed)
    cases = [False, True] * 6
    rng.shuffle(cases)
    counts = dict(attempted=0, task_success=0, stale_actions=0,
                  false_blocking=0, abstention=0, correct_abstention=0)
    trace = []
    started = time.perf_counter()
    with MemoryFabric(":memory:", recognise_copies=False, encrypt_content=False) as f:
        agents = ("observer", "planner", "executor")
        gate = ActionGate(f, ActionPolicy(
            tools={"publish": ToolRule("publish")},
            grants={a: frozenset({"publish"}) for a in agents}))
        for case, corrected in enumerate(cases):
            mid = f.remember(agents[0], f"Job {case} dispatch code is {rng.randrange(100, 999)}.",
                             scope="team", auto_activate=True)
            f.elevate(mid, approver="reviewer", reason="scenario source checked")
            for agent in agents:
                exposed = f.retrieve(agent, f"Job {case} dispatch code", k=1,
                                     within=[mid], min_relevance=0.0).exposed
                if [m.id for m in exposed] != [mid]:
                    raise RuntimeError("initial evidence exposure failed")
            certificates = {a: f.certify(f"dispatch-{case}", [mid], a) for a in agents}
            if corrected:
                f.quarantine(mid, actor="reviewer", reason="dispatch code withdrawn",
                             basis="contradicted")
            for agent in agents:
                tick = time.perf_counter()
                if arm == "shared_cached":
                    allowed = True
                elif arm == "shared_recheck":
                    allowed = f.get(mid).lifecycle_state.value == "active"
                elif arm == "governed":
                    allowed = gate.authorize("publish", agent, certificates[agent]).allowed
                else:
                    allowed = not corrected
                stale = allowed and corrected
                false_block = not allowed and not corrected
                counts["attempted"] += 1
                counts["task_success"] += int(allowed and not corrected)
                counts["stale_actions"] += int(stale)
                counts["false_blocking"] += int(false_block)
                counts["abstention"] += int(not allowed)
                counts["correct_abstention"] += int(not allowed and corrected)
                trace.append(dict(case=case, agent=agent, corrected=corrected,
                                  allowed=allowed, latency_ms=(time.perf_counter()-tick)*1000))
        elapsed = time.perf_counter() - started
        # Content bytes only: not disk size, encryption, indexes or log overhead.
        content_bytes = sum(len(m.content.encode("utf-8")) for m in f.state.memories.values())
        event_count = f.log.head_seq
    return dict(seed=seed, arm=arm, counts=counts, trace=trace,
                elapsed_s=elapsed, decisions_per_second=counts["attempted"]/elapsed,
                retained_content_bytes=content_bytes, event_count=event_count,
                model_calls=0, model_tokens=None, model_usd=0)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    rows = [run(seed, arm) for seed in SEEDS for arm in ARMS]
    violations = [r for r in rows if r["arm"] in ("governed", "oracle") and
                  (r["counts"]["stale_actions"] or r["counts"]["false_blocking"])]
    data = dict(commit=head(), decision="FAIL" if violations else "DESCRIPTIVE",
                seeds=SEEDS, arms=ARMS, violations=len(violations), rows=rows,
                scope="scripted single-process three-agent shared-store study; no real pilot",
                budget=dict(initial_evidence_per_agent=1, refresh_content_reads=0),
                caveats=["all arms include identical certificate setup overhead",
                         "recheck baseline has privileged local metadata access",
                         "timing includes store setup and teardown except per-decision latency",
                         "no model token or total disk-storage measurement"])
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(data, indent=2)+"\n", encoding="utf-8")
    return int(bool(violations))


if __name__ == "__main__":
    raise SystemExit(main())
