"""Property tests over the propagation state machine and the lineage graph.

`test_properties.py` walks random *operation* sequences against a store. This
file walks random *shapes*: adversarial transition orders through the
propagation machine, and randomly generated derivation graphs — chains,
diamonds, wide fan-out, shared roots, attempted cycles.

Shapes rather than operations because both of these have already produced bugs
that a linear walk would not reach. `_imports_of` quarantined a recipient's own
conclusions because a derived memory inherits its parent's federation origin —
needs a derivation edge *over* an import to show up. Root grouping and premise
promotion undid each other — needs a premise and conclusion sharing a root.
Independence checking missed lost premises — needs a diamond.

Seeded and bounded. A failure prints the seed, and re-running with it
reproduces the case exactly; a property test whose counterexample cannot be
replayed is a flake generator.
"""

from __future__ import annotations

import random
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from memory_fabric import LifecycleState, MemoryFabric
from memory_fabric.federation import offer
from memory_fabric.governance.firewall import (
    Firewall,
    rule_capabilities_must_be_granted,
    rule_must_be_active,
    rule_restricted_stays_private,
)
from memory_fabric.justification import JustificationKind, justification_context
from memory_fabric.protocol import (
    ALLOWED_TRANSITIONS,
    SETTLED_STATES,
    TERMINAL_STATES,
    PropagationState,
    can_transition,
)

SEEDS = range(12)


def permissive() -> Firewall:
    return Firewall(
        rules=[
            rule_must_be_active,
            rule_restricted_stays_private,
            rule_capabilities_must_be_granted,
        ]
    )


