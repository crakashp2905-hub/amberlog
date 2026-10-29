"""Property-based tests over many event sequences (roadmap §8).

The testing-layers table names five: unit, property-based, integration, system
and regression. Four existed; this is the missing one. Its job is the sequences
nobody thought to write down — duplicates, reordering, interleaved lifecycle
transitions — where the bug is in a combination rather than in a step.

Implemented with a seeded random walk rather than Hypothesis, because the core
is zero-dependency and adding a test-only dependency to CI would break the
"tests run with nothing installed" job that keeps that claim honest. The
trade-off is real and worth naming: no shrinking, so a failure prints the whole
sequence and the seed. That is enough to reproduce, which is what §5.4 asks of a
counterexample.

Each property is checked after **every** operation, not at the end. A property
that only holds at the end of a walk is a coincidence about that walk.
"""

from __future__ import annotations

import random
import sqlite3
import unittest

from amberlog import LifecycleState, Amberlog, WithdrawalBasis
from amberlog.enforcement import Verdict
from amberlog.justification import JustificationKind, justification_context
from amberlog.model import BLOCKED_STATES, EXPOSABLE_STATES
from amberlog.protocol import (
    PropagationState,
    Retraction,
    can_transition,
    new_retraction_id,
    new_store_id,
)

WALK_LENGTH = 60
WALKS = 12


class Walk:
    """A seeded sequence of fabric operations, with its own trace."""

    def __init__(self, seed: int) -> None:
        self.rng = random.Random(seed)
        self.seed = seed
        self.fabric = Amberlog(":memory:")
        self.memories: list[str] = []
        self.trace: list[str] = []

    def close(self) -> None:
        try:
            self.fabric.close()
        except Exception:
            pass

    # --- operations ------------------------------------------------------

    def remember(self) -> None:
        memory_id = self.fabric.remember(
            f"ag{self.rng.randint(1, 3)}",
            f"observation {len(self.memories)} about fault E{self.rng.randint(1, 4):02d}",
        )
        self.memories.append(memory_id)
        self.trace.append(f"remember -> {memory_id[-6:]}")

    def validate(self) -> None:
        target = self._pick(lambda m: m.lifecycle_state is LifecycleState.CANDIDATE)
        if target is None:
            return
        self.fabric.validate(target, actor="supervisor")
        self.trace.append(f"validate {target[-6:]}")

    def derive(self) -> None:
        usable = [
            m for m in self.memories
            if self.fabric.get(m).lifecycle_state in EXPOSABLE_STATES
        ]
        if len(usable) < 2:
            return
        parents = self.rng.sample(usable, 2)
        kind = self.rng.choice(
            [JustificationKind.REQUIRED, JustificationKind.ALTERNATIVE]
        )
        memory_id = self.fabric.derive(
            "ag1", f"conclusion {len(self.memories)}", parents=parents,
            context=justification_context([(p, kind) for p in parents]),
        )
        self.memories.append(memory_id)
        self.trace.append(
            f"derive -> {memory_id[-6:]} from {[p[-6:] for p in parents]} as {kind.value}"
        )

    def quarantine(self) -> None:
        target = self._pick(
            lambda m: m.lifecycle_state not in BLOCKED_STATES
        )
        if target is None:
            return
        basis = self.rng.choice(list(WithdrawalBasis))
        self.fabric.quarantine(
            target, reason="walk", actor="walker", basis=basis
        )
        self.trace.append(f"quarantine {target[-6:]} ({basis.value})")

    def release(self) -> None:
        target = self._pick(
            lambda m: m.lifecycle_state is LifecycleState.QUARANTINED
        )
        if target is None:
            return
        self.fabric.release(target, actor="reviewer")
        self.trace.append(f"release {target[-6:]}")

    def revise(self) -> None:
        # Erased memories are deliberately unrevisable: writing a new version
        # would make the content readable again. The walk respects the rule
        # rather than asserting against it — it was the walk that found it.
        target = self._pick(
            lambda m: m.lifecycle_state in EXPOSABLE_STATES
            and m.id not in self.fabric.state.erased
        )
        if target is None:
            return
        self.fabric.revise(
            target, f"revised {self.rng.randint(0, 999)}",
            agent_id="ag1", reason="walk",
        )
        self.trace.append(f"revise {target[-6:]}")

    def retract_durably(self) -> None:
        target = self._pick(lambda m: m.lifecycle_state not in BLOCKED_STATES)
        if target is None:
            return
        recipients = [new_store_id() for _ in range(self.rng.randint(1, 3))]
        self.fabric.request_retraction(
            target, reason="walk", recipients=recipients, actor="walker",
            basis=WithdrawalBasis.CONTRADICTED,
        )
        self.trace.append(f"request_retraction {target[-6:]} to {len(recipients)}")

    def receive_duplicate(self) -> None:
        """A retraction from a notional peer, delivered one to three times."""
        if not self.memories:
            return
        retraction = Retraction(
            retraction_id=new_retraction_id(),
            origin_store_id=new_store_id(),
            origin_memory_id=self.rng.choice(self.memories),
            origin_memory_version=1,
            origin_sequence=self.rng.randint(0, 50),
            reason_code=WithdrawalBasis.CONTRADICTED.value,
            requested_by="ag_peer",
            issued_at="2026-10-10T12:00:00Z",
        )
        for _ in range(self.rng.randint(1, 3)):
            self.fabric.receive_retraction(retraction, sender_authorised=True)
        self.trace.append("receive_retraction (duplicated)")

    def erase(self) -> None:
        target = self._pick(lambda m: True)
        if target is None:
            return
        self.fabric.erase_content(target, reason="walk", actor="dpo")
        self.trace.append(f"erase {target[-6:]}")

    def rebuild(self) -> None:
        self.fabric.rebuild()
        self.trace.append("rebuild")

    def _pick(self, predicate) -> str | None:
        candidates = [m for m in self.memories if predicate(self.fabric.get(m))]
        return self.rng.choice(candidates) if candidates else None

    OPERATIONS = (
        remember, remember, validate, validate, derive, derive,
        quarantine, release, revise, retract_durably, receive_duplicate,
        erase, rebuild,
    )

    def step(self) -> None:
        self.rng.choice(self.OPERATIONS)(self)


