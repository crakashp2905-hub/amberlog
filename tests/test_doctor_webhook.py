"""`doctor --webhook`: the store's first alerting path."""

from __future__ import annotations

import json
import os
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from io import StringIO
from unittest import mock

from amberlog import Amberlog
from amberlog import cli
from amberlog.cli import Finding, main


class Sink:
    def __init__(self) -> None:
        self.bodies: list[dict] = []
        sink = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                sink.bodies.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
                self.send_response(204)
                self.end_headers()

            def log_message(self, *a: object) -> None:
                return

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}/hook"

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


def failing(fabric: Amberlog) -> Finding:
    return Finding("fail", "event chain", "the chain does not verify", "restore from backup")


def warning(fabric: Amberlog) -> Finding:
    return Finding("warn", "pending deliveries", "3 retractions owed", "run maintain")


class DoctorWebhook(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.db = os.path.join(tmp.name, "s.db")
        Amberlog(self.db).close()
        self.sink = Sink()
        self.addCleanup(self.sink.close)

    def doctor(self, checks: list, *extra: str) -> int:
        with mock.patch.object(cli, "DOCTOR_CHECKS", checks), \
                mock.patch("sys.stdout", StringIO()):
            return main(["--db", self.db, "doctor", "--webhook", self.sink.url, *extra])

    def test_a_failing_store_alerts(self) -> None:
        self.assertEqual(self.doctor([failing, warning]), 5)
        self.assertEqual(len(self.sink.bodies), 1)
        body = self.sink.bodies[0]
        self.assertFalse(body["sound"])
        self.assertEqual(body["severity"], "fail")
        self.assertIn("event chain", body["text"])

    def test_a_sound_store_is_silent(self) -> None:
        self.assertEqual(self.doctor([]), 0)
        self.assertEqual(self.sink.bodies, [])

    def test_warnings_alert_only_when_asked(self) -> None:
        self.doctor([warning])
        self.assertEqual(self.sink.bodies, [])
        self.doctor([warning], "--webhook-on", "warn")
        self.assertEqual(self.sink.bodies[0]["severity"], "warn")

    def test_an_undeliverable_alert_is_reported_not_hidden(self) -> None:
        err = StringIO()
        with mock.patch.object(cli, "DOCTOR_CHECKS", [failing]), \
                mock.patch("sys.stdout", StringIO()), mock.patch("sys.stderr", err):
            code = main(["--db", self.db, "doctor", "--webhook", "http://127.0.0.1:9/none"])
        self.assertEqual(code, 5)
        self.assertIn("not delivered", err.getvalue())


if __name__ == "__main__":
    unittest.main()
