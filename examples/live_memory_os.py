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
   **across the store boundary**, carried by `propagate_retraction`.
6. A withdrawal made on weak evidence is itself **flagged for a human**, because
   Phase A measured that rule destroying more correct memory than wrong.
7. A newly imported memory is **actually retrievable** — the regression that
   made value-ranking fall through to creation time.
8. The event log survives a **backup**, and the backup verifies itself by
   replaying.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from amberlog import (
    EpsilonGreedyPolicy,
    LifecycleState,
    Amberlog,
    WithdrawalBasis,
)
from amberlog.adapters.ollama import (
    OllamaClient,
    OllamaEmbedder,
    OllamaError,
    OllamaMemoryAgent,
)
from amberlog.cli import configure_output
from amberlog.cli import main as cli_main
from amberlog.observability import report
from amberlog.federation import (
    descendants_of,
    imported_from,
    offer,
    propagate_retraction,
)
from amberlog.governance.firewall import (
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
    depot = Amberlog(seed=1, embedder=embedder, firewall=federating_firewall())
    workshop = Amberlog(seed=2, embedder=embedder, firewall=federating_firewall())

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
                         actor="safety-team", basis=WithdrawalBasis.CONTRADICTED)
        passed.append(check("source quarantined",
                            depot.get(memory_id).lifecycle_state is LifecycleState.QUARANTINED))
        passed.append(check(
            "the basis is recorded, not assumed",
            depot.state.withdrawal_basis.get(memory_id)
            == WithdrawalBasis.CONTRADICTED.value,
            depot.state.withdrawal_basis.get(memory_id, "none"),
        ))

        # The recipient holds an independent copy, so retraction does not
        # propagate automatically — it has to be carried. Provenance is what
        # makes that possible at all, and `propagate_retraction` is the API that
        # does it; this used to be hand-written here, which meant the product
        # did not actually have the feature it claimed.
        stale = descendants_of(depot, memory_id, [workshop])
        passed.append(check("recipient's copy is findable by origin", bool(stale),
                            f"{len(stale)} found"))
        results = propagate_retraction(depot, memory_id, [workshop])
        passed.append(check(
            "recipient's copy retracted",
            bool(results) and all(r.acted for r in results),
        ))
        passed.append(check(
            "the importer knows it was someone else's finding",
            all(
                workshop.state.withdrawal_basis.get(mid)
                == WithdrawalBasis.RETRACTED_AT_ORIGIN.value
                for _, mid in stale
            ),
        ))
        after = workshop.retrieve("workshop-agent", "cold morning breaker trip", k=3)
        passed.append(check("retracted memory no longer retrievable anywhere",
                            len(after.exposed) == 0))

        rule("6. A withdrawal on weak evidence is itself flagged for a human")

        # Phase A measured "withdraw whatever was in context when something
        # failed" cutting the rate at which a correct memory reached the prompt
        # from 60% of episodes to 18%. The store cannot refuse the rule, but it
        # refuses to present it as evidence.
        weak = depot.remember("depot-agent", "Chargers at bay 4 trip more often.", scope="team")
        depot.validate(weak, actor="supervisor")
        depot.quarantine(weak, reason="was in context when an episode failed",
                         actor="automation", basis=WithdrawalBasis.CO_OCCURRENCE)
        flagged = [i for i in report.attention(depot) if i.memory_id == weak]
        passed.append(check("the withdrawal becomes the finding", bool(flagged),
                            flagged[0].kind if flagged else "nothing"))
        passed.append(check(
            "it says why the basis is not enough",
            bool(flagged) and "agreement, not causation" in flagged[0].detail,
        ))
        passed.append(check(
            "it offers to undo rather than to inspect",
            bool(flagged) and "release" in flagged[0].action,
        ))

        rule("7. A newly imported memory is actually retrievable")

        # The regression this guards is subtle and was live for two days:
        # ranking on value fell through to the memory id, hence to creation
        # time, so an import — always newer than what the recipient already
        # held — could never be exposed, and value evidence can only be earned
        # by exposure.
        fresh = Amberlog(
            embedder=embedder, firewall=federating_firewall(),
            estimator="amortized",
            exposure_policy=EpsilonGreedyPolicy(epsilon=0.2, rank_by="value"),
        )
        try:
            for i in range(4):
                old_id = fresh.remember("fresh-agent", f"Unrelated note number {i}.", scope="team")
                fresh.validate(old_id, actor="supervisor")
            donor = depot.remember(
                "depot-agent",
                "Tyre pressure on the yard tug should be 3.5 bar in winter.", scope="team",
            )
            depot.validate(donor, actor="supervisor")
            handed = offer(depot, donor, fresh, recipient_agent="fresh-agent")
            passed.append(check("the import was accepted", handed.accepted))
            fresh.validate(handed.imported_memory_id, actor="fresh-agent")
            found = fresh.retrieve("fresh-agent", "yard tug tyre pressure in winter", k=3)
            passed.append(check(
                "the newest, most relevant memory is exposed",
                any(m.id == handed.imported_memory_id for m in found.exposed),
                f"{len(found.exposed)} exposed",
            ))
        finally:
            fresh.close()

        rule("8. The event log survives a backup, and the backup is verified")

        with tempfile.TemporaryDirectory() as tmp:
            # A file-backed store, because an in-memory one cannot be backed up
            # by path and the command now says so. The first version of this
            # section pointed it at `:memory:` and got a green tick for a
            # backup of nothing, which is how that bug was found.
            # Built by *writing* to a file-backed store, not by replaying the
            # depot's events into it.
            #
            # The earlier version did replay them, and it was wrong in a way
            # worth recording: a fresh store mints a `StoreIdentified` event of
            # its own, so the result held two identities, and content sealed
            # under the depot's identity failed its authentication check. The
            # error surfaced as "content failed authentication (AES-GCM)",
            # which reads as a tamper. Opening such a store is now refused with
            # an explanation instead.
            #
            # The lesson the example should teach: **replaying events into
            # another store is not a backup.** `amberlog backup` copies
            # the file, and therefore the identity and the keys with it.
            on_disk_path = str(Path(tmp) / "depot-on-disk.db")
            on_disk = Amberlog(on_disk_path)
            try:
                seeded = on_disk.remember(
                    "ag-n", "Oil change every 250 hours on the yard tug.", scope="team"
                )
                on_disk.validate(seeded, actor="supervisor")
                on_disk.quarantine(
                    seeded, reason="contradicted by the service log",
                    actor="supervisor", basis=WithdrawalBasis.CONTRADICTED,
                )
                on_disk_events = len(on_disk.log)
                on_disk_memory = seeded
            finally:
                on_disk.close()

            passed.append(check(
                "an in-memory store is refused, not silently copied",
                cli_main(["--db", ":memory:", "backup",
                          str(Path(tmp) / "nope.db")]) != 0,
            ))

            copy_path = str(Path(tmp) / "depot-backup.db")
            code = cli_main(["--db", on_disk_path, "backup", copy_path])
            passed.append(check("backup reported success", code == 0))
            restored = Amberlog(copy_path)
            try:
                passed.append(check(
                    "the copy replays to the same event count",
                    len(restored.log) == on_disk_events,
                    f"{len(restored.log)} vs {on_disk_events}",
                ))
                passed.append(check(
                    "projections that live only in the log survive",
                    restored.state.withdrawal_basis.get(on_disk_memory)
                    == WithdrawalBasis.CONTRADICTED.value,
                ))
                passed.append(check(
                    "sealed content is still readable from the copy",
                    "Oil change" in restored.get(on_disk_memory).content,
                ))
            finally:
                restored.close()

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