class ThePropagationMachineHolds(unittest.TestCase):
    """Random walks through the declared transitions.

    `ALLOWED_TRANSITIONS` is data, which is what makes this possible: the
    properties are checked against the declaration rather than against a
    second copy of the rules written in the test.
    """

    def test_a_random_walk_never_leaves_the_declared_graph(self) -> None:
        for seed in SEEDS:
            rng = random.Random(seed)
            with self.subTest(seed=seed):
                state = PropagationState.REQUESTED
                for _ in range(40):
                    allowed = sorted(ALLOWED_TRANSITIONS.get(state, set()),
                                     key=lambda s: s.value)
                    if not allowed:
                        break
                    nxt = rng.choice(allowed)
                    self.assertTrue(
                        can_transition(state, nxt),
                        f"seed {seed}: {state.value} -> {nxt.value} declared but refused",
                    )
                    state = nxt

    def test_a_terminal_state_is_terminal(self) -> None:
        """Nothing leaves `rejected`, `superseded`, `failed` or `verified`.

        This property is what split `TERMINAL_STATES` from `SETTLED_STATES`.
        One constant held both, and `enforced` was in it while declaring an
        outgoing transition to `verified` — so the set was simultaneously "no
        further transitions" and "no longer owed", and `enforced` answers those
        differently.
        """
        for state in TERMINAL_STATES:
            with self.subTest(state.value):
                self.assertEqual(
                    ALLOWED_TRANSITIONS.get(state, set()), set(),
                    f"{state.value} has outgoing transitions",
                )
                for other in PropagationState:
                    if other is state:
                        continue
                    self.assertFalse(
                        can_transition(state, other),
                        f"{state.value} -> {other.value}",
                    )

    def test_every_random_pair_outside_the_graph_is_refused(self) -> None:
        """The negative direction: anything not declared must be refused.

        A machine that accepts undeclared transitions is not a machine, and the
        declaration would be documentation rather than enforcement.
        """
        states = list(PropagationState)
        for seed in SEEDS:
            rng = random.Random(seed)
            with self.subTest(seed=seed):
                for _ in range(60):
                    source = rng.choice(states)
                    target = rng.choice(states)
                    declared = target in ALLOWED_TRANSITIONS.get(source, set())
                    self.assertEqual(
                        can_transition(source, target), declared,
                        f"{source.value} -> {target.value}",
                    )

    def test_settled_is_not_the_same_as_terminal(self) -> None:
        """`enforced` is settled and not terminal, and the distinction is
        load-bearing: collapsing them means either an unreachable `verified` or
        an enforced delivery that `pending()` reports forever."""
        self.assertIn(PropagationState.ENFORCED, SETTLED_STATES)
        self.assertNotIn(PropagationState.ENFORCED, TERMINAL_STATES)
        self.assertTrue(TERMINAL_STATES < SETTLED_STATES)
        self.assertTrue(
            can_transition(PropagationState.ENFORCED, PropagationState.VERIFIED)
        )

    def test_enforced_cannot_regress(self) -> None:
        """Specifically pinned because it is the one an out-of-order
        acknowledgement would try."""
        for earlier in (PropagationState.QUEUED, PropagationState.DELIVERED,
                        PropagationState.PERSISTED):
            with self.subTest(earlier.value):
                self.assertFalse(can_transition(PropagationState.ENFORCED, earlier))

    def test_the_outbox_refuses_an_undeclared_transition_rather_than_raising(self) -> None:
        """`advance` returns False rather than throwing, so a late duplicate
        acknowledgement cannot take down a dispatcher."""
        from memory_fabric.outbox import Outbox, now_ms

        fabric = MemoryFabric(":memory:")
        self.addCleanup(fabric.close)
        outbox: Outbox = fabric.outbox
        from memory_fabric.protocol import Retraction, new_retraction_id

        retraction = Retraction(
            retraction_id=new_retraction_id(),
            origin_store_id=fabric.store_id,
            origin_memory_id="m1",
            origin_memory_version=1,
            origin_sequence=1,
            reason_code="contradicted",
            requested_by="ops",
            issued_at="now",
        )
        with fabric.log.transaction():
            outbox.enqueue(retraction, ["st_peer"], now_ms())
        self.assertTrue(
            outbox.advance(retraction.retraction_id, "st_peer",
                           PropagationState.DELIVERED, now_ms())
        )
        # Via `persisted`: `delivered -> enforced` is not a declared edge,
        # because committing an event and rebuilding the projections that act
        # on it are separate acts. My first version of this test skipped the
        # step and read the refusal as a bug.
        self.assertTrue(
            outbox.advance(retraction.retraction_id, "st_peer",
                           PropagationState.PERSISTED, now_ms())
        )
        self.assertTrue(
            outbox.advance(retraction.retraction_id, "st_peer",
                           PropagationState.ENFORCED, now_ms())
        )
        # Backwards: refused, not raised.
        self.assertFalse(
            outbox.advance(retraction.retraction_id, "st_peer",
                           PropagationState.QUEUED, now_ms())
        )
        self.assertIs(
            outbox.state_of(retraction.retraction_id, "st_peer"),
            PropagationState.ENFORCED,
        )


