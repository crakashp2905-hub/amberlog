"""JSON-RPC 2.0 and MCP version negotiation, independent of any transport.

## The specification moved, and this is built against where it is now

The current revision is **2026-07-28**, and it is not a minor update. It made
MCP **stateless**: the `initialize` / `notifications/initialized` handshake is
gone. Every request now carries its own protocol version and client
capabilities in `_meta`:

    io.modelcontextprotocol/protocolVersion
    io.modelcontextprotocol/clientCapabilities
    io.modelcontextprotocol/clientInfo         (SHOULD)

and every result SHOULD identify the server in its own `_meta` as
`io.modelcontextprotocol/serverInfo`. `server/discover` is the one RPC a
server **MUST** implement; clients may call it first to choose a version, or
use it as a backward-compatibility probe on stdio. Every result carries a
required `resultType` (`"complete"`, or `"input_required"` for a multi
round-trip interim result), and `tools/list`, `prompts/list`,
`resources/list`, `resources/read` and `resources/templates/list` must carry
`ttlMs` and `cacheScope`.

Most of the published tutorials and samples predate this. A server written
from them sends an `initialize` result to a client that will never ask for one,
omits `resultType`, and leaves caching undefined. This one does not.

## And older clients still exist, so it speaks both

A client on 2025-11-25 or earlier opens with `initialize`. Rejecting it would
make the server unusable from most hosts shipping today, so the legacy
handshake is honoured: the requested version is accepted if supported and
otherwise answered with the newest legacy version this server speaks, which is
the negotiation rule those revisions defined. After that, the connection runs
at the negotiated version and results are shaped for it -- **no `resultType`,
no cache fields** -- because each revision's schema is what its clients
validate against.

A request with no version at all, from a client that never initialised, is
malformed under 2026-07-28. It is refused with Invalid Params and the list of
supported versions, rather than guessed at: this is a trust boundary, and a
server that silently picks a version for a client has decided something the
client did not ask for.

## Caching is a correctness property here, not a performance one

`cacheScope: "private"` and `ttlMs: 0` on anything that returns memory
content. A memory's lifecycle can change at any moment -- that is what a
retraction *is* -- and a client or intermediary that cached a memory read would
go on serving a memory its origin has withdrawn. That defeats the one
capability this project measures best (PB2: acting on retracted memory, 17% to
0%). Tool definitions carry no user data, so they are `public` with a long TTL.

## Errors

| code | meaning | when |
|---|---|---|
| -32700 | Parse error | the line is not JSON |
| -32600 | Invalid Request | not a JSON-RPC 2.0 request object |
| -32601 | Method not found | |
| -32602 | Invalid Params | including an unknown tool and, from 2026-07-28, a missing resource (it was -32002) |
| -32603 | Internal error | a bug, never an expected condition |
| -32022 | Unsupported protocol version | renumbered from -32004 in this revision |
| -32021 | Missing required client capability | |

**A tool that fails is not a protocol error.** It returns a normal result with
`isError: true` and a message, because the model needs to see the failure to
recover from it, and a JSON-RPC error is something the host swallows.
"""

from __future__ import annotations

import json
import sys
import traceback
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

CURRENT_VERSION = "2026-07-28"
LEGACY_VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26")
"""Spoken via the `initialize` handshake, newest first."""
SUPPORTED_VERSIONS = (CURRENT_VERSION,) + LEGACY_VERSIONS

META_PROTOCOL = "io.modelcontextprotocol/protocolVersion"
META_CLIENT_CAPABILITIES = "io.modelcontextprotocol/clientCapabilities"
META_CLIENT_INFO = "io.modelcontextprotocol/clientInfo"
META_SERVER_INFO = "io.modelcontextprotocol/serverInfo"

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603
MISSING_CAPABILITY = -32021
UNSUPPORTED_VERSION = -32022

CACHEABLE = frozenset({
    "tools/list", "prompts/list", "resources/list", "resources/read",
    "resources/templates/list",
})
"""Methods whose 2026-07-28 results MUST carry `ttlMs` and `cacheScope`."""


