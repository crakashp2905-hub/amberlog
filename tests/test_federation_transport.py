"""Phase 2 — distributed delivery and reconciliation.

Exit gate: offline recipients converge after reconnection, committed events are
not silently lost, pending/rejected/failed/unknown states are visible, and
reconciliation is idempotent.

Two layers are tested deliberately. `InProcessTransport` drives the protocol
semantics and the fault matrix without a network, which is the only way to make
a crash deterministic. `HttpTransport` against a real socket proves the
serialisation, the authentication and the HTTP status mapping — the parts the
in-process transport cannot exercise.

The observability server's read-only guarantee is checked here too, because
Phase 2 adds the project's first authenticated *write* path and the obvious way
to get that wrong is to bolt it onto the dashboard.
"""

from __future__ import annotations

import json
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from tempfile import TemporaryDirectory

from amberlog import LifecycleState, Amberlog, WithdrawalBasis
from amberlog.dispatcher import Dispatcher, reconcile
from amberlog.federation import offer
from amberlog.governance.firewall import (
    Firewall,
    rule_capabilities_must_be_granted,
    rule_must_be_active,
    rule_restricted_stays_private,
)
from amberlog.outbox import MAX_ATTEMPTS, now_ms
from amberlog.protocol import (
    Acknowledgement,
    PropagationState,
    RejectionCode,
    Retraction,
    new_retraction_id,
)
from amberlog.transport import (
    HttpTransport,
    InProcessTransport,
    Peer,
    PeerRegistry,
    TransportError,
    serve,
)


def permissive() -> Firewall:
    return Firewall(
        rules=(
            rule_restricted_stays_private,
            rule_must_be_active,
            rule_capabilities_must_be_granted,
        )
    )


class FederationCase(unittest.TestCase):
    """An origin and two recipients, each a real store on disk, each holding an
    import of the same memory."""

    def setUp(self) -> None:
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

        self.origin = self._store("origin")
        self.alice = self._store("alice")
        self.bob = self._store("bob")

        self.memory_id = self.origin.remember("ag_n", "E01 at coastal: swap the cable.")
        self.origin.validate(self.memory_id, actor="supervisor")
        self.imports: dict[str, str] = {}
        for store, agent in ((self.alice, "ag_a"), (self.bob, "ag_b")):
            result = offer(self.origin, self.memory_id, store, recipient_agent=agent)
            self.assertTrue(result.accepted)
            store.validate(result.imported_memory_id, actor=agent)
            self.imports[store.store_id] = result.imported_memory_id

        self.registry = PeerRegistry()
        for store in (self.origin, self.alice, self.bob):
            self.registry.add(
                Peer(store_id=store.store_id, endpoint="unused", key=b"shared-" + store.store_id.encode())
            )

    def _store(self, name: str) -> Amberlog:
        path = str(Path(self.tmp.name) / f"{name}.db")
        store = Amberlog(path, firewall=permissive())
        self.addCleanup(self._safe_close, store)
        setattr(self, f"_{name}_path", path)
        return store

    @staticmethod
    def _safe_close(store: Amberlog) -> None:
        try:
            store.close()
        except Exception:
            pass

    def transport(self, offline: set[str] | None = None) -> InProcessTransport:
        return InProcessTransport(
            {s.store_id: s for s in (self.alice, self.bob)},
            registry=self.registry,
            offline=offline,
        )

    def request(self) -> Retraction:
        return self.origin.request_retraction(
            self.memory_id,
            reason="root cause was elsewhere",
            recipients=[self.alice.store_id, self.bob.store_id],
            actor="ag_n",
            basis=WithdrawalBasis.CONTRADICTED,
        )


