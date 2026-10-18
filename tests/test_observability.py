"""The read model, the HTTP server, and the CLI.

The property these tests care about most is that the two surfaces agree: both
read through `observability.report`, so a fact shown in the dashboard and the
same fact printed by the CLI come from one place and cannot diverge.

Second most important: browsing is read-only. An observability tool that logged
exposure events while an operator looked around would quietly feed its own
queries into the data every value estimate is computed from.
"""

from __future__ import annotations

import dataclasses
import json
import threading
import unittest
import urllib.error
import urllib.request
from http import HTTPStatus

from memory_fabric import (
    SCHEMA_VERSION,
    EpsilonGreedyPolicy,
    LifecycleState,
    MemoryFabric,
    MemoryType,
    Scope,
)
from memory_fabric.cli import G, _strip, clip, main
from memory_fabric.observability import report
from memory_fabric.observability.auth import (
    InsecureConfiguration,
    build_config,
)
from memory_fabric.observability.server import build_server


def populated(path: str = ":memory:", **kwargs) -> MemoryFabric:
    """A small store with a retraction, a disagreement and a secret."""
    fabric = MemoryFabric(path, auto_activate=True, seed=3, **kwargs)
    root = fabric.remember(
        "agent-a", "The threshold is 45C.", context={"domain": "ev"}, scope="team"
    )
    belief = fabric.derive("agent-a", "Warn above 45C.", parents=[root], scope="team")
    fabric.derive("agent-b", "Procedure: warn above 45, stop above 60.", parents=[belief],
                  type=MemoryType.PROCEDURAL, scope="team")
    fabric.remember("agent-c", "Tyre pressure is 34 psi.", scope="team")
    fabric.remember("agent-d", "key AKIAIOSFODNN7EXAMPLE", scope="team")  # quarantined on ingest
    fabric.quarantine(root, reason="rig misconfigured", actor="safety")
    fabric._root, fabric._belief = root, belief
    return fabric


class TestOverview(unittest.TestCase):
    def test_empty_store_says_what_is_missing(self) -> None:
        with MemoryFabric() as fabric:
            data = report.overview(fabric)
            self.assertEqual(data.total_memories, 0)
            joined = " ".join(data.diagnostics)
            self.assertIn("No episodes recorded", joined)

    def test_counts_are_internally_consistent(self) -> None:
        """Regression: `no_value_evidence` read the projection while
        `contrastive_evidence` read the estimator, so the two contradicted
        each other and their sum exceeded the number of memories."""
        fabric = populated()
        try:
            data = report.overview(fabric)
            self.assertLessEqual(
                data.no_value_evidence + data.contrastive_evidence, data.total_memories
            )
            self.assertEqual(sum(data.by_state.values()), data.total_memories)
            self.assertEqual(sum(data.by_scope.values()), data.total_memories)
            self.assertEqual(sum(data.by_type.values()), data.total_memories)
        finally:
            fabric.close()

    def test_diagnostics_describe_the_log_not_the_reader(self) -> None:
        """The exposure policy is runtime configuration and is never persisted,
        so what a reader happens to have configured says nothing about how the
        stored data was produced."""
        path = ":memory:"
        fabric = MemoryFabric(
            path, auto_activate=True, seed=1, exposure_policy=EpsilonGreedyPolicy(epsilon=0.5)
        )
        try:
            fabric.remember("agent-a", "Retry once on a failed deploy.", scope="team")
            for index in range(10):
                episode = fabric.start_episode("agent-a", f"t{index}", {})
                fabric.retrieve("agent-a", "retry a failed deploy", episode_id=episode.id)
                fabric.record_outcome(episode.id, 1.0, verifier_id="ci")

            data = report.overview(fabric)
            self.assertGreater(data.randomised_exposures, 0)
            self.assertEqual(data.logged_policies, [fabric.policy.id])
            joined = " ".join(data.diagnostics)
            self.assertNotIn("cannot support causal value estimates", joined)

            # Same log, read by a session configured with a deterministic policy:
            # the verdict on the *data* must not change.
            from memory_fabric.exposure import TopKPolicy

            fabric.policy = TopKPolicy()
            reread = report.overview(fabric)
            self.assertEqual(reread.randomised_exposures, data.randomised_exposures)
            self.assertNotIn(
                "cannot support causal value estimates", " ".join(reread.diagnostics)
            )
            self.assertIn("will not add to it", " ".join(reread.diagnostics))
        finally:
            fabric.close()

    def test_deterministic_log_is_reported_as_unusable_for_causal_claims(self) -> None:
        fabric = MemoryFabric(auto_activate=True, exposure_policy="always")
        try:
            fabric.remember("agent-a", "A fact about deploys.", scope="team")
            episode = fabric.start_episode("agent-a", "t", {})
            fabric.retrieve("agent-a", "a fact about deploys", episode_id=episode.id)
            fabric.record_outcome(episode.id, 1.0, verifier_id="ci")
            joined = " ".join(report.overview(fabric).diagnostics)
            self.assertIn("deterministic", joined)
            self.assertIn("cannot support causal value estimates", joined)
        finally:
            fabric.close()



