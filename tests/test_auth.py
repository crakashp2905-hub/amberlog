"""Authentication for the observability server.

Covers the three attacks the design names: an unauthenticated caller on the
port, DNS rebinding, and cross-site reads through the session cookie.
"""

from __future__ import annotations

import json
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from http import HTTPStatus

from amberlog import Amberlog
from amberlog.observability.auth import (
    COOKIE_NAME,
    AuthConfig,
    Authenticator,
    InsecureConfiguration,
    build_config,
    default_allowed_hosts,
    generate_token,
    host_without_port,
    redact_token,
)
from amberlog.observability.server import build_server

TOKEN = "test-token-abcdefghijklmnop"


class TestTokens(unittest.TestCase):
    def test_generated_tokens_are_long_and_unique(self) -> None:
        tokens = {generate_token() for _ in range(200)}
        self.assertEqual(len(tokens), 200)
        self.assertTrue(all(len(t) >= 40 for t in tokens))

    def test_comparison_rejects_near_misses(self) -> None:
        auth = Authenticator(AuthConfig(token=TOKEN))
        self.assertTrue(auth.matches(TOKEN))
        for wrong in (TOKEN[:-1], TOKEN + "x", TOKEN.upper(), "", None):
            self.assertFalse(auth.matches(wrong))

    def test_disabled_auth_matches_nothing(self) -> None:
        """A disabled configuration must not accidentally accept an empty token."""
        auth = Authenticator(AuthConfig(token=None))
        self.assertFalse(auth.matches(""))
        self.assertFalse(auth.matches("anything"))

    def test_token_is_redacted_from_log_lines(self) -> None:
        line = f'GET /?token={TOKEN} HTTP/1.1'
        self.assertNotIn(TOKEN, redact_token(line))
        self.assertIn("token=REDACTED", redact_token(line))
        self.assertEqual(redact_token("GET /api/memories HTTP/1.1"), "GET /api/memories HTTP/1.1")


class TestHostParsing(unittest.TestCase):
    def test_strips_ports_and_brackets(self) -> None:
        cases = {
            "localhost:8765": "localhost",
            "localhost": "localhost",
            "127.0.0.1:80": "127.0.0.1",
            "[::1]:8765": "::1",
            "[::1]": "::1",
            "EXAMPLE.COM:443": "example.com",
        }
        for header, expected in cases.items():
            self.assertEqual(host_without_port(header), expected)

    def test_loopback_names_are_allowed_by_default(self) -> None:
        hosts = default_allowed_hosts("127.0.0.1")
        for name in ("localhost", "127.0.0.1", "::1"):
            self.assertIn(name, hosts)

    def test_wildcard_bind_does_not_allow_everything(self) -> None:
        hosts = default_allowed_hosts("0.0.0.0")
        self.assertNotIn("0.0.0.0", hosts)
        self.assertNotIn("evil.example.com", hosts)

    def test_extra_hosts_are_added(self) -> None:
        hosts = default_allowed_hosts("0.0.0.0", ["memory.internal"])
        self.assertIn("memory.internal", hosts)


class TestConfigRefusal(unittest.TestCase):
    def test_no_auth_off_loopback_is_refused(self) -> None:
        """A warning scrolls past; this combination is a refusal."""
        for host in ("0.0.0.0", "192.168.1.10", "::"):
            with self.subTest(host=host):
                with self.assertRaises(InsecureConfiguration):
                    build_config(bind_host=host, token=None, no_auth=True)

    def test_no_auth_on_loopback_is_allowed(self) -> None:
        config = build_config(bind_host="127.0.0.1", token=None, no_auth=True)
        self.assertFalse(config.enabled)

    def test_auth_is_on_by_default(self) -> None:
        config = build_config(bind_host="127.0.0.1", token=None, no_auth=False)
        self.assertTrue(config.enabled)
        self.assertTrue(config.token)

    def test_off_loopback_with_auth_is_allowed(self) -> None:
        config = build_config(bind_host="0.0.0.0", token=None, no_auth=False)
        self.assertTrue(config.enabled)

    def test_supplied_token_is_used(self) -> None:
        config = build_config(bind_host="127.0.0.1", token=TOKEN, no_auth=False)
        self.assertEqual(config.token, TOKEN)


class Headers(dict):
    """Minimal stand-in for the handler's header mapping."""

    def get(self, key, default=None):  # noqa: A003
        for name, value in self.items():
            if name.lower() == key.lower():
                return value
        return default


