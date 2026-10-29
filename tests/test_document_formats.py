"""Known-source fidelity and governed correction tests for local adapters."""
import hashlib
import io
import json
import importlib.util
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from amberlog import Amberlog, LifecycleState
from amberlog.document_formats import compile_csv, compile_html, compile_file, compile_docx, compile_pdf
from amberlog.docsource import import_document


class FormatTests(unittest.TestCase):
    def test_docx_paragraphs_and_table_cells(self):
        xml = ('<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
               '<w:body><w:p><w:r><w:t>Café review</w:t></w:r></w:p>'
               '<w:tbl><w:tr><w:tc><w:p><w:r><w:t>release</w:t></w:r></w:p></w:tc>'
               '<w:tc><w:p><w:r><w:t>two reviewers</w:t></w:r></w:p></w:tc></w:tr></w:tbl>'
               '</w:body></w:document>')
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("word/document.xml", xml)
        raw = buffer.getvalue()
        tree = compile_docx(raw, doc_id="d", version="1")
        self.assertEqual(tree["sections"][0]["text"], "Café review")
        self.assertEqual(json.loads(tree["sections"][1]["text"]),
                         {"rows": [["release", "two reviewers"]]})
        self.assertEqual(tree["sections"][1]["path"], "body/2")
        self.assertEqual(tree["source_sha256"], hashlib.sha256(raw).hexdigest())

    def test_invalid_docx_and_entities_are_refused(self):
        with self.assertRaises(ValueError):
            compile_docx(b"not a zip", doc_id="d", version="1")
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("word/document.xml", '<!DOCTYPE x [<!ENTITY e "secret">]><x/>')
        with self.assertRaises(ValueError):
            compile_docx(buffer.getvalue(), doc_id="d", version="1")

    @unittest.skipUnless(importlib.util.find_spec("pypdf"), "pypdf not installed")
    def test_real_pdf_page_text_and_textless_refusal(self):
        from pypdf import PdfWriter
        from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
        writer = PdfWriter()
        page = writer.add_blank_page(300, 300)
        font = DictionaryObject({NameObject("/Type"): NameObject("/Font"),
                                 NameObject("/Subtype"): NameObject("/Type1"),
                                 NameObject("/BaseFont"): NameObject("/Helvetica")})
        page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"):
            DictionaryObject({NameObject("/F1"): writer._add_object(font)})})
        stream = DecodedStreamObject()
        stream.set_data(b"BT /F1 12 Tf 20 200 Td (Review every release.) Tj ET")
        page[NameObject("/Contents")] = writer._add_object(stream)
        output = io.BytesIO()
        writer.write(output)
        tree = compile_pdf(output.getvalue(), doc_id="d", version="1")
        self.assertEqual(tree["sections"][0]["path"], "page/1")
        self.assertIn("Review every release.", tree["sections"][0]["text"])
        writer.add_blank_page(300, 300)
        output = io.BytesIO()
        writer.write(output)
        with self.assertRaisesRegex(ValueError, "page 2"):
            compile_pdf(output.getvalue(), doc_id="d", version="2")

    def test_multiline_csv_cells_and_original_spans(self):
        text = 'name,note\r\nCafé,"first\r\nsecond, quoted"\r\n'
        tree = compile_csv(text, doc_id="records", version="1")
        row = tree["sections"][1]
        self.assertEqual(json.loads(row["text"]),
                         {"name": "Café", "note": "first\r\nsecond, quoted"})
        self.assertEqual((row["line_start"], row["line_end"]), (2, 3))
        self.assertEqual(text.encode()[row["byte_start"]:row["byte_end"]].decode(),
                         'Café,"first\r\nsecond, quoted"\r\n')
        self.assertEqual(tree["source_sha256"], hashlib.sha256(text.encode()).hexdigest())

    def test_bad_csv_refused_without_silent_cell_loss(self):
        for text in ('a,a\n1,2', 'a,\n1,2', 'a,b\n1', 'a,b\n1,2,3', 'a\n"unclosed'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                compile_csv(text, doc_id="d", version="1")

    def test_formula_cells_are_literal_strings(self):
        row = compile_csv('value\n=1+1\n', doc_id="d", version="1")["sections"][1]
        self.assertEqual(json.loads(row["text"])["value"], "=1+1")

    def test_html_excludes_active_resources_and_preserves_text(self):
        source = ('<head><title>Metadata</title></head><h1>Café &amp; Tea</h1>'
                  '<script>stolen()</script><style>.x{}</style><template>hidden</template>'
                  '<p>Review <b>every</b> release.</p><img src="https://invalid.test/secret">'
                  '<table><tr><td>mode</td><td>review</td></tr></table>')
        tree = compile_html(source, doc_id="d", version="1")
        section = tree["sections"][0]
        self.assertIn("Café & Tea", section["text"])
        self.assertIn("Review every release.", section["text"])
        self.assertIn("mode\treview", section["text"])
        for hidden in ("stolen", "Metadata", "hidden", "invalid.test", ".x"):
            self.assertNotIn(hidden, section["text"])
        self.assertEqual(source.encode()[section["byte_start"]:section["byte_end"]], source.encode())

    def test_file_reader_preserves_crlf_source_digest(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "doc.md"
            raw = b'# Review\r\nReview every release.\r\n'
            path.write_bytes(raw)
            tree = compile_file(path, format="markdown", doc_id="d", version="1")
            self.assertEqual(tree["source_sha256"], hashlib.sha256(raw).hexdigest())
            self.assertEqual(tree["sections"][0]["byte_end"], len(raw) - 2)

    def test_governed_revision_invalidation_and_other_tenant_preservation(self):
        fabric = Amberlog(":memory:")
        self.addCleanup(fabric.close)
        first = compile_csv('name,rule\nrelease,one reviewer\n', doc_id="d", version="1")
        foreign = import_document(fabric, first, tenant_id="other", activate=True)
        imported = import_document(fabric, first, activate=True)
        mid = imported.added[1]
        child = fabric.derive("planner", "Schedule one reviewer.", parents=[mid], scope="team")
        fabric.validate(child, actor="reviewer")
        next_tree = compile_csv('name,rule\nrelease,two reviewers\n', doc_id="d", version="2")
        report = import_document(fabric, next_tree)
        self.assertIn(mid, report.withdrawn)
        self.assertIn(child, report.contested)
        self.assertIs(fabric.get(report.added[0]).lifecycle_state, LifecycleState.CANDIDATE)
        self.assertTrue(all(fabric.get(m).lifecycle_state is LifecycleState.ACTIVE
                            for m in foreign.added))