class TestTheBuilderCannotPublishUnauthenticated(unittest.TestCase):
    """`build_server(auth=None)` means no authentication.

    It used to mean that with **no host check**, so
    `build_server(fabric, host="0.0.0.0")` published every memory in the store
    to the network, silently, while `build_config` sat one call away raising
    for exactly that combination. The docstring said "`serve` refuses that off
    loopback" — true, and beside the point, since `build_server` is public and
    is the function a caller reaches for. Found by a by-hand validation probe
    that used it the obvious way.
    """

    def setUp(self) -> None:
        self.fabric = MemoryFabric(":memory:")
        self.addCleanup(self.fabric.close)

    def test_it_refuses_no_auth_off_loopback(self) -> None:
        for host in ("0.0.0.0", "::", "192.168.1.10"):
            with self.subTest(host=host):
                with self.assertRaises(InsecureConfiguration):
                    build_server(self.fabric, host=host, port=0)

    def test_no_auth_on_loopback_is_still_allowed(self) -> None:
        """A test and a local one-off both want it, and a refusal there would
        buy nothing."""
        server = build_server(self.fabric, host="127.0.0.1", port=0)
        self.addCleanup(server.server_close)
        self.assertIsNone(
            server.RequestHandlerClass.keywords["authenticator"].config.token
        )

    def test_an_explicit_config_is_honoured_off_loopback(self) -> None:
        """The refusal is about the *default*, not about binding widely with a
        token — which is what the container does."""
        config = build_config("0.0.0.0", token="t" * 32, no_auth=False)
        server = build_server(self.fabric, host="127.0.0.1", port=0, auth=config)
        self.addCleanup(server.server_close)
        self.assertEqual(
            server.RequestHandlerClass.keywords["authenticator"].config.token,
            "t" * 32,
        )