class TestDispatch(FederationCase):
    def test_a_pass_enforces_at_every_recipient(self) -> None:
        retraction = self.request()
        report = Dispatcher(self.origin, self.transport()).run_once()

        self.assertEqual(report.attempted, 2)
        self.assertEqual(report.enforced, 2)
        for store in (self.alice, self.bob):
            self.assertEqual(
                store.get(self.imports[store.store_id]).lifecycle_state,
                LifecycleState.QUARANTINED,
            )
            self.assertEqual(
                self.origin.outbox.state_of(retraction.retraction_id, store.store_id),
                PropagationState.ENFORCED,
            )

    def test_nothing_is_due_once_everything_is_enforced(self) -> None:
        self.request()
        dispatcher = Dispatcher(self.origin, self.transport())
        dispatcher.run_once()
        self.assertEqual(dispatcher.run_once().attempted, 0)
        self.assertEqual(self.origin.outbox.pending(), [])

    def test_the_origin_records_what_each_recipient_claimed(self) -> None:
        retraction = self.request()
        Dispatcher(self.origin, self.transport()).run_once()
        acks = self.origin.outbox.acknowledgements(retraction.retraction_id)
        self.assertEqual(set(acks), {self.alice.store_id, self.bob.store_id})
        for ack in acks.values():
            self.assertEqual(ack.state, PropagationState.ENFORCED)
            self.assertGreater(ack.state_revision, 0)

    def test_an_acknowledgement_survives_an_origin_restart(self) -> None:
        """Held in memory it would be lost on a crash and the origin would have
        no record of what had been confirmed."""
        retraction = self.request()
        Dispatcher(self.origin, self.transport()).run_once()
        self.origin.close()
        reopened = Amberlog(self._origin_path, firewall=permissive())
        self.addCleanup(self._safe_close, reopened)
        acks = reopened.outbox.acknowledgements(retraction.retraction_id)
        self.assertEqual(len(acks), 2)


class TestOfflineRecipient(FederationCase):
    def test_an_offline_recipient_stays_pending_and_visible(self) -> None:
        retraction = self.request()
        report = Dispatcher(self.origin, self.transport(offline={self.bob.store_id})).run_once()

        self.assertEqual(report.enforced, 1)
        self.assertEqual(report.retrying, 1)
        self.assertTrue(report.errors)

        pending = self.origin.outbox.pending()
        self.assertEqual([row.recipient for row in pending], [self.bob.store_id])
        self.assertEqual(pending[0].state, PropagationState.RETRYING)
        self.assertEqual(
            self.bob.get(self.imports[self.bob.store_id]).lifecycle_state,
            LifecycleState.ACTIVE,
        )
        self.assertNotEqual(
            self.origin.outbox.state_of(retraction.retraction_id, self.bob.store_id),
            PropagationState.VERIFIED,
            "an unreachable recipient was marked verified",
        )

    def test_it_converges_when_the_recipient_returns(self) -> None:
        self.request()
        offline = {self.bob.store_id}
        Dispatcher(self.origin, self.transport(offline=offline)).run_once()

        # Back online. Backoff has elapsed in the test by moving the row's
        # next attempt into the past rather than by waiting.
        self.origin.outbox._conn.execute("UPDATE outbox SET next_attempt_ms = 0")
        report = Dispatcher(self.origin, self.transport()).run_once()

        self.assertEqual(report.enforced, 1)
        self.assertEqual(self.origin.outbox.pending(), [])
        self.assertEqual(
            self.bob.get(self.imports[self.bob.store_id]).lifecycle_state,
            LifecycleState.QUARANTINED,
        )

    def test_a_permanent_route_failure_fails_fast(self) -> None:
        """A route that does not exist will not start existing, so it should not
        consume eight attempts first."""
        self.origin.request_retraction(
            self.memory_id, reason="r", recipients=["st_" + "Z" * 26], actor="ag_n"
        )
        report = Dispatcher(self.origin, self.transport()).run_once()
        self.assertEqual(report.failed, 1)
        self.assertEqual(report.retrying, 0)

    def test_repeated_transient_failure_ends_in_a_visible_failure(self) -> None:
        self.request()
        offline = {self.alice.store_id, self.bob.store_id}
        dispatcher = Dispatcher(self.origin, self.transport(offline=offline))
        for _ in range(MAX_ATTEMPTS + 1):
            self.origin.outbox._conn.execute("UPDATE outbox SET next_attempt_ms = 0")
            dispatcher.run_once()
        rows = self.origin.outbox._conn.execute("SELECT state, last_error FROM outbox").fetchall()
        self.assertTrue(all(row["state"] == PropagationState.FAILED.value for row in rows))
        self.assertTrue(all(row["last_error"] for row in rows))


