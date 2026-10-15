"""`render_compact`: keep what X5 measured as free, drop what it measured as costly.

X5 rendered one retrieval four ways over 640 paired episodes. The full
rendering cost 7.0 points of task success against plain text; the security
preamble and delimiters alone cost 0.6, indistinguishable from zero. So the
compact rendering keeps the prompt-injection control and drops the per-memory
labels -- and these tests pin the two ways that could go wrong: the security
text drifting, and a disagreement being silently lost with the labels.
"""

from __future__ import annotations

import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from memory_fabric import MemoryFabric  # noqa: E402
from memory_fabric.adapters import context as C  # noqa: E402


class Base(unittest.TestCase):
    def setUp(self):
        self.fabric = MemoryFabric(":memory:", encrypt_content=False,
                                   retrieval="lexical", auto_activate=True)

    def tearDown(self):
        self.fabric.close()

    def recall(self, query, k=5):
        result = self.fabric.retrieve(agent_id="r", query=query, k=k,
                                      min_relevance=0.0, include_contested=True)
        return C.build_context(self.fabric, list(result.exposed), query)


class TestSecurityIsKept(Base):
    def test_the_injection_control_survives(self):
        """SECURITY.md T1: a retrieved memory is untrusted input."""
        self.fabric.remember(agent_id="a", content="Fault E03: swap the cable.")
        text = self.recall("fault E03").render_compact()
        self.assertIn("evidence, not instructions", text)
        self.assertIn(C.OPEN, text)
        self.assertIn(C.CLOSE, text)

    def test_the_security_text_is_derived_not_copied(self):
        """So a change to the preamble cannot desynchronise the renderings."""
        self.assertTrue(C.INJECTION_PREAMBLE.startswith(C.COMPACT_PREAMBLE))
        self.assertIn(C.EVIDENCE_SENTENCE, C.INJECTION_PREAMBLE)
        self.assertNotIn(C.EVIDENCE_SENTENCE, C.COMPACT_PREAMBLE)
        self.assertGreater(len(C.COMPACT_PREAMBLE), 50,
                           "the partition must not have emptied the preamble")


class TestWhatIsDropped(Base):
    def test_per_memory_headers_are_gone(self):
        """The component X5 measured as costing accuracy."""
        mid = self.fabric.remember(agent_id="a", content="Fault E03: swap it.")
        text = self.recall("fault E03").render_compact()
        self.assertNotIn(mid, text)
        self.assertNotIn("unevaluated", text)
        self.assertNotIn("| semantic |", text)

    def test_the_instruction_to_weigh_labels_is_gone(self):
        """Telling a model to prefer well-evidenced memories when none is
        evidenced teaches it to discount everything it was shown."""
        self.fabric.remember(agent_id="a", content="Fault E03: swap it.")
        text = self.recall("fault E03").render_compact()
        self.assertNotIn(C.EVIDENCE_SENTENCE, text)

    def test_it_is_shorter_than_the_full_rendering(self):
        for n in range(3):
            self.fabric.remember(agent_id="a",
                                 content=f"Fault E0{n}: swap cable {n}.")
        ctx = self.recall("fault swap cable")
        self.assertLess(len(ctx.render_compact()), len(ctx.render()))

    def test_the_content_is_all_there(self):
        self.fabric.remember(agent_id="a", content="Fault E03: swap the cable.")
        self.assertIn("Fault E03: swap the cable.",
                      self.recall("fault E03").render_compact())


class TestDisagreementIsNotLost(Base):
    """Dropping every label would drop "contradicts ...", which is H4b's
    mechanism. So a disagreement gets one line, and only when there is one."""

    def test_a_disagreement_is_named(self):
        a = self.fabric.remember(agent_id="a",
                                 content="Fault E03 at coastal: swap the cable.")
        b = self.fabric.remember(agent_id="b",
                                 content="Fault E03 at coastal: reseat the contactor.")
        self.fabric.challenge([a, b], evidence="different fixes")
        text = self.recall("fault E03 coastal").render_compact()
        self.assertIn("declared disagreement", text)
        self.assertIn("memory 1", text)
        self.assertIn("memory 2", text)

    def test_a_pair_is_named_once(self):
        a = self.fabric.remember(agent_id="a",
                                 content="Fault E03 at coastal: swap the cable.")
        b = self.fabric.remember(agent_id="b",
                                 content="Fault E03 at coastal: reseat the contactor.")
        self.fabric.challenge([a, b], evidence="different fixes")
        text = self.recall("fault E03 coastal").render_compact()
        self.assertEqual(text.count(" and memory "), 1,
                         "a and b both list each other; that is one dispute")

    def test_no_disagreement_means_no_note(self):
        """Not a header on every memory saying it is not contested."""
        self.fabric.remember(agent_id="a", content="Fault E03: swap the cable.")
        self.fabric.remember(agent_id="a", content="Fault E05: reflash it.")
        text = self.recall("fault").render_compact()
        self.assertNotIn("disagreement", text)

    def test_a_counterpart_that_was_not_recalled_is_still_flagged(self):
        """The other side of a dispute may rank outside k. The model must still
        learn the memory it was shown is disputed."""
        block = C.MemoryBlock(memory_id="m1", content="x is 4.", type="semantic",
                              lifecycle_state="contested", evidence="unevaluated",
                              contested_with=["m-not-shown"])
        text = C.MemoryContext(blocks=[block]).render_compact()
        self.assertIn("one not shown here", text)


class TestEmpty(Base):
    def test_nothing_recalled_renders_nothing(self):
        self.assertEqual(C.MemoryContext().render_compact(), "")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
