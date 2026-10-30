"""The product's lead demo: "why did this agent remember this, and can we pull it back?"

Run from the repository root:

    python examples/poisoning_and_rollback.py

The story: an agent learns something false, consolidates a belief from it, builds
a procedure on that belief, and shares it. Then the source turns out to be
poisoned. The demo shows the trace that explains every downstream memory, and the
retraction that reaches all of them.

None of this needs an outcome signal, which is the point of leading with
governance (ROADMAP.md).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

# Windows consoles default to a legacy code page that cannot encode the
# punctuation below; this reconfigures stdout the way the CLI does.
from amberlog.cli import configure_output

configure_output()

from amberlog import LifecycleState, Amberlog, MemoryType, Scope


def rule(title: str) -> None:
    print(f"\n{'=' * 74}\n{title}\n{'=' * 74}")


def main() -> None:
    fabric = Amberlog(auto_activate=True, seed=0)

    rule("1. An agent learns something from an episode")

    episode = fabric.start_episode(
        "diagnostic-agent", task_id="battery-anomaly-4471", context={"domain": "ev"}
    )
    observation = fabric.remember(
        "diagnostic-agent",
        "The battery temperature threshold is 45 degrees C.",
        context={"domain": "ev", "vehicle": "model-x"},
        source_episodes=[episode.id], scope="team",
    )
    fabric.record_outcome(episode.id, outcome=1.0, verifier_id="test-rig")
    print(f"  observation  {observation}")

    rule("2. A belief is consolidated from it, and a procedure built on the belief")

    belief = fabric.derive(
        "diagnostic-agent",
        "Warn the operator whenever the pack exceeds 45 degrees C.",
        parents=[observation], scope="team",
    )
    procedure = fabric.derive(
        "ops-agent",
        "Procedure: poll pack temperature every 5s, warn above 45, shut down above 60.",
        parents=[belief],
        type=MemoryType.PROCEDURAL, scope="team",
    )
    print(f"  belief       {belief}")
    print(f"  procedure    {procedure}")

    unrelated = fabric.remember("ops-agent", "Tyre pressure should be 34 psi.", scope="team")
    print(f"  unrelated    {unrelated}")

    rule("3. Someone tries to share the procedure with the wider fleet")

    ruling = fabric.share(procedure, Scope.FEDERATED, granted_capabilities=["telemetry"])
    print(f"  decision: {ruling.decision.value}")
    for reason in ruling.reasons:
        print(f"    - {reason}")
    print(f"  scope is still: {fabric.get(procedure).scope.value}")
    print(
        "\n  The refusal is the correct answer. Nothing has measured whether this\n"
        "  procedure helps, and the exposure policy is deterministic, so no data\n"
        "  it produced could show that either."
    )

    rule('4. "Why does the system believe this?"')

    print(fabric.explain(procedure).narrative())

    rule("5. The original observation turns out to be poisoned")

    print("  The test rig was misconfigured; the real threshold is 38 C.\n")
    contested = fabric.quarantine(
        observation,
        reason="source test rig was misconfigured; readings invalid",
        actor="safety-team",
    )
    print(f"  quarantined: {observation}")
    print(f"  contested downstream ({len(contested)}):")
    for memory_id in contested:
        print(f"    - {memory_id}  {fabric.get(memory_id).content[:52]}...")

    print("\n  States after retraction:")
    for label, memory_id in [
        ("observation", observation),
        ("belief", belief),
        ("procedure", procedure),
        ("unrelated", unrelated),
    ]:
        print(f"    {label:<12} {fabric.get(memory_id).lifecycle_state.value}")

    rule("6. The retracted knowledge no longer reaches any agent")

    result = fabric.retrieve(
        "ops-agent", "what temperature should trigger a warning on the pack?"
    )
    print(f"  memories exposed for a live query: {len(result.exposed)}")
    assert all(m.id not in {observation, belief, procedure} for m in result.exposed)
    print("  The unrelated memory is untouched and still retrievable:")
    tyres = fabric.retrieve("ops-agent", "tyre pressure psi")
    print(f"    {[m.content for m in tyres.exposed]}")

    rule("7. The audit trail explains the procedure's fate without guesswork")

    print(fabric.explain(procedure).narrative())

    rule("8. Store health")

    health = fabric.health()
    print(f"  total memories        {health.total}")
    print(f"  by state              {health.by_state}")
    print(f"  quarantined           {health.quarantined}")
    print(f"  contested             {health.contested}")
    print(f"  never exposed         {health.never_exposed}")
    print(f"  no value evidence     {health.unverified}")
    print(f"  events in the log     {health.events}")

    rule("9. The log is the source of truth")

    before = len(fabric.state.memories)
    fabric.rebuild()
    print(f"  rebuilt {len(fabric.state.memories)} memories from {health.events} events")
    assert len(fabric.state.memories) == before
    assert fabric.get(observation).lifecycle_state is LifecycleState.QUARANTINED
    print("  state after rebuild matches state before it")

    fabric.close()
    print()


if __name__ == "__main__":
    main()