class TestAttention(unittest.TestCase):
    def setUp(self) -> None:
        self.fabric = populated()

    def tearDown(self) -> None:
        self.fabric.close()

    def test_quarantined_and_retracted_are_high_severity(self) -> None:
        items = report.attention(self.fabric)
        kinds = {i.kind for i in items}
        self.assertIn("quarantined", kinds)
        self.assertIn("retracted_ancestor", kinds)
        for item in items:
            if item.kind in ("quarantined", "retracted_ancestor"):
                self.assertEqual(item.severity, "high")

    def test_retraction_and_disagreement_are_separate_kinds(self) -> None:
        """They need different actions, so they must not share one message."""
        a = self.fabric.remember("agent-e", "Retry three times.", scope="team")
        b = self.fabric.remember("agent-f", "Never retry.", scope="team")
        self.fabric.challenge([a, b], evidence="contradictory")

        items = report.attention(self.fabric)
        # A memory can legitimately raise several findings (say, contested and
        # also due for retention), so collect kinds per id rather than assuming
        # one each.
        kinds: dict[str, set[str]] = {}
        for item in items:
            if item.memory_id:
                kinds.setdefault(item.memory_id, set()).add(item.kind)

        self.assertIn("retracted_ancestor", kinds[self.fabric._belief])
        self.assertNotIn("disagreement", kinds[self.fabric._belief])
        self.assertIn("disagreement", kinds[a])
        self.assertNotIn("retracted_ancestor", kinds[a])

        severities = {i.severity for i in items if i.memory_id == a and i.kind == "disagreement"}
        self.assertEqual(severities, {"medium"})

    def test_every_item_carries_a_runnable_action(self) -> None:
        """The gate is that a reader can act unaided, which means each finding
        arrives with the command that addresses it."""
        for item in report.attention(self.fabric):
            self.assertTrue(item.action.startswith("memory-fabric "))
            self.assertTrue(item.title)
            self.assertTrue(item.detail)

    def test_ordered_worst_first(self) -> None:
        severities = [i.severity for i in report.attention(self.fabric)]
        ranks = [{"high": 0, "medium": 1, "low": 2}[s] for s in severities]
        self.assertEqual(ranks, sorted(ranks))

    def test_clean_store_needs_no_attention(self) -> None:
        with MemoryFabric(auto_activate=True) as fabric:
            fabric.remember("agent-a", "An ordinary fact.", scope="team")
            self.assertEqual(report.attention(fabric), [])


class TestReadOnly(unittest.TestCase):
    def test_browsing_writes_no_events(self) -> None:
        """The property that matters most: reading cannot change the store."""
        fabric = populated()
        try:
            before = len(fabric.log)

            report.overview(fabric)
            report.attention(fabric)
            report.memory_rows(fabric)
            report.episode_rows(fabric)
            report.memory_detail(fabric, fabric._belief)
            report.lineage_tree(fabric, fabric._root)
            report.lineage_tree(fabric, fabric._belief, direction="ancestors")
            report.retention_preview(fabric)
            report.preview_search(fabric, "threshold warn")

            self.assertEqual(len(fabric.log), before)
        finally:
            fabric.close()

    def test_search_preview_logs_no_exposure(self) -> None:
        """`fabric.retrieve` would write ExposureDecided events and enter an
        operator's browsing into the data value estimates are computed from."""
        fabric = populated()
        try:
            exposures_before = len(fabric.state.exposures)
            report.preview_search(fabric, "threshold", k=10)
            self.assertEqual(len(fabric.state.exposures), exposures_before)

            # Contrast: the real retrieval path does log.
            fabric.retrieve("agent-a", "tyre pressure")
            self.assertGreater(len(fabric.state.exposures), exposures_before)
        finally:
            fabric.close()

    def test_retention_preview_changes_nothing(self) -> None:
        fabric = populated()
        try:
            states = {m.id: m.lifecycle_state for m in fabric.state.memories.values()}
            report.retention_preview(fabric)
            after = {m.id: m.lifecycle_state for m in fabric.state.memories.values()}
            self.assertEqual(states, after)
        finally:
            fabric.close()


SECRET = "AKIAIOSFODNN7EXAMPLE"


