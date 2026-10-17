"""Authentication for the observability server.

A local HTTP server that will hand out every memory in a store needs more than a
loopback bind. Three attacks matter here, and each gets its own control:

* **Anyone who can reach the port.** A shared token, compared in constant time,
  carried in an HttpOnly cookie after a one-time bootstrap through the URL.
* **DNS rebinding.** A page on the open internet can point a hostname it owns at
  127.0.0.1 and make a victim's own browser talk to this server. The loopback
  bind does not help at all, and neither does the cookie, because the browser
  sends it. Validating the `Host` header stops it: the attacker controls the
  hostname, so it will not be one of ours.
* **Cross-site reads.** A cookie that a browser attaches to requests from any
  origin lets another page read the API. `SameSite=Strict` plus an `Origin`
  check refuses those.

The token never goes in a log line: `redact_token` is applied before any request
is written out.
"""

from __future__ import annotations

import hmac
import re
import secrets
from dataclasses import dataclass, field
from http import HTTPStatus
from http.cookies import CookieError, SimpleCookie
from typing import Iterable
from urllib.parse import parse_qs, urlparse

COOKIE_NAME = "memory_fabric_session"
TOKEN_PARAM = "token"
ENV_TOKEN = "MEMORY_FABRIC_TOKEN"

LOOPBACK_NAMES = frozenset({"localhost", "127.0.0.1", "::1", "[::1]"})
WILDCARD_BINDS = frozenset({"0.0.0.0", "::", ""})

_TOKEN_IN_QUERY = re.compile(rf"([?&]{TOKEN_PARAM}=)[^&\s]*")


def generate_token() -> str:
    """256 bits of entropy: brute force is not a threat model worth coding for."""
    return secrets.token_urlsafe(32)


def redact_token(text: str) -> str:
    return _TOKEN_IN_QUERY.sub(r"\1REDACTED", text)


def default_allowed_hosts(bind_host: str, extra: Iterable[str] = ()) -> frozenset[str]:
    hosts = set(LOOPBACK_NAMES)
    if bind_host not in WILDCARD_BINDS:
        hosts.add(bind_host.strip("[]"))
        hosts.add(bind_host)
    hosts.update(h.lower() for h in extra)
    return frozenset(hosts)


def host_without_port(header: str) -> str:
    """The hostname from a Host header, IPv6 brackets and port removed."""
    value = header.strip().lower()
    if value.startswith("["):
        end = value.find("]")
        return value[1:end] if end != -1 else value
    return value.rsplit(":", 1)[0] if value.count(":") == 1 else value


@dataclass
class AuthOutcome:
    ok: bool
    status: HTTPStatus = HTTPStatus.OK
    message: str = ""
    set_cookie: str | None = None
    redirect_to: str | None = None
    operator: str | None = None
    """Who this request is, when authentication identified someone."""


@dataclass
class AuthConfig:
    """`token=None` disables authentication entirely."""

    token: str | None
    allowed_hosts: frozenset[str] = field(default_factory=lambda: frozenset(LOOPBACK_NAMES))
    check_origin: bool = True
    operators: dict[str, str] = field(default_factory=dict)
    """Named tokens, name -> token. With them, every request is attributable to
    a person, which one shared token never was: DEPLOYMENT.md recorded "no audit
    of *who looked*" as a limit. The shared `token`, when also set, is the
    operator named `shared`."""

    @property
    def enabled(self) -> bool:
        return self.token is not None or bool(self.operators)

    def credentials(self) -> list[tuple[str, str]]:
        named = list(self.operators.items())
        return named + ([("shared", self.token)] if self.token is not None else [])


MIN_OPERATOR_TOKEN = 32


class InsecureConfiguration(Exception):
    """Raised for a combination that cannot be made safe, rather than warned about."""


