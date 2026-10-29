"""Masterplan MF-004..MF-006: source spans, parser edge cases, tenant isolation, recoverable import."""

from __future__ import annotations

import random
import unittest
from unittest import mock

from amberlog import LifecycleState, Amberlog
from amberlog.identity import DEFAULT_TENANT
from amberlog.docsource import current_sections, import_document
from amberlog.knowledge_compiler import MAX_BYTES, PARSER_VERSION, compile_markdown


def tree(text: str, version: str = "1", doc_id: str = "d") -> dict:
    return compile_markdown(text, doc_id=doc_id, version=version)


def span_text(source: str, s: dict) -> str:
    return source.encode("utf-8")[s["byte_start"]:s["byte_end"]].decode("utf-8")


class SpanFidelity(unittest.TestCase):
    SOURCE = "Intro line.\n\n# Één\nCafé ünïcode body.\n\n## Child\nChild text.\n\n\n# Two\nLast.\n"

    def test_every_span_resolves_to_the_exact_source_text(self) -> None:
        t = tree(self.SOURCE)
        self.assertEqual(t["parser_version"], PARSER_VERSION)
        lines = self.SOURCE.splitlines()
        for s in t["sections"]:
            exact = span_text(self.SOURCE, s)
            self.assertIn(s["text"], exact)
            self.assertEqual(exact.splitlines(), lines[s["line_start"] - 1:s["line_end"]])
            if s["title"]:
                self.assertIn(s["title"], exact.splitlines()[0])

    def test_trailing_blank_lines_are_not_in_the_span(self) -> None:
        child = next(s for s in tree(self.SOURCE)["sections"] if s["title"] == "Child")
        self.assertEqual((child["line_start"], child["line_end"]), (6, 7))

    def test_crlf_compiles_to_the_same_sections_with_true_offsets(self) -> None:
        crlf = self.SOURCE.replace("\n", "\r\n")
        a, b = tree(self.SOURCE)["sections"], tree(crlf)["sections"]
        self.assertEqual([(s["path"], s["text"], s["line_start"], s["line_end"]) for s in a],
                         [(s["path"], s["text"], s["line_start"], s["line_end"]) for s in b])
        for s in b:
            self.assertIn(s["text"].split("\n")[0], span_text(crlf, s))

    def test_spans_reach_the_stored_provenance(self) -> None:
        f = Amberlog(":memory:")
        self.addCleanup(f.close)
        r = import_document(f, tree(self.SOURCE))
        src = f.get(r.added[0]).context["source"]
        for key in ("line_start", "line_end", "byte_start", "byte_end", "parser_version",
                    "source_sha256", "mime", "sha256", "doc_id", "version", "path"):
            self.assertIn(key, src)


class ParserMatrix(unittest.TestCase):
    def titles(self, text: str) -> list[str]:
        return [s["title"] for s in tree(text)["sections"]]

    def test_fences(self) -> None:
        for fence in ("```", "~~~", "````"):
            text = f"# A\n{fence}\n# not a heading\n{fence}\nafter\n# B\nb"
            self.assertEqual(self.titles(text), ["A", "B"], fence)
        # A shorter closing run does not close a longer fence.
        self.assertEqual(self.titles("# A\n````\n```\n# inside\n````\n# B\nb"), ["A", "B"])
        # A tilde run does not close a backtick fence.
        self.assertEqual(self.titles("# A\n```\n~~~\n# inside\n```\n# B\nb"), ["A", "B"])

    def test_not_headings(self) -> None:
        for text in ("\\# escaped\nbody", "#nospace\nbody", "    # indented code\nbody",
                     "####### seven\nbody"):
            self.assertEqual(self.titles(text), [""], text)

    def test_closing_hashes_and_unicode_titles(self) -> None:
        t = tree("## Résumé ##\nx\n# 日本語\ny")["sections"]
        self.assertEqual([s["title"] for s in t], ["Résumé", "日本語"])
        self.assertTrue(all(s["path"] for s in t))

    def test_empty_and_whitespace_documents_have_no_sections(self) -> None:
        for text in ("", "\n\n   \n", "# Only\n## Headings\n"):
            self.assertEqual(tree(text)["sections"], [], repr(text))

    def test_deep_nesting_and_level_jumps(self) -> None:
        text = "".join(f"{'#' * n} L{n}\nt{n}\n" for n in range(1, 7)) + "# Top\nz"
        paths = [s["path"] for s in tree(text)["sections"]]
        self.assertEqual(paths[5].count("/"), 5)
        self.assertEqual(paths[-1].count("/"), 0)
        self.assertEqual(len(set(paths)), 7)

    def test_size_limit(self) -> None:
        with self.assertRaises(ValueError):
            compile_markdown("x" * (MAX_BYTES + 1), doc_id="d", version="1")

    def test_deterministic(self) -> None:
        rng = random.Random(7)
        parts = ["# H", "## Sub", "text", "```", "~~~", "| a | b |", "Title", "===", "---", "- item", ""]
        for _ in range(200):
            text = "\n".join(rng.choice(parts) for _ in range(rng.randint(0, 30)))
            self.assertEqual(tree(text), tree(text))
            paths = [s["path"] for s in tree(text)["sections"]]
            self.assertEqual(len(paths), len(set(paths)), text)


class TenantIsolation(unittest.TestCase):
    """Same doc_id and the same text in many tenants: no import touches another tenant."""

    def test_property(self) -> None:
        rng = random.Random(11)
        f = Amberlog(":memory:")
        self.addCleanup(f.close)
        tenants = [None, "t1", "t2", "t3"]
        texts = ["# A\nalpha", "# A\nbeta", "# A\nalpha\n# B\nbravo", "# B\nbravo"]
        latest: dict[str | None, str] = {}
        for step in range(40):
            tenant, text = rng.choice(tenants), rng.choice(texts)
            import_document(f, tree(text, str(step), doc_id="shared"), tenant_id=tenant)
            latest[tenant] = text
            for t, last in latest.items():
                standing = current_sections(f, "shared", t or DEFAULT_TENANT)
                expected = {s["text"] for s in tree(last)["sections"]}
                got = {f.get(m.id).content.split(": ", 1)[1] for m in standing.values()}
                self.assertEqual(got, expected, (step, t))
                self.assertTrue(all(m.tenant_id == (t or DEFAULT_TENANT) for m in standing.values()))


class RecoverableImport(unittest.TestCase):
    def test_a_crash_mid_import_is_repaired_by_running_it_again(self) -> None:
        f = Amberlog(":memory:")
        self.addCleanup(f.close)
        import_document(f, tree("# A\nold a\n# B\nold b"), activate=True)
        new = tree("# A\nnew a\n# B\nnew b\n# C\nc", "2")
        real = f.remember
        calls = {"n": 0}

        def flaky(*a, **k):
            calls["n"] += 1
            if calls["n"] == 2:
                raise RuntimeError("crash")
            return real(*a, **k)

        with mock.patch.object(f, "remember", side_effect=flaky):
            with self.assertRaises(RuntimeError):
                import_document(f, new, activate=True)
        again = import_document(f, new, activate=True)
        standing = current_sections(f, "d", DEFAULT_TENANT)
        self.assertEqual(sorted(m.content for m in standing.values()), ["A: new a", "B: new b", "C: c"])
        self.assertEqual(len(again.withdrawn), 2)
        for mid in again.withdrawn:
            self.assertIs(f.get(mid).lifecycle_state, LifecycleState.QUARANTINED)


if __name__ == "__main__":
    unittest.main()
