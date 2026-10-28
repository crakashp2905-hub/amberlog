"""Local Markdown compiler for the existing governed document import boundary.

Compilation never approves content or writes memories. The returned tree goes
through docsource.import_document, including its screening and review workflow.
"""
from __future__ import annotations

__stability__ = "experimental"

import hashlib
import re
from typing import Any

PARSER_VERSION = "markdown-2"
"""Bumped when the same text would compile to different sections."""
MAX_BYTES = 20_000_000


def compile_markdown(text: str, *, doc_id: str, version: str,
                     uri: str = "") -> dict[str, Any]:
    """Compile ATX (`# Title`) and setext (`Title` over `===`/`---`) headings into section anchors.

An anchor is the heading path; duplicate sibling headings get occurrence
suffixes. So renaming a heading, moving it under another parent, or inserting
a same-named sibling before it changes its anchor; inserting a differently
named heading that does not become its parent does not. `import_document`
matches sections by their text before their anchor, so a section whose text
is unchanged keeps its memory whichever of these happened. A heading with no
text of its own (only subsections) produces no section. Fenced code is
preserved literally. Tables remain verbatim Markdown, not inferred entities.
Each section records `line_start`/`line_end` (1-based, inclusive, heading
line first, trailing blank lines excluded) and `byte_start`/`byte_end` (UTF-8
offsets into the source, end exclusive), so a citation resolves to the exact
span. CRLF and LF sources compile to the same sections; offsets are of the
bytes actually given. No network, model, approval, or completeness claim is
involved.
    """
    if not doc_id.strip() or not version.strip():
        raise ValueError("doc_id and version must be non-empty")
    raw = text.encode("utf-8")
    if len(raw) > MAX_BYTES:
        raise ValueError(f"document is {len(raw)} bytes; the limit is {MAX_BYTES}")
    sections: list[dict[str, Any]] = []
    stack: list[tuple[int, str]] = []
    counts: dict[str, int] = {}
    # Body lines as (line number, text, byte offset of its start, byte offset after it).
    body: list[tuple[int, str, int, int]] = []
    title, anchor = "", "preamble"
    head: tuple[int, int] | None = None   # (line, byte offset) of the current heading
    fence = ""
    fence_length = 0

    def flush() -> None:
        content = "\n".join(line for _, line, _, _ in body).strip()
        if not content:
            return
        kept = [b for b in body if b[1].strip()]
        first_line, first_byte = head if head else (kept[0][0], kept[0][2])
        sections.append({"path": anchor, "title": title, "text": content,
                         "line_start": first_line, "line_end": kept[-1][0],
                         "byte_start": first_byte, "byte_end": kept[-1][3]})

    offset = 0
    for number, full in enumerate(text.splitlines(keepends=True), 1):
        line = full.rstrip("\r\n")
        span = (number, line, offset, offset + len(line.encode("utf-8")))
        offset += len(full.encode("utf-8"))
        marker = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", line)
        if marker:
            run, tail = marker.groups()
            if not fence:
                fence, fence_length = run[0], len(run)
            elif run[0] == fence and len(run) >= fence_length and not tail.strip():
                fence = ""
            body.append(span)
            continue
        atx = None if fence else re.match(r"^ {0,3}(#{1,6})\s+(.+?)\s*$", line)
        underline = None if fence or atx else re.match(r"^ {0,3}(=+|-+)\s*$", line)
        if atx:
            level, heading_text = len(atx[1]), re.sub(r"\s+#+\s*$", "", atx[2])
            heading_at = (number, span[2])
        elif (underline and body and body[-1][1].strip()
              and not re.match(r"^\s*([|>*+-]|\d+[.)]\s)", body[-1][1])):
            # Setext: the paragraph line above is the heading (one-line titles only).
            above = body.pop()
            level, heading_text = (1 if underline[1][0] == "=" else 2), above[1]
            heading_at = (above[0], above[2])
        else:
            body.append(span)
            continue
        flush()
        body = []
        head = heading_at
        title = heading_text.strip()
        while stack and stack[-1][0] >= level:
            stack.pop()
        slug = re.sub(r"[^\w-]+", "-", title.lower()).strip("-") or "section"
        # Length prefix makes title-derived anchors unambiguous, including
        # literal '-2' headings and repeated heading names.
        base = "/".join([p for _, p in stack] + [f"{len(slug)}:{slug}"])
        counts[base] = counts.get(base, 0) + 1
        component = f"{len(slug)}:{slug}:{counts[base]}"
        stack.append((level, component))
        anchor = "/".join(p for _, p in stack)
    flush()
    return {"doc_id": doc_id, "version": version, "uri": uri,
            "source_sha256": hashlib.sha256(raw).hexdigest(),
            "format": "markdown", "mime": "text/markdown", "parser_version": PARSER_VERSION,
            "sections": sections}