class TestReconciliation(FederationCase):
    def test_a_recipient_catches_up_from_its_own_cursor(self) -> None:
        self.request()
        Dispatcher(self.origin, self.transport(offline={self.bob.store_id})).run_once()

        since = self.bob.outbox.missed_since(self.origin.store_id)
        missed = self.origin.retractions_since(since)
        self.assertEqual(len(missed), 1)

        acks = reconcile(self.bob, missed, self.origin.store_id)
        self.assertEqual([a.state for a in acks], [PropagationState.ENFORCED])
        self.assertEqual(
            self.bob.get(self.imports[self.bob.store_id]).lifecycle_state,
            LifecycleState.QUARANTINED,
        )

    def test_reconciliation_is_idempotent(self) -> None:
        self.request()
        Dispatcher(self.origin, self.transport()).run_once()
        missed = self.origin.retractions_since(-1)

        reconcile(self.alice, missed, self.origin.store_id)
        reconcile(self.alice, missed, self.origin.store_id)
        applied = [e for e in self.alice.log.read() if e.type == "RetractionApplied"]
        self.assertEqual(len(applied), 1)

    def test_replaying_too_much_is_safe(self) -> None:
        """The reason the cursor is the recipient's: over-replaying costs
        nothing, under-replaying is the only real failure."""
        self.request()
        everything = self.origin.retractions_since(-1)
        acks = reconcile(self.alice, everything, self.origin.store_id)
        acks += reconcile(self.alice, everything, self.origin.store_id)
        self.assertTrue(all(a.state == PropagationState.ENFORCED for a in acks))

    def test_a_replay_is_applied_in_the_origins_order(self) -> None:
        """Feeding a newer retraction before an older one would have the older
        refused as superseded when it should simply have been applied first."""
        second_memory = self.origin.remember("ag_n", "E02 at urban: reflash firmware.")
        self.origin.validate(second_memory, actor="supervisor")
        extra = offer(self.origin, second_memory, self.alice, recipient_agent="ag_a")
        self.alice.validate(extra.imported_memory_id, actor="ag_a")

        first = self.request()
        second = self.origin.request_retraction(
            second_memory, reason="r", recipients=[self.alice.store_id], actor="ag_n"
        )
        self.assertGreater(second.origin_sequence, first.origin_sequence)

        acks = reconcile(
            self.alice, [second, first], self.origin.store_id  # deliberately reversed
        )
        self.assertTrue(all(a.state == PropagationState.ENFORCED for a in acks))
        self.assertEqual(
            self.alice.get(self.imports[self.alice.store_id]).lifecycle_state,
            LifecycleState.QUARANTINED,
        )
        self.assertEqual(
            self.alice.get(extra.imported_memory_id).lifecycle_state,
            LifecycleState.QUARANTINED,
        )

    def test_a_replay_cannot_carry_another_origins_events(self) -> None:
        """Otherwise a compromised peer could retract on someone else's
        behalf."""
        forged = Retraction(
            retraction_id=new_retraction_id(),
            origin_store_id=self.bob.store_id,  # not the origin we are talking to
            origin_memory_id=self.memory_id,
            origin_memory_version=1,
            origin_sequence=1,
            reason_code="contradicted",
            requested_by="ag_evil",
            issued_at="2026-10-10T12:00:00Z",
        )
        acks = reconcile(self.alice, [forged], self.origin.store_id)
        self.assertEqual(acks, [])
        self.assertEqual(
            self.alice.get(self.imports[self.alice.store_id]).lifecycle_state,
            LifecycleState.ACTIVE,
        )


