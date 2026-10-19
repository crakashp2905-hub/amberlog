"""Phase 2 — authenticated transport for the retraction protocol.

Peer-to-peer and brokers stay deferred (roadmap §9): this is authenticated HTTP
plus durable reconciliation, which is what the measured need actually is.

**Why a separate server from `observability/`.** That surface is read-only *by
test* — there is no mutating HTTP endpoint at all, because an observability tool
that logged an operator's queries would feed its own browsing into the data
every value estimate is computed from. Adding a write path to it would delete
that guarantee. Federation therefore gets its own endpoint, its own port and its
own credentials, and the read-only property of the dashboard is untouched.

**Authentication is per peer and symmetric.** Each peer pair shares an HMAC key.
A signature proves the message came from the holder of that key and was not
modified; it proves **nothing** about whether the retracted claim was false, and
nothing downstream may treat it as evidence about the memory (roadmap §6.3).

The transport is an interface with two implementations so the fault matrix can
be driven without a network: `InProcessTransport` for tests of the protocol
semantics, `HttpTransport` for the real thing. A test that needs a real socket
uses the server in this module.
"""

from __future__ import annotations

__stability__ = "stable"

import contextlib

import json
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Mapping, Protocol

from .protocol import (
    Acknowledgement,
    PropagationState,
    ProtocolError,
    RejectionCode,
    Retraction,
)

MAX_BODY_BYTES = 256 * 1024
"""A retraction carries a digest, never the evidence, so a legitimate message is
small. Bounded to make a trivial memory-exhaustion attempt fail early."""


class TransportError(RuntimeError):
    """A delivery failed in a way that may succeed on retry.

    Deliberately distinct from `ProtocolError`: a connection refused is
    transient and should back off, while a malformed message is permanent and
    should be rejected. Conflating them means retrying forever on a message that
    will never be accepted.
    """

    def __init__(self, detail: str, permanent: bool = False) -> None:
        super().__init__(detail)
        self.detail = detail
        self.permanent = permanent


@dataclass(frozen=True)
class Peer:
    """How to reach one store, and the key shared with it."""

    store_id: str
    endpoint: str
    key: bytes
    key_id: str = "k1"
    accepted: Mapping[str, bytes] = field(default_factory=dict)
    """Earlier keys still accepted from this peer, by key id: the overlap
    window of a rotation (RUNBOOKS.md §3). This store always *signs* with
    `key`; it *verifies* with whichever key the signature names, if that key
    is `key` or in here. Remove an old key to end its window."""


class PeerRegistry:
    """Who this store will talk to.

    Explicit rather than discovered. An unknown peer is not reachable and not
    authorised — the registry is the authorisation boundary, so a store cannot
    be made to accept retractions from somewhere it was never configured to
    trust.
    """

    def __init__(self, peers: Mapping[str, Peer] | None = None) -> None:
        self._peers: dict[str, Peer] = dict(peers or {})

    def add(self, peer: Peer) -> None:
        self._peers[peer.store_id] = peer

    def get(self, store_id: str) -> Peer | None:
        return self._peers.get(store_id)

    def key_for(self, store_id: str, key_id: str | None = None) -> bytes | None:
        """The key to verify a message from this peer, by the key id it was signed with.

        None for an unknown peer, or a key id that is neither current nor in
        the overlap window: a retired key is refused, not tried.
        """
        peer = self._peers.get(store_id)
        if peer is None:
            return None
        if key_id is None or key_id == peer.key_id:
            return peer.key
        return peer.accepted.get(key_id)

    def __contains__(self, store_id: object) -> bool:
        return store_id in self._peers

    def __len__(self) -> int:
        return len(self._peers)