# --- properties -------------------------------------------------------------


def property_blocked_is_never_retrievable(walk: Walk) -> str | None:
    fabric = walk.fabric
    for memory_id, memory in fabric.state.memories.items():
        if memory.lifecycle_state not in BLOCKED_STATES:
            continue
        hits = fabric.retrieve("probe", memory.content, k=10)
        if memory_id in {m.id for m in hits.exposed}:
            return f"blocked {memory_id[-6:]} was retrievable"
    return None


def property_use_agrees_with_lifecycle(walk: Walk) -> str | None:
    """The enforcement layer and the lifecycle state cannot disagree."""
    fabric = walk.fabric
    for memory_id, memory in fabric.state.memories.items():
        decision = fabric.enforcer.check(memory_id)
        if memory.lifecycle_state in EXPOSABLE_STATES:
            if decision.verdict is not Verdict.USABLE:
                return f"{memory_id[-6:]} is active but {decision.verdict.value}"
        elif memory.lifecycle_state in BLOCKED_STATES:
            if decision.usable:
                return f"{memory_id[-6:]} is {memory.lifecycle_state.value} but usable"
    return None


def property_event_count_never_falls(walk: Walk) -> str | None:
    count = len(walk.fabric.log)
    previous = getattr(walk, "_events_seen", 0)
    walk._events_seen = max(previous, count)  # type: ignore[attr-defined]
    if count < previous:
        return f"event count fell from {previous} to {count}"
    return None


def property_one_apply_per_retraction(walk: Walk) -> str | None:
    seen: dict[tuple[str, str], int] = {}
    for event in walk.fabric.log.read():
        if event.type != "RetractionApplied":
            continue
        key = (event.payload["retraction_id"], event.payload["local_memory_id"])
        seen[key] = seen.get(key, 0) + 1
    for (retraction_id, local_id), count in seen.items():
        if count > 1:
            return f"retraction {retraction_id[-6:]} applied {count}x to {local_id[-6:]}"
    return None


def property_contested_has_no_surviving_justification(walk: Walk) -> str | None:
    """Invariant 8, as a property: nothing contested by a retraction should
    still have independent support."""
    fabric = walk.fabric
    for memory_id, memory in fabric.state.memories.items():
        if memory.lifecycle_state is not LifecycleState.CONTESTED:
            continue
        if memory.hypothesis_set:
            continue  # contested by a genuine disagreement
        if fabric.justifications.recompute(memory_id).still_justified:
            return f"{memory_id[-6:]} is contested but still justified"
    return None


def property_erased_content_stays_erased(walk: Walk) -> str | None:
    fabric = walk.fabric
    for memory_id in fabric.vault.erased_ids():
        memory = fabric.state.memories.get(memory_id)
        if memory is None:
            continue
        if "[CONTENT ERASED]" not in memory.content:
            return f"erased {memory_id[-6:]} reads as content again"
    return None


