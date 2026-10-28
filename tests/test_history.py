"""history.believed_at: what the store would have shown at a past log position."""

from __future__ import annotations

import unittest

from memory_fabric import MemoryFabric
from memory_fabric.history import believed_at, seq_at


class BelievedAt(unittest.TestCase):
    def setUp(self) -> None:
        self.f = MemoryFabric(":memory:")
        self.addCleanup(self.f.close)

    def ids(self, agent: str, query: str, seq: int, **kw) -> list[str]:
        return [b.id for b in believed_at(self.f, agent, query, seq, **kw)]

    def test_a_correction_after_tau_does_not_change_what_was_believed(self) -> None:
        wrong = self.f.remember("a", "Pump P-3 relief valve is set to 15 bar.", scope="team")
        self.f.validate(wrong, actor="r")
        tau = self.f.log.head_seq
        self.f.quarantine(wrong, reason="recorded wrong", actor="auditor", basis="contradicted")
        right = self.f.remember("a", "Pump P-3 relief valve is set to 12 bar.", scope="team")
        self.f.validate(right, actor="r")
        self.assertEqual(self.ids("b", "relief valve", tau), [wrong])
        self.assertEqual(self.ids("b", "relief valve", self.f.log.head_seq), [right])

    def test_the_version_at_tau_is_returned(self) -> None:
        mid = self.f.remember("a", "Gate code is 1234.", scope="team")
        self.f.validate(mid, actor="r")
        tau = self.f.log.head_seq
        self.f.revise(mid, "Gate code is 9999.", "a", "rotated")
        then = believed_at(self.f, "b", "gate code", tau)[0]
        self.assertEqual((then.version, then.content), (1, "Gate code is 1234."))

    def test_scope_and_tenant_hold_at_tau(self) -> None:
        private = self.f.remember("a", "My locker combination is 4410.", scope="private")
        other = self.f.remember("a", "Locker combination policy changed.", scope="team", tenant_id="t2")
        for m in (private, other):
            self.f.validate(m, actor="r")
        tau = self.f.log.head_seq
        self.assertEqual(self.ids("b", "locker combination", tau, tenant_id="tn_default"), [])
        self.assertIn(private, self.ids("a", "locker combination", tau))

    def test_erased_content_never_returns_text(self) -> None:
        mid = self.f.remember("a", "Badge PIN is 8812.", scope="team")
        self.f.validate(mid, actor="r")
        tau = self.f.log.head_seq
        self.f.erase_content(mid, reason="erasure request")
        got = believed_at(self.f, "b", "", tau)
        self.assertTrue(got)
        self.assertTrue(all(b.content is None for b in got if b.id == mid))

    def test_seq_at_and_validation(self) -> None:
        self.f.remember("a", "x y z words here.")
        self.assertGreaterEqual(seq_at(self.f, 10 ** 15), 1)
        self.assertEqual(seq_at(self.f, 0), 0)
        with self.assertRaises(ValueError):
            believed_at(self.f, "a", "x", -1)


if __name__ == "__main__":
    unittest.main()