class TheLineageGraphHoldsOverRandomShapes(unittest.TestCase):
    """Random derivation graphs, then the invariants that must survive them."""

    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def _store(self, name: str) -> MemoryFabric:
        fabric = MemoryFabric(
            self.dir / f"{name}.db", firewall=permissive(), auto_activate=True
        )
        self.addCleanup(fabric.close)
        return fabric

    def _random_graph(self, fabric: MemoryFabric, rng: random.Random, size: int):
        """Build a random DAG of memories.

        Parents are always chosen from *already created* memories, which makes
        a cycle unconstructible — and that is the point rather than a
        limitation: `derive` takes existing ids, so the data model cannot
        express a cycle and a test that tried to build one would be testing the
        test.
        """
        created: list[str] = []
        for index in range(size):
            if created and rng.random() < 0.65:
                count = rng.randint(1, min(3, len(created)))
                parents = rng.sample(created, count)
                memory_id = fabric.derive(
                    agent_id="ag",
                    content=f"conclusion {index} from {len(parents)} premise(s)",
                    parents=parents,
                )
            else:
                memory_id = fabric.remember(
                    agent_id="ag", content=f"observation {index}"
                )
            created.append(memory_id)
        return created

    def test_ancestor_walks_terminate_and_exclude_self(self) -> None:
        for seed in SEEDS:
            with self.subTest(seed=seed):
                rng = random.Random(seed)
                fabric = self._store(f"anc{seed}")
                created = self._random_graph(fabric, rng, size=14)
                graph = fabric.lineage_graph
                for memory_id in created:
                    ancestors = {node.memory_id for node in graph.ancestors(memory_id)}
                    self.assertNotIn(
                        memory_id, ancestors, f"seed {seed}: {memory_id} is its own ancestor"
                    )
                    self.assertLessEqual(len(ancestors), len(created))

    def test_every_memory_has_at_least_one_root(self) -> None:
        """A memory with no root would make `source_root` arbitrary, and the
        grouping key depends on it being deterministic."""
        for seed in SEEDS:
            with self.subTest(seed=seed):
                rng = random.Random(seed)
                fabric = self._store(f"root{seed}")
                created = self._random_graph(fabric, rng, size=14)
                for memory_id in created:
                    roots = fabric.lineage_graph.roots(memory_id)
                    self.assertTrue(roots, f"seed {seed}: {memory_id} has no root")
                    # The root of an observation is itself.
                    if not fabric.state.parents.get(memory_id):
                        self.assertEqual(roots, [memory_id])

    def test_source_root_is_stable_and_deterministic(self) -> None:
        """Called twice must give the same answer, and the answer must not
        depend on walk order — a grouping key that varied by insertion order
        would make deduplication nondeterministic."""
        for seed in SEEDS:
            with self.subTest(seed=seed):
                rng = random.Random(seed)
                fabric = self._store(f"stable{seed}")
                created = self._random_graph(fabric, rng, size=12)
                first = {m: fabric.source_root(m) for m in created}
                second = {m: fabric.source_root(m) for m in reversed(created)}
                self.assertEqual(first, second)

    def test_a_descendant_is_never_its_ancestors_ancestor(self) -> None:
        """Antisymmetry. A violation would mean the graph has a cycle, and a
        cycle would make retraction cascades non-terminating."""
        for seed in SEEDS:
            with self.subTest(seed=seed):
                rng = random.Random(seed)
                fabric = self._store(f"anti{seed}")
                created = self._random_graph(fabric, rng, size=12)
                graph = fabric.lineage_graph
                for memory_id in created:
                    for node in graph.ancestors(memory_id):
                        back = {n.memory_id for n in graph.ancestors(node.memory_id)}
                        self.assertNotIn(
                            memory_id, back,
                            f"seed {seed}: cycle between {memory_id} and {node.memory_id}",
                        )

    def test_quarantining_a_root_never_deletes_a_descendant(self) -> None:
        """The project's central question, over random shapes.

        A conclusion losing its support becomes contested. It must never become
        deleted, and it must never stay plain `active` with no support at all.
        """
        for seed in SEEDS:
            with self.subTest(seed=seed):
                rng = random.Random(seed)
                fabric = self._store(f"quar{seed}")
                created = self._random_graph(fabric, rng, size=12)
                roots = [m for m in created if not fabric.state.parents.get(m)]
                if not roots:
                    continue
                victim = rng.choice(roots)
                fabric.quarantine(
                    victim, reason="contradicted", actor="ops", basis="contradicted"
                )
                for memory_id in created:
                    state = fabric.get(memory_id).lifecycle_state
                    self.assertIsNot(
                        state, LifecycleState.DELETED,
                        f"seed {seed}: {memory_id} was deleted by a quarantine",
                    )

    def test_a_conjunction_is_contested_when_any_premise_is_lost(self) -> None:
        """`derive`'s default is `REQUIRED`, i.e. a conjunction — the safe
        reading, since a caller who says nothing about independence has not
        established it.

        My first version of this test asserted the conclusion stayed ACTIVE
        after losing one of two premises, and called the CONTESTED result a
        bug. It was the test that was wrong: two parents are a conjunction
        unless the caller says otherwise, and both halves of that are
        deliberate.
        """
        for seed in SEEDS:
            with self.subTest(seed=seed):
                fabric = self._store(f"conj{seed}")
                first = fabric.remember(agent_id="ag", content="premise A")
                second = fabric.remember(agent_id="ag", content="premise B")
                conclusion = fabric.derive(
                    agent_id="ag", content="A and B therefore C",
                    parents=[first, second],
                )
                fabric.quarantine(
                    first, reason="contradicted", actor="ops", basis="contradicted"
                )
                self.assertIs(
                    fabric.get(conclusion).lifecycle_state,
                    LifecycleState.CONTESTED,
                    "a conjunction loses its support when any premise goes",
                )
                self.assertIsNot(
                    fabric.get(conclusion).lifecycle_state, LifecycleState.DELETED
                )

    def test_genuine_alternatives_survive_losing_one(self) -> None:
        """The invariant the justification layer exists for, with the edge
        kinds actually declared.

        `ALTERNATIVE` is what "two independent premises" means in the data
        model; it has to be supplied at `derive` time because that is the only
        moment the caller knows, and nothing can recover it afterwards.
        """
        for seed in SEEDS:
            with self.subTest(seed=seed):
                fabric = self._store(f"alt{seed}")
                first = fabric.remember(agent_id="ag", content="measurement A says 3.5")
                second = fabric.remember(agent_id="ag", content="measurement B says 3.5")
                conclusion = fabric.derive(
                    agent_id="ag", content="the limit is 3.5",
                    parents=[first, second],
                    context=justification_context(
                        [
                            (first, JustificationKind.ALTERNATIVE),
                            (second, JustificationKind.ALTERNATIVE),
                        ]
                    ),
                )
                fabric.quarantine(
                    first, reason="instrument fault", actor="ops",
                    basis="contradicted",
                )
                self.assertIs(
                    fabric.get(conclusion).lifecycle_state,
                    LifecycleState.ACTIVE,
                    "an alternative premise surviving must keep the conclusion",
                )
                fabric.quarantine(
                    second, reason="instrument fault", actor="ops",
                    basis="contradicted",
                )
                self.assertIsNot(
                    fabric.get(conclusion).lifecycle_state,
                    LifecycleState.ACTIVE,
                    "with every alternative gone, the conclusion must not stand",
                )
                self.assertIsNot(
                    fabric.get(conclusion).lifecycle_state, LifecycleState.DELETED
                )

    def test_a_derived_conclusion_at_a_recipient_is_not_treated_as_an_import(self) -> None:
        """The bug that appeared twice, over random shapes.

        `derive` inherits its parent's context, federation origin record
        included, so a locally derived conclusion looks exactly like a second
        copy of an import to anything matching on the origin key. It made
        `descendants_of` and then `_imports_of` quarantine a recipient's own
        conclusions outright.
        """
        for seed in SEEDS:
            with self.subTest(seed=seed):
                rng = random.Random(seed)
                origin = self._store(f"o{seed}")
                recipient = self._store(f"r{seed}")
                shared = origin.remember(
                    agent_id="ag", content="valve 7 is upstream of the pump"
                )
                imported = offer(origin, shared, recipient, "ag-b", activate=True)
                self.assertTrue(imported.accepted, imported.reasons)

                local = [
                    recipient.remember(agent_id="ag-b", content=f"local fact {i}")
                    for i in range(rng.randint(1, 3))
                ]
                conclusion = recipient.derive(
                    agent_id="ag-b",
                    content="therefore the pump is limited",
                    parents=[imported.imported_memory_id, *local],
                )

                origin.request_retraction(
                    shared, reason="contradicted",
                    recipients=[recipient.store_id], basis="contradicted",
                )
                from memory_fabric.dispatcher import Dispatcher
                from memory_fabric.transport import InProcessTransport

                transport = InProcessTransport(
                    {origin.store_id: origin, recipient.store_id: recipient}
                )
                Dispatcher(origin, transport).drain()

                self.assertIs(
                    recipient.get(imported.imported_memory_id).lifecycle_state,
                    LifecycleState.QUARANTINED,
                    "the import itself must be withdrawn",
                )
                self.assertIsNot(
                    recipient.get(conclusion).lifecycle_state,
                    LifecycleState.QUARANTINED,
                    f"seed {seed}: the recipient's own conclusion was quarantined "
                    "outright instead of having its support recomputed",
                )
                for memory_id in local:
                    self.assertIs(
                        recipient.get(memory_id).lifecycle_state,
                        LifecycleState.ACTIVE,
                        "an unrelated local memory must be untouched",
                    )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
