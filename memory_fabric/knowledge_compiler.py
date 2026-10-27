"""Local Markdown compiler for the existing governed document import boundary.

Compilation never approves content or writes memories. The returned tree goes
through docsource.import_document, including its screening and review workflow.
"""
from __future__ import annotations

__stability__ = "experimental"

import hashlib
import re
from typing import Any


def compile_markdown(text: str, *, doc_id: str, version: str,
                     uri: str = "") -> dict[str, Any]:
    """Compile ATX headings into deterministic hierarchical section anchors.

Duplicate sibling headings have occurrence suffixes. Renaming a heading changes
its anchor; inserting an unrelated heading does not. Fenced code is preserved
literally. Tables remain verbatim Markdown, not inferred entities. No network,
model, approval, or completeness claim is involved.
    """
    if not doc_id.strip() or not version.strip():
        raise ValueError("doc_id and version must be non-empty")
    sections: list[dict[str, Any]] = []
    stack: list[tuple[int, str]] = []
    counts: dict[str, int] = {}
    body: list[str] = []
    title, anchor, start = "", "preamble", 1
    fence = ""
    fence_length = 0

    def flush() -> None:
        content = "\n".join(body).strip()
        if content or title:
            sections.append({"path": anchor, "title": title, "text": content,
                             "line_start": start})

    for number, line in enumerate(text.splitlines(), 1):
        marker = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", line)
        if marker:
            run, tail = marker.groups()
            if not fence:
                fence, fence_length = run[0], len(run)
            elif run[0] == fence and len(run) >= fence_length and not tail.strip():
                fence = ""
            body.append(line)
            continue
        heading = None if fence else re.match(r"^ {0,3}(#{1,6})\s+(.+?)\s*$", line)
        if not heading:
            body.append(line)
            continue
        flush()
        body = []
        level = len(heading[1])
        title = re.sub(r"\s+#+\s*$", "", heading[2]).strip()
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
        start = number
    flush()
    return {"doc_id": doc_id, "version": version, "uri": uri,
            "source_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "format": "markdown-atx-v1", "sections": sections}
