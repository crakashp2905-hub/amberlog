"""A retraction forwarded over HTTP is verified with the forwarder's key, not the origin's.

Found by experiments/multihost.py: every second hop over HTTP was refused
with 401, because the recipient verified a forwarded retraction with the
key it shares with the *origin* (or had none, if it never met the origin).
The in-process transport checks no signatures, so no earlier test saw it.
Here C knows only B, as in a real chain.
"""

from __future__ import annotations

import unittest

from memory_fabric import LifecycleState, MemoryFabric, correction
from memory_fabric.dispatcher import Dispatcher
from memory_fabric.federation import offer_remote
from memory_fabric.governance.firewall import SHARE_POLICIES, Firewall
from memory_fabric.transport import HttpTransport, Peer, PeerRegistry, serve

AB, BC = b"key-shared-by-a-and-b-0000000000", b"key-shared-by-b-and-c-0000000000"


def store() -> MemoryFabric:
    return MemoryFabric(":memory:", firewall=Firewall(rules=SHARE_POLICIES["reviewed"]))


class TwoHopsOverHttp(unittest.TestCase):
    def test_a_correction_reaches_a_store_that_never_met_the_origin(self) -> None:
        a, b, c = store(), store(), store()
        for s in (a, b, c):
            self.addCleanup(s.close)
        served_b = serve(b, PeerRegistry({a.store_id: Peer(a.store_id, "unused", AB),
                                          c.store_id: Peer(c.store_id, "unused", BC)}))
        served_c = serve(c, PeerRegistry({b.store_id: Peer(b.store_id, "unused", BC)}))
        self.addCleanup(served_b.close)
        self.addCleanup(served_c.close)
        a_to_b = HttpTransport(PeerRegistry({b.store_id: Peer(b.store_id, served_b.endpoint, AB)}),
                               a.store_id)
        b_to_c = HttpTransport(PeerRegistry({c.store_id: Peer(c.store_id, served_c.endpoint, BC)}),
                               b.store_id)

        note = a.remember("tech", "Line 3 conveyor belt speed is 40 m/min.", scope="team")
        a.validate(note, actor="lead")
        at_b = offer_remote(a, note, a_to_b, b.store_id, "op").imported_memory_id
        b.validate(at_b, actor="reviewer")
        at_c = offer_remote(b, at_b, b_to_c, c.store_id, "op").imported_memory_id
        c.validate(at_c, actor="reviewer")

        correction.apply(a, note, reason="re-measured", actor="lead")
        Dispatcher(a, a_to_b).run_once()
        self.assertIs(b.get(at_b).lifecycle_state, LifecycleState.QUARANTINED)
        report = Dispatcher(b, b_to_c).run_once()
        self.assertEqual(report.enforced, 1, "the second hop is accepted")
        self.assertIs(c.get(at_c).lifecycle_state, LifecycleState.QUARANTINED)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