class McpError(Exception):
    """A protocol-level failure, which becomes a JSON-RPC error object."""

    def __init__(self, code: int, message: str,
                 data: Any | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data

    def to_error(self) -> dict[str, Any]:
        out: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.data is not None:
            out["data"] = self.data
        return out


@dataclass
class Cache:
    """A result's caching hint, attached at the dispatch layer.

    Handlers declare it so that the decision sits next to the data it is
    about, rather than in a table here that would drift from the handlers.
    """

    ttl_ms: int
    scope: str = "private"

    def __post_init__(self) -> None:
        if self.scope not in ("public", "private"):
            raise ValueError("cacheScope must be 'public' or 'private'")
        if self.ttl_ms < 0:
            raise ValueError("ttlMs must be non-negative")


@dataclass
class Handled:
    """What a method handler returns: the result body and, for cacheable
    methods, how it may be cached."""

    result: dict[str, Any]
    cache: Cache | None = None


Handler = Callable[[Mapping[str, Any], "Context"], Handled]


@dataclass
class Context:
    """What a handler knows about the request it is serving."""

    version: str
    client_info: Mapping[str, Any] = field(default_factory=dict)
    client_capabilities: Mapping[str, Any] = field(default_factory=dict)
    stateless: bool = True


@dataclass
class Server:
    """A transport-agnostic MCP server.

    `handle()` takes one parsed JSON-RPC message and returns the response
    object to send, or `None` for a notification. Transports own the bytes;
    this owns the meaning.
    """

    name: str
    version: str
    capabilities: dict[str, Any]
    instructions: str = ""
    methods: dict[str, Handler] = field(default_factory=dict)
    session_version: str | None = None
    """Set by a legacy `initialize`. `None` means stateless operation."""
    initialized: bool = False

    # --- registration -----------------------------------------------------

    def method(self, name: str) -> Callable[[Handler], Handler]:
        def register(fn: Handler) -> Handler:
            self.methods[name] = fn
            return fn
        return register

    # --- dispatch ---------------------------------------------------------

    def handle(self, message: Any) -> Any:
        """One message in, one response out (or None for a notification).

        A JSON array is processed as a batch. Batching was removed in
        2025-06-18, so no current client sends one, but accepting it costs
        nothing and a 2025-03-26 client is entitled to.
        """
        if isinstance(message, list):
            if not message:
                return _error(None, McpError(INVALID_REQUEST,
                                             "empty batch"))
            out = [r for r in (self._one(m) for m in message) if r is not None]
            return out or None
        return self._one(message)

    def _one(self, message: Any) -> dict[str, Any] | None:
        if not isinstance(message, Mapping) or message.get("jsonrpc") != "2.0":
            return _error(_id_of(message), McpError(
                INVALID_REQUEST, "not a JSON-RPC 2.0 message"))
        method = message.get("method")
        is_notification = "id" not in message
        request_id = message.get("id")
        if not isinstance(method, str):
            if is_notification:
                return None
            return _error(request_id, McpError(
                INVALID_REQUEST, "missing method"))

        params = message.get("params") or {}
        if not isinstance(params, Mapping):
            if is_notification:
                return None
            return _error(request_id, McpError(
                INVALID_PARAMS, "params must be an object"))

        try:
            if method == "initialize":
                result = self._initialize(params)
                return _ok(request_id, result)
            if method == "notifications/initialized":
                # Legacy handshake completion. A notification never gets a
                # response, including when it is unexpected.
                self.initialized = True
                return None
            if method.startswith("notifications/"):
                return None

            context = self._context(method, params)
            handler = self.methods.get(method)
            if handler is None:
                raise McpError(METHOD_NOT_FOUND, f"method not found: {method}")
            handled = handler(params, context)
            body = self._shape(method, handled, context)
            return None if is_notification else _ok(request_id, body)
        except McpError as error:
            return None if is_notification else _error(request_id, error)
        except Exception as error:  # noqa: BLE001 - must not kill the loop
            # Logged to stderr, never stdout: on stdio, stdout is the protocol
            # and a stray line corrupts the stream for the host.
            print(f"[memory-fabric mcp] internal error in {method}: "
                  f"{error!r}\n{traceback.format_exc()}", file=sys.stderr)
            if is_notification:
                return None
            return _error(request_id, McpError(
                INTERNAL_ERROR, f"internal error in {method}"))

    # --- version handling ------------------------------------------------

    def _initialize(self, params: Mapping[str, Any]) -> dict[str, Any]:
        """The legacy handshake, for clients on 2025-11-25 and earlier.

        Negotiation as those revisions defined it: accept the requested
        version if it is one this server speaks, otherwise answer with the
        newest legacy version and let the client decide whether to proceed.
        A client asking `initialize` for 2026-07-28 is contradicting itself --
        that revision has no `initialize` -- and is answered with the newest
        legacy version, which is the only coherent reading.
        """
        requested = params.get("protocolVersion")
        version = (requested if requested in LEGACY_VERSIONS
                   else LEGACY_VERSIONS[0])
        self.session_version = version
        result: dict[str, Any] = {
            "protocolVersion": version,
            "capabilities": self.capabilities,
            "serverInfo": {"name": self.name, "version": self.version},
        }
        if self.instructions:
            result["instructions"] = self.instructions
        return result

    def _context(self, method: str, params: Mapping[str, Any]) -> Context:
        meta = params.get("_meta") or {}
        if not isinstance(meta, Mapping):
            meta = {}
        requested = meta.get(META_PROTOCOL)

        if requested is not None:
            if requested not in SUPPORTED_VERSIONS:
                raise McpError(
                    UNSUPPORTED_VERSION,
                    f"unsupported protocol version: {requested!r}",
                    {"supported": list(SUPPORTED_VERSIONS),
                     "requested": requested})
            return Context(
                version=requested,
                client_info=meta.get(META_CLIENT_INFO) or {},
                client_capabilities=meta.get(META_CLIENT_CAPABILITIES) or {},
                stateless=(requested == CURRENT_VERSION),
            )

        if self.session_version is not None:
            return Context(version=self.session_version, stateless=False)

        if method == "server/discover":
            # The probe a stateless client sends before it knows what this
            # server speaks. It is the one request allowed to arrive without
            # a version, because answering it is how the version gets chosen.
            return Context(version=CURRENT_VERSION, stateless=True)

        raise McpError(
            INVALID_PARAMS,
            "no protocol version: send "
            f"_meta[{META_PROTOCOL!r}] (protocol {CURRENT_VERSION}) or "
            "open with initialize (earlier protocols)",
            {"supported": list(SUPPORTED_VERSIONS)})

    def _shape(self, method: str, handled: Handled,
               context: Context) -> dict[str, Any]:
        """Fit a result to the schema of the version the client speaks."""
        body = dict(handled.result)
        if context.version != CURRENT_VERSION:
            return body
        body.setdefault("resultType", "complete")
        meta = dict(body.get("_meta") or {})
        meta[META_SERVER_INFO] = {"name": self.name, "version": self.version}
        body["_meta"] = meta
        if method in CACHEABLE:
            cache = handled.cache or Cache(ttl_ms=0, scope="private")
            body["ttlMs"] = cache.ttl_ms
            body["cacheScope"] = cache.scope
        return body

    def discover(self) -> dict[str, Any]:
        """The body of `server/discover`."""
        return {
            "supportedVersions": list(SUPPORTED_VERSIONS),
            "capabilities": self.capabilities,
            "serverInfo": {"name": self.name, "version": self.version},
            **({"instructions": self.instructions} if self.instructions else {}),
        }


def _ok(request_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _error(request_id: Any, error: McpError) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": error.to_error()}


def _id_of(message: Any) -> Any:
    return message.get("id") if isinstance(message, Mapping) else None


def parse(line: str) -> Any:
    """One line of input, or a Parse error response to send back."""
    try:
        return json.loads(line)
    except (ValueError, TypeError) as error:
        raise McpError(PARSE_ERROR, f"parse error: {error}") from error
