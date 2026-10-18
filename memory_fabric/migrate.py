"""Bring memories in from another store, as reviewable candidates.

The gradual migration path: export from the store you have, import here, and
review what arrives -- nothing imported is trusted on arrival. Each record goes
through the ordinary write path, so it is screened for secrets and injection,
recognised if it duplicates something already held, and lands as a private
**candidate** with `imported` provenance and its source recorded. It reaches
retrieval only when someone approves it (`review`), exactly like an agent's
own write.

Accepted shapes, one record per JSON object (a JSON list, or JSONL):

| shape | content field | author field |
|---|---|---|
| Mem0 export | `memory` | `user_id` / `agent_id` |
| LangChain `Document` | `page_content` | `metadata.agent_id` |
| plain | `content` or `text` | `agent_id` / `author` |

Anything else is reported as skipped with its line, not guessed at.
"""

from __future__ import annotations

__stability__ = "beta"

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterable, Iterator

from .model import LifecycleState, ProvenanceMethod

if TYPE_CHECKING:  # pragma: no cover
    from .fabric import MemoryFabric

CONTENT_FIELDS = ("memory", "page_content", "content", "text")
AUTHOR_FIELDS = ("agent_id", "user_id", "author")


@dataclass
class ImportReport:
    source: str
    imported: list[str] = field(default_factory=list)
    quarantined: list[str] = field(default_factory=list)
    """Imported, and quarantined on the way in by an ingest screen."""
    duplicates: list[str] = field(default_factory=list)
    """Imported, and recognised as a copy of something already held."""
    skipped: list[str] = field(default_factory=list)
    """`line N: why`, for records with no recognisable content."""

    def to_json(self) -> dict[str, Any]:
        return dict(self.__dict__)


def read_records(path: str | Path) -> Iterator[tuple[int, Any]]:
    """`(line or index, record)` from a JSON list or a JSONL file."""
    text = Path(path).read_text(encoding="utf-8")
    stripped = text.lstrip()
    if stripped.startswith("["):
        for index, record in enumerate(json.loads(text), start=1):
            yield index, record
        return
    for number, line in enumerate(text.splitlines(), start=1):
        if line.strip():
            try:
                yield number, json.loads(line)
            except ValueError:
                yield number, None


def _content(record: dict[str, Any]) -> str | None:
    for key in CONTENT_FIELDS:
        value = record.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _author(record: dict[str, Any], default: str) -> str:
    raw = record.get("metadata")
    metadata: dict[str, Any] = raw if isinstance(raw, dict) else {}
    for source in (record, metadata):
        for key in AUTHOR_FIELDS:
            value = source.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return default


def import_records(fabric: "MemoryFabric", records: Iterable[tuple[int, Any]], source: str,
                   default_agent: str, tenant_id: str | None = None) -> ImportReport:
    report = ImportReport(source=source)
    for number, record in records:
        if not isinstance(record, dict):
            report.skipped.append(f"line {number}: not a JSON object")
            continue
        content = _content(record)
        if content is None:
            report.skipped.append(f"line {number}: no {' / '.join(CONTENT_FIELDS)} field")
            continue
        context = {"imported_from": source}
        raw = record.get("metadata")
        metadata: dict[str, Any] = raw if isinstance(raw, dict) else {}
        original = record.get("id", metadata.get("id"))
        if original is not None:
            context["source_id"] = str(original)
        kwargs: dict[str, Any] = {}
        if tenant_id is not None:
            kwargs["tenant_id"] = tenant_id
        before = fabric.state.suppressed_duplicates
        memory_id = fabric.remember(_author(record, default_agent), content, context=context,
                                    method=ProvenanceMethod.IMPORTED, auto_activate=False,
                                    **kwargs)
        memory = fabric.state.memories[memory_id]
        report.imported.append(memory_id)
        if memory.lifecycle_state is LifecycleState.QUARANTINED:
            report.quarantined.append(memory_id)
        if memory_id in fabric.state.copy_of or fabric.state.suppressed_duplicates > before:
            report.duplicates.append(memory_id)
    return report