def _tree(doc_id: str, version: str, uri: str, raw: bytes, fmt: str, mime: str,
          sections: list[dict[str, Any]]) -> dict[str, Any]:
    if not doc_id.strip() or not version.strip():
        raise ValueError("doc_id and version must be non-empty")
    return {"doc_id": doc_id, "version": version, "uri": uri,
            "source_sha256": hashlib.sha256(raw).hexdigest(), "format": fmt, "mime": mime,
            "parser_version": f"{fmt}-1", "sections": sections}


def compile_html(text: str, *, doc_id: str, version: str, uri: str = "") -> dict[str, Any]:
    """Sections from `<h1>`-`<h6>`, text from everything else that is shown.

    Scripts, styles, templates and navigation are dropped; table cells keep
    their row order, joined by " | ". Line numbers locate each section in the
    source. Nothing is fetched, and no markup is executed.
    """
    from html.parser import HTMLParser

    raw = text.encode("utf-8")
    if len(raw) > MAX_BYTES:
        raise ValueError(f"document is {len(raw)} bytes; the limit is {MAX_BYTES}")
    sections: list[dict[str, Any]] = []
    stack: list[tuple[int, str]] = []
    counts: dict[str, int] = {}

    class P(HTMLParser):
        def __init__(self) -> None:
            super().__init__(convert_charrefs=True)
            self.skip = 0
            self.heading: int | None = None
            self.title_buf: list[str] = []
            self.body: list[str] = []
            self.cell = False
            self.anchor, self.title, self.start = "preamble", "", 1
            self.last_line = 1

        def flush(self) -> None:
            content = re.sub(r"[ \t]+", " ", "".join(self.body)).strip()
            content = re.sub(r"\n\s*\n+", "\n", content)
            if content:
                sections.append({"path": self.anchor, "title": self.title, "text": content,
                                 "line_start": self.start, "line_end": self.last_line})
            self.body = []

        def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
            if tag in ("script", "style", "template", "nav", "noscript"):
                self.skip += 1
            elif not self.skip and re.fullmatch(r"h[1-6]", tag):
                self.flush()
                self.heading, self.title_buf, self.start = int(tag[1]), [], self.getpos()[0]
            elif tag in ("p", "div", "li", "tr", "br", "section", "article"):
                self.body.append("\n")
            elif tag in ("td", "th"):
                self.body.append(" | " if self.cell else "")
                self.cell = True

        def handle_endtag(self, tag: str) -> None:
            if tag in ("script", "style", "template", "nav", "noscript") and self.skip:
                self.skip -= 1
            elif self.heading is not None and tag == f"h{self.heading}":
                title = " ".join("".join(self.title_buf).split())
                level, self.heading = self.heading, None
                while stack and stack[-1][0] >= level:
                    stack.pop()
                slug = re.sub(r"[^\w-]+", "-", title.lower()).strip("-") or "section"
                base = "/".join([p for _, p in stack] + [f"{len(slug)}:{slug}"])
                counts[base] = counts.get(base, 0) + 1
                stack.append((level, f"{len(slug)}:{slug}:{counts[base]}"))
                self.anchor, self.title = "/".join(p for _, p in stack), title
            elif tag == "tr":
                self.cell = False

        def handle_data(self, data: str) -> None:
            if self.skip:
                return
            (self.title_buf if self.heading is not None else self.body).append(data)
            if data.strip():
                self.last_line = self.getpos()[0] + data.count("\n")

    parser = P()
    parser.feed(text)
    parser.close()
    parser.flush()
    return _tree(doc_id, version, uri, raw, "html", "text/html", sections)


