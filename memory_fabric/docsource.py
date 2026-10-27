"""Compiled documents as provenance-tracked sources, withdrawn when the document changes.

A knowledge fabric that compiles documents into a section tree (Sarvam's, or
your own pipeline) gives agents the document as it stands. Memory Fabric adds
what happens *after*: which agent read which section, what it concluded from
it, and what must stop when the section changes.

    from memory_fabric.docsource import import_document
    report = import_document(fabric, {
        "doc_id": "sop-12", "version": "2026-10", "uri": "https://intranet/sop-12",
        "sections": [{"path": "4.2", "title": "Relief valve", "text": "Set P-14 relief to 12 bar."}],
    })

Each section becomes one memory authored by `docs:<doc_id>`, with
`context.source = {doc_id, version, path, uri, sha256}`. Importing the
document again compares sections by path:

- **unchanged** sections are left alone (same memory, no new event);
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
    from .fabric import MemoryFabric

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


def _sections(tree: Mapping[str, Any]) -> dict[str, tuple[str, str]]:
    """path -> (content, sha256), validated."""
    for key in ("doc_id", "version", "sections"):
        if key not in tree:
            raise ValueError(f"document has no {key!r}")
    out: dict[str, tuple[str, str]] = {}
    for i, s in enumerate(tree["sections"]):
        if not isinstance(s, Mapping) or not str(s.get("path", "")).strip() or not isinstance(s.get("text"), str):
            raise ValueError(f"section {i}: needs a path and text")
        path = str(s["path"])
        if path in out:
            raise ValueError(f"section path {path!r} appears twice")
        title = str(s.get("title") or "").strip()
        content = f"{title}: {s['text'].strip()}" if title else s["text"].strip()
        out[path] = (content, hashlib.sha256(content.encode()).hexdigest())
    return out


def current_sections(fabric: "MemoryFabric", doc_id: str, tenant_id: str | None = None) -> dict[str, Any]:
    """path -> the memory currently standing for that section of `doc_id`."""
    from .conflicts import author

    out: dict[str, Any] = {}
    for m in fabric.state.memories.values():
        # Only the document's own sections: a conclusion derived from one inherits its context.
        if author(m) != f"docs:{doc_id}":
            continue
        src = m.context.get("source") if isinstance(m.context, Mapping) else None
        if (isinstance(src, Mapping) and src.get("doc_id") == doc_id
                and (tenant_id is None or m.tenant_id == tenant_id)
                and (m.lifecycle_state in EXPOSABLE_STATES
                     or m.lifecycle_state is LifecycleState.CANDIDATE)):
            out[str(src.get("path"))] = m
    return out


def import_document(fabric: "MemoryFabric", tree: Mapping[str, Any], actor: str = "docs-import",
                    activate: bool = False, tenant_id: str | None = None,
                    scope: str = "team") -> DocumentReport:
    """Bring a compiled document in; withdraw what a new version changed or removed."""
    sections = _sections(tree)
    doc_id, version = str(tree["doc_id"]), str(tree["version"])
    report = DocumentReport(doc_id, version)
    # An omitted tenant means the default tenant on writes, never every tenant.
    # Otherwise an import could withdraw another tenant's same-named document.
    before = current_sections(fabric, doc_id, tenant_id or DEFAULT_TENANT)
    kwargs: dict[str, Any] = {"tenant_id": tenant_id} if tenant_id is not None else {}
    for path, (content, digest) in sections.items():
        old = before.get(path)
        if old is not None and old.context["source"].get("sha256") == digest:
            report.unchanged.append(old.id)
            continue
        source = {"doc_id": doc_id, "version": version, "path": path,
                  "uri": str(tree.get("uri") or ""), "sha256": digest}
        mid = fabric.remember(f"docs:{doc_id}", content, context={"source": source},
                              method=ProvenanceMethod.IMPORTED, auto_activate=False,
                              scope=scope, **kwargs)
        if activate and fabric.state.memories[mid].lifecycle_state is LifecycleState.CANDIDATE:
            fabric.validate(mid, actor=actor, reason=f"{doc_id} {version} §{path}")
        report.added.append(mid)
    for path, old in before.items():
        if path in sections and old.id in report.unchanged:
            continue
        why = (f"{CHANGED}: {doc_id} §{path} " +
               ("removed" if path not in sections else "revised") + f" in {version}")
        report.contested += fabric.quarantine(old.id, reason=why, actor=actor,
                                              basis=WithdrawalBasis.RETRACTED_AT_ORIGIN)
        report.withdrawn.append(old.id)
    return report