class TestAuthenticateUnit(unittest.TestCase):
    def setUp(self) -> None:
        self.auth = Authenticator(build_config("127.0.0.1", TOKEN, no_auth=False))

    def test_missing_host_header_is_rejected(self) -> None:
        """HTTP/1.1 requires Host; accepting its absence would bypass the check."""
        outcome = self.auth.authenticate("/", Headers())
        self.assertFalse(outcome.ok)
        self.assertEqual(outcome.status, HTTPStatus.BAD_REQUEST)

    def test_foreign_host_is_rejected(self) -> None:
        """DNS rebinding: the attacker controls the name, so it is not ours."""
        outcome = self.auth.authenticate(
            "/", Headers({"Host": "attacker.example.com:8765", "Cookie": f"{COOKIE_NAME}={TOKEN}"})
        )
        self.assertFalse(outcome.ok)
        self.assertEqual(outcome.status, HTTPStatus.BAD_REQUEST)
        self.assertIn("--allowed-host", outcome.message)

    def test_cross_origin_is_rejected_even_with_a_valid_cookie(self) -> None:
        outcome = self.auth.authenticate(
            "/api/overview",
            Headers({
                "Host": "localhost:8765",
                "Origin": "https://evil.example.com",
                "Cookie": f"{COOKIE_NAME}={TOKEN}",
            }),
        )
        self.assertFalse(outcome.ok)
        self.assertEqual(outcome.status, HTTPStatus.FORBIDDEN)

    def test_same_origin_is_accepted(self) -> None:
        outcome = self.auth.authenticate(
            "/api/overview",
            Headers({
                "Host": "localhost:8765",
                "Origin": "http://localhost:8765",
                "Cookie": f"{COOKIE_NAME}={TOKEN}",
            }),
        )
        self.assertTrue(outcome.ok)

    def test_absent_origin_is_not_a_failure(self) -> None:
        """curl sends no Origin, and neither does same-origin navigation."""
        outcome = self.auth.authenticate(
            "/", Headers({"Host": "localhost:8765", "Cookie": f"{COOKIE_NAME}={TOKEN}"})
        )
        self.assertTrue(outcome.ok)

    def test_bearer_token_is_accepted(self) -> None:
        outcome = self.auth.authenticate(
            "/api/overview",
            Headers({"Host": "localhost:8765", "Authorization": f"Bearer {TOKEN}"}),
        )
        self.assertTrue(outcome.ok)

    def test_wrong_bearer_token_is_rejected(self) -> None:
        outcome = self.auth.authenticate(
            "/api/overview",
            Headers({"Host": "localhost:8765", "Authorization": "Bearer nope"}),
        )
        self.assertFalse(outcome.ok)
        self.assertEqual(outcome.status, HTTPStatus.UNAUTHORIZED)

    def test_url_token_trades_itself_for_a_cookie(self) -> None:
        outcome = self.auth.authenticate(
            f"/?token={TOKEN}", Headers({"Host": "localhost:8765"})
        )
        self.assertTrue(outcome.ok)
        self.assertEqual(outcome.status, HTTPStatus.SEE_OTHER)
        self.assertIn(f"{COOKIE_NAME}={TOKEN}", outcome.set_cookie or "")
        self.assertEqual(outcome.redirect_to, "/")

    def test_redirect_keeps_other_query_parameters(self) -> None:
        outcome = self.auth.authenticate(
            f"/api/memories?state=active&token={TOKEN}&sort=value",
            Headers({"Host": "localhost:8765"}),
        )
        self.assertEqual(outcome.redirect_to, "/api/memories?state=active&sort=value")

    def test_cookie_is_httponly_and_samesite_strict(self) -> None:
        header = self.auth.cookie_header()
        self.assertIn("HttpOnly", header)
        self.assertIn("SameSite=Strict", header)
        self.assertIn("Path=/", header)

    def test_malformed_cookie_does_not_crash(self) -> None:
        outcome = self.auth.authenticate(
            "/", Headers({"Host": "localhost:8765", "Cookie": "this is not; a=valid=cookie;;"})
        )
        self.assertFalse(outcome.ok)
        self.assertEqual(outcome.status, HTTPStatus.UNAUTHORIZED)

    def test_disabled_auth_still_checks_host(self) -> None:
        """Rebinding protection is independent of authentication."""
        auth = Authenticator(build_config("127.0.0.1", None, no_auth=True))
        self.assertTrue(auth.authenticate("/", Headers({"Host": "localhost:8765"})).ok)
        self.assertFalse(
            auth.authenticate("/", Headers({"Host": "attacker.example.com"})).ok
        )