def build_config(
    bind_host: str,
    token: str | None,
    no_auth: bool,
    allowed_hosts: Iterable[str] = (),
    operators: dict[str, str] | None = None,
) -> AuthConfig:
    """Decide the server's auth configuration, refusing the unsafe combination.

    Serving unauthenticated on anything but loopback publishes the whole store to
    the network. That is not a warning, because a warning scrolls past: it is a
    refusal.
    """
    is_loopback = bind_host in LOOPBACK_NAMES
    if no_auth:
        if not is_loopback:
            raise InsecureConfiguration(
                f"refusing to serve without authentication on {bind_host!r}: "
                "anyone who can reach the port could read every memory in the store. "
                "Bind to 127.0.0.1, or drop --no-auth."
            )
        if operators:
            raise InsecureConfiguration("--no-auth and named operators contradict each other")
        return AuthConfig(token=None, allowed_hosts=default_allowed_hosts(bind_host, allowed_hosts))

    if operators:
        # Named operators replace the shared token unless one is given
        # explicitly: an auto-generated shared token alongside named ones would
        # be an unattributed way in.
        return AuthConfig(
            token=token,
            allowed_hosts=default_allowed_hosts(bind_host, allowed_hosts),
            operators=dict(operators),
        )
    return AuthConfig(
        token=token or generate_token(),
        allowed_hosts=default_allowed_hosts(bind_host, allowed_hosts),
    )


