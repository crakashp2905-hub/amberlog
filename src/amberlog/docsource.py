"""Compiled documents as provenance-tracked sources, withdrawn when the document changes.

A knowledge fabric that compiles documents into a section tree (Sarvam's, or
your own pipeline) gives agents the document as it stands. Amberlog adds
what happens *after*: which agent read which section, what it concluded from
it, and what must stop when the section changes.

    from amberlog.docsource import import_document
    report = import_document(fabric, {
        "doc_id": "sop-12", "version": "2026-10", "uri": "https://intranet/sop-12",
        "sections": [{"path": "4.2", "title": "Relief valve", "text": "Set P-14 relief to 12 bar."}],
    })

Each section becomes one memory authored by `docs:<doc_id>`, with
`context.source = {doc_id, version, path, uri, sha256}`. Importing the
document again compares sections by their text:

- **unchanged** sections are left alone (same memory, no new event), even if
  they moved to a new path;
- **changed** sections get a new memory, and the old one is withdrawn with
  basis `retracted_at_origin` and reason "source document changed";
- **removed** sections are withdrawn the same way.

Withdrawal is the ordinary `quarantine`, so it propagates: conclusions derived
from the old section are contested, and an action whose evidence certificate
cites it is refused by the action gate (`evidence_withdrawn`). Sections land as
candidates unless `activate=True`, which the owner of the document sets when
the document itself is the authority.
"""

from __future__ import annotations

__stability__ = "experimental"

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Mapping

from .model import EXPOSABLE_STATES, LifecycleState, ProvenanceMethod, WithdrawalBasis
from .identity import DEFAULT_TENANT

if TYPE_CHECKING:  # pragma: no cover
    from .fabric import Amberlog

CHANGED = "source document changed"


@dataclass
class DocumentReport:
    doc_id: str
    version: str
    added: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    withdrawn: list[str] = field(default_factory=list)
    contested: list[str] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return {"doc_id": self.doc_id, "version": self.version, "added": self.added,
                "unchanged": self.unchanged, "withdrawn": self.withdrawn,
                "contested": self.contested}


def read_document(path: str | Path) -> dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("a document is one JSON object with doc_id, version and sections")
    return data


SPAN_FIELDS = ("line_start", "line_end", "byte_start", "byte_end")
TREE_FIELDS = ("format", "mime", "parser_version", "source_sha256")


def _sections(tree: Mapping[str, Any]) -> dict[str, tuple[str, str, dict[str, Any]]]:
    """path -> (content, sha256, span fields the section states), validated."""
    for key in ("doc_id", "version", "sections"):
        if key not in tree:
            raise ValueError(f"document has no {key!r}")
    out: dict[str, tuple[str, str, dict[str, Any]]] = {}
    for i, s in enumerate(tree["sections"]):
        if not isinstance(s, Mapping) or not str(s.get("path", "")).strip() or not isinstance(s.get("text"), str):
            raise ValueError(f"section {i}: needs a path and text")
        path = str(s["path"])
        if path in out:
            raise ValueError(f"section path {path!r} appears twice")
        title = str(s.get("title") or "").strip()
        content = f"{title}: {s['text'].strip()}" if title else s["text"].strip()
        span = {k: s[k] for k in SPAN_FIELDS if isinstance(s.get(k), int)}
        out[path] = (content, hashlib.sha256(content.encode()).hexdigest(), span)
    return out


def _standing(fabric: "Amberlog", doc_id: str, tenant_id: str | None) -> list[Any]:
    """Every memory currently standing for a section of `doc_id`, oldest first."""
    from .conflicts import author

    out = []
    for m in fabric.state.memories.values():
        # Only the document's own sections: a conclusion derived from one inherits its context.
        if author(m) != f"docs:{doc_id}":
            continue
        src = m.context.get("source") if isinstance(m.context, Mapping) else None
        if (isinstance(src, Mapping) and src.get("doc_id") == doc_id
                and (tenant_id is None or m.tenant_id == tenant_id)
                and (m.lifecycle_state in EXPOSABLE_STATES
                     or m.lifecycle_state is LifecycleState.CANDIDATE)):
            out.append(m)
    return sorted(out, key=lambda m: m.created_at)


def current_sections(fabric: "Amberlog", doc_id: str, tenant_id: str | None = None) -> dict[str, Any]:
    """path -> the memory standing for that section of `doc_id`.

    The path is the one recorded when the memory was written: a section that
    later moved without changing keeps its memory and its original path.
    """
    return {str(m.context["source"].get("path")): m for m in _standing(fabric, doc_id, tenant_id)}


def import_document(fabric: "Amberlog", tree: Mapping[str, Any], actor: str = "docs-import",
                    activate: bool = False, tenant_id: str | None = None,
                    scope: str = "team") -> DocumentReport:
    """Bring a compiled document in; withdraw what a new version changed or removed."""
    sections = _sections(tree)
    doc_id, version = str(tree["doc_id"]), str(tree["version"])
    report = DocumentReport(doc_id, version)
    # An omitted tenant means the default tenant on writes, never every tenant.
    # Otherwise an import could withdraw another tenant's same-named document.
    standing = _standing(fabric, doc_id, tenant_id or DEFAULT_TENANT)
    kwargs: dict[str, Any] = {"tenant_id": tenant_id} if tenant_id is not None else {}
    # Match by content first: a section whose text is unchanged keeps its
    # memory even if its path moved (renumbered duplicate heading, new parent),
    # so a harmless edit elsewhere never withdraws it or contests what rests on it.
    by_digest: dict[str, list[Any]] = {}
    for m in standing:
        by_digest.setdefault(m.context["source"].get("sha256"), []).append(m)
    kept: set[str] = set()
    about = {k: str(tree[k]) for k in TREE_FIELDS if tree.get(k)}
    for path, (content, digest, span) in sections.items():
        same = [m for m in by_digest.get(digest, []) if m.id not in kept]
        if same:
            match = next((m for m in same if m.context["source"].get("path") == path), same[0])
            kept.add(match.id)
            report.unchanged.append(match.id)
            continue
        source = {"doc_id": doc_id, "version": version, "path": path,
                  "uri": str(tree.get("uri") or ""), "sha256": digest, **about, **span}
        mid = fabric.remember(f"docs:{doc_id}", content, context={"source": source},
                              method=ProvenanceMethod.IMPORTED, auto_activate=False,
                              scope=scope, **kwargs)
        if activate and fabric.state.memories[mid].lifecycle_state is LifecycleState.CANDIDATE:
            fabric.validate(mid, actor=actor, reason=f"{doc_id} {version} §{path}")
        report.added.append(mid)
    for old in standing:
        if old.id in kept:
            continue
        path = str(old.context["source"].get("path"))
        why = (f"{CHANGED}: {doc_id} §{path} " +
               ("revised" if path in sections else "removed") + f" in {version}")
        report.contested += fabric.quarantine(old.id, reason=why, actor=actor,
                                              basis=WithdrawalBasis.RETRACTED_AT_ORIGIN)
        report.withdrawn.append(old.id)
    return report
