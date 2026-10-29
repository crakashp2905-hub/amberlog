"""After crypto-erasure, nothing derived from the erased text stays in memory.

Invariant 12 says the text goes and the accountability stays. The log only
holds ciphertext, so a *replay* after erasure cannot see the text. A process
that was already running could, in three places, all found while making
cross-process refresh incremental (tests/test_catch_up.py):

1. `state.history` kept every earlier version's plaintext, served by
   `history()` and the dashboard's version list.
2. The copy index kept the erased text's term set; `_unindex` deliberately
   leaves it alone so withdrawn documents stay recognisable, and the erased
   marker is too short to replace it.
3. (2) for a memory erased by *another* process, folded in by `refresh`.

What must not change: a quarantined document is still recognised when it is
re-ingested, because withdrawn is not erased.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from amberlog import Amberlog
from amberlog.governance.erasure import ERASED_MARKER

TEXT = "Pump seven bypass valve torque procedure for the coastal depot requires two people"


class ErasureLeavesNoResidue(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = str(Path(self.tmp.name) / "store.db")

    def open(self) -> Amberlog:
        fabric = Amberlog(self.path, auto_activate=True)
        self.addCleanup(fabric.close)
        return fabric

    def test_every_version_is_erased_in_the_erasing_process(self) -> None:
        fabric = self.open()
        mid = fabric.remember("a", TEXT)
        fabric.revise(mid, TEXT + " and a spotter", agent_id="a", reason="correction")
        fabric.erase_content(mid, reason="request", actor="dpo")
        self.assertEqual({m.content for m in fabric.history(mid)}, {ERASED_MARKER})

    def test_the_copy_index_forgets_the_erased_text(self) -> None:
        fabric = self.open()
        mid = fabric.remember("a", TEXT)
        self.assertIn(mid, fabric.copy_index.terms)
        fabric.erase_content(mid, reason="request", actor="dpo")
        self.assertNotIn(mid, fabric.copy_index.terms)
        for table in (fabric.copy_index.postings, fabric.copy_index.anchors):
            self.assertFalse(any(mid in ids for ids in table.values()))

    def test_an_erasure_by_another_process_is_folded_without_residue(self) -> None:
        live, other = self.open(), self.open()
        mid = live.remember("a", TEXT)
        live.revise(mid, TEXT + " and a spotter", agent_id="a", reason="correction")
        other.refresh()
        other.erase_content(mid, reason="request", actor="dpo")
        live.refresh()
        self.assertEqual({m.content for m in live.history(mid)}, {ERASED_MARKER})
        self.assertNotIn(mid, live.copy_index.terms)
        self.assertNotIn("torque", live.lexical._terms.get(mid, frozenset()))

    def test_a_revision_replaces_its_old_terms(self) -> None:
        fabric = self.open()
        mid = fabric.remember("a", TEXT)
        fabric.revise(mid, "Completely different wording about the inland reservoir gauge",
                      agent_id="a", reason="rewrite")
        self.assertNotIn("torque", fabric.copy_index.terms[mid])
        self.assertFalse(mid in fabric.copy_index.postings.get("torque", set()))

    def test_a_quarantined_document_is_still_recognised(self) -> None:
        fabric = self.open()
        mid = fabric.remember("a", TEXT)
        fabric.quarantine(mid, reason="poisoned", actor="op")
        self.assertIn(mid, fabric.copy_index.terms)
        self.assertIn(mid, fabric.copy_index.candidates(TEXT))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
