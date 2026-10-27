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
