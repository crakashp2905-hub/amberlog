from __future__ import annotations

import threading
import unittest
from unittest.mock import patch

from experiments import p12b_api_load


class TestP12bApiLoad(unittest.TestCase):
    def test_agent_reaches_fetch_and_verify_after_recall(self) -> None:
        calls: list[str] = []

        def fake_post(port: int, op: str, body: dict, bearer: str):
            calls.append(op)
            if op == "recall":
                return 200, {"memories": [{"memory_id": "m1"}]}
            return 200, {}

        out: list[tuple[str, float, int]] = []
        barrier = threading.Barrier(1)
        with patch.object(p12b_api_load, "post", side_effect=fake_post):
            p12b_api_load.agent_loop(1, "token", 0, barrier, out)

        self.assertIn("recall", calls)
        self.assertIn("fetch", calls)
        self.assertIn("verify", calls)
        self.assertTrue(any(op == "fetch+verify" for op, _, _ in out))


if __name__ == "__main__":
    unittest.main()
