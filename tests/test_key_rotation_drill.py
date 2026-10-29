"""The federation key rotation drill (RUNBOOKS.md §3), over a real socket.

Four phases, each with a real retraction delivered over HTTP:

1. **before**: both stores use k1;
2. **overlap**: the recipient makes k2 current and still accepts k1; the
   origin, not yet switched, signs with k1, and it is accepted;
3. **switched**: the origin signs with k2, and it is accepted;
4. **retired**: the recipient drops k1. A message signed with k1, which is
   what an attacker holding the leaked old key would send, is refused and
   changes nothing.

Plus the in-flight case: a retraction owed while the origin switches keys is
signed at send time, so it goes out under k2 and lands.
"""

from __future__ import annotations

from amberlog import LifecycleState
from amberlog.dispatcher import Dispatcher
from amberlog.federation import offer
from amberlog.transport import HttpTransport, Peer, PeerRegistry, TransportError, serve

from tests.test_federation_transport import FederationCase

K1, K2 = b"rotation-drill-key-one-000000000", b"rotation-drill-key-two-000000000"


class KeyRotationDrill(FederationCase):
    def setUp(self) -> None:
        super().setUp()
        self.alice_registry = PeerRegistry(
            {self.origin.store_id: Peer(self.origin.store_id, "unused", K1, "k1")})
        self.served = serve(self.alice, self.alice_registry)
        self.addCleanup(self.served.close)

    def shared(self, text: str) -> tuple[str, str]:
        mid = self.origin.remember("ag_n", text)
        self.origin.validate(mid, actor="supervisor")
        imported = offer(self.origin, mid, self.alice, recipient_agent="ag_a").imported_memory_id
        self.alice.validate(imported, actor="reviewer")
        return mid, imported

    def origin_signs_with(self, key: bytes, key_id: str) -> HttpTransport:
        return HttpTransport(PeerRegistry({self.alice.store_id: Peer(
            self.alice.store_id, self.served.endpoint, key, key_id)}), self.origin.store_id)

    def retract(self, mid: str, transport: HttpTransport) -> int:
        self.origin.request_retraction(mid, reason="drill", recipients=[self.alice.store_id],
                                       actor="ag_n")
        return Dispatcher(self.origin, transport).run_once().enforced

    def state(self, imported: str) -> LifecycleState:
        return self.alice.get(imported).lifecycle_state

    def test_the_four_phases(self) -> None:
        # 1. before
        mid, imported = self.shared("Phase 1 note: valve V1 opens at 2 bar.")
        self.assertEqual(self.retract(mid, self.origin_signs_with(K1, "k1")), 1)
        self.assertIs(self.state(imported), LifecycleState.QUARANTINED)

        # 2. overlap: the recipient moves first, keeping k1 accepted
        self.alice_registry.add(Peer(self.origin.store_id, "unused", K2, "k2", accepted={"k1": K1}))
        mid, imported = self.shared("Phase 2 note: valve V2 opens at 3 bar.")
        self.assertEqual(self.retract(mid, self.origin_signs_with(K1, "k1")), 1,
                         "the origin has not switched yet; k1 is still accepted")
        self.assertIs(self.state(imported), LifecycleState.QUARANTINED)

        # 3. switched
        mid, imported = self.shared("Phase 3 note: valve V3 opens at 4 bar.")
        self.assertEqual(self.retract(mid, self.origin_signs_with(K2, "k2")), 1)
        self.assertIs(self.state(imported), LifecycleState.QUARANTINED)

        # 4. retired: the old key no longer works, for anyone
        self.alice_registry.add(Peer(self.origin.store_id, "unused", K2, "k2"))
        mid, imported = self.shared("Phase 4 note: valve V4 opens at 5 bar.")
        retraction = self.origin.request_retraction(
            mid, reason="forged with the leaked old key", recipients=[self.alice.store_id],
            actor="ag_n")
        with self.assertRaises(TransportError) as caught:
            self.origin_signs_with(K1, "k1").send(self.alice.store_id, retraction)
        self.assertTrue(caught.exception.permanent)
        self.assertIs(self.state(imported), LifecycleState.ACTIVE, "a retired key changes nothing")

    def test_a_key_id_the_recipient_never_had_is_refused(self) -> None:
        mid, imported = self.shared("Note: valve V9 opens at 9 bar.")
        retraction = self.origin.request_retraction(
            mid, reason="r", recipients=[self.alice.store_id], actor="ag_n")
        with self.assertRaises(TransportError):
            self.origin_signs_with(K1, "k-unknown").send(self.alice.store_id, retraction)
        self.assertIs(self.state(imported), LifecycleState.ACTIVE)

    def test_a_retraction_in_flight_during_the_switch_goes_out_under_the_new_key(self) -> None:
        mid, imported = self.shared("In-flight note: valve V5 opens at 6 bar.")
        self.origin.request_retraction(mid, reason="owed before the switch",
                                       recipients=[self.alice.store_id], actor="ag_n")
        # the switch happens with the retraction still in the outbox, and the
        # recipient has already retired k1
        self.alice_registry.add(Peer(self.origin.store_id, "unused", K2, "k2"))
        report = Dispatcher(self.origin, self.origin_signs_with(K2, "k2")).run_once()
        self.assertEqual(report.enforced, 1)
        self.assertIs(self.state(imported), LifecycleState.QUARANTINED)


if __name__ == "__main__":  # pragma: no cover
    import unittest

    unittest.main()
