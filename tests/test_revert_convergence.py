"""A fact the origin reverts (56 -> 79 -> 56) converges at every recipient, re-shares included.

Regression for a hold introduced when claim validation became the default:
a newer version restating a value whose older copy had been withdrawn was held
as `reasserts_corrected` and never released, so recipients served nothing
(S1 CorrectionSim at HEAD: convergence 1.00 -> 0.70).
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from memory_fabric.validation import _newer_version_of


def copy(store: str, mid: str, version: int | None) -> SimpleNamespace:
    root = {"store": store, "memory_id": mid}
    if version is not None:
        root["version"] = version
    return SimpleNamespace(context={"federation": {"root": root, "store": "via", "version": 1}})


class NewerVersion(unittest.TestCase):
    def test_only_a_higher_version_of_the_same_root_counts(self) -> None:
        self.assertTrue(_newer_version_of(copy("A", "m1", 3), copy("A", "m1", 2)))
        self.assertFalse(_newer_version_of(copy("A", "m1", 2), copy("A", "m1", 2)))   # same version re-sent
        self.assertFalse(_newer_version_of(copy("A", "m1", 1), copy("A", "m1", 2)))   # stale copy
        self.assertFalse(_newer_version_of(copy("A", "m2", 3), copy("A", "m1", 2)))   # another memory
        self.assertFalse(_newer_version_of(copy("B", "m1", 3), copy("A", "m1", 2)))   # another store
        self.assertFalse(_newer_version_of(copy("A", "m1", None), copy("A", "m1", 2)))  # pre-0.14 import
        self.assertFalse(_newer_version_of(SimpleNamespace(context={}), copy("A", "m1", 2)))   # local write


class Convergence(unittest.TestCase):
    def test_the_seeds_that_regressed_converge_again(self) -> None:
        from experiments import s1_correction_sim as s

        for seed in (2, 5):
            p = s.plan(seed)
            arm = s.FabricArm("versioned", seed)
            arm.setup(p)
            index = {f: 0 for f in p.origin}
            for step in range(s.STEPS):
                arm.offline = set(p.offline.get(step, set()))
                for fid in p.corrections.get(step, []):
                    index[fid] += 1
                    arm.correct(fid, p.values[fid][index[fid]])
                arm.step()
            for fid in p.origin:
                for store in s.holders(p, fid):
                    self.assertEqual(arm.served(fid, store), {arm.current_value(fid)}, (seed, fid, store))


if __name__ == "__main__":
    unittest.main()