def compile_csv(text: str, *, doc_id: str, version: str, uri: str = "",
                key: str | None = None) -> dict[str, Any]:
    """One section per row: cells kept verbatim as `column: value`, row provenance by line.

    `key` names the column that identifies a row, so a re-import matches rows
    by key (a moved row is the same section); without it the path is the row
    number. Values are never converted: "0012", "-3" and "1e3" stay text, so
    no sign, leading zero, date or unit is lost.
    """
    import csv
    import io

    raw = text.encode("utf-8")
    if len(raw) > MAX_BYTES:
        raise ValueError(f"document is {len(raw)} bytes; the limit is {MAX_BYTES}")
    reader = csv.reader(io.StringIO(text))
    try:
        header = next(reader)
    except StopIteration:
        return _tree(doc_id, version, uri, raw, "csv", "text/csv", [])
    if key is not None and key not in header:
        raise ValueError(f"key column {key!r} is not in the header")
    sections: list[dict[str, Any]] = []
    seen: set[str] = set()
    for number, row in enumerate(reader, 2):
        if not any(cell.strip() for cell in row):
            continue
        cells = dict(zip(header, row))
        path = f"row:{cells[key]}" if key else f"row:{number}"
        if path in seen:
            raise ValueError(f"duplicate row {path!r} at line {number}")
        seen.add(path)
        sections.append({"path": path, "title": "", "line_start": number, "line_end": number,
                         "text": "; ".join(f"{h}: {v}" for h, v in zip(header, row)),
                         "cells": cells})
    return _tree(doc_id, version, uri, raw, "csv", "text/csv", sections)


def compile_docx(data: bytes, *, doc_id: str, version: str, uri: str = "") -> dict[str, Any]:
    """Sections from a .docx's Heading styles; paragraphs and table rows as text.

    Read with the standard library (`zipfile`, `xml.etree`): no macro, field or
    embedded object is evaluated. Paragraph indexes locate each section.
    Archives over the size limit, or that expand past it, are refused.
    """
    import io
    import zipfile
    from xml.etree import ElementTree as ET

    if len(data) > MAX_BYTES:
        raise ValueError(f"document is {len(data)} bytes; the limit is {MAX_BYTES}")
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
        info = archive.getinfo("word/document.xml")
    except (zipfile.BadZipFile, KeyError) as exc:
        raise ValueError("not a .docx file (no word/document.xml)") from exc
    if info.file_size > MAX_BYTES * 5:
        raise ValueError("document.xml expands past the size limit")
    w = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    root = ET.fromstring(archive.read(info))
    body = root.find(f"{w}body")
    sections: list[dict[str, Any]] = []
    stack: list[tuple[int, str]] = []
    counts: dict[str, int] = {}
    anchor, title, start, index = "preamble", "", 0, 0
    buf: list[str] = []

    def flush(end: int) -> None:
        content = "\n".join(b for b in buf if b.strip()).strip()
        if content:
            sections.append({"path": anchor, "title": title, "text": content,
                             "line_start": start, "line_end": end})

    for block in (list(body) if body is not None else []):
        index += 1
        if block.tag == f"{w}tbl":
            for tr in block.iter(f"{w}tr"):
                buf.append(" | ".join("".join(t.text or "" for t in tc.iter(f"{w}t"))
                                      for tc in tr.iter(f"{w}tc")))
            continue
        if block.tag != f"{w}p":
            continue
        text_run = "".join(t.text or "" for t in block.iter(f"{w}t"))
        style = block.find(f"{w}pPr/{w}pStyle")
        level_m = re.fullmatch(r"(?i)heading\s*([1-9])", (style.get(f"{w}val") or "") if style is not None else "")
        if level_m and text_run.strip():
            flush(index - 1)
            buf = []
            level = int(level_m[1])
            title = " ".join(text_run.split())
            while stack and stack[-1][0] >= level:
                stack.pop()
            slug = re.sub(r"[^\w-]+", "-", title.lower()).strip("-") or "section"
            base = "/".join([p for _, p in stack] + [f"{len(slug)}:{slug}"])
            counts[base] = counts.get(base, 0) + 1
            stack.append((level, f"{len(slug)}:{slug}:{counts[base]}"))
            anchor, start = "/".join(p for _, p in stack), index
        else:
            buf.append(text_run)
    flush(index)
    return _tree(doc_id, version, uri, data, "docx",
                 "application/vnd.openxmlformats-officedocument.wordprocessingml.document", sections)