class TestOverstatedAcknowledgement(FederationCase):
    def test_the_origin_refuses_a_claim_with_no_revision_behind_it(self) -> None:
        class Liar:
            def send(self, recipient_store_id: str, retraction: Retraction):
                return Acknowledgement(
                    retraction_id=retraction.retraction_id,
                    recipient_store_id=recipient_store_id,
                    state=PropagationState.ENFORCED,
                    at="2026-10-10T12:00:00Z",
                    state_revision=0,
                )

        retraction = self.request()
        report = Dispatcher(self.origin, Liar()).run_once()
        self.assertEqual(report.refused_overstatement, 2)
        self.assertEqual(report.enforced, 0)
        self.assertNotEqual(
            self.origin.outbox.state_of(retraction.retraction_id, self.alice.store_id),
            PropagationState.ENFORCED,
            "recorded a guarantee the recipient never gave",
        )


class TestIntegritySnapshot(FederationCase):
    def test_a_snapshot_names_the_unresolved_retractions(self) -> None:
        """A restore that silently dropped pending retractions would
        reintroduce withdrawn knowledge and nothing downstream could detect
        it."""
        self.request()
        Dispatcher(self.origin, self.transport(offline={self.bob.store_id})).run_once()

        snapshot = self.origin.integrity_snapshot()
        self.assertEqual(snapshot["store_id"], self.origin.store_id)
        self.assertEqual(snapshot["protocol_version"], 1)
        self.assertEqual(len(snapshot["unresolved_retractions"]), 1)
        self.assertEqual(
            snapshot["unresolved_retractions"][0]["recipient"], self.bob.store_id
        )
        self.assertTrue(snapshot["checksum"].startswith("sha256:"))

    def test_the_checksum_changes_when_integrity_state_does(self) -> None:
        self.request()
        before = self.origin.integrity_snapshot()["checksum"]
        Dispatcher(self.origin, self.transport()).run_once()
        self.assertNotEqual(before, self.origin.integrity_snapshot()["checksum"])

    def test_a_recipient_snapshot_carries_its_cursors(self) -> None:
        self.request()
        Dispatcher(self.origin, self.transport()).run_once()
        snapshot = self.alice.integrity_snapshot()
        self.assertIn(self.origin.store_id, snapshot["origin_cursors"])


