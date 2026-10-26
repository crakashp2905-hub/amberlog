"""Read-only HTTP server for the dashboard, on the standard library alone.

Three deliberate constraints:

* **Read-only.** There is no endpoint that changes a memory. Browsing a store can
  therefore never alter it, and the server needs no CSRF defence because there is
  nothing to forge a request against. Mutation lives in the SDK and the CLI.
* **Localhost by default.** There is no authentication, so the socket must not be
  reachable from the network unless someone asks for that explicitly and is told
  what it means.
* **No filesystem routing.** Static assets come from a fixed allowlist, so no
  request path ever reaches a path join and traversal is impossible by
  construction rather than by sanitising.
"""

from __future__ import annotations

__stability__ = "beta"

import hashlib
import json
import re
import threading
import time
from dataclasses import is_dataclass
from functools import partial
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qs, urlparse

from ..identity import DEFAULT_TENANT
from . import report
from .auth import (
    AuthConfig,
    Authenticator,
    AuthOutcome,
    InsecureConfiguration,
    build_config,
    redact_token,
)

if TYPE_CHECKING:  # pragma: no cover
    from ..fabric import MemoryFabric

__all__ = [
    "Api",
    "ApiError",
    "AuthConfig",
    "InsecureConfiguration",
    "build_config",
    "build_server",
    "serve",
]

STATIC_DIR = Path(__file__).resolve().parent / "static"

# The only files this server will ever serve, by exact request path.
STATIC_ROUTES: dict[str, tuple[str, str]] = {
    "/": ("dashboard.html", "text/html; charset=utf-8"),
    "/dashboard.html": ("dashboard.html", "text/html; charset=utf-8"),
}

_ULID = re.compile(r"^[0-9A-HJKMNP-TV-Z]{26}$")
_BRANCH = re.compile(r"^[a-z0-9][a-z0-9._-]{0,62}$")
_RECEIPT = re.compile(r"^ctx_[0-9A-HJKMNP-TV-Z]{26}$")


