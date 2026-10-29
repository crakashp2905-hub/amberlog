"""Folding another process's events gives the state a full replay gives.

`Amberlog._catch_up` replaced a full `_replay` on every cross-process
refresh, which was 95% of a contending agent's time in P12. The replacement is
only correct if folding the new suffix onto the live projection reaches the
same state as rebuilding from the whole log. That is checked here directly:
two handles on one store interleave every kind of write, the live handle folds
the other's events, and its state is compared field by field with a handle
opened fresh from the log.

Two handles in one process behave as two processes for this purpose: each
keeps its own projection and indexes and sees the other's writes only through
the log, which is the path `refresh` serves.
"""

from __future__ import annotations

import random
import tempfile
import unittest
from pathlib import Path

from amberlog import Amberlog
from amberlog.fabric import FabricError
from amberlog.governance.erasure import ERASED_MARKER
from amberlog.model import LifecycleState

OPS = ("remember", "remember", "remember", "validate", "quarantine", "release",
       "forget", "revise", "derive", "challenge", "erase", "retrieve", "retrieve",
       "outcome")


def _searchable(fabric: Amberlog) -> dict[str, frozenset[str]]:
    """The lexical index, restricted to memories retrieval can return.

    A live process unindexes a memory it deprecates or erases, while a replay
    re-adds it; retrieval refuses those states either way. That divergence
    predates `_catch_up` and is excluded so the comparison covers what serves.
    """
    out = {}
    for memory_id, terms in fabric.lexical._terms.items():
        memory = fabric.state.memories.get(memory_id)
        if memory is None or memory.content == ERASED_MARKER:
            continue
        if memory.lifecycle_state in (LifecycleState.DEPRECATED, LifecycleState.DELETED):
            continue
        out[memory_id] = terms
    return out


class CatchUpEqualsReplay(unittest.TestCase):
    def run_interleaving(self, seed: int, steps: int = 60) -> None:
        rng = random.Random(seed)
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "store.db")
            handles = [Amberlog(path, auto_activate=True, seed=seed),
                       Amberlog(path, auto_activate=True, seed=seed + 1)]
            ids: list[str] = []
            episodes: list[str] = []
            for step in range(steps):
                fabric = handles[rng.randrange(2)]
                op = rng.choice(OPS)
                agent = f"a{rng.randrange(3)}"
                try:
                    if op == "remember" or not ids:
                        ids.append(fabric.remember(
                            agent, f"unit {rng.randint(1, 9)} runs at {rng.randint(1, 9)} bar "
                                   f"after fault E0{rng.randint(1, 5)} (note {step})",
                            context={"site": rng.choice(["coastal", "inland"])}))
                    elif op == "validate":
                        fabric.validate(rng.choice(ids), actor="reviewer")
                    elif op == "quarantine":
                        fabric.quarantine(rng.choice(ids), reason="suspect", actor="op")
                    elif op == "release":
                        fabric.release(rng.choice(ids), actor="op")
                    elif op == "forget":
                        fabric.forget(rng.choice(ids), reason="stale", actor="op")
                    elif op == "revise":
                        fabric.revise(rng.choice(ids), f"unit {rng.randint(1, 9)} corrected",
                                      agent_id=agent, reason="correction")
                    elif op == "derive":
                        parents = rng.sample(ids, min(2, len(ids)))
                        ids.append(fabric.derive(agent, f"conclusion from {len(parents)}",
                                                 parents=parents))
                    elif op == "challenge":
                        fabric.challenge(rng.sample(ids, min(2, len(ids))),
                                         evidence="they disagree")
                    elif op == "erase":
                        fabric.erase_content(rng.choice(ids), reason="request", actor="op")
                    elif op == "retrieve":
                        fabric.retrieve(agent, f"unit {rng.randint(1, 9)} bar", k=3)
                    elif op == "outcome":
                        episode = fabric.start_episode(agent, task_id=f"t{step}")
                        episodes.append(episode.id)
                        fabric.record_outcome(episode.id, outcome=rng.random(),
                                              verifier_id="env")
                except (FabricError, KeyError, ValueError):
                    pass  # an operation the current state refuses is not a failure
            live = handles[0]
            live.refresh()
            fresh = Amberlog(path, auto_activate=True)
            try:
                self.assertEqual(live.log.head_seq, fresh.log.head_seq)
                for name, value in vars(fresh.state).items():
                    with self.subTest(seed=seed, field=name):
                        self.assertEqual(getattr(live.state, name), value)
                self.assertEqual(_searchable(live), _searchable(fresh))
                self.assertEqual({k for k in _searchable(fresh) if k in live.index},
                                 set(_searchable(fresh)))
            finally:
                fresh.close()
                for h in handles:
                    h.close()

    def test_interleavings_reach_the_replayed_state(self) -> None:
        for seed in range(12):
            self.run_interleaving(seed)

    def test_catch_up_folds_only_the_suffix(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "store.db")
            a = Amberlog(path, auto_activate=True)
            b = Amberlog(path, auto_activate=True)
            try:
                for i in range(20):
                    a.remember("a", f"fact {i} about pump {i}")
                b.refresh()
                a.remember("a", "one more fact about valve 9")
                calls = {"replay": 0}
                original = Amberlog._replay
                Amberlog._replay = lambda self: (calls.__setitem__("replay", 1),  # type: ignore[method-assign]
                                                     original(self))[1]
                try:
                    folded = b._catch_up()
                finally:
                    Amberlog._replay = original  # type: ignore[method-assign]
                self.assertEqual(calls["replay"], 0)
                self.assertLessEqual(folded, 3, "only the new events are read")
                self.assertTrue(any("valve" in m.content for m in b.state.memories.values()))
            finally:
                a.close()
                b.close()


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
