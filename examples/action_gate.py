"""Gating a tool call on the evidence behind it.

Run from the repository root:

    python examples/action_gate.py

The host owns the tool loop, so the host owns the gate. An agent recalls
memories, certifies the ones its decision rests on, and asks to call a tool.
Before the tool runs, the gate checks the grant first and then re-verifies the
evidence against the store, as it is now. In between, one memory is retracted.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from amberlog.cli import configure_output

configure_output()

from amberlog import Amberlog
from amberlog.actions import ActionGate, ActionPolicy, ToolRule


def main() -> int:
    fabric = Amberlog(seed=0)
    gauge = fabric.remember("ag_field", "Valve 7 pressure reads 4 bar.", scope="team")
    fabric.validate(gauge, actor="supervisor")

    policy = ActionPolicy(
        tools={"open_valve": ToolRule("open_valve"),
               "read_gauge": ToolRule("read_gauge", protected=False)},
        grants={"ag_ops": frozenset({"open_valve", "read_gauge"}),
                "ag_intern": frozenset({"read_gauge"})},
    )
    gate = ActionGate(fabric, policy)

    certificate = fabric.certify("open-valve-7", [gauge], "ag_ops")
    first = gate.authorize("open_valve", "ag_ops", certificate)
    print(f"1. evidence current         -> {first.allowed!s:5}  {first.reason_codes}")

    intern_cert = fabric.certify("open-valve-7", [gauge], "ag_intern")
    second = gate.authorize("open_valve", "ag_intern", intern_cert)
    print(f"2. valid evidence, no grant -> {second.allowed!s:5}  {second.reason_codes}")

    fabric.quarantine(gauge, reason="gauge was miscalibrated", actor="safety",
                      basis="contradicted")
    third = gate.authorize("open_valve", "ag_ops", certificate)
    print(f"3. evidence retracted       -> {third.allowed!s:5}  {third.reason_codes}")

    audited = [e.payload["allowed"] for e in fabric.log.read() if e.type == "ActionGated"]
    print(f"   audit trail (ActionGated): {audited}")
    fabric.close()
    return 0 if (first.allowed, second.allowed, third.allowed) == (True, False, False) else 1


if __name__ == "__main__":
    raise SystemExit(main())