def _canonical(body: Mapping[str, Any]) -> bytes:
    return json.dumps(body, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def sign_body(body: Mapping[str, Any], key: bytes, key_id: str) -> dict[str, str]:
    """HMAC-SHA256 over the canonical JSON of a message body."""
    import hashlib
    import hmac

    return {"alg": "hmac-sha256", "key_id": key_id,
            "value": hmac.new(key, _canonical(body), hashlib.sha256).hexdigest()}


def verify_body(body: Mapping[str, Any], signature: Mapping[str, Any], key: bytes) -> bool:
    import hashlib
    import hmac

    if signature.get("alg") != "hmac-sha256":
        return False
    expected = hmac.new(key, _canonical(body), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, str(signature.get("value", "")))


def peer_agent(origin_store_id: str) -> str:
    """The agent a networked import is recorded under at the recipient.

    Fixed, never chosen by the sender: a remote peer naming a local agent id
    ("lead") would file its memory as that agent's.
    """
    return f"peer:{origin_store_id}"


class Transport(Protocol):
    """Deliver one retraction and return the recipient's acknowledgement."""

    def send(self, recipient_store_id: str, retraction: Retraction) -> Acknowledgement:
        ...


class InProcessTransport:
    """Hands the retraction to another `MemoryFabric` in this process.

    This is a *test* transport and is named so. It still goes through
    `receive_retraction`, so the protocol semantics it exercises are the real
    ones — what it does not exercise is serialisation, authentication or the
    network, which is exactly what `HttpTransport` is for.

    `offline` lets a test drop a recipient without tearing anything down, which
    is how the reconciliation fault scenarios are driven.
    """

    def __init__(
        self,
        stores: Mapping[str, Any],
        registry: PeerRegistry | None = None,
        offline: set[str] | None = None,
    ) -> None:
        self.stores = dict(stores)
        self.registry = registry or PeerRegistry()
        self.offline: set[str] = set(offline or ())
        self.sent: list[tuple[str, str]] = []

    def send(self, recipient_store_id: str, retraction: Retraction) -> Acknowledgement:
        self.sent.append((recipient_store_id, retraction.retraction_id))
        if recipient_store_id in self.offline:
            raise TransportError(f"{recipient_store_id} is offline")
        store = self.stores.get(recipient_store_id)
        if store is None:
            raise TransportError(f"no route to {recipient_store_id}", permanent=True)
        sender = retraction.forwarded_by or retraction.origin_store_id
        authorised = sender in self.registry if len(self.registry) else True
        return store.receive_retraction(retraction, sender_authorised=authorised)

    def send_notice(self, recipient_store_id: str, notice: Any) -> bool:
        if recipient_store_id in self.offline:
            raise TransportError(f"{recipient_store_id} is offline")
        store = self.stores.get(recipient_store_id)
        if store is None:
            raise TransportError(f"no route to {recipient_store_id}", permanent=True)
        authorised = notice.origin_store_id in self.registry if len(self.registry) else True
        return bool(store.receive_notice(notice, sender_authorised=authorised))

    def send_offer(self, recipient_store_id: str, prepared: Any, recipient_agent: str
                   ) -> dict[str, Any]:
        """Offer over the in-process route, with the network's rules: a candidate, as `peer:`."""
        from .federation import accept_offer

        if recipient_store_id in self.offline:
            raise TransportError(f"{recipient_store_id} is offline")
        store = self.stores.get(recipient_store_id)
        if store is None:
            raise TransportError(f"no route to {recipient_store_id}", permanent=True)
        if len(self.registry) and prepared.origin_store_id not in self.registry:
            raise TransportError("not authorised", permanent=True)
        result = accept_offer(store, prepared, peer_agent(prepared.origin_store_id))
        return {"accepted": result.accepted, "decision": result.decision.value,
                "reasons": result.reasons, "imported_memory_id": result.imported_memory_id}


class HttpTransport:
    """The real transport: authenticated HTTP POST, stdlib only."""

    def __init__(
        self, registry: PeerRegistry, origin_store_id: str, timeout: float = 10.0
    ) -> None:
        self.registry = registry
        self.origin_store_id = origin_store_id
        self.timeout = timeout

    def send_offer(self, recipient_store_id: str, prepared: Any, recipient_agent: str
                   ) -> dict[str, Any]:
        """POST a signed offer to a peer's `/federation/offer`; return its decision."""
        peer = self.registry.get(recipient_store_id)
        if peer is None:
            raise TransportError(f"no peer configured for {recipient_store_id}", permanent=True)
        offer = prepared.to_json()
        body = json.dumps({"offer": offer, "signature": sign_body(offer, peer.key, peer.key_id)},
                          default=str).encode("utf-8")
        request = urllib.request.Request(peer.endpoint.rstrip("/") + "/federation/offer",
                                         data=body, headers={"Content-Type": "application/json"},
                                         method="POST")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return dict(json.load(response))
        except urllib.error.HTTPError as exc:
            raise TransportError(f"offer refused: {exc.code}", permanent=exc.code < 500) from exc
        except (urllib.error.URLError, OSError) as exc:
            raise TransportError(f"cannot reach {recipient_store_id}: {exc}") from exc

    def send_notice(self, recipient_store_id: str, notice: Any) -> bool:
        """POST a signed source notice to a peer's `/federation/notice`."""
        peer = self.registry.get(recipient_store_id)
        if peer is None:
            raise TransportError(f"no peer configured for {recipient_store_id}", permanent=True)
        body = json.dumps({"notice": notice.to_json(),
                           "signature": notice.sign(peer.key, peer.key_id)}).encode("utf-8")
        request = urllib.request.Request(peer.endpoint.rstrip("/") + "/federation/notice",
                                         data=body, headers={"Content-Type": "application/json"},
                                         method="POST")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return bool(json.load(response).get("accepted"))
        except urllib.error.HTTPError as exc:
            raise TransportError(f"notice refused: {exc.code}", permanent=exc.code < 500) from exc
        except (urllib.error.URLError, OSError) as exc:
            raise TransportError(f"cannot reach {recipient_store_id}: {exc}") from exc

    def send(self, recipient_store_id: str, retraction: Retraction) -> Acknowledgement:
        peer = self.registry.get(recipient_store_id)
        if peer is None:
            # Not configured is permanent: retrying will not conjure a route.
            raise TransportError(f"no peer configured for {recipient_store_id}", permanent=True)

        body = json.dumps(
            {
                "retraction": retraction.to_json(),
                "signature": retraction.sign(peer.key, peer.key_id),
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            peer.endpoint.rstrip("/") + "/federation/retraction",
            data=body,
            headers={
                "Content-Type": "application/json",
                "X-Memory-Fabric-Origin": self.origin_store_id,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return Acknowledgement.from_json(json.load(response))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:400]
            # 4xx will not improve on retry; 5xx might.
            raise TransportError(
                f"{peer.endpoint} returned {exc.code}: {detail}",
                permanent=exc.code < 500,
            ) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise TransportError(f"cannot reach {peer.endpoint}: {exc}") from exc


# --- the receiving end ------------------------------------------------------


def _store_lock(fabric: Any) -> Any:
    """The fabric's lock, held around each store call and never around I/O.

    `ThreadingHTTPServer` answers peers concurrently, and two retractions
    arriving at once used the store's one connection from two threads, the
    defect `tests/test_concurrent_requests.py` documents for the agent API.
    A fabric stand-in without a lock (some tests pass one) gets a no-op.
    """
    lock = getattr(fabric, "lock", None)
    return lock if lock is not None else contextlib.nullcontext()


def build_federation_server(
    fabric: Any,
    registry: PeerRegistry,
    host: str = "127.0.0.1",
    port: int = 0,
) -> ThreadingHTTPServer:
    """An HTTP server that accepts retractions and reconciliation requests.

    Separate from the observability server on purpose; see the module docstring.

    **Order of operations, stated precisely because an earlier version of this
    docstring claimed something stronger and false.** It said an
    unauthenticated request was refused "before the message is even parsed".
    It is not, and it cannot be: the key is looked up by the *claimed* origin
    store, and that claim lives in the body. So the envelope is parsed first,
    and the authentication gate sits between parsing and anything consequential
    — which is what invariant 11 actually requires. Nothing is applied, and no
    lifecycle changes, until the HMAC verifies.

    Two consequences are handled rather than hoped about:

    * **The parser is reachable unauthenticated.** Bounded by `MAX_BODY_BYTES`, a Content-Length check and a strict `Retraction.from_json`, and the detail of a parse failure is *not* echoed to the caller.
    * **A refusal says as little as possible.** An unauthorised caller gets a rejection code and nothing else. The full `Acknowledgement` carries this store's id, its event-log head sequence and how far it has read a given origin's sequence; served on the fail-closed path that made the head sequence a live activity oracle for anyone who could reach the port. The same reasoning as the `wrong_tenant` access decision, which reports version 0 and no detail.
    """

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args: Any) -> None:  # pragma: no cover
            pass

        def _reply(self, status: HTTPStatus, payload: Mapping[str, Any]) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _drain(self) -> None:
            """Read and discard the request body.

            `protocol_version = "HTTP/1.1"` means keep-alive, and a handler
            that replies without consuming the body leaves the connection
            desynchronised: the next read picks up the unread bytes, and the
            server aborts. A client then sees a connection reset instead of the
            404 or 401 the server meant to send — which for the auth path turns
            a clean refusal into something indistinguishable from a crash.

            Found by a test-ordering change making the unknown-endpoint test
            fail with `ConnectionAbortedError`.
            """
            length = int(self.headers.get("Content-Length") or 0)
            remaining = min(max(length, 0), MAX_BODY_BYTES)
            while remaining > 0:
                chunk = self.rfile.read(min(remaining, 65536))
                if not chunk:
                    break
                remaining -= len(chunk)

        def _read_body(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0:
                raise ProtocolError(RejectionCode.MALFORMED, "empty body")
            if length > MAX_BODY_BYTES:
                raise ProtocolError(RejectionCode.MALFORMED, "body too large")
            try:
                return json.loads(self.rfile.read(length))
            except json.JSONDecodeError as exc:
                raise ProtocolError(RejectionCode.MALFORMED, f"bad JSON: {exc}") from exc

        def do_POST(self) -> None:  # noqa: N802
            if self.path == "/federation/retraction":
                self._retraction()
            elif self.path == "/federation/notice":
                self._notice()
            elif self.path == "/federation/offer":
                self._offer()
            elif self.path == "/federation/reconcile":
                self._reconcile()
            else:
                # Drained first: the body is unread at this point and replying
                # without consuming it breaks the connection.
                self._drain()
                self._reply(HTTPStatus.NOT_FOUND, {"error": "unknown endpoint"})

        def do_GET(self) -> None:  # noqa: N802
            if self.path == "/federation/health":
                self._reply(
                    HTTPStatus.OK,
                    {"store_id": fabric.store_id, "peers": len(registry)},
                )
                return
            self._reply(HTTPStatus.NOT_FOUND, {"error": "unknown endpoint"})

        def _retraction(self) -> None:
            try:
                body = self._read_body()
                retraction = Retraction.from_json(body.get("retraction", {}))
            except ProtocolError as exc:
                # The code, not the detail. `detail` quotes the parser's own
                # message about attacker-supplied bytes, which is a free
                # description of this build's parsing to anyone who can reach
                # the port and tells a legitimate sender nothing its own
                # serialiser could not have told it.
                self._reply(
                    HTTPStatus.BAD_REQUEST, {"rejection_code": exc.code.value}
                )
                return

            # Authenticate, then authorise, before anything is applied. Not
            # before parsing — see this function's docstring for why that is
            # impossible when the key is named by the claimed origin.
            signature = body.get("signature") or {}
            # The key of the store that *sent* this: the forwarder for a
            # forwarded retraction, the origin otherwise. Verifying a forwarded
            # one with the origin's key refused every second hop over HTTP
            # (experiments/multihost.py); the in-process transport, which
            # checks no signatures, never showed it. `forwarded_by` is inside
            # the signed payload, so a forwarder cannot claim another name.
            sender = retraction.forwarded_by or retraction.origin_store_id
            key = registry.key_for(sender,
                                   signature.get("key_id") if isinstance(signature, Mapping)
                                   else None)
            if key is None or not retraction.verify(signature, key):
                # Still recorded locally: a refused retraction is an audit
                # event worth having. But the acknowledgement is *not* the
                # reply. It carries `recipient_store_id`, `state_revision` —
                # this store's event-log head — and `origin_sequence_seen`,
                # none of which an unauthenticated caller may learn, and the
                # head sequence in particular is pollable as an activity
                # oracle.
                with _store_lock(fabric):
                    fabric.receive_retraction(retraction, sender_authorised=False)
                self._reply(
                    HTTPStatus.UNAUTHORIZED,
                    {"rejection_code": RejectionCode.UNAUTHORIZED.value},
                )
                return

            with _store_lock(fabric):
                ack = fabric.receive_retraction(retraction, sender_authorised=True)
            status = (
                HTTPStatus.OK
                if ack.state
                not in (PropagationState.REJECTED,)
                else HTTPStatus.CONFLICT
            )
            self._reply(status, ack.to_json())

        def _notice(self) -> None:
            from .protocol import SourceNotice

            try:
                body = self._read_body()
                notice = SourceNotice.from_json(body.get("notice", {}))
            except ProtocolError as exc:
                self._reply(HTTPStatus.BAD_REQUEST, {"rejection_code": exc.code.value})
                return
            sig = body.get("signature") or {}
            key = registry.key_for(notice.origin_store_id,
                                   sig.get("key_id") if isinstance(sig, Mapping) else None)
            if key is None or not notice.verify(body.get("signature") or {}, key):
                with _store_lock(fabric):
                    fabric.receive_notice(notice, sender_authorised=False)
                self._reply(HTTPStatus.UNAUTHORIZED,
                            {"rejection_code": RejectionCode.UNAUTHORIZED.value})
                return
            with _store_lock(fabric):
                fabric.receive_notice(notice, sender_authorised=True)
            self._reply(HTTPStatus.OK, {"accepted": True})

        def _offer(self) -> None:
            """Import a peer's signed offer as a candidate, recorded as `peer:<store>`."""
            from .federation import PreparedOffer, accept_offer

            try:
                body = self._read_body()
                raw = body.get("offer") or {}
                prepared = PreparedOffer.from_json(raw)
            except (ProtocolError, KeyError, TypeError, ValueError):
                self._reply(HTTPStatus.BAD_REQUEST,
                            {"rejection_code": RejectionCode.MALFORMED.value})
                return
            signature = body.get("signature") or {}
            key = registry.key_for(prepared.origin_store_id,
                                   signature.get("key_id") if isinstance(signature, Mapping)
                                   else None)
            if key is None or not isinstance(signature, Mapping) or not verify_body(
                    raw, signature, key):
                self._reply(HTTPStatus.UNAUTHORIZED,
                            {"rejection_code": RejectionCode.UNAUTHORIZED.value})
                return
            with _store_lock(fabric):
                result = accept_offer(fabric, prepared, peer_agent(prepared.origin_store_id))
            self._reply(HTTPStatus.OK, {"accepted": result.accepted,
                                        "decision": result.decision.value,
                                        "reasons": result.reasons,
                                        "imported_memory_id": result.imported_memory_id})

        def _reconcile(self) -> None:
            """A recipient asks: what have I missed from you since my cursor?

            The cursor is the *recipient's*, never the origin's guess about it.
            Replaying too much is safe because processing is idempotent;
            replaying too little is the only real failure.
            """
            try:
                body = self._read_body()
            except ProtocolError as exc:
                self._reply(
                    HTTPStatus.BAD_REQUEST,
                    {"rejection_code": exc.code.value, "detail": exc.detail},
                )
                return

            asker = str(body.get("store_id", ""))
            if registry.get(asker) is None:
                # A code and nothing else, which is also what the retraction
                # path now returns. An unknown peer must not be able to tell
                # "no such store here" from "that store exists but you are not
                # it" — the registry is the authorisation boundary, and a
                # distinguishable refusal would make it an enumeration oracle.
                self._reply(
                    HTTPStatus.UNAUTHORIZED,
                    {"rejection_code": RejectionCode.UNAUTHORIZED.value},
                )
                return
            since = int(body.get("since_sequence", -1))
            with _store_lock(fabric):
                payload = {
                    "store_id": fabric.store_id,
                    "retractions": [
                        r.to_json() for r in fabric.retractions_since(since)
                    ],
                }
            self._reply(HTTPStatus.OK, payload)

    server = ThreadingHTTPServer((host, port), Handler)
    return server


@dataclass
class ServedFabric:
    """A fabric with a federation server running in a thread, for tests and for
    the reference deployment."""

    fabric: Any
    server: ThreadingHTTPServer
    thread: threading.Thread = field(init=False)

    def __post_init__(self) -> None:
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def endpoint(self) -> str:
        host, port = self.server.server_address[:2]
        # Typed `str | bytes`: bytes only for an AF_UNIX socket, never here.
        if isinstance(host, bytes):
            host = host.decode()
        return f"http://{host}:{port}"

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


def serve(
    fabric: Any, registry: PeerRegistry, host: str = "127.0.0.1", port: int = 0
) -> ServedFabric:
    return ServedFabric(fabric, build_federation_server(fabric, registry, host, port))
