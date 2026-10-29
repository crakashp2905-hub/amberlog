"""A copy never travels further than its retraction can follow (experiments/fed_scale.py)."""

from __future__ import annotations

import unittest

from experiments import fed_scale
from amberlog.protocol import MAX_HOPS


class Reach(unittest.TestCase):
    def test_a_long_chain_stops_at_the_hop_limit_and_converges(self) -> None:
        row = fed_scale.run("chain", MAX_HOPS + 4, fed_scale.chain)
        self.assertEqual(row["reach"], MAX_HOPS + 1)
        self.assertEqual(row["still_exposable"], 0)
        self.assertEqual(row["hop_limit_rejections"], 0)

    def test_a_mesh_with_cycles_converges(self) -> None:
        row = fed_scale.run("mesh", 30, fed_scale.mesh(3))
        self.assertGreater(row["reach"], 20)
        self.assertEqual(row["still_exposable"], 0)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