class ServerCase(unittest.TestCase):
    AUTH: AuthConfig | None = None

    @classmethod
    def setUpClass(cls) -> None:
        cls.fabric = Amberlog(auto_activate=True, seed=1)
        cls.mid = cls.fabric.remember("agent-a", "A memory worth protecting.")
        cls.server = build_server(
            cls.fabric, host="127.0.0.1", port=0, quiet=True, auth=cls.AUTH
        )
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.fabric.close()

    def url(self, path: str) -> str:
        return f"http://127.0.0.1:{self.port}{path}"

    def request(self, path: str, headers: dict | None = None, redirect: bool = True):
        opener = (
            urllib.request.build_opener()
            if redirect
            else urllib.request.build_opener(_NoRedirect)
        )
        req = urllib.request.Request(self.url(path), headers=headers or {})
        try:
            with opener.open(req, timeout=10) as res:
                return res.status, res.read().decode("utf-8"), dict(res.headers)
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read().decode("utf-8"), dict(exc.headers)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):  # noqa: D102
        return None


class TestServerWithAuth(ServerCase):
    AUTH = AuthConfig(token=TOKEN, allowed_hosts=default_allowed_hosts("127.0.0.1"))

    def test_unauthenticated_request_is_refused(self) -> None:
        for path in ("/", "/api/overview", "/api/memories", f"/api/memories/{self.mid}"):
            with self.subTest(path=path):
                status, body, _ = self.request(path)
                self.assertEqual(status, HTTPStatus.UNAUTHORIZED)
                self.assertNotIn("worth protecting", body)

    def test_refusal_advertises_the_scheme(self) -> None:
        _, _, headers = self.request("/api/overview")
        self.assertIn("Bearer", headers.get("WWW-Authenticate", ""))

    def test_auth_precedes_routing(self) -> None:
        """An unauthenticated caller must not learn which paths exist from the
        difference between 404 and 401."""
        status, _, _ = self.request("/api/definitely-not-a-route")
        self.assertEqual(status, HTTPStatus.UNAUTHORIZED)

    def test_bearer_token_grants_access(self) -> None:
        status, body, _ = self.request(
            "/api/overview", headers={"Authorization": f"Bearer {TOKEN}"}
        )
        self.assertEqual(status, 200)
        json.loads(body)

    def test_cookie_grants_access(self) -> None:
        status, _, _ = self.request(
            "/api/overview", headers={"Cookie": f"{COOKIE_NAME}={TOKEN}"}
        )
        self.assertEqual(status, 200)

    def test_url_token_sets_a_cookie_and_redirects(self) -> None:
        status, _, headers = self.request(f"/?token={TOKEN}", redirect=False)
        self.assertEqual(status, HTTPStatus.SEE_OTHER)
        self.assertIn(COOKIE_NAME, headers.get("Set-Cookie", ""))
        self.assertEqual(headers.get("Location"), "/")

    def test_wrong_token_is_refused(self) -> None:
        status, _, _ = self.request("/api/overview?token=wrong")
        self.assertEqual(status, HTTPStatus.UNAUTHORIZED)

    def test_foreign_host_header_is_refused(self) -> None:
        status, body, _ = self.request(
            "/api/overview",
            headers={"Host": "attacker.example.com", "Authorization": f"Bearer {TOKEN}"},
        )
        self.assertEqual(status, HTTPStatus.BAD_REQUEST)
        self.assertNotIn("worth protecting", body)

    def test_cross_origin_read_is_refused(self) -> None:
        status, body, _ = self.request(
            "/api/memories",
            headers={"Origin": "https://evil.example.com", "Cookie": f"{COOKIE_NAME}={TOKEN}"},
        )
        self.assertEqual(status, HTTPStatus.FORBIDDEN)
        self.assertNotIn("worth protecting", body)

    def test_no_memory_content_leaks_in_any_refusal(self) -> None:
        attempts = [
            ("/api/memories", {}),
            ("/api/memories", {"Origin": "https://evil.example.com", "Cookie": f"{COOKIE_NAME}={TOKEN}"}),
            ("/api/memories", {"Host": "evil.example.com"}),
            (f"/api/memories/{self.mid}", {"Authorization": "Bearer wrong"}),
        ]
        for path, headers in attempts:
            with self.subTest(headers=headers):
                _, body, _ = self.request(path, headers=headers)
                self.assertNotIn("worth protecting", body)
                self.assertNotIn(TOKEN, body)


class TestServerWithoutAuth(ServerCase):
    AUTH = None  # explicit opt-out, as the CLI only permits on loopback

    def test_requests_succeed(self) -> None:
        status, body, _ = self.request("/api/overview")
        self.assertEqual(status, 200)
        json.loads(body)

    def test_host_checking_still_applies(self) -> None:
        """Rebinding protection does not depend on authentication being on."""
        status, _, _ = self.request(
            "/api/overview", headers={"Host": "attacker.example.com"}
        )
        self.assertEqual(status, HTTPStatus.BAD_REQUEST)


if __name__ == "__main__":
    unittest.main()
