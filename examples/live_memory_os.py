"""The memory OS layer, exercised end to end by real local models.

    python examples/live_memory_os.py

Needs Ollama running with `qwen2.5:3b` and `nomic-embed-text`. Everything here
goes through the real fabric — governed writes, real semantic retrieval,
provenance, federation across a store boundary, and retraction — driven by
models that have no idea any of that is happening.

What it checks, in order:

1. An agent writes a memory and it lands **unvalidated**, not retrievable.
2. A reviewer validates it; a second agent then retrieves and uses it.
3. A model that tries to memorise a credential is **quarantined** on ingest.
4. Two agents with separate stores **federate**, and the recipient decides.
5. The source turns out to be wrong, and the retraction follows the memory
   **across the store boundary**.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from memory_fabric import LifecycleState, MemoryFabric
from memory_fabric.adapters.ollama import (
    OllamaClient,
    OllamaEmbedder,
    OllamaError,
    OllamaMemoryAgent,
)
from memory_fabric.cli import configure_output
from memory_fabric.federation import imported_from, offer
from memory_fabric.governance.firewall import (
    Firewall,
    rule_capabilities_must_be_granted,
    rule_must_be_active,
    rule_restricted_stays_private,
)

configure_output()

MODEL = "qwen2.5:3b"


def rule(title: str) -> None:
    print(f"\n{'=' * 74}\n{title}\n{'=' * 74}")


def check(label: str, condition: bool, detail: str = "") -> bool:
    print(f"  [{'PASS' if condition else 'FAIL'}] {label}" + (f" - {detail}" if detail else ""))
    return condition


def federating_firewall() -> Firewall:
    """Without the value rule, which refuses everything lacking contrastive
    evidence — see SECURITY.md on that gate asking the sender's question."""
    return Firewall(
        rules=(rule_restricted_stays_private, rule_must_be_active,
               rule_capabilities_must_be_granted)
    )


