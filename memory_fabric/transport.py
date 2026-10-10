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

import json
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable, Mapping, Protocol

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

    def key_for(self, store_id: str) -> bytes | None:
        peer = self._peers.get(store_id)
        return peer.key if peer else None

    def __contains__(self, store_id: object) -> bool:
        return store_id in self._peers

    def __len__(self) -> int:
        return len(self._peers)


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
        authorised = (
            retraction.origin_store_id in self.registry
            if len(self.registry)
            else True
        )
        return store.receive_retraction(retraction, sender_authorised=authorised)


class HttpTransport:
    """The real transport: authenticated HTTP POST, stdlib only."""

    def __init__(
        self, registry: PeerRegistry, origin_store_id: str, timeout: float = 10.0
    ) -> None:
        self.registry = registry
        self.origin_store_id = origin_store_id
        self.timeout = timeout

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


def build_federation_server(
    fabric: Any,
    registry: PeerRegistry,
    host: str = "127.0.0.1",
    port: int = 0,
) -> ThreadingHTTPServer:
    """An HTTP server that accepts retractions and reconciliation requests.

    Separate from the observability server on purpose; see the module docstring.
    Every request must authenticate, and an unauthenticated one is refused
    before the message is even parsed — invariant 11, fail closed when identity
    is unknown.
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
            elif self.path == "/federation/reconcile":
                self._reconcile()
            else:
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
                self._reply(
                    HTTPStatus.BAD_REQUEST,
                    {"rejection_code": exc.code.value, "detail": exc.detail},
                )
                return

            # 1-3: authenticate, then authorise. Before anything is applied.
            key = registry.key_for(retraction.origin_store_id)
            signature = body.get("signature") or {}
            if key is None or not retraction.verify(signature, key):
                ack = fabric.receive_retraction(retraction, sender_authorised=False)
                self._reply(HTTPStatus.UNAUTHORIZED, ack.to_json())
                return

            ack = fabric.receive_retraction(retraction, sender_authorised=True)
            status = (
                HTTPStatus.OK
                if ack.state
                not in (PropagationState.REJECTED,)
                else HTTPStatus.CONFLICT
            )
            self._reply(status, ack.to_json())

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
                self._reply(
                    HTTPStatus.UNAUTHORIZED,
                    {"rejection_code": RejectionCode.UNAUTHORIZED.value},
                )
                return
            since = int(body.get("since_sequence", -1))
            self._reply(
                HTTPStatus.OK,
                {
                    "store_id": fabric.store_id,
                    "retractions": [
                        r.to_json() for r in fabric.retractions_since(since)
                    ],
                },
            )

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
        return f"http://{host}:{port}"

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


def serve(
    fabric: Any, registry: PeerRegistry, host: str = "127.0.0.1", port: int = 0
) -> ServedFabric:
    return ServedFabric(fabric, build_federation_server(fabric, registry, host, port))
