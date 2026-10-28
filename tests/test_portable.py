"""GOV-16: an exported event log re-imported elsewhere keeps tombstones, versions, erasures and tenancy."""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from memory_fabric import LifecycleState, MemoryFabric
from memory_fabric.portable import export_events, import_events


def snapshot(f: MemoryFabric) -> dict:
    return {mid: (m.version, m.lifecycle_state, m.tenant_id, m.scope, tuple(sorted(m.context)))
            for mid, m in f.state.memories.items()}


class Portable(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.path = Path(self.dir.name) / "s.events.jsonl"
        self.src = MemoryFabric(":memory:", encrypt_content=False)
        self.addCleanup(self.src.close)
        f = self.src
        self.kept = f.remember("a", "The canteen opens at 8.", scope="team")
        self.gone = f.remember("a", "Pump P-3 relief is 15 bar.", scope="team")
        self.erased = f.remember("a", "Badge PIN is 4410.", scope="team")
        self.other = f.remember("b", "Tenant two note about lockers.", tenant_id="t2")
        for m in (self.kept, self.gone, self.erased):
            f.validate(m, actor="r")
        f.revise(self.kept, "The canteen opens at 9.", "a", "new hours")
        f.quarantine(self.gone, reason="wrong", actor="r", basis="contradicted")
        f.erase_content(self.erased, reason="erasure request")

    def test_round_trip_keeps_every_state(self) -> None:
        manifest = export_events(self.src, self.path)
        dst = MemoryFabric(":memory:", encrypt_content=False)
        self.addCleanup(dst.close)
        result = import_events(dst, self.path)
        self.assertEqual(result["imported"], manifest["events"] - 1)
        self.assertEqual(result["imported_from"], self.src.store_id)
        self.assertEqual(snapshot(dst), snapshot(self.src))
        self.assertIs(dst.get(self.gone).lifecycle_state, LifecycleState.QUARANTINED)
        self.assertIn(self.erased, dst.state.erased)
        self.assertEqual(dst.get(self.kept).content, "The canteen opens at 9.")
        self.assertNotIn(self.gone, [m.id for m in dst.retrieve("x", "relief", min_relevance=0.0).exposed])

    def test_damaged_or_truncated_exports_and_non_empty_targets_are_refused(self) -> None:
        export_events(self.src, self.path)
        lines = self.path.read_text(encoding="utf-8").splitlines()
        hit = next(i for i, line in enumerate(lines) if "canteen" in line)
        tampered = lines[:hit] + [lines[hit].replace("canteen", "kitchen")] + lines[hit + 1:]
        for bad in (lines[:-1], lines[:-2] + lines[-1:], tampered):
            p = Path(self.dir.name) / "bad.jsonl"
            p.write_text("\n".join(bad) + "\n", encoding="utf-8")
            dst = MemoryFabric(":memory:")
            self.addCleanup(dst.close)
            with self.assertRaises(ValueError):
                import_events(dst, p)
        with self.assertRaises(ValueError):
            import_events(self.src, self.path)

    def test_the_export_carries_no_plaintext_when_content_is_encrypted(self) -> None:
        enc = MemoryFabric(":memory:")
        self.addCleanup(enc.close)
        enc.remember("a", "Vault combination is 7731.")
        export_events(enc, self.path)
        self.assertNotIn("7731", self.path.read_text(encoding="utf-8"))
        self.assertEqual(json.loads(self.path.read_text(encoding="utf-8").splitlines()[-1])["manifest"]["events"],
                         enc.log.head_seq)
        dst = MemoryFabric(":memory:")
        self.addCleanup(dst.close)
        with self.assertRaises(ValueError):
            import_events(dst, self.path)
        self.assertEqual([e.type for e in dst.log.read()], ["StoreIdentified"])   # nothing written


if __name__ == "__main__":
    unittest.main()