def property_outbox_rows_exist_for_every_request(walk: Walk) -> str | None:
    fabric = walk.fabric
    for event in fabric.log.read():
        if event.type != "RetractionRequested":
            continue
        retraction_id = event.payload["retraction_id"]
        for recipient in event.payload.get("recipients", []):
            if fabric.outbox.state_of(retraction_id, recipient) is PropagationState.UNKNOWN:
                return f"retraction {retraction_id[-6:]} lost its row for {recipient[-6:]}"
    return None


def property_versions_only_increase(walk: Walk) -> str | None:
    fabric = walk.fabric
    for memory_id, memory in fabric.state.memories.items():
        history = fabric.state.history.get(memory_id, ())
        versions = [h.version for h in history] + [memory.version]
        if versions != sorted(versions):
            return f"{memory_id[-6:]} versions out of order: {versions}"
    return None


PROPERTIES = (
    property_event_count_never_falls,
    property_blocked_is_never_retrievable,
    property_use_agrees_with_lifecycle,
    property_one_apply_per_retraction,
    property_contested_has_no_surviving_justification,
    property_erased_content_stays_erased,
    property_outbox_rows_exist_for_every_request,
    property_versions_only_increase,
)


class TestRandomWalks(unittest.TestCase):
    """Many event sequences, each property checked after every operation."""

    def test_properties_hold_across_seeded_walks(self) -> None:
        for seed in range(WALKS):
            walk = Walk(seed)
            try:
                for index in range(WALK_LENGTH):
                    walk.step()
                    for prop in PROPERTIES:
                        violation = prop(walk)
                        if violation:
                            self.fail(
                                f"seed {seed}, step {index + 1}: {violation}\n"
                                f"  property: {prop.__name__}\n"
                                f"  sequence:\n    "
                                + "\n    ".join(walk.trace)
                            )
            finally:
                walk.close()

    def test_a_walk_actually_exercises_the_interesting_operations(self) -> None:
        """A property suite that silently stopped doing anything would still
        pass. This asserts the walks reach the states the properties are about.
        """
        kinds: set[str] = set()
        for seed in range(WALKS):
            walk = Walk(seed)
            try:
                for _ in range(WALK_LENGTH):
                    walk.step()
                kinds.update(line.split()[0] for line in walk.trace)
            finally:
                walk.close()
        for required in (
            "remember", "validate", "derive", "quarantine", "release",
            "revise", "request_retraction", "receive_retraction", "erase",
            "rebuild",
        ):
            self.assertIn(required, kinds, f"no walk ever performed {required}")


class TestStateMachineProperties(unittest.TestCase):
    """The propagation state machine, exhaustively rather than by sampling."""

    def test_no_state_can_reach_itself_by_a_declared_transition(self) -> None:
        for state in PropagationState:
            self.assertFalse(
                can_transition(state, state), f"{state.value} declares a self-loop"
            )

    def test_terminal_states_have_no_exits(self) -> None:
        for state in (
            PropagationState.VERIFIED,
            PropagationState.REJECTED,
            PropagationState.SUPERSEDED,
            PropagationState.FAILED,
        ):
            for target in PropagationState:
                self.assertFalse(
                    can_transition(state, target),
                    f"{state.value} -> {target.value} should not exist",
                )

    def test_every_state_is_reachable_from_requested(self) -> None:
        """An unreachable state is dead code pretending to be a guarantee."""
        reachable = {PropagationState.REQUESTED}
        frontier = [PropagationState.REQUESTED]
        while frontier:
            current = frontier.pop()
            for target in PropagationState:
                if can_transition(current, target) and target not in reachable:
                    reachable.add(target)
                    frontier.append(target)
        self.assertEqual(
            set(PropagationState) - reachable, set(), "unreachable states exist"
        )

    def test_enforced_is_only_reachable_through_persisted(self) -> None:
        """Committing an event and rebuilding the projections that act on it are
        separate acts, and the ordering is the point."""
        into_enforced = [
            state for state in PropagationState
            if can_transition(state, PropagationState.ENFORCED)
        ]
        self.assertEqual(into_enforced, [PropagationState.PERSISTED])


class TestAppendOnlyUnderWalks(unittest.TestCase):
    def test_the_triggers_survive_every_operation(self) -> None:
        walk = Walk(99)
        self.addCleanup(walk.close)
        for _ in range(WALK_LENGTH):
            walk.step()
        with self.assertRaises(sqlite3.IntegrityError):
            walk.fabric.log._conn.execute("DELETE FROM events WHERE seq = 1")
        with self.assertRaises(sqlite3.IntegrityError):
            walk.fabric.log._conn.execute("UPDATE events SET payload = '{}'")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