def main() -> int:
    client = OllamaClient()
    try:
        available = client.available()
    except OllamaError as exc:
        print(f"{exc}", file=sys.stderr)
        return 2
    if MODEL not in available:
        print(f"{MODEL} not installed; have: {', '.join(available[:6])}", file=sys.stderr)
        return 2

    embedder = OllamaEmbedder(client)
    passed: list[bool] = []

    # Two separate stores: this is federation, not one store with flags.
    depot = MemoryFabric(seed=1, embedder=embedder, firewall=federating_firewall())
    workshop = MemoryFabric(seed=2, embedder=embedder, firewall=federating_firewall())

    try:
        rule("1. An agent writes a memory; it is NOT retrievable yet")

        writer = OllamaMemoryAgent(
            depot, "depot-agent", model=MODEL, client=client, allow_remember=True
        )
        run = writer.run(
            task_id="incident-8814",
            prompt=(
                "A depot charger tripped its breaker on a cold morning. The cause was "
                "a damp earth bond, which trips on the first high-current draw. "
                "Record the durable lesson for future incidents."
            ),
            context={"domain": "ev"},
            recall=False,
        )
        print(f"  model said: {run.text[:120]}")
        passed.append(check("agent wrote a memory", bool(run.remembered),
                            f"{len(run.remembered)} written"))
        if not run.remembered:
            print("  (model declined the tool; the rest of the demo needs it)")
            return 1

        memory_id = run.remembered[0]
        memory = depot.get(memory_id)
        print(f"  recorded: {memory.content[:100]}")
        passed.append(check("arrived as a candidate",
                            memory.lifecycle_state is LifecycleState.CANDIDATE,
                            memory.lifecycle_state.value))
        hits = depot.retrieve("other-agent", "cold morning breaker trip", k=3)
        passed.append(check("not retrievable before review", len(hits.exposed) == 0))

        rule("2. A reviewer validates it; another agent then uses it")

        depot.validate(memory_id, actor="reviewer")
        reader = OllamaMemoryAgent(depot, "night-agent", model=MODEL, client=client)
        answer = reader.run(
            task_id="incident-8820",
            prompt=("A depot charger just tripped its breaker on a cold morning. "
                    "What should I check first? Answer in one sentence."),
            context={"domain": "ev"},
        )
        passed.append(check("retrieved after review", bool(answer.recalled),
                            f"{len(answer.recalled)} exposed"))
        used = "earth bond" in answer.text.lower() or "bond" in answer.text.lower()
        passed.append(check("model used the retrieved memory", used))
        print(f"  model said: {answer.text[:160]}")

        rule("3. A model that memorises a credential is quarantined on ingest")

        leaker = OllamaMemoryAgent(
            depot, "onboarding-agent", model=MODEL, client=client, allow_remember=True
        )
        leak = leaker.run(
            task_id="onboarding-1",
            prompt=("Record this deployment note verbatim so the team has it: "
                    "'to deploy, export AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE "
                    "and run make ship'."),
            recall=False,
        )
        if leak.remembered:
            leaked = depot.get(leak.remembered[0])
            passed.append(check(
                "credential quarantined on ingest",
                leaked.lifecycle_state is LifecycleState.QUARANTINED,
                leaked.lifecycle_state.value,
            ))
            shown = depot.explain(leak.remembered[0]).narrative()
            passed.append(check("secret redacted in the explanation",
                                "AKIAIOSFODNN7EXAMPLE" not in shown))
        else:
            print("  (model declined to record it; governance untested this run)")

        rule("4. Federation: the depot offers its lesson to the workshop")

        result = offer(depot, memory_id, workshop, recipient_agent="workshop-agent")
        passed.append(check("offer accepted", result.accepted, result.decision.value))
        imported_id = result.imported_memory_id
        passed.append(check(
            "import arrives unvalidated",
            workshop.get(imported_id).lifecycle_state is LifecycleState.CANDIDATE,
        ))
        origin = imported_from(workshop, imported_id)
        passed.append(check("provenance crossed the boundary",
                            origin is not None and origin["memory_id"] == memory_id,
                            f"from {origin['agent']}" if origin else ""))

        workshop.validate(imported_id, actor="workshop-lead")
        workshop_agent = OllamaMemoryAgent(
            workshop, "workshop-agent", model=MODEL, client=client
        )
        across = workshop_agent.run(
            task_id="workshop-1",
            prompt=("A charger trips its breaker on cold mornings. What do I check "
                    "first? Answer in one sentence."),
        )
        passed.append(check("second store's agent used the imported memory",
                            bool(across.recalled)))
        print(f"  workshop model said: {across.text[:160]}")

        rule("5. The source was wrong - retraction follows it across the boundary")

        depot.quarantine(memory_id, reason="root cause was a faulty RCD, not the bond",
                         actor="safety-team")
        passed.append(check("source quarantined",
                            depot.get(memory_id).lifecycle_state is LifecycleState.QUARANTINED))

        # The recipient holds an independent copy, so retraction does not
        # propagate automatically — it has to be carried. Provenance is what
        # makes that possible at all.
        stale = [
            mid for mid in workshop.state.memories
            if (o := imported_from(workshop, mid)) and o["memory_id"] == memory_id
        ]
        passed.append(check("recipient's copy is findable by origin", bool(stale),
                            f"{len(stale)} found"))
        for mid in stale:
            workshop.quarantine(mid, reason=f"origin {memory_id} retracted at source",
                                actor="federation")
        passed.append(check(
            "recipient's copy retracted",
            all(workshop.get(m).lifecycle_state is LifecycleState.QUARANTINED for m in stale),
        ))
        after = workshop.retrieve("workshop-agent", "cold morning breaker trip", k=3)
        passed.append(check("retracted memory no longer retrievable anywhere",
                            len(after.exposed) == 0))

        rule("Summary")
        print(f"  {sum(passed)}/{len(passed)} checks passed")
        print(f"  depot store:    {len(depot.state.memories)} memories, {len(depot.log)} events")
        print(f"  workshop store: {len(workshop.state.memories)} memories, {len(workshop.log)} events")
        print(f"  embedder calls: {embedder.calls}")
        return 0 if all(passed) else 1
    finally:
        depot.close()
        workshop.close()


if __name__ == "__main__":
    sys.exit(main())
