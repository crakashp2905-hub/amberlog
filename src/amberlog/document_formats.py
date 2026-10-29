"""Opt-in local format adapters returning the governed compiled-tree contract.

No adapter fetches resources, approves content, or invokes an extraction model.
CSV cell values remain strings, including spreadsheet formula-looking content.
"""
from __future__ import annotations

__stability__ = "experimental"

import csv
import hashlib
import io
import json
import zipfile
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from .knowledge_compiler import MAX_BYTES, compile_markdown


def _tree(raw: bytes, doc_id: str, version: str, uri: str,
          kind: str, mime: str, sections: list[dict[str, Any]]) -> dict[str, Any]:
    if not doc_id.strip() or not version.strip():
        raise ValueError("doc_id and version must be non-empty")
    if len(raw) > MAX_BYTES:
        raise ValueError(f"document exceeds the {MAX_BYTES} byte limit")
    return {"doc_id": doc_id, "version": version, "uri": uri,
            "source_sha256": hashlib.sha256(raw).hexdigest(), "format": kind,
            "mime": mime, "parser_version": f"{kind}-1", "sections": sections}


def compile_csv(text: str, *, doc_id: str, version: str, uri: str = "",
                delimiter: str = ",") -> dict[str, Any]:
    """Compile a header and each data row with exact physical-line/UTF-8 spans.

Duplicate/empty column names and ragged rows are refused rather than silently
discarding cells. Row positions are citation anchors, not semantic primary keys.
    """
    raw = text.encode("utf-8")
    tree = _tree(raw, doc_id, version, uri, "csv", "text/csv", [])
    offsets = [0]
    for line in text.splitlines(keepends=True):
        offsets.append(offsets[-1] + len(line.encode("utf-8")))
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter, strict=True)
    sections = tree["sections"]
    header: list[str] | None = None
    previous = 0
    try:
        for row in reader:
            start, end = previous + 1, reader.line_num
            previous = end
            if not row:
                continue
            if header is None:
                header = row
                if any(not name.strip() for name in header) or len(set(header)) != len(header):
                    raise ValueError("CSV headers must be non-empty and unique")
                content: Any = {"columns": header}
                anchor = "header"
            else:
                if len(row) != len(header):
                    raise ValueError(f"CSV line {start}: expected {len(header)} cells, got {len(row)}")
                content = dict(zip(header, row))
                anchor = f"row/{start}"
            sections.append({"path": anchor, "text": json.dumps(content, ensure_ascii=False),
                             "line_start": start, "line_end": end,
                             "byte_start": offsets[start - 1], "byte_end": offsets[end]})
    except csv.Error as exc:
        raise ValueError(f"invalid CSV near line {reader.line_num}: {exc}") from exc
    return tree


class _HTMLText(HTMLParser):
    """Visible text only; never execute scripts or resolve external resources."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.hidden = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "template", "head"}:
            self.hidden += 1
        if not self.hidden and tag in {"p", "div", "br", "tr", "li", "h1", "h2", "h3",
                                       "h4", "h5", "h6", "section", "article"}:
            self.parts.append("\n")
        if not self.hidden and tag in {"td", "th"}:
            self.parts.append("\t")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "template", "head"}:
            self.hidden = max(0, self.hidden - 1)
        if not self.hidden and tag in {"p", "div", "tr", "li", "h1", "h2", "h3",
                                       "h4", "h5", "h6", "section", "article"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.hidden:
            self.parts.append(data)


def compile_html(text: str, *, doc_id: str, version: str, uri: str = "") -> dict[str, Any]:
    """Extract visible text with a whole-document citation, without completeness claims.