class TestSecretsAreNotDisplayed(unittest.TestCase):
    """Regression: the dashboard printed the full AWS key of the very memory the
    firewall had quarantined for containing it.

    Quarantining a credential and then rendering it in the review tool defeats
    the control that caught it: the value reaches a terminal scrollback, a
    browser's memory, and any screenshot of either. The reviewer needs the *kind*
    of secret to decide what to do, not its value.
    """

    def setUp(self) -> None:
        self.fabric = MemoryFabric(auto_activate=True)
        self.mid = self.fabric.remember(
            "agent-a", f"To deploy, export AWS_ACCESS_KEY_ID={SECRET} and run make ship.", scope="team"
        )

    def tearDown(self) -> None:
        self.fabric.close()

    def test_the_memory_was_quarantined(self) -> None:
        self.assertIs(self.fabric.get(self.mid).lifecycle_state, LifecycleState.QUARANTINED)

    def test_secret_is_absent_from_every_read_surface(self) -> None:
        f = self.fabric
        surfaces = {
            "rows": [r.to_json() for r in report.memory_rows(f)],
            "attention": [i.to_json() for i in report.attention(f)],
            "detail": report.memory_detail(f, self.mid),
            "search": [h.to_json() for h in report.preview_search(f, "deploy export")],
            "lineage": report.lineage_tree(f, self.mid).to_json(),
        }
        for name, payload in surfaces.items():
            with self.subTest(surface=name):
                self.assertNotIn(SECRET, json.dumps(payload))

    def test_the_kind_of_secret_is_still_reported(self) -> None:
        """Redaction must not leave the reviewer unable to judge it."""
        detail = report.memory_detail(self.fabric, self.mid)
        self.assertIn("aws_access_key", detail["redacted_kinds"])
        self.assertIn("REDACTED", detail["full_content"])

    def test_the_stored_memory_is_untouched(self) -> None:
        """Redaction is a display concern; it must not rewrite the record."""
        self.assertIn(SECRET, self.fabric.get(self.mid).content)

    def test_clean_content_is_not_altered(self) -> None:
        mid = self.fabric.remember("agent-a", "Prefer email follow-up after onboarding.", scope="team")
        row = next(r for r in report.memory_rows(self.fabric) if r.id == mid)
        self.assertEqual(row.content, "Prefer email follow-up after onboarding.")
        self.assertEqual(row.redacted_kinds, [])


class TestReadModel(unittest.TestCase):
    def setUp(self) -> None:
        self.fabric = populated()

    def tearDown(self) -> None:
        self.fabric.close()

    def test_rows_can_be_filtered(self) -> None:
        f = self.fabric
        self.assertTrue(all(r.lifecycle_state == "contested"
                            for r in report.memory_rows(f, state="contested")))
        self.assertTrue(all(r.type == "procedural" for r in report.memory_rows(f, type="procedural")))
        self.assertTrue(all("tyre" in r.content.lower() for r in report.memory_rows(f, query="tyre")))

    def test_query_filter_is_substring_not_retrieval(self) -> None:
        """Listing must not depend on the embedder or touch the exposure log."""
        rows = report.memory_rows(self.fabric, query="zzz-no-such-text")
        self.assertEqual(rows, [])

    def test_limit_and_sort(self) -> None:
        rows = report.memory_rows(self.fabric, limit=2)
        self.assertEqual(len(rows), 2)
        by_state = report.memory_rows(self.fabric, sort="state")
        self.assertEqual(
            [r.lifecycle_state for r in by_state], sorted(r.lifecycle_state for r in by_state)
        )

    def test_lineage_tree_nests_descendants(self) -> None:
        tree = report.lineage_tree(self.fabric, self.fabric._root)
        self.assertEqual(tree.id, self.fabric._root)
        self.assertEqual(len(tree.children), 1)
        self.assertEqual(len(tree.children[0].children), 1)
        self.assertEqual(tree.children[0].children[0].depth, 2)

    def test_lineage_tree_respects_max_depth(self) -> None:
        tree = report.lineage_tree(self.fabric, self.fabric._root, max_depth=1)
        self.assertEqual(len(tree.children), 1)
        self.assertEqual(tree.children[0].children, [])
        self.assertTrue(tree.children[0].truncated)

    def test_lineage_direction_must_be_valid(self) -> None:
        with self.assertRaises(ValueError):
            report.lineage_tree(self.fabric, self.fabric._root, direction="sideways")

    def test_detail_includes_narrative_and_audit(self) -> None:
        detail = report.memory_detail(self.fabric, self.fabric._belief)
        self.assertIn("Memory", detail["narrative"])
        self.assertTrue(detail["audit"])
        self.assertTrue(any(e["type"] == "LifecycleChanged" for e in detail["audit"]))

    def test_audit_rows_omit_the_memory_snapshot(self) -> None:
        """A MemoryCreated payload holds the whole memory, which would repeat the
        content on every row and bury what actually changed."""
        detail = report.memory_detail(self.fabric, self.fabric._belief)
        for row in detail["audit"]:
            self.assertNotIn("memory", row["payload"])
            self.assertNotIn("candidates", row["payload"])

    def test_search_marks_non_retrievable_hits(self) -> None:
        hits = report.preview_search(self.fabric, "threshold 45", k=10)
        self.assertTrue(hits)
        quarantined = [h for h in hits if h.lifecycle_state == "quarantined"]
        self.assertTrue(quarantined)
        self.assertFalse(quarantined[0].retrievable)

    def test_search_can_restrict_to_retrievable_states(self) -> None:
        hits = report.preview_search(self.fabric, "threshold 45", all_states=False)
        self.assertTrue(all(h.retrievable for h in hits))

    def test_enum_values_cover_the_model(self) -> None:
        enums = report.enum_values()
        self.assertIn(LifecycleState.QUARANTINED.value, enums["lifecycle_state"])
        self.assertIn(Scope.FEDERATED.value, enums["scope"])
        self.assertIn(MemoryType.PROCEDURAL.value, enums["type"])

    def test_preview_collapses_whitespace(self) -> None:
        self.assertEqual(report.preview("a\n  b\tc"), "a b c")
        self.assertTrue(report.preview("x" * 400).endswith("…"))
        self.assertLessEqual(len(report.preview("x" * 400)), report.PREVIEW_CHARS)


