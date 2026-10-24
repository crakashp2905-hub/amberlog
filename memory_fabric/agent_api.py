"""An authenticated HTTP API for agents, in its own process.

The MCP server serves one agent on one machine over stdio. This serves many
agents over a socket, so an agent in another language, process or machine can
use the fabric -- the deployment `service.py` describes as "the service runs in
its own process and the application talks to it over a socket".

Three properties carry over unchanged and are the point:

* **The surface is the agent's narrow one.** Each request is handled by an
  `AgentClient` bound to the *verified* principal: `recall`, `fetch`,
  `verify`, `remember`. No unenforced read, no scope argument, and no outcome
  endpoint -- an outcome needs a third-party verifier, and the caller here is
  the agent being scored.
* **Identity is verified on every request**, from a signed, expiring credential
  issued by `identity.PrincipalRegistry`. Revocation and expiry act at the next
  call, not at the next restart.
* **The observability server stays read-only.** This is a separate server on a
  separate port, so the dashboard's "no mutating endpoint" guarantee and its
  tests are untouched.

What it adds for being on a network:

* Off loopback it refuses to start unless told TLS terminates in front of it
  (`--behind-tls`): a bearer credential over plain HTTP is a leaked credential.
* A request carrying an `Origin` header is refused. Only browsers send one, and
  no browser has business calling this API; that closes cross-site use and DNS
  rebinding without a cookie or CORS policy to get wrong.
* Bodies are capped, and every authentication failure returns the same 401 so
  a caller cannot tell an unknown agent from an expired or revoked credential.

Exposure tokens stay on the server, keyed by agent and memory, exactly as in
the MCP server: a caller names a memory by id and cannot forge a token. They
are bounded per agent (`MAX_TOKENS_PER_AGENT`, oldest evicted), so a caller
cannot grow the server's memory by recalling without end; an evicted memory
is simply recalled again before `verify`.

**Rate limits.** Each authenticated agent has a token bucket
(`RateLimit`, default 20 requests a second with a burst of 40), and failed
authentications are limited per remote address, so a flood is refused with
`429` and `Retry-After` before it reaches the store's single write lock.
Before this, nothing limited a caller: P12 measured that the store queues
rather than fails under contention, so one agent in a loop could make every
other agent wait.
"""

from __future__ import annotations

__stability__ = "beta"

import base64
import json
import logging
import math
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable, Mapping

from .limits import LimitExceeded
from .enforcement import ExposureToken, RiskLevel
from .identity import Credential, IdentityError, ROLE_AGENT
from .sdk import AgentClient, NotUsable, UsableMemory, public_error
from .service import MemoryService

MAX_BODY = 64 * 1024
# How much of a refused body is read and discarded before replying. Closing a
# socket with unread bytes makes the OS reset the connection, and the client
# then sees an abort instead of the 413 -- one run in five on Windows for a
# 70 KB body. Draining fixes that; the bound keeps a refusal from becoming a
# way to make the server read an unlimited upload. Beyond it, the connection
# is closed unread and a reset is the expected outcome.
MAX_DRAIN = 1024 * 1024
LOOPBACK = frozenset({"127.0.0.1", "localhost", "::1"})
MIN_KEY_BYTES = 32
MAX_TOKENS_PER_AGENT = 4096


class ConfigurationError(Exception):
    """A configuration that cannot be made safe; refused rather than warned."""


# --- configuration -----------------------------------------------------------


@dataclass(frozen=True)
class AgentEntry:
    agent_id: str
    tenant_id: str
    key: bytes