This is a conservative text adapter, not browser DOM or CSS layout evaluation.
The byte span cites the original markup rather than invented text offsets.
    """
    raw = text.encode("utf-8")
    tree = _tree(raw, doc_id, version, uri, "html", "text/html", [])
    parser = _HTMLText()
    parser.feed(text)
    parser.close()
    content = "\n".join(line.strip() for line in "".join(parser.parts).splitlines()
                        if line.strip())
    if content:
        tree["sections"].append({"path": "document", "text": content,
                                 "byte_start": 0, "byte_end": len(raw),
                                 "line_start": 1, "line_end": len(text.splitlines())})
    return tree


def compile_file(path: str | Path, *, format: str, doc_id: str, version: str,
                 uri: str = "") -> dict[str, Any]:
    """Read a bounded local UTF-8 source; preserve CRLF for citation offsets."""
    if format not in {"markdown", "csv", "html", "docx", "pdf"}:
        raise ValueError(f"unsupported document format: {format}")
    with Path(path).open("rb") as source:
        raw = source.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError(f"document exceeds the {MAX_BYTES} byte limit")
    if format == "docx":
        return compile_docx(raw, doc_id=doc_id, version=version, uri=uri)
    if format == "pdf":
        return compile_pdf(raw, doc_id=doc_id, version=version, uri=uri)
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("document must be UTF-8") from exc
    compiler = {"markdown": compile_markdown, "csv": compile_csv, "html": compile_html}[format]
    return compiler(text, doc_id=doc_id, version=version, uri=uri)


def compile_docx(raw: bytes, *, doc_id: str, version: str, uri: str = "") -> dict[str, Any]:
    """Read OOXML body paragraphs and table cells; never extract files or follow links.

Anchors name the XML body child, not visual pages. Headers, footers, tracked
deletions, embedded objects and layout interpretation are outside this adapter.
    """
    tree = _tree(raw, doc_id, version, uri, "docx",
                 "application/vnd.openxmlformats-officedocument.wordprocessingml.document", [])
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            if sum(info.file_size for info in archive.infolist()) > MAX_BYTES:
                raise ValueError("DOCX expanded contents exceed the document byte limit")
            if archive.namelist().count("word/document.xml") != 1:
                raise ValueError("DOCX needs exactly one word/document.xml")
            xml = archive.read("word/document.xml")
        # Reject UTF-16/32 rather than let declaration checks inspect a different
        # encoding from the XML parser. OOXML UTF-8 is this adapter's contract.
        if b"\x00" in xml:
            raise ValueError("DOCX document XML must be UTF-8")
        if b"<!DOCTYPE" in xml.upper() or b"<!ENTITY" in xml.upper():
            raise ValueError("DOCX entity declarations are not supported")
        root = ET.fromstring(xml)
    except (zipfile.BadZipFile, KeyError, ET.ParseError) as exc:
        raise ValueError(f"invalid DOCX: {exc}") from exc
    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    body = root.find("w:body", ns)
    if body is None:
        raise ValueError("DOCX has no document body")

    def text_of(element: ET.Element) -> str:
        return "".join(e.text or "" for e in element.iter(f"{{{ns['w']}}}t"))

    for number, element in enumerate(body, 1):
        if element.tag == f"{{{ns['w']}}}p":
            content = text_of(element)
        elif element.tag == f"{{{ns['w']}}}tbl":
            rows = [[text_of(cell) for cell in row.findall("w:tc", ns)]
                    for row in element.findall("w:tr", ns)]
            content = json.dumps({"rows": rows}, ensure_ascii=False)
        else:
            continue
        if content.strip():
            tree["sections"].append({"path": f"body/{number}", "text": content})
    return tree


def compile_pdf(raw: bytes, *, doc_id: str, version: str, uri: str = "") -> dict[str, Any]:
    """Optional pypdf text extraction with original page anchors; no OCR or table inference.

Refuse textless pages instead of silently withdrawing unreadable source facts.
Run untrusted binary parsers in a resource-limited worker in production: input
and output bounds do not bound the parser's intermediate allocations.
    """
    tree = _tree(raw, doc_id, version, uri, "pdf", "application/pdf", [])
    try:
        from pypdf import PdfReader, __version__ as pdf_version
    except ImportError as exc:
        raise ValueError('PDF support requires pip install ".[documents]"') from exc
    try:
        tree["parser_version"] = f"pdf-1/pypdf-{pdf_version}"
        reader = PdfReader(io.BytesIO(raw), strict=True)
        if reader.is_encrypted:
            raise ValueError("encrypted PDF is not supported; supply an approved decrypted source")
        if not reader.pages or len(reader.pages) > 2000:
            raise ValueError("PDF must have between 1 and 2000 pages")
        size = 0
        for number, page in enumerate(reader.pages, 1):
            content = page.extract_text() or ""
            if not content.strip():
                raise ValueError(f"PDF page {number} has no extractable text; OCR review required")
            size += len(content.encode("utf-8"))
            if size > MAX_BYTES:
                raise ValueError("PDF extracted text exceeds the document byte limit")
            tree["sections"].append({"path": f"page/{number}", "text": content})
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(f"PDF extraction failed: {type(exc).__name__}") from exc
    return tree