class TestServer(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        # The `ips` estimator returns infinite bounds when it has no comparison
        # group, which is what produced the invalid-JSON bug. `naive_usage`
        # never emits them, so a fixture using it would not exercise the path.
        cls.fabric = populated(estimator="ips")
        cls.server = build_server(cls.fabric, host="127.0.0.1", port=0, quiet=True)
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

    def get(self, path: str) -> tuple[int, Any, str]:
        try:
            with urllib.request.urlopen(self.url(path), timeout=10) as res:
                body = res.read().decode("utf-8")
                ctype = res.headers.get("Content-Type", "")
                status = res.status
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8")
            ctype = exc.headers.get("Content-Type", "")
            status = exc.code
        parsed = json.loads(body) if "json" in ctype else body
        return status, parsed, ctype

    def test_serves_the_dashboard(self) -> None:
        status, body, ctype = self.get("/")
        self.assertEqual(status, 200)
        self.assertIn("text/html", ctype)
        self.assertIn("Memory Fabric", body)

    def test_dashboard_loads_no_third_party_resources(self) -> None:
        """The page must work offline and leak nothing to a CDN."""
        _, body, _ = self.get("/")
        for marker in ("http://", "https://", "//cdn", "integrity="):
            self.assertNotIn(marker, body.replace('xmlns="http://www.w3.org/', ""))

    def test_every_endpoint_emits_strictly_valid_json(self) -> None:
        """Regression: the API emitted `-Infinity` for an unknown value estimate.

        Python's `json.dumps` writes it and `json.loads` reads it back, so a
        round-trip test in Python sees nothing wrong — but it is not valid JSON,
        `JSON.parse` rejects the entire document, and every non-Python client
        breaks. Parsing with a strict hook is what the browser actually does.
        """

        def reject(value: str) -> float:
            raise AssertionError(f"non-finite literal {value!r} is not valid JSON")

        paths = [
            "/api/overview",
            "/api/attention",
            "/api/memories",
            "/api/episodes",
            "/api/enums",
            "/api/retention",
            f"/api/memories/{self.fabric._belief}",
            f"/api/memories/{self.fabric._root}/lineage",
            f"/api/memories/{self.fabric._belief}/audit",
            "/api/search?q=threshold",
        ]
        for path in paths:
            with self.subTest(path=path):
                with urllib.request.urlopen(self.url(path), timeout=10) as res:
                    raw = res.read().decode("utf-8")
                for literal in ("Infinity", "NaN"):
                    self.assertNotIn(literal, raw)
                json.loads(raw, parse_constant=reject)

    def test_api_endpoints_return_json(self) -> None:
        for path in ("/api/overview", "/api/attention", "/api/memories",
                     "/api/episodes", "/api/enums", "/api/retention"):
            with self.subTest(path=path):
                status, payload, ctype = self.get(path)
                self.assertEqual(status, 200)
                self.assertIn("json", ctype)
                self.assertIsNotNone(payload)

    def test_memory_detail_and_lineage(self) -> None:
        status, payload, _ = self.get(f"/api/memories/{self.fabric._belief}")
        self.assertEqual(status, 200)
        self.assertIn("narrative", payload)
        self.assertIn("descendants", payload)

        status, tree, _ = self.get(f"/api/memories/{self.fabric._root}/lineage")
        self.assertEqual(status, 200)
        self.assertEqual(tree["id"], self.fabric._root)

        status, audit, _ = self.get(f"/api/memories/{self.fabric._belief}/audit")
        self.assertEqual(status, 200)
        self.assertIsInstance(audit, list)

    def test_search_requires_a_query(self) -> None:
        status, payload, _ = self.get("/api/search")
        self.assertEqual(status, HTTPStatus.BAD_REQUEST)
        self.assertIn("error", payload)

    def test_search_returns_hits(self) -> None:
        status, hits, _ = self.get("/api/search?q=threshold")
        self.assertEqual(status, 200)
        self.assertTrue(hits)

    def test_malformed_memory_id_is_rejected(self) -> None:
        """Ids are ULIDs, so anything else is a client error, and rejecting early
        keeps arbitrary strings out of messages rendered back into the page."""
        for bad in ("notaulid", "0" * 25, "l" * 26, "abc123"):
            with self.subTest(bad=bad):
                status, payload, _ = self.get(f"/api/memories/{bad}")
                self.assertEqual(status, HTTPStatus.BAD_REQUEST)
                self.assertEqual(payload["error"], "malformed memory id")

    def test_hostile_ids_are_rejected_without_echoing_them(self) -> None:
        """Paths with extra segments are a different route, so 404 is correct;
        either way nothing hostile comes back in the response body."""
        for bad in ("../../etc/passwd", "<script>alert(1)</script>", "a/b/c"):
            with self.subTest(bad=bad):
                status, payload, _ = self.get(
                    "/api/memories/" + urllib.parse.quote(bad, safe="")
                )
                self.assertIn(status, (HTTPStatus.BAD_REQUEST, HTTPStatus.NOT_FOUND))
                self.assertNotIn("script", json.dumps(payload))
                self.assertNotIn("passwd", json.dumps(payload))

    def test_unknown_but_wellformed_id_is_not_found(self) -> None:
        status, payload, _ = self.get("/api/memories/" + "0" * 26)
        self.assertEqual(status, HTTPStatus.NOT_FOUND)
        self.assertIn("error", payload)

    def test_unknown_routes_are_not_found(self) -> None:
        for path in ("/api/nope", "/api/memories/x/y/z", "/nope"):
            with self.subTest(path=path):
                status, _, _ = self.get(path)
                self.assertEqual(status, HTTPStatus.NOT_FOUND)

    def test_bad_integer_parameter_is_a_client_error(self) -> None:
        status, payload, _ = self.get("/api/memories?limit=abc")
        self.assertEqual(status, HTTPStatus.BAD_REQUEST)
        self.assertIn("integer", payload["error"])

    def test_no_static_path_traversal(self) -> None:
        """Static assets come from a fixed allowlist, so no request path ever
        reaches a path join."""
        for path in ("/../cli.py", "/static/../../fabric.py", "/dashboard.html/../cli.py"):
            with self.subTest(path=path):
                status, _, _ = self.get(path)
                self.assertEqual(status, HTTPStatus.NOT_FOUND)

    def test_writes_are_not_possible(self) -> None:
        """There is no mutating endpoint, so browsing cannot change the store.

        Each method is refused cleanly with 405 and an `Allow` header. The
        refusal must be a proper response rather than a dropped connection: the
        default handler leaves the request body unread, which desynchronises a
        keep-alive connection and shows up as an intermittent failure.
        """
        before = len(self.fabric.log)
        for method in ("POST", "PUT", "PATCH", "DELETE"):
            with self.subTest(method=method):
                request = urllib.request.Request(
                    self.url("/api/memories"),
                    data=b'{"content": "injected"}',
                    method=method,
                )
                with self.assertRaises(urllib.error.HTTPError) as ctx:
                    urllib.request.urlopen(request, timeout=10)
                self.assertEqual(ctx.exception.code, HTTPStatus.METHOD_NOT_ALLOWED)
                self.assertEqual(ctx.exception.headers.get("Allow"), "GET, HEAD")
        self.assertEqual(len(self.fabric.log), before)

    def test_the_server_survives_a_refused_write(self) -> None:
        """Regression: an unread request body desynchronised the next request
        on the same keep-alive connection."""
        request = urllib.request.Request(
            self.url("/api/overview"), data=b"x" * 2048, method="POST"
        )
        with self.assertRaises(urllib.error.HTTPError):
            urllib.request.urlopen(request, timeout=10)
        status, payload, _ = self.get("/api/overview")
        self.assertEqual(status, 200)
        self.assertIn("total_memories", payload)

    def test_security_headers_are_set(self) -> None:
        with urllib.request.urlopen(self.url("/"), timeout=10) as res:
            self.assertIn("default-src 'none'", res.headers["Content-Security-Policy"])
            self.assertEqual(res.headers["X-Content-Type-Options"], "nosniff")
            self.assertEqual(res.headers["Cache-Control"], "no-store")

    def test_serving_does_not_grow_the_log(self) -> None:
        before = len(self.fabric.log)
        for path in ("/api/overview", "/api/attention", "/api/memories",
                     f"/api/memories/{self.fabric._belief}", "/api/search?q=warn"):
            self.get(path)
        self.assertEqual(len(self.fabric.log), before)


class TestCli(unittest.TestCase):
    def setUp(self) -> None:
        self.db = ":memory:"

    def run_cli(self, *argv: str) -> int:
        return main(list(argv))

    def test_help_exits_cleanly(self) -> None:
        with self.assertRaises(SystemExit) as ctx:
            self.run_cli("--help")
        self.assertEqual(ctx.exception.code, 0)

    def test_overview_on_an_empty_store(self) -> None:
        self.assertEqual(self.run_cli("--db", self.db, "overview"), 0)

    def test_json_output_is_strictly_valid(self) -> None:
        """Same guarantee as the HTTP API: the CLI's --json must be parseable by
        something that is not Python."""
        import contextlib
        import io
        import tempfile
        from pathlib import Path

        def reject(value: str) -> float:
            raise AssertionError(f"non-finite literal {value!r} is not valid JSON")

        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "store.db")
            fabric = populated(path=path)
            target = fabric._belief
            fabric.close()

            # --estimator ips is what surfaces the non-finite bounds.
            for argv in (
                ["--estimator", "ips", "--json", "show", target],
                ["--estimator", "ips", "--json", "list"],
                ["--json", "overview"],
                ["--json", "attention"],
                ["--json", "list"],
                ["--json", "show", target],
                ["--json", "episodes"],
            ):
                with self.subTest(argv=argv):
                    buffer = io.StringIO()
                    with contextlib.redirect_stdout(buffer):
                        self.run_cli("--db", path, *argv)
                    raw = buffer.getvalue()
                    self.assertNotIn("Infinity", raw)
                    json.loads(raw, parse_constant=reject)

    def test_attention_exit_code_signals_high_severity(self) -> None:
        """A non-zero exit lets this run as a health check in a script."""
        import contextlib
        import io
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "store.db")
            fabric = MemoryFabric(path, auto_activate=True)
            fabric.remember("agent-a", "An ordinary fact.", scope="team")
            fabric.close()
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                clean = self.run_cli("--db", path, "attention")
            self.assertEqual(clean, 0)

            fabric = MemoryFabric(path, auto_activate=True)
            fabric.remember("agent-b", "token AKIAIOSFODNN7EXAMPLE", scope="team")
            fabric.close()
            with contextlib.redirect_stdout(buffer):
                dirty = self.run_cli("--db", path, "attention")
            self.assertEqual(dirty, 1)

    def test_missing_store_is_an_error_not_an_empty_one(self) -> None:
        """A typo in --db would otherwise create an empty store and report
        nothing wrong, which for an inspection tool looks like an answer."""
        import contextlib
        import io
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            missing = str(Path(tmp) / "nope.db")
            err = io.StringIO()
            with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
                code = self.run_cli("--db", missing, "overview")
            self.assertEqual(code, 2)
            self.assertIn("no store at", err.getvalue())
            self.assertFalse(Path(missing).exists())

            # --create is the explicit opt-in.
            with contextlib.redirect_stdout(io.StringIO()):
                code = self.run_cli("--db", missing, "--create", "overview")
            self.assertEqual(code, 0)
            self.assertTrue(Path(missing).exists())

    def test_demo_may_create_its_own_store(self) -> None:
        import contextlib
        import io
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "demo.db")
            with contextlib.redirect_stdout(io.StringIO()):
                code = self.run_cli("--db", path, "demo")
            self.assertEqual(code, 0)
            self.assertTrue(Path(path).exists())

    def test_missing_memory_exits_with_a_code(self) -> None:
        import contextlib
        import io

        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            code = self.run_cli("--db", self.db, "show", "0" * 26)
        self.assertEqual(code, 3)

    def test_ansi_aware_width(self) -> None:
        self.assertEqual(_strip("\033[31mred\033[0m"), "red")
        self.assertEqual(len(_strip("\033[2m0123\033[0m")), 4)

    def test_clip_respects_the_glyph_width(self) -> None:
        clipped = clip("x" * 50, 10)
        self.assertLessEqual(len(clipped), 10)
        self.assertTrue(clipped.endswith(G.ELLIPSIS))