def load_agents(path: str) -> list[AgentEntry]:
    """Read `agent_id:tenant_id:hex_key` lines; `#` comments and blanks ignored.

    The keys are secrets: this file belongs on the server only, with owner-only
    permissions. Short keys and duplicates are refused.
    """
    entries: list[AgentEntry] = []
    seen: set[str] = set()
    with open(path, encoding="utf-8") as handle:
        for number, raw in enumerate(handle, 1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split(":")
            if len(parts) != 3 or not all(p.strip() for p in parts):
                raise ConfigurationError(f"{path}:{number}: expected agent_id:tenant_id:hex_key")
            agent_id, tenant_id, hex_key = (p.strip() for p in parts)
            try:
                key = bytes.fromhex(hex_key)
            except ValueError:
                raise ConfigurationError(f"{path}:{number}: key is not hex") from None
            if len(key) < MIN_KEY_BYTES:
                raise ConfigurationError(
                    f"{path}:{number}: key for {agent_id!r} is shorter than "
                    f"{MIN_KEY_BYTES} bytes; generate one with "
                    "python -c 'import secrets; print(secrets.token_hex(32))'")
            if agent_id in seen:
                raise ConfigurationError(f"{path}:{number}: duplicate agent {agent_id!r}")
            seen.add(agent_id)
            entries.append(AgentEntry(agent_id, tenant_id, key))
    if not entries:
        raise ConfigurationError(f"{path}: no agents defined")
    return entries


def register_all(service: MemoryService, entries: list[AgentEntry]) -> None:
    for entry in entries:
        service.register_agent(entry.agent_id, key=entry.key,
                               tenant_id=entry.tenant_id, roles=(ROLE_AGENT,))


def encode_credential(credential: Credential) -> str:
    raw = json.dumps(credential.to_json(), sort_keys=True, separators=(",", ":"))
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def decode_credential(token: str) -> Credential:
    try:
        padded = token + "=" * (-len(token) % 4)
        data = json.loads(base64.urlsafe_b64decode(padded.encode()).decode())
    except (ValueError, UnicodeDecodeError) as exc:
        raise IdentityError(f"malformed credential: {exc}") from None
    if not isinstance(data, dict):
        raise IdentityError("malformed credential")
    return Credential.from_json(data)


def check_bind(host: str, behind_tls: bool) -> None:
    if host not in LOOPBACK and not behind_tls:
        raise ConfigurationError(
            f"refusing to serve agent credentials over plain HTTP on {host!r}. "
            "Bind to 127.0.0.1, or put a TLS-terminating proxy in front and pass "
            "--behind-tls.")


# --- the API -----------------------------------------------------------------


class _ApiError(Exception):
    def __init__(self, status: HTTPStatus, message: str,
                 retry_after: float | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.message = message
        self.retry_after = retry_after


@dataclass(frozen=True)
class RateLimit:
    """A token bucket: `rate` requests a second on average, `burst` at once.

    `rate <= 0` turns limiting off. `auth_failures` is the same budget a
    second for failed authentications from one remote address.
    """

    rate: float = 20.0
    burst: int = 40
    auth_failures: float = 5.0


@dataclass
class _Bucket:
    tokens: float
    stamp: float


@dataclass
class RateLimiter:
    """Token buckets by key. Thread-safe; the clock is injectable for tests."""

    rate: float
    burst: int
    clock: Callable[[], float] = time.monotonic
    max_keys: int = 100_000
    _buckets: "OrderedDict[str, _Bucket]" = field(default_factory=OrderedDict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def acquire(self, key: str) -> float:
        """0.0 if the request may proceed, else the seconds until it could."""
        if self.rate <= 0:
            return 0.0
        now = self.clock()
        with self._lock:
            bucket = self._buckets.pop(key, None) or _Bucket(float(self.burst), now)
            bucket.tokens = min(float(self.burst),
                                bucket.tokens + (now - bucket.stamp) * self.rate)
            bucket.stamp = now
            self._buckets[key] = bucket
            while len(self._buckets) > self.max_keys:
                self._buckets.popitem(last=False)
            if bucket.tokens >= 1.0:
                bucket.tokens -= 1.0
                return 0.0
            return (1.0 - bucket.tokens) / self.rate


class AgentApi:
    """Request handling, separate from HTTP so it can be tested with dicts."""

    def __init__(self, service: MemoryService, limits: RateLimit | None = None,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.service = service
        # The server owns the service; reaching its fabric here is the server
        # building the narrow per-agent client, not a caller bypassing it.
        self._fabric = service._fabric
        self._issued: dict[str, OrderedDict[str, ExposureToken]] = {}
        limits = limits or RateLimit()
        self._per_agent = RateLimiter(limits.rate, limits.burst, clock)
        self._per_address = RateLimiter(limits.auth_failures,
                                        max(1, int(limits.auth_failures * 2)), clock)

    def _refused(self, remote: str) -> "_ApiError":
        # One answer for every failure: unknown agent, bad signature,
        # expired, revoked. Distinguishing them tells an attacker which.
        wait = self._per_address.acquire(remote)
        if wait:
            return _ApiError(HTTPStatus.TOO_MANY_REQUESTS, "too many requests",
                             retry_after=wait)
        return _ApiError(HTTPStatus.UNAUTHORIZED, "authentication required")

    def precheck(self, bearer: str | None, remote: str = "") -> Credential:
        """Refuse or rate-limit without touching the store; return the credential.

        Signature and expiry need only the in-memory registrations, so a forged
        or expired credential, and an agent over its rate, are answered here,
        before the request can queue on the store's lock.
        """
        try:
            if not bearer:
                raise IdentityError("no credential")
            credential = decode_credential(bearer)
            agent_id = self.service.precheck(credential)
        except IdentityError:
            raise self._refused(remote) from None
        wait = self._per_agent.acquire(agent_id)
        if wait:
            raise _ApiError(HTTPStatus.TOO_MANY_REQUESTS, "too many requests",
                            retry_after=wait)
        return credential

    def client_for(self, credential: Credential, remote: str = "") -> AgentClient:
        """Full verification, revocation included. Call under the fabric's lock."""
        try:
            principal = self.service.session(credential).principal()
        except IdentityError:
            raise self._refused(remote) from None
        return AgentClient(self._fabric, principal.agent_id, principal.tenant_id)

    def handle(self, operation: str, bearer: str | None, body: Mapping[str, Any],
               remote: str = "") -> Any:
        # Two halves. Signature, expiry and the rate limit need no store and
        # run first, so a forged, expired or over-rate request never queues on
        # the store's lock. Revocation is a read on the store's one
        # connection, so it runs under the lock with the operation: it used to
        # run outside it, and concurrently with another request it failed 39
        # of 200 times under ten agents (experiments/p12_http.py) -- an
        # interfered-with read is a revocation check that can say "not
        # revoked".
        credential = self.precheck(bearer, remote)
        with self._fabric.lock:
            client = self.client_for(credential, remote)
            if operation == "recall":
                return self._recall(client, body)
            if operation == "fetch":
                return self._fetch(client, body)
            if operation == "verify":
                return self._verify(client, body)
            if operation == "remember":
                return self._remember(client, body)
            raise _ApiError(HTTPStatus.NOT_FOUND, "unknown operation")

    def _recall(self, client: AgentClient, body: Mapping[str, Any]) -> dict[str, Any]:
        query = _string(body, "query")
        k = body.get("k", 5)
        if not isinstance(k, int) or isinstance(k, bool) or not 1 <= k <= 20:
            raise _ApiError(HTTPStatus.BAD_REQUEST, "k must be an integer from 1 to 20")
        include = body.get("include_contested", False)
        if not isinstance(include, bool):
            raise _ApiError(HTTPStatus.BAD_REQUEST, "include_contested must be a boolean")
        hits = client.recall(query, k=k, include_contested=include)
        return {"memories": [self._present(client, m) for m in hits]}

    def _fetch(self, client: AgentClient, body: Mapping[str, Any]) -> dict[str, Any]:
        memory_id = _string(body, "memory_id")
        try:
            return self._present(client, client.fetch(memory_id))
        except NotUsable as exc:
            raise _ApiError(HTTPStatus.FORBIDDEN,
                            f"not usable: {exc.decision.reason_code}") from None

    def _verify(self, client: AgentClient, body: Mapping[str, Any]) -> dict[str, Any]:
        memory_id = _string(body, "memory_id")
        issued = self._issued.get(client.agent_id, OrderedDict()).get(memory_id)
        if issued is None:
            raise _ApiError(HTTPStatus.CONFLICT,
                            "recall or fetch this memory before verifying it")
        decision = self._fabric.verify_before_action(issued, client.agent_id,
                                                     risk=RiskLevel.HIGH)
        return {"memory_id": memory_id, "usable": decision.usable,
                "verdict": decision.verdict.value, "reason": decision.reason_code}

    def _remember(self, client: AgentClient, body: Mapping[str, Any]) -> dict[str, Any]:
        content = _string(body, "content")
        kind = body.get("type", "semantic")
        if kind not in ("semantic", "procedural"):
            raise _ApiError(HTTPStatus.BAD_REQUEST, "type must be semantic or procedural")
        memory_id = client.remember(content, type=kind)
        return {"memory_id": memory_id,
                "state": self._fabric.lifecycle_of(memory_id).value}

    def _present(self, client: AgentClient, memory: UsableMemory) -> dict[str, Any]:
        issued = self._issued.setdefault(client.agent_id, OrderedDict())
        issued.pop(memory.memory_id, None)
        issued[memory.memory_id] = memory.token
        while len(issued) > MAX_TOKENS_PER_AGENT:
            issued.popitem(last=False)
        out: dict[str, Any] = {"memory_id": memory.memory_id, "version": memory.version,
                               "type": memory.type, "content": memory.content}
        if memory.warnings:
            out["warnings"] = list(memory.warnings)
        return out


def _string(body: Mapping[str, Any], key: str) -> str:
    value = body.get(key)
    if not isinstance(value, str) or not value.strip():
        raise _ApiError(HTTPStatus.BAD_REQUEST, f"{key} must be a non-empty string")
    return value


# --- HTTP --------------------------------------------------------------------


def build_agent_server(api: AgentApi, host: str = "127.0.0.1", port: int = 8766,
                       behind_tls: bool = False) -> ThreadingHTTPServer:
    check_bind(host, behind_tls)

    class Handler(BaseHTTPRequestHandler):
        server_version = "MemoryFabricAgentAPI/1"
        protocol_version = "HTTP/1.1"

        def log_message(self, *args: Any) -> None:  # never log headers or bodies
            return

        def _reply(self, status: HTTPStatus, payload: Any,
                   retry_after: float | None = None) -> None:
            body = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            if status == HTTPStatus.UNAUTHORIZED:
                self.send_header("WWW-Authenticate", 'Bearer realm="memory-fabric-agents"')
            if retry_after is not None:
                self.send_header("Retry-After", str(max(1, math.ceil(retry_after))))
            self.end_headers()
            self.wfile.write(body)

        def _drain_and_refuse(self, status: HTTPStatus, message: str) -> None:
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                length = 0
            if 0 < length <= MAX_DRAIN:
                remaining = length
                while remaining > 0:
                    chunk = self.rfile.read(min(remaining, MAX_BODY))
                    if not chunk:
                        break
                    remaining -= len(chunk)
            self.close_connection = True
            self._reply(status, {"error": message})

        def do_POST(self) -> None:  # noqa: N802
            if self.headers.get("Origin"):
                self._drain_and_refuse(HTTPStatus.FORBIDDEN, "browser requests are not accepted")
                return
            if not self.path.startswith("/v1/"):
                self._drain_and_refuse(HTTPStatus.NOT_FOUND, "not found")
                return
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                length = -1
            if length < 0 or length > MAX_BODY:
                self._drain_and_refuse(HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                                       f"body must be at most {MAX_BODY} bytes")
                return
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
            except (ValueError, UnicodeDecodeError):
                self._reply(HTTPStatus.BAD_REQUEST, {"error": "body is not JSON"})
                return
            if not isinstance(body, dict):
                self._reply(HTTPStatus.BAD_REQUEST, {"error": "body must be an object"})
                return
            header = self.headers.get("Authorization") or ""
            scheme, _, value = header.partition(" ")
            bearer = value.strip() if scheme.lower() == "bearer" else None
            try:
                result = api.handle(self.path[len("/v1/"):], bearer, body,
                                    remote=self.client_address[0])
            except _ApiError as exc:
                self._reply(exc.status, {"error": exc.message}, exc.retry_after)
            except LimitExceeded as exc:
                self._reply(HTTPStatus.TOO_MANY_REQUESTS if exc.code != "payload_too_large"
                            else HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                            {"error": exc.code}, 1)
            except Exception as exc:  # a refused write is an answer, not a crash
                logging.getLogger(__name__).warning("request refused", exc_info=exc)
                self._reply(HTTPStatus.UNPROCESSABLE_ENTITY, {"error": public_error(exc)})
            else:
                self._reply(HTTPStatus.OK, result)

        def do_GET(self) -> None:  # noqa: N802
            if self.path == "/v1/health":
                self._reply(HTTPStatus.OK, {"ok": True})
            else:
                self._reply(HTTPStatus.METHOD_NOT_ALLOWED, {"error": "use POST"})

    server = _Server((host, port), Handler)
    server.daemon_threads = True
    return server


class _Server(ThreadingHTTPServer):
    # The socketserver default backlog is 5. With 100 agents connecting at
    # once the kernel reset the overflow (P12b), and callers saw a dropped
    # connection rather than a queue.
    request_queue_size = 128