class TestHttpTransport(FederationCase):
    """The parts the in-process transport cannot reach: serialisation,
    authentication, and HTTP status mapping."""

    def setUp(self) -> None:
        super().setUp()
        self.key = b"a-shared-key-between-origin-and-alice"
        self.alice_registry = PeerRegistry(
            {self.origin.store_id: Peer(self.origin.store_id, "unused", self.key)}
        )
        self.served = serve(self.alice, self.alice_registry)
        self.addCleanup(self.served.close)
        self.origin_registry = PeerRegistry(
            {self.alice.store_id: Peer(self.alice.store_id, self.served.endpoint, self.key)}
        )

    def test_a_retraction_crosses_a_real_socket_and_is_enforced(self) -> None:
        self.origin.request_retraction(
            self.memory_id, reason="r", recipients=[self.alice.store_id], actor="ag_n"
        )
        transport = HttpTransport(self.origin_registry, self.origin.store_id)
        report = Dispatcher(self.origin, transport).run_once()

        self.assertEqual(report.enforced, 1)
        self.assertEqual(
            self.alice.get(self.imports[self.alice.store_id]).lifecycle_state,
            LifecycleState.QUARANTINED,
        )

    def test_an_unsigned_retraction_is_refused(self) -> None:
        retraction = self.origin.request_retraction(
            self.memory_id, reason="r", recipients=[self.alice.store_id], actor="ag_n"
        )
        body = json.dumps({"retraction": retraction.to_json()}).encode("utf-8")
        request = urllib.request.Request(
            self.served.endpoint + "/federation/retraction",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(request, timeout=5)
        self.assertEqual(ctx.exception.code, 401)
        self.assertEqual(
            self.alice.get(self.imports[self.alice.store_id]).lifecycle_state,
            LifecycleState.ACTIVE,
        )

    def test_a_wrong_key_is_refused(self) -> None:
        retraction = self.origin.request_retraction(
            self.memory_id, reason="r", recipients=[self.alice.store_id], actor="ag_n"
        )
        wrong = PeerRegistry(
            {self.alice.store_id: Peer(self.alice.store_id, self.served.endpoint, b"wrong")}
        )
        transport = HttpTransport(wrong, self.origin.store_id)
        with self.assertRaises(TransportError) as ctx:
            transport.send(self.alice.store_id, retraction)
        self.assertTrue(ctx.exception.permanent, "a bad key should not be retried forever")
        self.assertEqual(
            self.alice.get(self.imports[self.alice.store_id]).lifecycle_state,
            LifecycleState.ACTIVE,
        )

    def test_a_malformed_body_is_rejected_with_a_code(self) -> None:
        request = urllib.request.Request(
            self.served.endpoint + "/federation/retraction",
            data=b"not json",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(request, timeout=5)
        self.assertEqual(ctx.exception.code, 400)
        self.assertEqual(
            json.load(ctx.exception)["rejection_code"], RejectionCode.MALFORMED.value
        )

    def test_a_refusal_tells_an_unauthenticated_caller_nothing(self) -> None:
        """A rejection code and nothing else.

        The full `Acknowledgement` was the reply here, and it carries this
        store's id, its event-log head sequence (`state_revision`) and how far
        it has read a given origin's sequence. Served on the *fail-closed*
        path, which made the head sequence a pollable activity oracle for
        anyone who could reach the port — and told an unauthenticated caller
        the identity of the store it had just failed to authenticate to.

        No test was watching this body, which is why the leak survived the
        suite; found by a by-hand validation probe. The same reasoning as the
        `wrong_tenant` access decision, which reports version 0 and no detail.
        """
        retraction = self.origin.request_retraction(
            self.memory_id, reason="r", recipients=[self.alice.store_id], actor="ag_n"
        )
        request = urllib.request.Request(
            self.served.endpoint + "/federation/retraction",
            data=json.dumps({"retraction": retraction.to_json()}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(request, timeout=5)
        payload = json.load(ctx.exception)

        self.assertEqual(ctx.exception.code, 401)
        self.assertEqual(payload, {"rejection_code": RejectionCode.UNAUTHORIZED.value})
        for leaked in (
            "state_revision", "origin_sequence_seen", "recipient_store_id",
            "retraction_id", "at", "detail", "state",
        ):
            self.assertNotIn(leaked, payload, f"{leaked} must not reach an unauthenticated caller")
        self.assertNotIn(self.alice.store_id, json.dumps(payload))

    def test_the_refusal_is_still_audited_locally(self) -> None:
        """Saying nothing to the caller is not the same as recording nothing.

        The pair matters: if quietening the reply had also dropped the local
        event, the fix would have traded a disclosure for a blind spot.
        """
        retraction = self.origin.request_retraction(
            self.memory_id, reason="r", recipients=[self.alice.store_id], actor="ag_n"
        )
        request = urllib.request.Request(
            self.served.endpoint + "/federation/retraction",
            data=json.dumps({"retraction": retraction.to_json()}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.assertRaises(urllib.error.HTTPError):
            urllib.request.urlopen(request, timeout=5)

        rejected = [
            event for event in self.alice.log.read()
            if event.type == "RetractionRejected"
            and event.payload.get("retraction_id") == retraction.retraction_id
        ]
        self.assertEqual(len(rejected), 1)
        self.assertEqual(
            rejected[0].payload["rejection_code"], RejectionCode.UNAUTHORIZED.value
        )

    def test_a_parse_failure_does_not_echo_the_parser_message(self) -> None:
        """`detail` quoted the parser's own complaint about attacker bytes.

        That is a free description of this build's parsing to anyone who can
        reach the port, and it tells a legitimate sender nothing its own
        serialiser could not. The code stays; the prose goes.
        """
        for body in (b"not json", b"{}", json.dumps({"garbage": True}).encode()):
            with self.subTest(body=body[:20]):
                request = urllib.request.Request(
                    self.served.endpoint + "/federation/retraction",
                    data=body,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with self.assertRaises(urllib.error.HTTPError) as ctx:
                    urllib.request.urlopen(request, timeout=5)
                payload = json.load(ctx.exception)
                self.assertEqual(ctx.exception.code, 400)
                self.assertEqual(list(payload), ["rejection_code"])
                self.assertNotIn("detail", payload)

    def test_an_unknown_peer_cannot_tell_refusal_apart_from_absence(self) -> None:
        """The registry is the authorisation boundary. A distinguishable
        refusal would make it an enumeration oracle."""
        bodies = (
            {"store_id": "st_" + "Q" * 26, "since_sequence": -1},
            {"store_id": self.bob.store_id, "since_sequence": -1},
        )
        replies = []
        for body in bodies:
            request = urllib.request.Request(
                self.served.endpoint + "/federation/reconcile",
                data=json.dumps(body).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(request, timeout=5)
            replies.append((ctx.exception.code, json.load(ctx.exception)))
        # A store that exists elsewhere in the federation but is not a peer of
        # alice's looks exactly like one that does not exist at all.
        self.assertEqual(replies[0], replies[1])
        self.assertEqual(replies[0][0], 401)

    def test_reconciliation_over_http_requires_a_known_peer(self) -> None:
        request = urllib.request.Request(
            self.served.endpoint + "/federation/reconcile",
            data=json.dumps({"store_id": "st_" + "Q" * 26, "since_sequence": -1}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(request, timeout=5)
        self.assertEqual(ctx.exception.code, 401)

    def test_health_reports_the_store_identity(self) -> None:
        with urllib.request.urlopen(
            self.served.endpoint + "/federation/health", timeout=5
        ) as response:
            payload = json.load(response)
        self.assertEqual(payload["store_id"], self.alice.store_id)

    def test_an_unknown_endpoint_replies_rather_than_dropping_the_connection(self) -> None:
        """A 404, not a connection reset.

        The handler replied without reading the request body, and with
        HTTP/1.1 keep-alive that desynchronises the connection: the server
        aborts and the client gets `ConnectionAbortedError` instead of the
        status the server meant to send. For the auth paths that would turn a
        clean refusal into something indistinguishable from a crash.

        Repeated on one connection on purpose — a single request would not
        reach the desynchronised state.
        """
        import http.client
        from urllib.parse import urlparse

        parsed = urlparse(self.served.endpoint)
        connection = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=5)
        self.addCleanup(connection.close)
        for attempt in range(3):
            with self.subTest(attempt=attempt):
                connection.request(
                    "POST", "/federation/whatever", body=b'{"a": 1}',
                    headers={"Content-Type": "application/json"},
                )
                response = connection.getresponse()
                self.assertEqual(response.status, 404)
                response.read()

    def test_an_unknown_endpoint_is_not_found(self) -> None:
        request = urllib.request.Request(
            self.served.endpoint + "/federation/whatever", data=b"{}", method="POST"
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(request, timeout=5)
        self.assertEqual(ctx.exception.code, 404)


class TestObservabilityStaysReadOnly(unittest.TestCase):
    """Phase 2 adds the first authenticated write path in the project. The
    obvious way to get that wrong is to bolt it onto the dashboard, which is
    read-only by test for a reason: an observability tool that wrote exposure
    events while an operator browsed would feed its own browsing into the data
    every value estimate is computed from."""

    def test_the_federation_endpoint_is_not_on_the_observability_server(self) -> None:
        from amberlog.observability import server as observability

        source = Path(observability.__file__).read_text(encoding="utf-8")
        self.assertNotIn("federation/retraction", source)
        self.assertNotIn("receive_retraction", source)

    def test_the_federation_server_is_a_separate_module(self) -> None:
        from amberlog import transport

        self.assertTrue(hasattr(transport, "build_federation_server"))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