if __name__ == "__main__":
    unittest.main()


class TestSchemaVersionReporting(unittest.TestCase):
    """The question a store has to be able to answer is "can this build read my
    log?", and the answer is a comparison between two facts, not one of them.
    """

    def test_overview_reports_both_the_package_and_the_log(self) -> None:
        fabric = populated()
        self.addCleanup(fabric.close)
        data = report.overview(fabric)
        self.assertEqual(data.schema_version, SCHEMA_VERSION)
        self.assertEqual(data.log_schema_versions, [SCHEMA_VERSION])

    def test_a_log_written_by_a_newer_schema_is_flagged(self) -> None:
        fabric = populated()
        self.addCleanup(fabric.close)
        last = list(fabric.log.read())[-1]
        fabric.log.append(
            dataclasses.replace(last, event_id=last.event_id + "Z", schema_version="0.10.0")
        )

        data = report.overview(fabric)
        self.assertIn("0.10.0", data.log_schema_versions)
        self.assertTrue(
            any("newer than the installed" in note for note in data.diagnostics),
            f"no diagnostic warned about the newer schema: {data.diagnostics}",
        )

    def test_versions_compare_numerically_not_as_strings(self) -> None:
        """"0.10.0" sorts before "0.2.0" as a string, which would tell a reader
        its log was older than it is and let it act on incomplete figures."""
        self.assertGreater(report._version("0.10.0"), report._version("0.2.0"))
        self.assertGreater(report._version("1.0.0"), report._version("0.99.0"))
        self.assertEqual(report._version("0.2.0rc1"), (0, 2, 1))

    def test_package_version_is_not_behind_the_schema(self) -> None:
        """VERSIONING.md's one enforced invariant. A build may run ahead of the
        schema — a release can be packaging-only — but a build advertising an
        older version than the events it writes would mislead every reader of
        the log about what it can replay.
        """
        import tomllib
        from pathlib import Path

        pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
        if not pyproject.exists():  # installed copy, not a checkout
            self.skipTest("no pyproject.toml beside the package")
        declared = tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]["version"]
        self.assertGreaterEqual(report._version(declared), report._version(SCHEMA_VERSION))
