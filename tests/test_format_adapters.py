"""MF-007: HTML, CSV and .docx compile to the same governed section tree as Markdown."""

from __future__ import annotations

import io
import json
import subprocess
import sys
import unittest
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory

from memory_fabric import MemoryFabric
from memory_fabric.docsource import import_document
from memory_fabric.knowledge_compiler import MAX_BYTES, compile_csv, compile_docx, compile_html

ID = {"doc_id": "d", "version": "1"}


def docx(paragraphs: list[tuple[str | None, str]], table: list[list[str]] | None = None) -> bytes:
    w = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
    parts = []
    for style, text in paragraphs:
        ppr = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style else ""
        parts.append(f"<w:p>{ppr}<w:r><w:t>{text}</w:t></w:r></w:p>")
    if table:
        rows = "".join("<w:tr>" + "".join(f"<w:tc><w:p><w:r><w:t>{c}</w:t></w:r></w:p></w:tc>" for c in r)
                       + "</w:tr>" for r in table)
        parts.append(f"<w:tbl>{rows}</w:tbl>")
    xml = f'<?xml version="1.0"?><w:document {w}><w:body>{"".join(parts)}</w:body></w:document>'
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml", xml)
    return buf.getvalue()


class Html(unittest.TestCase):
    def test_headings_text_tables_and_dropped_markup(self) -> None:
        t = compile_html("<html><head><style>x{}</style></head><body><nav>menu</nav>"
                         "<h1>Release</h1><p>Review every release.</p><script>alert(1)</script>"
                         "<h2>Limits</h2><table><tr><th>pump</th><th>bar</th></tr><tr><td>P-3</td><td>12</td></tr></table>"
                         "</body></html>", **ID)
        self.assertEqual([s["title"] for s in t["sections"]], ["Release", "Limits"])
        text = " ".join(s["text"] for s in t["sections"])
        for gone in ("alert", "menu", "x{}"):
            self.assertNotIn(gone, text)
        self.assertIn("P-3 | 12", t["sections"][1]["text"])
        self.assertEqual(t["sections"][1]["path"].count("/"), 1)
        self.assertEqual((t["format"], t["mime"]), ("html", "text/html"))

    def test_entities_and_line_spans(self) -> None:
        t = compile_html("<h1>A &amp; B</h1>\n<p>one</p>\n<p>two</p>\n<h1>C</h1>\n<p>three</p>", **ID)
        self.assertEqual(t["sections"][0]["title"], "A & B")
        self.assertEqual((t["sections"][0]["line_start"], t["sections"][0]["line_end"]), (1, 3))


class Csv(unittest.TestCase):
    TEXT = "id,pump,limit,code\nP3,feed,-3,0012\n\nP4,drain,1e3,0040\n"

    def test_cells_are_verbatim_with_row_provenance(self) -> None:
        t = compile_csv(self.TEXT, key="id", **ID)
        self.assertEqual([s["path"] for s in t["sections"]], ["row:P3", "row:P4"])
        first = t["sections"][0]
        self.assertEqual(first["cells"], {"id": "P3", "pump": "feed", "limit": "-3", "code": "0012"})
        self.assertIn("limit: -3", first["text"])
        self.assertEqual(t["sections"][1]["line_start"], 4)

    def test_a_moved_row_with_a_key_withdraws_nothing(self) -> None:
        f = MemoryFabric(":memory:")
        self.addCleanup(f.close)
        import_document(f, compile_csv(self.TEXT, key="id", **ID), activate=True)
        moved = "id,pump,limit,code\nP4,drain,1e3,0040\nP3,feed,-3,0012\n"
        r = import_document(f, compile_csv(moved, key="id", doc_id="d", version="2"))
        self.assertEqual((r.added, r.withdrawn), ([], []))

    def test_bad_key_and_duplicates(self) -> None:
        with self.assertRaises(ValueError):
            compile_csv(self.TEXT, key="nope", **ID)
        with self.assertRaises(ValueError):
            compile_csv("id,x\n1,a\n1,b\n", key="id", **ID)
        self.assertEqual(compile_csv("", **ID)["sections"], [])


class Docx(unittest.TestCase):
    def test_headings_paragraphs_and_tables(self) -> None:
        t = compile_docx(docx([("Heading1", "Safety"), (None, "Wear gloves."), ("Heading2", "Valves"),
                               (None, "Close slowly.")], table=[["V-1", "12 bar"]]), **ID)
        self.assertEqual([s["title"] for s in t["sections"]], ["Safety", "Valves"])
        self.assertIn("V-1 | 12 bar", t["sections"][1]["text"])
        self.assertEqual(t["sections"][1]["path"].count("/"), 1)

    def test_not_a_docx_and_size_limit(self) -> None:
        with self.assertRaises(ValueError):
            compile_docx(b"plain text", **ID)
        with self.assertRaises(ValueError):
            compile_docx(b"x" * (MAX_BYTES + 1), **ID)


class Cli(unittest.TestCase):
    def test_each_format_imports_through_the_cli(self) -> None:
        with TemporaryDirectory() as d:
            files = {"html": ("a.html", "<h1>T</h1><p>body text</p>".encode()),
                     "csv": ("a.csv", b"id,v\n1,x\n"), "docx": ("a.docx", docx([("Heading1", "T"), (None, "b")]))}
            db = str(Path(d) / "s.db")
            for fmt, (name, data) in files.items():
                (Path(d) / name).write_bytes(data)
                cmd = [sys.executable, "-m", "memory_fabric", "--db", db, "--create", "--json", "import-docs",
                       str(Path(d) / name), "--format", fmt, "--doc-id", fmt, "--source-version", "1"]
                done = subprocess.run(cmd + (["--key", "id"] if fmt == "csv" else []), capture_output=True, text=True)
                self.assertEqual(done.returncode, 0, done.stderr)
                self.assertEqual(len(json.loads(done.stdout)["added"]), 1, fmt)


if __name__ == "__main__":
    unittest.main()
