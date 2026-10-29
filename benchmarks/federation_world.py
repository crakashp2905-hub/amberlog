"""INT-02: seeded five-store correction/delay world; descriptive, not a model study.

Delivery is withheld by the scheduler during a partition. Real production
offer, outbox, dispatcher, derivation and action-certificate paths are used.
This is one physical process and does not measure network or wall-clock SLOs.
"""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path
from typing import Any

SEEDS = (1, 2, 3, 4, 5)
ROOT = Path(__file__).resolve().parents[1]


def run_seed(seed: int, topology: str = "chain") -> dict[str, Any]:
    from amberlog import Amberlog, LifecycleState
    from amberlog.actions import ActionGate, ActionPolicy, ToolRule
    from amberlog.dispatcher import Dispatcher
    from amberlog.federation import offer
    from amberlog.governance.firewall import (
        Firewall, rule_must_be_active, rule_restricted_stays_private,
        rule_capabilities_must_be_granted,
    )
    from amberlog.transport import InProcessTransport

    if topology not in {"chain", "star"}:
        raise ValueError("topology must be chain or star")
    rng = random.Random(seed)
    stores = [Amberlog(":memory:", recognise_copies=False,
                           firewall=Firewall(rules=[rule_must_be_active,
                               rule_restricted_stays_private, rule_capabilities_must_be_granted]))
              for _ in range(5)]
    traces: list[dict[str, Any]] = []
    try:
        gates = [ActionGate(store, ActionPolicy(
            tools={"publish": ToolRule("publish")}, grants={f"agent-{index}": frozenset({"publish"})},
            approvers=frozenset({"reviewer"}))) for index, store in enumerate(stores)]
        origin = stores[0].remember("observer", f"Release window opens at {rng.randint(1, 9)} hours.",
                                    auto_activate=True, scope="team")
        stores[0].elevate(origin, approver="reviewer", reason="checked against scenario source")
        copies = [origin]
        parents = [0] + [i - 1 if topology == "chain" else 0 for i in range(1, 5)]
        for index in range(1, 5):
            parent = parents[index]
            result = offer(stores[parent], copies[parent], stores[index],
                           f"agent-{index}", activate=True)
            if not result.accepted or not result.imported_memory_id:
                raise RuntimeError(f"share refused: {result.reasons}")
            copies.append(result.imported_memory_id)
            stores[index].elevate(copies[index], approver="reviewer", reason="reviewed source import")
        children, independent, certificates = [], [], []
        for index, store in enumerate(stores):
            children.append(store.derive(f"planner-{index}", "Schedule work in the release window.",
                                         parents=[copies[index]], scope="team"))
            store.validate(children[-1], actor="reviewer")
            independent.append(store.remember(f"inspector-{index}",
                f"Independent check {index}: the rollback package is available.", auto_activate=True))
            certificates.append(store.certify("release window", [copies[index]], f"agent-{index}"))
        decisions_before = [g.authorize("publish", f"agent-{i}", c)
                            for i, (g, c) in enumerate(zip(gates, certificates))]
        allowed_before = sum(d.allowed for d in decisions_before)
        traces.append({"step": "before", "reason_codes": [list(d.reason_codes) for d in decisions_before]})
        recipients = [stores[i].store_id for i in range(1, 5) if parents[i] == 0]
        stores[0].request_retraction(origin, reason="authoritative source revised",
                                     recipients=recipients, basis="retracted_at_origin")
        # The simulator knows the source is wrong; disconnected stores cannot.
        stale_during_partition = sum(s.get(mid).lifecycle_state is LifecycleState.ACTIVE
                                     for s, mid in zip(stores[1:], copies[1:]))
        traces.append({"step": "partition", "stale_copies": stale_during_partition})
        transport = InProcessTransport({s.store_id: s for s in stores})
        passes = 0
        for _ in range(10):
            order = list(range(5))
            rng.shuffle(order)
            attempted = sum(Dispatcher(stores[i], transport).drain().attempted for i in order)
            passes += 1
            traces.append({"step": "delivery", "pass": passes, "attempted": attempted,
                           "quarantined": sum(s.get(m).lifecycle_state is LifecycleState.QUARANTINED
                                               for s, m in zip(stores, copies))})
            if attempted == 0:
                break
        withdrawn = sum(s.get(m).lifecycle_state is LifecycleState.QUARANTINED
                        for s, m in zip(stores, copies))
        contested = sum(s.get(m).lifecycle_state is LifecycleState.CONTESTED
                        for s, m in zip(stores, children))
        survived = sum(s.get(m).lifecycle_state is LifecycleState.ACTIVE
                       for s, m in zip(stores, independent))
        stale_actions = sum(g.authorize("publish", f"agent-{i}", c).allowed
                            for i, (g, c) in enumerate(zip(gates, certificates)))
        return {"seed": seed, "topology": topology, "copies": 5,
                "allowed_before": allowed_before, "stale_during_partition": stale_during_partition,
                "withdrawn_after_rejoin": withdrawn, "contested_derivatives": contested,
                "independent_survivors": survived, "stale_actions_after_rejoin": stale_actions,
                "scheduler_passes": passes, "trace": traces}
    finally:
        for store in stores:
            store.close()


def main(argv: list[str]) -> int:
    from benchmarks.manifest import Manifest, head, write

    rows = [run_seed(seed, topology) for seed in SEEDS for topology in ("chain", "star")]
    violations = [r for r in rows if r["withdrawn_after_rejoin"] != 5
                  or r["contested_derivatives"] != 5 or r["independent_survivors"] != 5
                  or r["stale_actions_after_rejoin"] != 0 or r["allowed_before"] != 5]
    data = {"commit": head(), "rows": rows, "invariant_violations": len(violations),
            "scope": "single-process scheduled partition; no models or network SLO claim"}
    print(json.dumps(data, indent=1))
    if "--no-write" not in argv:
        path = ROOT / "research/results/int02-federation-world.json"
        path.write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")
        write(Manifest(run_id="int02-federation-world", suite="INT-02", arm="chain/star",
                       decision="FAIL" if violations else "DESCRIPTIVE", repo_commit=head(),
                       reason="functional regression world; no superiority hypothesis",
                       dataset={"generator": "benchmarks/federation_world.py", "topologies": ["chain", "star"]},
                       seeds=list(SEEDS), results={"invariant_violations": len(violations)},
                       counts={"attempted": len(rows), "completed": len(rows), "failed": len(violations)},
                       cost={"model_calls": 0, "model_usd": 0.0}))
    return bool(violations)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
