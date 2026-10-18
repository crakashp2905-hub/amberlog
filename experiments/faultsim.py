"""Phase 5 — a deterministic multi-store simulator for integrity faults.

The roadmap's framing, and it is the right one: *statistical benchmarks do not
prove deterministic safety; a reproducible counterexample to an invariant is a
bug.* So this is not another seeded experiment measuring an average. It is a
scheduler that replays an exact sequence of faults and asserts invariants after
every step, and whose failures are counterexamples rather than effect sizes.

Nothing here samples. Every schedule is a literal list, every store is real, and
a failure prints the schedule that produced it so it can be pasted into a
regression test — which is what roadmap §5.4's "a deterministic regression test
for every discovered bug" needs to be cheap.

    python -m experiments.faultsim            # run every scenario
    python -m experiments.faultsim --list     # name them
    python -m experiments.faultsim --only duplicate_storm
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Callable, Sequence

from memory_fabric import LifecycleState, MemoryFabric, WithdrawalBasis
from memory_fabric.dispatcher import Dispatcher, reconcile
from memory_fabric.federation import offer
from memory_fabric.governance.firewall import (
    Firewall,
    rule_capabilities_must_be_granted,
    rule_must_be_active,
    rule_restricted_stays_private,
)
from memory_fabric.justification import JustificationKind, justification_context
from memory_fabric.protocol import PropagationState, Retraction, new_retraction_id
from memory_fabric.transport import InProcessTransport, Peer, PeerRegistry


def permissive() -> Firewall:
    return Firewall(
        rules=(
            rule_restricted_stays_private,
            rule_must_be_active,
            rule_capabilities_must_be_granted,
        )
    )


# --- invariant checks -------------------------------------------------------
#
# Each returns a list of violations. They run after *every* step of every
# schedule, because an invariant that only holds at the end of a scenario is not
# an invariant — it is a coincidence about that scenario's final state.


def check_no_blocked_memory_is_retrievable(world: "World") -> list[str]:
    """Invariant 6, checked by actually retrieving rather than by reading state."""
    violations = []
    for name, store in world.stores.items():
        blocked = {
            memory_id
            for memory_id, memory in store.state.memories.items()
            if memory.lifecycle_state
            in (LifecycleState.QUARANTINED, LifecycleState.DEPRECATED, LifecycleState.DELETED)
        }
        if not blocked:
            continue
        for memory_id in blocked:
            content = store.state.memories[memory_id].content
            hits = store.retrieve(f"probe-{name}", content, k=10)
            if memory_id in {m.id for m in hits.exposed}:
                violations.append(
                    f"{name}: blocked memory {memory_id} was retrievable"
                )
    return violations


def check_history_is_append_only(world: "World") -> list[str]:
    """Invariant 1. The event count may only grow."""
    violations = []
    for name, store in world.stores.items():
        seen = world.event_counts.get(name, 0)
        now = len(store.log)
        if now < seen:
            violations.append(f"{name}: event count fell from {seen} to {now}")
        world.event_counts[name] = max(seen, now)
    return violations


def check_one_effect_per_retraction(world: "World") -> list[str]:
    """Invariant 4. However many times a retraction is delivered, each recipient
    applies it to each local memory once."""
    violations = []
    for name, store in world.stores.items():
        seen: dict[tuple[str, str], int] = {}
        for event in store.log.read():
            if event.type != "RetractionApplied":
                continue
            key = (event.payload["retraction_id"], event.payload["local_memory_id"])
            seen[key] = seen.get(key, 0) + 1
        for (retraction_id, local_id), count in seen.items():
            if count > 1:
                violations.append(
                    f"{name}: retraction {retraction_id} applied {count}x to {local_id}"
                )
    return violations


def check_no_acknowledgement_overstates(world: "World") -> list[str]:
    """Invariant 5. A recorded acknowledgement claiming persistence must have a
    state revision behind it."""
    violations = []
    for name, store in world.stores.items():
        rows = store.log._conn.execute(
            "SELECT retraction_id, recipient, state, state_revision FROM acknowledgements"
        ).fetchall()
        for row in rows:
            if row["state"] in ("persisted", "enforced", "verified") and row["state_revision"] <= 0:
                violations.append(
                    f"{name}: acknowledgement for {row['retraction_id']} claims "
                    f"{row['state']} with revision {row['state_revision']}"
                )
    return violations


def check_committed_retractions_are_still_owed(world: "World") -> list[str]:
    """Invariant 3. Every retraction this store requested must appear in the
    outbox for every recipient it named, until it reaches a terminal state.
    A row that vanished is a silently lost correction."""
    violations = []
    for name, store in world.stores.items():
        for event in store.log.read():
            if event.type != "RetractionRequested":
                continue
            retraction_id = event.payload["retraction_id"]
            for recipient in event.payload.get("recipients", []):
                state = store.outbox.state_of(retraction_id, recipient)
                if state is PropagationState.UNKNOWN:
                    violations.append(
                        f"{name}: retraction {retraction_id} for {recipient} "
                        "has no outbox row at all"
                    )
    return violations


def check_independent_knowledge_survives(world: "World") -> list[str]:
    """Invariant 8. Nothing contested should have a surviving independent
    justification; if it does, it was withdrawn indiscriminately."""
    violations = []
    for name, store in world.stores.items():
        for memory_id, memory in store.state.memories.items():
            if memory.lifecycle_state is not LifecycleState.CONTESTED:
                continue
            if memory.hypothesis_set:
                # Contested by a genuine disagreement, not by a retraction.
                continue
            verdict = store.justifications.recompute(memory_id)
            if verdict.still_justified:
                violations.append(
                    f"{name}: {memory_id} is contested but still justified "
                    f"({verdict.reason})"
                )
    return violations


def check_onward_obligations_are_recorded(world: "World") -> list[str]:
    """Invariant 3, one hop out. A store that applied a retraction to a memory
    it had re-shared must have the onward delivery recorded — not merely
    intend it.

    This is the transitive form of the gap `request_retraction` closed at the
    origin. A store that withdrew its own copy and then crashed before writing
    down what it owed would leave live copies downstream that nothing in the
    federation was tracking, and no check anywhere would notice: the upstream
    acknowledgement already said "enforced", truthfully, about the one copy it
    was asked about.

    Note what this does *not* assert. It does not require the downstream copy
    to be withdrawn yet. Forwarding is asynchronous by construction — a
    synchronous cascade would put an unbounded number of network calls inside
    one recipient's transaction — so convergence is a property of the system at
    rest and belongs in an explicit end-of-schedule expectation, not in a check
    that runs between every pair of steps.
    """
    violations = []
    for name, store in world.stores.items():
        for event in store.log.read():
            if event.type != "RetractionApplied":
                continue
            local_id = event.payload.get("local_memory_id")
            if local_id is None:
                continue
            downstream = store.shared_with(local_id)
            if not downstream:
                continue
            for recipient in downstream:
                owed = [
                    row
                    for row in store.log._conn.execute(
                        "SELECT recipient, state FROM outbox WHERE recipient = ?",
                        (recipient,),
                    )
                ]
                if not owed:
                    violations.append(
                        f"{name}: applied a retraction to {local_id}, which it "
                        f"had re-shared to {world.name_of(recipient)}, with no "
                        "onward delivery recorded"
                    )
    return violations


CHECKS: tuple[Callable[["World"], list[str]], ...] = (
    check_history_is_append_only,
    check_no_blocked_memory_is_retrievable,
    check_one_effect_per_retraction,
    check_no_acknowledgement_overstates,
    check_committed_retractions_are_still_owed,
    check_independent_knowledge_survives,
    check_onward_obligations_are_recorded,
)


# --- the world --------------------------------------------------------------


@dataclass
class World:
    """Real stores on disk, plus the bookkeeping the checks need."""

    root: Path
    stores: dict[str, MemoryFabric] = field(default_factory=dict)
    registry: PeerRegistry = field(default_factory=PeerRegistry)
    offline: set[str] = field(default_factory=set)
    memories: dict[str, str] = field(default_factory=dict)
    event_counts: dict[str, int] = field(default_factory=dict)
    log: list[str] = field(default_factory=list)

    def store(self, name: str) -> MemoryFabric:
        if name not in self.stores:
            fabric = MemoryFabric(str(self.root / f"{name}.db"), firewall=permissive())
            self.stores[name] = fabric
            self.registry.add(
                Peer(store_id=fabric.store_id, endpoint="unused", key=b"k-" + name.encode())
            )
        return self.stores[name]

    def id_of(self, name: str) -> str:
        return self.store(name).store_id

    def name_of(self, store_id: str) -> str:
        for name, store in self.stores.items():
            if store.store_id == store_id:
                return name
        return store_id

    def transport(self) -> InProcessTransport:
        return InProcessTransport(
            {s.store_id: s for s in self.stores.values()},
            registry=self.registry,
            offline={self.id_of(n) for n in self.offline if n in self.stores},
        )

    def reopen(self, name: str) -> MemoryFabric:
        """A crash and restart: close the handle and open the same file."""
        path = str(self.root / f"{name}.db")
        self.stores[name].close()
        fabric = MemoryFabric(path, firewall=permissive())
        self.stores[name] = fabric
        return fabric

    def close(self) -> None:
        for store in self.stores.values():
            try:
                store.close()
            except Exception:
                pass


# --- steps ------------------------------------------------------------------
#
# A schedule is a list of these. Each is a plain callable so a scenario reads
# as the sequence of events it is meant to represent.


def observe(store: str, agent: str, content: str, key: str) -> Callable[[World], None]:
    def step(world: World) -> None:
        fabric = world.store(store)
        memory_id = fabric.remember(agent, content, scope="team")
        fabric.validate(memory_id, actor="supervisor")
        world.memories[key] = memory_id
        world.log.append(f"{store}: observed {key}")

    return step


def derive(
    store: str, agent: str, content: str, key: str, parents: dict[str, JustificationKind]
) -> Callable[[World], None]:
    def step(world: World) -> None:
        fabric = world.store(store)
        resolved = {world.memories[p]: kind for p, kind in parents.items()}
        memory_id = fabric.derive(
            agent, content, parents=list(resolved),
            context=justification_context(resolved.items()), scope="team",
        )
        fabric.validate(memory_id, actor="supervisor")
        world.memories[key] = memory_id
        world.log.append(f"{store}: derived {key} from {sorted(parents)}")

    return step


def share(origin: str, key: str, recipient: str, as_key: str) -> Callable[[World], None]:
    def step(world: World) -> None:
        source = world.store(origin)
        target = world.store(recipient)
        result = offer(source, world.memories[key], target, recipient_agent=f"ag-{recipient}")
        if not result.accepted:
            raise AssertionError(f"offer refused: {result.reasons}")
        target.validate(result.imported_memory_id, actor=f"ag-{recipient}")
        world.memories[as_key] = result.imported_memory_id
        world.log.append(f"{origin} -> {recipient}: shared {key} as {as_key}")

    return step


def share_refused(origin: str, key: str, recipient: str, because: str) -> Callable[[World], None]:
    """An offer that must be refused, and for the stated reason."""
    def step(world: World) -> None:
        result = offer(world.store(origin), world.memories[key], world.store(recipient),
                       recipient_agent=f"ag-{recipient}")
        if result.accepted or not any(because in r for r in result.reasons):
            raise AssertionError(f"expected refusal ({because}), got {result.accepted} "
                                 f"{result.reasons}")
        world.log.append(f"{origin} -> {recipient}: {key} refused ({because})")

    return step


def retract(origin: str, key: str, recipients: Sequence[str], reason: str = "contradicted"):
    def step(world: World) -> None:
        fabric = world.store(origin)
        retraction = fabric.request_retraction(
            world.memories[key], reason=reason,
            recipients=[world.id_of(r) for r in recipients],
            actor=f"ag-{origin}", basis=WithdrawalBasis.CONTRADICTED,
        )
        world.memories[f"__retraction_{key}"] = retraction.retraction_id
        world.log.append(f"{origin}: retracted {key} to {list(recipients)}")

    return step


def dispatch(origin: str, times: int = 1) -> Callable[[World], None]:
    def step(world: World) -> None:
        fabric = world.store(origin)
        dispatcher = Dispatcher(fabric, world.transport())
        for _ in range(times):
            # Clear any backoff so a schedule does not depend on wall time.
            fabric.log._conn.execute("UPDATE outbox SET next_attempt_ms = 0")
            fabric.log._conn.commit()
            dispatcher.run_once()
        world.log.append(f"{origin}: dispatched x{times}")

    return step


def settle(max_rounds: int = 8) -> Callable[[World], None]:
    """Dispatch every store until nothing moves.

    Needed as soon as the graph is deeper than one hop: `dispatch("origin")`
    cannot deliver what the origin does not know about. A store one hop out
    commits its own onward obligation and returns, so the second hop travels on
    *that* store's dispatcher.

    Bounded, and the bound is an assertion rather than a convenience: a
    federation that will not settle in `max_rounds` is a failure to report, not
    a loop to keep turning.
    """

    def step(world: World) -> None:
        for round_number in range(max_rounds):
            moved = 0
            transport = world.transport()
            for store in list(world.stores.values()):
                store.log._conn.execute("UPDATE outbox SET next_attempt_ms = 0")
                store.log._conn.commit()
                moved += Dispatcher(store, transport).drain().attempted
            if moved == 0:
                world.log.append(f"settled after {round_number} round(s)")
                return
        raise AssertionError(f"federation did not settle in {max_rounds} rounds")

    return step


def go_offline(*names: str) -> Callable[[World], None]:
    def step(world: World) -> None:
        world.offline.update(names)
        world.log.append(f"offline: {list(names)}")

    return step


def come_online(*names: str) -> Callable[[World], None]:
    def step(world: World) -> None:
        world.offline.difference_update(names)
        world.log.append(f"online: {list(names)}")

    return step


def crash(name: str) -> Callable[[World], None]:
    def step(world: World) -> None:
        world.reopen(name)
        world.log.append(f"{name}: crashed and restarted")

    return step


def reconcile_from(recipient: str, origin: str) -> Callable[[World], None]:
    def step(world: World) -> None:
        target = world.store(recipient)
        source = world.store(origin)
        since = target.outbox.missed_since(source.store_id)
        reconcile(target, source.retractions_since(since), source.store_id)
        world.log.append(f"{recipient}: reconciled from {origin} since {since}")

    return step


def deliver_stale(origin: str, key: str, recipient: str, sequence: int):
    """A delayed older retraction arriving after a newer one."""

    def step(world: World) -> None:
        source = world.store(origin)
        target = world.store(recipient)
        stale = Retraction(
            retraction_id=new_retraction_id(),
            origin_store_id=source.store_id,
            origin_memory_id=world.memories[key],
            origin_memory_version=1,
            origin_sequence=sequence,
            reason_code=WithdrawalBasis.CONTRADICTED.value,
            requested_by=f"ag-{origin}",
            issued_at="2026-01-01T00:00:00Z",
        )
        target.receive_retraction(stale, sender_authorised=True)
        world.log.append(f"{recipient}: received stale retraction at seq {sequence}")

    return step


def deliver_unauthorised(origin: str, key: str, recipient: str):
    def step(world: World) -> None:
        source = world.store(origin)
        target = world.store(recipient)
        forged = Retraction(
            retraction_id=new_retraction_id(),
            origin_store_id=source.store_id,
            origin_memory_id=world.memories[key],
            origin_memory_version=1,
            origin_sequence=9_999,
            reason_code=WithdrawalBasis.CONTRADICTED.value,
            requested_by="ag-attacker",
            issued_at="2026-01-01T00:00:00Z",
        )
        target.receive_retraction(forged, sender_authorised=False)
        world.log.append(f"{recipient}: refused an unauthorised retraction")

    return step


def expect(name: str, state: LifecycleState, store: str) -> Callable[[World], None]:
    """An assertion inside a schedule, so a scenario states its own outcome."""

    def step(world: World) -> None:
        actual = world.store(store).get(world.memories[name]).lifecycle_state
        if actual is not state:
            raise AssertionError(
                f"{store}:{name} expected {state.value}, found {actual.value}"
            )
        world.log.append(f"ok: {store}:{name} is {state.value}")

    return step


# --- scenarios --------------------------------------------------------------

Scenario = tuple[str, str, list[Callable[[World], None]]]

SCENARIOS: list[Scenario] = [
    (
        "happy_path",
        "A memory crosses a boundary, is retracted, and enforcement follows.",
        [
            observe("origin", "ag-n", "Tug tyre pressure is 3.5 bar.", "fact"),
            share("origin", "fact", "alice", "fact@alice"),
            retract("origin", "fact", ["alice"]),
            dispatch("origin"),
            expect("fact@alice", LifecycleState.QUARANTINED, "alice"),
        ],
    ),
    (
        "duplicate_storm",
        "The same retraction delivered twenty times has one semantic effect.",
        [
            observe("origin", "ag-n", "Charger E01 needs a new RCD.", "fact"),
            share("origin", "fact", "alice", "fact@alice"),
            retract("origin", "fact", ["alice"]),
            dispatch("origin", times=20),
            expect("fact@alice", LifecycleState.QUARANTINED, "alice"),
        ],
    ),
    (
        "offline_then_reconcile",
        "An offline recipient converges by reconciling from its own cursor.",
        [
            observe("origin", "ag-n", "Circuit 3 is rated 32A.", "fact"),
            share("origin", "fact", "alice", "fact@alice"),
            share("origin", "fact", "bob", "fact@bob"),
            go_offline("bob"),
            retract("origin", "fact", ["alice", "bob"]),
            dispatch("origin"),
            expect("fact@alice", LifecycleState.QUARANTINED, "alice"),
            expect("fact@bob", LifecycleState.ACTIVE, "bob"),
            come_online("bob"),
            reconcile_from("bob", "origin"),
            expect("fact@bob", LifecycleState.QUARANTINED, "bob"),
        ],
    ),
    (
        "crash_before_dispatch",
        "The origin crashes after committing a retraction and before sending it.",
        [
            observe("origin", "ag-n", "Gate code is 4417.", "fact"),
            share("origin", "fact", "alice", "fact@alice"),
            retract("origin", "fact", ["alice"]),
            crash("origin"),
            dispatch("origin"),
            expect("fact@alice", LifecycleState.QUARANTINED, "alice"),
        ],
    ),
    (
        "crash_after_apply",
        "The recipient crashes after applying, and a redelivery is still idempotent.",
        [
            observe("origin", "ag-n", "Pump seal is 40mm.", "fact"),
            share("origin", "fact", "alice", "fact@alice"),
            retract("origin", "fact", ["alice"]),
            dispatch("origin"),
            crash("alice"),
            dispatch("origin", times=3),
            expect("fact@alice", LifecycleState.QUARANTINED, "alice"),
        ],
    ),
    (
        "stale_retraction_after_newer",
        "A delayed older retraction must not invalidate a revalidated version.",
        [
            observe("origin", "ag-n", "Torque is 90Nm.", "fact"),
            share("origin", "fact", "alice", "fact@alice"),
            retract("origin", "fact", ["alice"]),
            dispatch("origin"),
            expect("fact@alice", LifecycleState.QUARANTINED, "alice"),
            # Reviewed, found sound, put back into service.
            lambda world: world.store("alice").release(
                world.memories["fact@alice"], actor="reviewer"
            ),
            lambda world: world.store("alice").validate(
                world.memories["fact@alice"], actor="reviewer"
            ),
            deliver_stale("origin", "fact", "alice", sequence=0),
            expect("fact@alice", LifecycleState.ACTIVE, "alice"),
        ],
    ),
    (
        "unauthorised_sender",
        "An unauthorised retraction changes nothing and is recorded.",
        [
            observe("origin", "ag-n", "Spare keys are in the office.", "fact"),
            share("origin", "fact", "alice", "fact@alice"),
            deliver_unauthorised("origin", "fact", "alice"),
            expect("fact@alice", LifecycleState.ACTIVE, "alice"),
        ],
    ),
    (
        "independent_support_survives",
        "Retracting one of two independent premises leaves the conclusion alone.",
        [
            observe("origin", "ag1", "Tug A overheated at 40C.", "a"),
            observe("origin", "ag2", "Tug B overheated at 41C.", "b"),
            derive(
                "origin", "ag3", "Tugs overheat above 40C.", "conclusion",
                {"a": JustificationKind.ALTERNATIVE, "b": JustificationKind.ALTERNATIVE},
            ),
            retract("origin", "a", []),
            expect("conclusion", LifecycleState.ACTIVE, "origin"),
            retract("origin", "b", []),
            expect("conclusion", LifecycleState.CONTESTED, "origin"),
        ],
    ),
    (
        "derived_conclusion_at_recipient",
        "A recipient's own conclusion is contested when its imported premise is "
        "retracted at the origin, and its unrelated knowledge is not.",
        [
            observe("origin", "ag-n", "Winter pressure is 3.5 bar.", "fact"),
            share("origin", "fact", "alice", "fact@alice"),
            derive(
                "alice", "ag-a", "Inflate the yard tug to 3.5 bar.", "plan",
                {"fact@alice": JustificationKind.REQUIRED},
            ),
            observe("alice", "ag-a", "The yard gate sticks in frost.", "unrelated"),
            retract("origin", "fact", ["alice"]),
            dispatch("origin"),
            expect("fact@alice", LifecycleState.QUARANTINED, "alice"),
            expect("plan", LifecycleState.CONTESTED, "alice"),
            expect("unrelated", LifecycleState.ACTIVE, "alice"),
        ],
    ),
    (
        "fan_out_with_partial_outage",
        "Three recipients, one offline throughout, then reconciling.",
        [
            observe("origin", "ag-n", "Use grade 8.8 bolts.", "fact"),
            share("origin", "fact", "alice", "fact@alice"),
            share("origin", "fact", "bob", "fact@bob"),
            share("origin", "fact", "carol", "fact@carol"),
            go_offline("carol"),
            retract("origin", "fact", ["alice", "bob", "carol"]),
            dispatch("origin", times=3),
            expect("fact@alice", LifecycleState.QUARANTINED, "alice"),
            expect("fact@bob", LifecycleState.QUARANTINED, "bob"),
            expect("fact@carol", LifecycleState.ACTIVE, "carol"),
            come_online("carol"),
            dispatch("origin", times=2),
            expect("fact@carol", LifecycleState.QUARANTINED, "carol"),
        ],
    ),
    (
        "colliding_local_ids",
        "Two stores minting the same local id must not retract each other's "
        "memory.",
        [
            observe("origin", "ag-n", "Origin's own claim.", "mine"),
            observe("alice", "ag-a", "Alice's unrelated claim.", "theirs"),
            retract("origin", "mine", ["alice"]),
            dispatch("origin"),
            expect("theirs", LifecycleState.ACTIVE, "alice"),
        ],
    ),
    (
        "transitive_chain",
        "A retraction reaches a store the origin has never heard of.",
        [
            observe("origin", "ag-n", "Valve 7 is upstream of the pump.", "fact"),
            share("origin", "fact", "alice", "fact@alice"),
            share("alice", "fact@alice", "bob", "fact@bob"),
            retract("origin", "fact", ["alice"]),
            settle(),
            expect("fact@alice", LifecycleState.QUARANTINED, "alice"),
            # The origin named only alice. Bob is reachable at all because
            # alice recorded that she had passed the memory on.
            expect("fact@bob", LifecycleState.QUARANTINED, "bob"),
        ],
    ),
    (
        "transitive_chain_with_outage",
        "The second hop is offline when the first hop forwards.",
        [
            observe("origin", "ag-n", "Valve 7 is upstream of the pump.", "fact"),
            share("origin", "fact", "alice", "fact@alice"),
            share("alice", "fact@alice", "bob", "fact@bob"),
            go_offline("bob"),
            retract("origin", "fact", ["alice"]),
            dispatch("origin", times=2),
            dispatch("alice", times=2),
            # Still live at bob, and that is correct rather than a failure:
            # what must not happen is the obligation disappearing.
            expect("fact@bob", LifecycleState.ACTIVE, "bob"),
            come_online("bob"),
            settle(),
            expect("fact@bob", LifecycleState.QUARANTINED, "bob"),
        ],
    ),
    (
        "transitive_crash_before_forwarding",
        "The middle store crashes between applying and forwarding.",
        [
            observe("origin", "ag-n", "Valve 7 is upstream of the pump.", "fact"),
            share("origin", "fact", "alice", "fact@alice"),
            share("alice", "fact@alice", "bob", "fact@bob"),
            retract("origin", "fact", ["alice"]),
            dispatch("origin", times=2),
            # Alice has withdrawn her copy and owes bob one. The crash lands in
            # exactly that window, which is the window the obligation had to be
            # committed inside a transaction to survive.
            crash("alice"),
            settle(),
            expect("fact@alice", LifecycleState.QUARANTINED, "alice"),
            expect("fact@bob", LifecycleState.QUARANTINED, "bob"),
        ],
    ),
    (
        "diamond_both_copies",
        "Two paths to the same store withdraw both of its copies.",
        [
            observe("origin", "ag-n", "Valve 7 is upstream of the pump.", "fact"),
            share("origin", "fact", "alice", "fact@alice"),
            share("alice", "fact@alice", "bob", "via-alice@bob"),
            share("origin", "fact", "bob", "direct@bob"),
            retract("origin", "fact", ["alice", "bob"]),
            settle(),
            # Deduplicating on the campaign alone answered the second arrival
            # "already handled" and left one copy live.
            expect("via-alice@bob", LifecycleState.QUARANTINED, "bob"),
            expect("direct@bob", LifecycleState.QUARANTINED, "bob"),
        ],
    ),
    (
        "cycle_terminates",
        "A share back to the origin is refused as an echo (F12); retraction converges "
        "without a hop limit.",
        [
            observe("origin", "ag-n", "Valve 7 is upstream of the pump.", "fact"),
            share("origin", "fact", "alice", "fact@alice"),
            share("alice", "fact@alice", "bob", "fact@bob"),
            share_refused("bob", "fact@bob", "origin", "provenance chain"),
            share_refused("bob", "fact@bob", "alice", "provenance chain"),
            retract("origin", "fact", ["alice"]),
            # `settle` raises if the federation will not come to rest, so the
            # schedule itself is the termination assertion.
            settle(),
            expect("fact@alice", LifecycleState.QUARANTINED, "alice"),
            expect("fact@bob", LifecycleState.QUARANTINED, "bob"),
            expect("fact", LifecycleState.QUARANTINED, "origin"),
        ],
    ),
    (
        "restart_everything",
        "Both sides restart mid-flight and the outcome is unchanged.",
        [
            observe("origin", "ag-n", "Oil change every 250 hours.", "fact"),
            share("origin", "fact", "alice", "fact@alice"),
            retract("origin", "fact", ["alice"]),
            crash("origin"),
            crash("alice"),
            dispatch("origin", times=2),
            expect("fact@alice", LifecycleState.QUARANTINED, "alice"),
            crash("alice"),
            expect("fact@alice", LifecycleState.QUARANTINED, "alice"),
        ],
    ),
]


# --- runner -----------------------------------------------------------------


@dataclass
class ScenarioResult:
    name: str
    passed: bool
    violations: list[str] = field(default_factory=list)
    error: str = ""
    steps: int = 0
    trace: list[str] = field(default_factory=list)


def run_scenario(name: str, description: str, steps: Sequence[Callable]) -> ScenarioResult:
    with TemporaryDirectory() as tmp:
        world = World(root=Path(tmp))
        result = ScenarioResult(name=name, passed=True)
        try:
            for index, step in enumerate(steps, start=1):
                step(world)
                result.steps = index
                for check in CHECKS:
                    violations = check(world)
                    if violations:
                        result.passed = False
                        result.violations.extend(
                            f"after step {index}: {v}" for v in violations
                        )
                if not result.passed:
                    break
        except AssertionError as exc:
            result.passed = False
            result.error = str(exc)
        except Exception as exc:  # noqa: BLE001 - a crash is a result
            result.passed = False
            result.error = f"{type(exc).__name__}: {exc}"
        finally:
            result.trace = list(world.log)
            world.close()
        return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Deterministic integrity fault matrix")
    parser.add_argument("--list", action="store_true", help="name the scenarios")
    parser.add_argument("--only", help="run one scenario by name")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    if args.list:
        for name, description, steps in SCENARIOS:
            print(f"  {name:<34} {len(steps):>2} steps  {description}")
        return 0

    selected = [s for s in SCENARIOS if not args.only or s[0] == args.only]
    if not selected:
        print(f"no scenario named {args.only!r}", file=sys.stderr)
        return 2

    print("Deterministic integrity fault matrix")
    print(f"{len(selected)} scenario(s), {len(CHECKS)} invariant checks after every step\n")

    results = [run_scenario(*scenario) for scenario in selected]
    for result in results:
        mark = "PASS" if result.passed else "FAIL"
        print(f"  [{mark}] {result.name:<34} {result.steps:>2} steps")
        if result.passed:
            continue
        if result.error:
            print(f"         {result.error}")
        for violation in result.violations:
            print(f"         {violation}")
        # The schedule that produced it, so a counterexample becomes a
        # regression test by copy and paste.
        print("         schedule:")
        for line in result.trace:
            print(f"           {line}")

    failed = [r for r in results if not r.passed]
    print(f"\n{len(results) - len(failed)}/{len(results)} scenarios passed")
    if failed:
        print("A reproducible counterexample to an invariant is a bug, not a "
              "statistic. Add a regression test for each before fixing.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