def load_operators(path: str) -> dict[str, str]:
    """Read `name:token` lines. Blank lines and `#` comments are ignored.

    Refuses short tokens and duplicate names or tokens rather than warning:
    a guessable or shared token defeats the attribution this file exists for.
    """
    operators: dict[str, str] = {}
    seen: set[str] = set()
    with open(path, encoding="utf-8") as handle:
        for number, raw in enumerate(handle, 1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            name, sep, token = line.partition(":")
            name, token = name.strip(), token.strip()
            if not sep or not name or not token:
                raise InsecureConfiguration(f"{path}:{number}: expected name:token")
            if not re.fullmatch(r"[A-Za-z0-9._@-]{1,64}", name):
                raise InsecureConfiguration(f"{path}:{number}: invalid operator name {name!r}")
            if len(token) < MIN_OPERATOR_TOKEN:
                raise InsecureConfiguration(
                    f"{path}:{number}: token for {name!r} is shorter than "
                    f"{MIN_OPERATOR_TOKEN} characters; generate one with "
                    "python -c 'import secrets; print(secrets.token_urlsafe(32))'")
            if name in operators or token in seen:
                raise InsecureConfiguration(
                    f"{path}:{number}: duplicate operator name or token; each "
                    "person needs their own")
            operators[name] = token
            seen.add(token)
    if not operators:
        raise InsecureConfiguration(f"{path}: no operators defined")
    return operators


class Authenticator:
    def __init__(self, config: AuthConfig) -> None:
        self.config = config

    # --- individual checks ------------------------------------------------

    def check_host(self, host_header: str | None) -> AuthOutcome:
        """Reject a Host this server does not answer to (DNS rebinding)."""
        if not host_header:
            # HTTP/1.1 requires Host. Its absence is a malformed request, and
            # accepting it would be a way around this check.
            return AuthOutcome(False, HTTPStatus.BAD_REQUEST, "missing Host header")
        host = host_without_port(host_header)
        if host not in self.config.allowed_hosts:
            return AuthOutcome(
                False,
                HTTPStatus.BAD_REQUEST,
                f"unrecognised Host {host!r}; if this address is intended, pass it "
                "with --allowed-host",
            )
        return AuthOutcome(True)

    def check_origin(self, origin: str | None, host_header: str | None) -> AuthOutcome:
        """Refuse a cross-origin browser request.

        Only browsers send `Origin`, and they send it on exactly the requests
        that a malicious page would make. Its absence is normal for curl and for
        same-origin navigation, so absence is not treated as failure.
        """
        if not self.config.check_origin or not origin or origin == "null":
            return AuthOutcome(True)
        parsed = urlparse(origin)
        if not parsed.hostname:
            return AuthOutcome(False, HTTPStatus.FORBIDDEN, "malformed Origin")
        if parsed.hostname.lower() not in self.config.allowed_hosts:
            return AuthOutcome(False, HTTPStatus.FORBIDDEN, "cross-origin request refused")
        if host_header and parsed.netloc.lower() != host_header.strip().lower():
            return AuthOutcome(False, HTTPStatus.FORBIDDEN, "cross-origin request refused")
        return AuthOutcome(True)

    def identify(self, candidate: str | None) -> str | None:
        """The operator a token belongs to, or None.

        Every credential is compared in constant time, whether or not an
        earlier one matched, so response time does not say which entry -- or
        how much of one -- a guess got right.
        """
        if not self.config.enabled or not candidate:
            return None
        found = None
        for name, token in self.config.credentials():
            if hmac.compare_digest(candidate.encode(), token.encode()):
                found = name
        return found

    def matches(self, candidate: str | None) -> bool:
        return self.identify(candidate) is not None

    def token_from_cookie(self, cookie_header: str | None) -> str | None:
        if not cookie_header:
            return None
        jar = SimpleCookie()
        try:
            jar.load(cookie_header)
        except CookieError:
            return None
        morsel = jar.get(COOKIE_NAME)
        return morsel.value if morsel else None

    @staticmethod
    def token_from_authorization(header: str | None) -> str | None:
        if not header:
            return None
        scheme, _, value = header.partition(" ")
        return value.strip() if scheme.lower() == "bearer" and value.strip() else None

    # --- the whole decision ----------------------------------------------

    def authenticate(self, path: str, headers) -> AuthOutcome:
        host_header = headers.get("Host")

        outcome = self.check_host(host_header)
        if not outcome.ok:
            return outcome

        outcome = self.check_origin(headers.get("Origin"), host_header)
        if not outcome.ok:
            return outcome

        if not self.config.enabled:
            return AuthOutcome(True)

        operator = self.identify(self.token_from_cookie(headers.get("Cookie")))
        if operator is not None:
            return AuthOutcome(True, operator=operator)

        operator = self.identify(self.token_from_authorization(headers.get("Authorization")))
        if operator is not None:
            return AuthOutcome(True, operator=operator)

        parsed = urlparse(path)
        query = parse_qs(parsed.query)
        values = query.get(TOKEN_PARAM)
        supplied = values[0] if values else None
        operator = self.identify(supplied)
        if operator is not None:
            # Bootstrap: trade the URL token for a cookie and redirect to a clean
            # address, so the token stops appearing in the address bar, in
            # browser history, and in any Referer this page might later send.
            return AuthOutcome(
                True,
                status=HTTPStatus.SEE_OTHER,
                set_cookie=self.cookie_header(supplied),
                redirect_to=_strip_token(parsed),
                operator=operator,
            )

        return AuthOutcome(
            False, HTTPStatus.UNAUTHORIZED, "authentication required"
        )

    def cookie_header(self, token: str | None = None) -> str:
        # No `Secure`: this server speaks plain HTTP on loopback, and setting it
        # would stop the cookie being stored at all. That is also why binding
        # off-loopback needs something terminating TLS in front. The cookie
        # carries the operator's own token, so the session stays attributable.
        value = token if token is not None else self.config.token
        return f"{COOKIE_NAME}={value}; HttpOnly; SameSite=Strict; Path=/"

    def bootstrap_url(self, host: str, port: int, token: str | None = None) -> str:
        display = host if ":" not in host else f"[{host}]"
        base = f"http://{display}:{port}/"
        value = token if token is not None else self.config.token
        if not self.config.enabled or value is None:
            return base
        return f"{base}?{TOKEN_PARAM}={value}"


def _strip_token(parsed) -> str:
    pairs = [
        (key, value)
        for key, value in _ordered_pairs(parsed.query)
        if key != TOKEN_PARAM
    ]
    query = "&".join(f"{k}={v}" for k, v in pairs)
    return f"{parsed.path or '/'}{'?' + query if query else ''}"


def _ordered_pairs(query: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for chunk in query.split("&"):
        if not chunk:
            continue
        key, _, value = chunk.partition("=")
        out.append((key, value))
    return out
