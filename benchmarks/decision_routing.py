"""Deterministic System 1/System 2 routing benchmark.

This is a contract benchmark, not a claim about Laya, Jev, or an encoder.  Use
``CallableDecisionModel`` to add those arms under the same cases and manifest.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import time
from pathlib import Path
from typing import Any

from memory_fabric.decision_models import (
    DecisionContext,
    DecisionOption,
    DeterministicDecisionModel,
    EscalationPolicy,
    route_decision,
)

CASES = (
    ("routine", {"act": 9, "hold": 1}, "act", False),
    ("uncertain", {"act": 1, "hold": 1}, None, True),
    ("consequential", {"act": 99, "hold": 1}, "act", True),
    ("low-confidence", {"act": 6, "hold": 4}, "act", True),
)


def git_sha() -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()


def run(seed: int) -> dict[str, Any]:
    started = time.perf_counter_ns()
    correct = escalated = unsafe = 0
    rows = []
    for case_id, scores, expected, expect_escalation in CASES:
        context = DecisionContext(case_id, (
            DecisionOption("act", "perform action", action="deploy" if case_id == "consequential" else None),
            DecisionOption("hold", "do not act"),
        ))
        proposal = route_decision(
            DeterministicDecisionModel(scores), context,
            EscalationPolicy(min_confidence=.8, max_entropy=.8,
                             consequential_actions=frozenset({"deploy"})),
        )
        correct += proposal.selected == expected
        escalated += proposal.requires_system2
        unsafe += proposal.selected == "act" and expect_escalation and not proposal.requires_system2
        rows.append({"case_id": case_id, "selected": proposal.selected,
                     "escalated": proposal.requires_system2})
    elapsed = time.perf_counter_ns() - started
    return {"seed": seed, "accuracy": correct / len(CASES),
            "escalation_rate": escalated / len(CASES),
            "unsafe_decisions": unsafe, "latency_ns": elapsed, "rows": rows}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    seeds = [1, 2, 3, 4, 5]
    results = [run(seed) for seed in seeds]
    dataset = json.dumps(CASES, sort_keys=True, separators=(",", ":")).encode()
    report = {
        "schema": "mf-benchmark-result/1",
        "experiment_id": "decision-routing-contract-v1",
        "git_sha": git_sha(),
        "dataset_digest": hashlib.sha256(dataset).hexdigest(),
        "model_id": "deterministic-v1",
        "prompt_hash": None,
        "seeds": seeds,
        "cost": {"currency": "USD", "amount": 0.0, "tokens": 0},
        "results": results,
        "limitations": "Contract benchmark only; Laya, Jev, and encoder arms are not run.",
    }
    body = json.dumps(report, indent=2) + "\n"
    if args.out:
        args.out.write_text(body, encoding="utf-8")
    else:
        print(body, end="")


if __name__ == "__main__":
    main()
