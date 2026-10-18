"""The correction preview is what the correction does.

A preview that differs from the outcome is worse than none: an operator
approves one blast radius and gets another. So the property is checked
directly, over random derivation graphs mixing conjunctions (every premise
required) and alternatives (independent premises, any one enough): preview,
apply, and compare what was predicted with what each memory's state became.
"""

from __future__ import annotations

import random
import unittest

from memory_fabric import MemoryFabric
from memory_fabric.correction import apply, preview, status
from memory_fabric.justification import JustificationKind, justification_context
from memory_fabric.model import LifecycleState, Scope


def random_graph(fabric: MemoryFabric, rng: random.Random) -> list[str]:
    ids = [fabric.remember(f"a{i % 3}", f"observation {i}: unit {rng.randint(1, 99)} "
                           f"at {rng.randint(1, 9)} bar", scope="team")
           for i in range(rng.randint(3, 6))]
    for n in range(rng.randint(4, 10)):
        parents = rng.sample(ids, min(len(ids), rng.randint(1, 3)))
        kind = rng.choice([JustificationKind.REQUIRED, JustificationKind.ALTERNATIVE])
        ids.append(fabric.derive(
            "a0", f"conclusion {n} from {len(parents)} premises", parents=parents, scope="team",
            context=justification_context([(p, kind) for p in parents])))
    return ids


class ThePreviewIsTheOutcome(unittest.TestCase):
    def test_over_random_graphs(self) -> None:
        checked = 0
        for seed in range(40):
            rng = random.Random(seed)
            fabric = MemoryFabric(":memory:", auto_activate=True)
            try:
                ids = random_graph(fabric, rng)
                target = rng.choice(ids)
                if fabric.state.memories[target].lifecycle_state is not LifecycleState.ACTIVE:
                    continue
                before = {m: fabric.state.memories[m].lifecycle_state for m in ids}
                predicted = preview(fabric, target)
                apply(fabric, target, reason="wrong", actor="carol")
                after = {m: fabric.state.memories[m].lifecycle_state for m in ids}
                with self.subTest(seed=seed):
                    self.assertIs(after[target], LifecycleState.QUARANTINED)
                    for m in predicted.would_contest:
                        self.assertIsNot(after[m], LifecycleState.ACTIVE, f"{m} predicted contested")
                    for m in predicted.would_survive:
                        self.assertIs(after[m], LifecycleState.ACTIVE, f"{m} predicted to survive")
                    changed = {m for m in ids if m != target and before[m] is LifecycleState.ACTIVE
                               and after[m] is not LifecycleState.ACTIVE}
                    self.assertEqual(changed, set(predicted.would_contest),
                                     "something changed that the preview did not name")
                checked += 1
            finally:
                fabric.close()
        self.assertGreater(checked, 30)


class IndependentSupportSurvives(unittest.TestCase):
    def test_a_conclusion_with_another_independent_premise_is_kept(self) -> None:
        fabric = MemoryFabric(":memory:", auto_activate=True)
        self.addCleanup(fabric.close)
        a = fabric.remember("ana", "tug 3 overheated at 40C in July", scope="team")
        b = fabric.remember("ben", "tug 3 engine log shows 41C in August", scope="team")
        c = fabric.derive("cho", "tug 3 runs hot", parents=[a, b], scope="team",
                          context=justification_context([(a, JustificationKind.ALTERNATIVE),
                                                         (b, JustificationKind.ALTERNATIVE)]))
        self.assertEqual(preview(fabric, a).would_survive, [c])
        self.assertEqual(preview(fabric, a).would_contest, [])


class StoresAreOwedTheRetraction(unittest.TestCase):
    def test_apply_owes_every_store_that_received_it_and_status_follows(self) -> None:
        from memory_fabric.dispatcher import Dispatcher
        from memory_fabric.federation import offer
        from memory_fabric.governance.firewall import (Firewall, rule_capabilities_must_be_granted,
                                                       rule_must_be_active,
                                                       rule_restricted_stays_private)
        from memory_fabric.transport import InProcessTransport, Peer, PeerRegistry

        permissive = Firewall(rules=(rule_restricted_stays_private, rule_must_be_active,
                                     rule_capabilities_must_be_granted))
        origin = MemoryFabric(":memory:", firewall=permissive, auto_activate=True)
        recipient = MemoryFabric(":memory:", firewall=permissive)
        self.addCleanup(origin.close)
        self.addCleanup(recipient.close)
        mid = origin.remember("ana", "tug tyre pressure is 3.5 bar")
        origin.share(mid, Scope.FEDERATED, actor="op")
        offer(origin, mid, recipient, recipient_agent="ben")
        self.assertEqual([s["store_id"] for s in preview(origin, mid).stores], [recipient.store_id])
        result = apply(origin, mid, reason="bulletin: 2.8 bar", actor="carol")
        self.assertEqual(result["owed_to"], [recipient.store_id])
        self.assertEqual([s["state"] for s in status(origin, mid)], ["queued"])
        registry = PeerRegistry({origin.store_id: Peer(origin.store_id, "x", b"k")})
        Dispatcher(origin, InProcessTransport({recipient.store_id: recipient},
                                              registry=registry)).run_once()
        self.assertEqual([s["state"] for s in status(origin, mid)], ["enforced"])

    def test_a_correction_needs_a_named_actor(self) -> None:
        fabric = MemoryFabric(":memory:", auto_activate=True)
        self.addCleanup(fabric.close)
        mid = fabric.remember("ana", "x")
        with self.assertRaises(ValueError):
            apply(fabric, mid, reason="wrong", actor="operator")


class TheCommand(unittest.TestCase):
    def test_preview_then_apply_from_the_command_line(self) -> None:
        import contextlib
        import io
        import os
        import tempfile

        from memory_fabric.cli import main

        with tempfile.TemporaryDirectory() as tmp:
            db = os.path.join(tmp, "s.db")
            fabric = MemoryFabric(db, auto_activate=True)
            root = fabric.remember("ana", "tug 3 overheated at 40C", scope="team")
            child = fabric.derive("cho", "tug 3 runs hot", parents=[root], scope="team")
            fabric.close()
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(main(["--db", db, "--json", "correct", root]), 0)
            self.assertEqual(__import__("json").loads(out.getvalue())["would_contest"], [child])
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(["--db", db, "correct", root, "--apply",
                                       "--reason", "sensor fault", "--actor", "carol"]), 0)
            reopened = MemoryFabric(db)
            try:
                self.assertIs(reopened.state.memories[root].lifecycle_state,
                              LifecycleState.QUARANTINED)
                self.assertIsNot(reopened.state.memories[child].lifecycle_state,
                                 LifecycleState.ACTIVE)
            finally:
                reopened.close()


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