class ApiError(Exception):
    def __init__(self, status: HTTPStatus, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def _json_default(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        if hasattr(value, "to_json"):
            return value.to_json()
        from dataclasses import asdict

        return asdict(value)
    if isinstance(value, (set, frozenset)):
        return sorted(value)
    return str(value)


def _one(params: dict[str, list[str]], key: str) -> str | None:
    values = params.get(key)
    if not values:
        return None
    value = values[0].strip()
    return value or None


def _int(params: dict[str, list[str]], key: str, default: int | None = None) -> int | None:
    raw = _one(params, key)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        raise ApiError(HTTPStatus.BAD_REQUEST, f"{key} must be an integer, got {raw!r}")


def _memory_id(raw: str) -> str:
    """Validate the shape before it reaches the store.

    Ids are ULIDs, so anything else is a client error rather than a lookup that
    happens to miss, and rejecting early keeps arbitrary strings out of error
    messages that get rendered back into the page.
    """
    if not _ULID.match(raw):
        raise ApiError(HTTPStatus.BAD_REQUEST, "malformed memory id")
    return raw


class Api:
    """Routes to the shared read model. Holds a lock because the fabric's
    projections are plain dicts and `ThreadingHTTPServer` serves concurrently."""

    def __init__(self, fabric: "MemoryFabric") -> None:
        self.fabric = fabric
        # The fabric's own lock, not one of ours: a process serving the
        # dashboard and the agent API on one store must serialise across both.
        self._lock = fabric.lock
        self._metrics: Any = None

    def metrics_text(self) -> str:
        """Prometheus exposition for this store (`metrics.py`), behind the same auth."""
        from .metrics import StoreMetrics

        with self._lock:
            self.fabric.refresh()
            if self._metrics is None:
                self._metrics = StoreMetrics()
            return self._metrics.render(self.fabric)

    def handle(self, path: str, params: dict[str, list[str]]) -> Any:
        from ..fabric import NotFound

        parts = [p for p in path.strip("/").split("/") if p]
        if not parts or parts[0] != "api":
            raise ApiError(HTTPStatus.NOT_FOUND, "not found")
        rest = parts[1:]

        with self._lock:
            # A dashboard runs for hours while operators act from the CLI. It
            # must show what the log says now, not what it said at startup.
            self.fabric.refresh()
            try:
                return self._route(rest, params)
            except NotFound as exc:
                raise ApiError(HTTPStatus.NOT_FOUND, str(exc)) from exc
            except ValueError as exc:
                raise ApiError(HTTPStatus.BAD_REQUEST, str(exc)) from exc

    def _route(self, rest: list[str], params: dict[str, list[str]]) -> Any:
        f = self.fabric

        match rest:
            case ["overview"]:
                return report.overview(f).to_json()

            case ["enums"]:
                return report.enum_values()

            case ["attention"]:
                return [i.to_json() for i in report.attention(f)]

            case ["lifecycle"]:
                from ..lifecycle import center

                return center(f, stale_days=_int(params, "stale_days", 90) or 90)

            case ["posture"]:
                from ..posture import posture

                return posture(f)

            case ["review"]:
                # The queue only. Decisions are writes and stay in the CLI and
                # SDK: this server has no endpoint that changes a memory.
                from ..review import queue

                return [i.to_json() for i in queue(f)]

            case ["propagation"]:
                # Invariant 9 made visible. Read-only, like everything here:
                # the dashboard shows propagation state, it does not drive it.
                # An offline recipient appears as `unknown` or `retrying`,
                # never as healthy — which is the specific failure the roadmap
                # calls out for this view.
                return {
                    "pending": report.propagation_rows(f),
                    "store_id": f.store_id,
                }
            case ["retention"]:
                return report.retention_preview(f)

            case ["memories"]:
                rows = report.memory_rows(
                    f,
                    state=_one(params, "state"),
                    scope=_one(params, "scope"),
                    type=_one(params, "type"),
                    query=_one(params, "q"),
                    limit=_int(params, "limit", 200),
                    sort=_one(params, "sort") or "created",
                )
                return [r.to_json() for r in rows]

            case ["memories", raw]:
                return report.memory_detail(f, _memory_id(raw))

            case ["memories", raw, "lineage"]:
                direction = _one(params, "direction") or "descendants"
                depth = _int(params, "depth", 6) or 6
                return report.lineage_tree(
                    f, _memory_id(raw), direction=direction, max_depth=depth
                ).to_json()

            case ["memories", raw, "why"]:
                from .control import eligibility

                return eligibility(f, _memory_id(raw), agent_id=_one(params, "agent") or "",
                                   tenant_id=_one(params, "tenant"), query=_one(params, "q") or "")

            case ["memories", raw, "dependence"]:
                from .control import dependence

                return dependence(f, _memory_id(raw))

            case ["memories", raw, "timeline"]:
                from .control import timeline

                return timeline(f, _memory_id(raw))

            case ["memories", raw, "if-wrong"]:
                from .control import if_wrong

                return if_wrong(f, _memory_id(raw))

            case ["map"]:
                from .control import knowledge_map

                return knowledge_map(f, per_topic=min(_int(params, "per_topic", 4) or 4, 8))
            case ["graph"]:
                from .control import graph

                return graph(f, limit=min(_int(params, "limit", 400) or 400, 2000))

            case ["agents"]:
                from .control import agents

                return agents(f)

            case ["story"]:
                from .control import story

                return story(f, after=_int(params, "after", 0) or 0,
                             limit=_int(params, "limit", 300) or 300)

            case ["actions"]:
                from .control import action_rows

                return action_rows(f, limit=_int(params, "limit", 200) or 200)

            case ["actions", raw_seq]:
                from .control import action_detail

                if not raw_seq.isdigit():
                    raise ApiError(HTTPStatus.BAD_REQUEST, "action is a log sequence number")
                try:
                    return action_detail(f, int(raw_seq))
                except KeyError as exc:
                    raise ApiError(HTTPStatus.NOT_FOUND, "no such action") from exc

            case ["limitations"]:
                from .control import limitations

                return limitations()

            case ["memories", raw, "audit"]:
                return report.memory_detail(f, _memory_id(raw))["audit"]

            case ["episodes"]:
                return report.episode_rows(f, limit=_int(params, "limit", 200))

            case ["capabilities"]:
                return json.loads((Path(__file__).parent / "static" / "capabilities.json")
                                  .read_text(encoding="utf-8"))

            case ["memories", raw, "correction"]:
                from ..correction import preview

                try:
                    return preview(f, _memory_id(raw)).to_json()
                except KeyError as exc:
                    raise ApiError(HTTPStatus.NOT_FOUND, "no such memory") from exc

            case ["branches"]:
                from ..branching import Branches

                return [b.to_json() for b in Branches(f).list_branches(
                    tenant_id=_one(params, "tenant") or DEFAULT_TENANT)]

            case ["branches", name] | ["branches", name, "preview"]:
                from ..branching import Branches

                if not _BRANCH.match(name):
                    raise ApiError(HTTPStatus.BAD_REQUEST, "malformed branch name")
                b = Branches(f)
                tenant = _one(params, "tenant") or DEFAULT_TENANT
                try:
                    branch = b.get(name, tenant)
                except KeyError as exc:
                    raise ApiError(HTTPStatus.NOT_FOUND, "no such branch") from exc
                if rest[-1] == "preview":
                    if branch.closed:
                        return {"branch": name, "closed": True, "changes": []}
                    # The operator's view, read-only: computed as the owner would see it.
                    return b.preview_merge(name, branch.owner, tenant).to_json()
                return {**branch.to_json(), "history": b.history(name, tenant),
                        "diff": b.diff(name, tenant)}

            case ["receipts"]:
                from ..context_receipt import receipts

                found = receipts(f, tenant_id=_one(params, "tenant"),
                                 agent_id=_one(params, "agent"))
                return found[-(_int(params, "limit", 200) or 200):]

            case ["receipts", rid]:
                from ..context_receipt import explain_receipt

                if not _RECEIPT.match(rid):
                    raise ApiError(HTTPStatus.BAD_REQUEST, "malformed receipt id")
                try:
                    return explain_receipt(f, rid, tenant_id=_one(params, "tenant"))
                except KeyError as exc:
                    raise ApiError(HTTPStatus.NOT_FOUND, "no such receipt") from exc

            case ["search"]:
                query = _one(params, "q")
                if not query:
                    raise ApiError(HTTPStatus.BAD_REQUEST, "q is required")
                hits = report.preview_search(
                    f,
                    query,
                    k=_int(params, "k", 10) or 10,
                    all_states=_one(params, "all") != "0",
                )
                return [h.to_json() for h in hits]

        raise ApiError(HTTPStatus.NOT_FOUND, "not found")


class AccessLog:
    """Who looked at what, one JSON line per request, in its own file.

    DEPLOYMENT.md listed "no audit of *who looked*" as a limit of the dashboard.
    This is that audit. It is deliberately **not** the event log: browsing
    must not write events, because the event log is the evidence every value
    estimate is computed from, and an operator's reading is not evidence about
    any memory. Refused and unauthenticated requests are recorded too -- they
    are the ones an investigation most wants. Tokens never appear in it.

    **Hash-chained** (security review O6): each line carries `prev`, the
    SHA-256 of the line before it, so a deleted, edited or reordered line
    breaks the chain at that point (`verify_access_log`). Like the event log,
    this detects tampering; it cannot stop someone who rewrites the whole file
    consistently. Lines written before chaining are accepted as its start.
    """

    def __init__(self, path: str) -> None:
        self.path = path
        self._lock = threading.Lock()
        # Fail at startup, not at the first request, if it cannot be written.
        with open(self.path, "a", encoding="utf-8"):
            pass
        self._prev = _last_line_hash(self.path)

    def record(self, operator: str | None, method: str, path: str, status: int,
               client: str) -> None:
        entry = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "operator": operator,
            "method": method,
            "path": redact_token(path),
            "status": status,
            "client": client,
        }
        with self._lock, open(self.path, "a", encoding="utf-8") as handle:
            entry["prev"] = self._prev
            line = json.dumps(entry, sort_keys=True)
            handle.write(line + "\n")
            self._prev = _hash_line(line)


def _hash_line(line: str) -> str:
    return hashlib.sha256(line.encode("utf-8")).hexdigest()


def _last_line_hash(path: str) -> str:
    last = ""
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                last = line.rstrip("\n")
    return _hash_line(last) if last else ""


def verify_access_log(path: str) -> tuple[bool, int | None, str]:
    """(intact, first broken line number or None, detail).

    Unchained lines before the first chained one are accepted (they predate
    chaining). After the first chained line, every line must name the hash
    of the line before it.
    """
    prev_line: str | None = None
    chained = False
    with open(path, encoding="utf-8") as handle:
        for number, raw in enumerate(handle, start=1):
            line = raw.rstrip("\n")
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
            except ValueError:
                return False, number, "not JSON"
            if "prev" in entry:
                expected = _hash_line(prev_line) if prev_line is not None else ""
                if entry["prev"] != expected:
                    return False, number, "does not follow the line before it"
                chained = True
            elif chained:
                return False, number, "an unchained line after chaining began"
            prev_line = line
    return True, None, "intact" if chained else "no chained lines yet"


class Handler(BaseHTTPRequestHandler):
    server_version = "MemoryFabricObservability/0.1"
    protocol_version = "HTTP/1.1"

    def __init__(
        self,
        *args: Any,
        api: Api,
        authenticator: Authenticator,
        quiet: bool = False,
        access_log: AccessLog | None = None,
        **kwargs: Any,
    ) -> None:
        self.api = api
        self.authenticator = authenticator
        self.quiet = quiet
        self.access_log = access_log
        self.operator: str | None = None
        super().__init__(*args, **kwargs)

    # Only GET and HEAD exist. Anything else is refused explicitly.
    def do_GET(self) -> None:  # noqa: N802
        self._serve(body=True)

    def do_HEAD(self) -> None:  # noqa: N802
        self._serve(body=False)

    def _refuse_write(self) -> None:
        """Answer a mutating method with 405, after draining its body.

        The default handler's 501 leaves the request body unread in the socket.
        On a keep-alive HTTP/1.1 connection the next request then starts parsing
        mid-body, and the connection desynchronises — which surfaces as an
        intermittent dropped connection rather than a clean refusal. Draining
        first, and closing after, keeps the refusal well-formed.
        """
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length > 0:
            self.rfile.read(length)
        self.close_connection = True
        self._send_json(
            {"error": f"{self.command} is not supported; this server is read-only"},
            HTTPStatus.METHOD_NOT_ALLOWED,
            body=True,
            extra_headers={"Allow": "GET, HEAD"},
        )

    do_POST = do_PUT = do_PATCH = do_DELETE = do_OPTIONS = _refuse_write  # noqa: N815

    def _serve(self, body: bool) -> None:
        # Authenticate before routing, so an unauthenticated caller cannot learn
        # which paths exist from the difference between 404 and 401.
        outcome = self.authenticator.authenticate(self.path, self.headers)
        self.operator = outcome.operator
        if not outcome.ok:
            self._send_auth_failure(outcome, body)
            return
        if outcome.redirect_to is not None:
            self._send_redirect(outcome, body)
            return

        parsed = urlparse(self.path)
        path = parsed.path

        if path in STATIC_ROUTES:
            filename, content_type = STATIC_ROUTES[path]
            try:
                payload = (STATIC_DIR / filename).read_bytes()
            except OSError:
                self._send(HTTPStatus.INTERNAL_SERVER_ERROR, b"missing asset", "text/plain", body)
                return
            self._send(HTTPStatus.OK, payload, content_type, body)
            return

        if path == "/metrics":
            payload = self.api.metrics_text().encode("utf-8")
            from .metrics import CONTENT_TYPE

            self._send(HTTPStatus.OK, payload, CONTENT_TYPE, body)
            return

        if path.startswith("/api/"):
            try:
                result = self.api.handle(path, parse_qs(parsed.query))
            except ApiError as exc:
                self._send_json({"error": exc.message}, exc.status, body)
            except Exception as exc:  # pragma: no cover - defensive
                self._send_json({"error": f"internal error: {exc}"}, HTTPStatus.INTERNAL_SERVER_ERROR, body)
            else:
                self._send_json(result, HTTPStatus.OK, body)
            return

        self._send_json({"error": "not found"}, HTTPStatus.NOT_FOUND, body)

    def _send_auth_failure(self, outcome: AuthOutcome, body: bool) -> None:
        extra = {}
        if outcome.status == HTTPStatus.UNAUTHORIZED:
            # Tells a curl user what to send; a browser ignores it for Bearer.
            extra["WWW-Authenticate"] = 'Bearer realm="memory-fabric"'
        self._send_json({"error": outcome.message}, outcome.status, body, extra_headers=extra)

    def _send_redirect(self, outcome: AuthOutcome, body: bool) -> None:
        headers = {"Location": outcome.redirect_to or "/"}
        if outcome.set_cookie:
            headers["Set-Cookie"] = outcome.set_cookie
        self._send(outcome.status, b"", "text/plain; charset=utf-8", body, headers)

    def _send_json(
        self,
        payload: Any,
        status: HTTPStatus,
        body: bool,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        # allow_nan=False turns an accidental Infinity or NaN into an error here
        # rather than into a document no JSON.parse will accept.
        encoded = json.dumps(
            report.jsonable(payload), default=_json_default, allow_nan=False
        ).encode("utf-8")
        self._send(
            status, encoded, "application/json; charset=utf-8", body, extra_headers
        )

    def _send(
        self,
        status: HTTPStatus,
        payload: bytes,
        content_type: str,
        body: bool,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        if self.access_log is not None:
            self.access_log.record(self.operator, self.command, self.path,
                                   int(status), self.client_address[0])
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        # The page loads no third-party resources, so lock that in.
        self.send_header(
            "Content-Security-Policy",
            "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; "
            "connect-src 'self'; img-src 'self' data:",
        )
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        for name, value in (extra_headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        if body:
            self.wfile.write(payload)

    def log_message(self, format: str, *args: Any) -> None:
        """Log with the bootstrap token removed.

        The request line carries `?token=...` on the very first visit, and a log
        file is exactly the sort of place a shared secret should not come to
        rest.
        """
        if self.quiet:
            return
        super().log_message("%s", redact_token(format % args))


def build_server(
    fabric: "MemoryFabric",
    host: str = "127.0.0.1",
    port: int = 8765,
    quiet: bool = False,
    auth: AuthConfig | None = None,
    access_log: str | None = None,
) -> ThreadingHTTPServer:
    """Build the server.

    `auth=None` means no authentication, and it now goes through the same
    refusal `serve` uses rather than past it. It did not: this function built a
    tokenless `AuthConfig` directly with **no host check**, so
    `build_server(fabric, host="0.0.0.0")` published every memory in the store
    to the network, silently, while `build_config` sat one call away raising
    `InsecureConfiguration` for exactly that combination. The old docstring
    said "`serve` refuses that off loopback", which was true and beside the
    point — `build_server` is public and is the function a caller reaches for.

    The unauthenticated-on-loopback case still works, because a test and a
    local one-off both want it, and a refusal there would buy nothing.
    """
    config = (
        auth
        if auth is not None
        else build_config(host, token=None, no_auth=True)
    )
    handler = partial(
        Handler, api=Api(fabric), authenticator=Authenticator(config), quiet=quiet,
        access_log=AccessLog(access_log) if access_log else None,
    )
    server = ThreadingHTTPServer((host, port), handler)
    server.daemon_threads = True
    return server


def serve(
    fabric: "MemoryFabric",
    host: str = "127.0.0.1",
    port: int = 8765,
    quiet: bool = False,
    auth: AuthConfig | None = None,
    access_log: str | None = None,
) -> None:
    config = auth if auth is not None else build_config(host, token=None, no_auth=False)
    server = build_server(fabric, host, port, quiet, config, access_log=access_log)
    authenticator = Authenticator(config)
    actual_host, actual_port = server.server_address[:2]

    print("Memory Fabric dashboard")
    print(f"  store:  {fabric.log.path}")
    print("  mode:   read-only")
    if config.operators:
        # Each operator's token is that person's secret: never printed here.
        names = ", ".join(sorted(config.operators))
        print(f"  auth:   named operators ({names})")
        print(f"\n  {authenticator.bootstrap_url(host, actual_port, token='<your-token>')}\n")
        print("  For scripts:  Authorization: Bearer <your-token>")
        if access_log:
            print(f"  access log:   {access_log}")
    elif config.enabled:
        print("  auth:   token (open this URL once; it sets a session cookie)")
        print(f"\n  {authenticator.bootstrap_url(host, actual_port)}\n")
        print(f"  For scripts:  Authorization: Bearer {config.token}")
    else:
        print("  auth:   NONE")
        print(f"\n  http://{host}:{actual_port}/\n")
        print(
            "  Anyone who can reach this port can read every memory in the store. "
            "This is only permitted because it is bound to loopback."
        )
    print("\n  Ctrl-C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        server.server_close()
