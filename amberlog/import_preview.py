"""Operator-only structural document preview and atomic batch import.

Plans disclose metadata in one tenant, never source content. Predicted impact
is an upper bound: independent support may prevent actual invalidation.
"""
from __future__ import annotations

__stability__ = "experimental"

from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any, Mapping, Sequence

from .docsource import DocumentReport, _sections, _standing, import_document
from .events import EventType
from .identity import DEFAULT_TENANT

if TYPE_CHECKING:
    from .fabric import Amberlog

MAX_BYTES = 20_000_000


def read_batch(path: str | Path) -> list[dict[str, Any]]:
    with Path(path).open("rb") as source:
        raw = source.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError("batch manifest exceeds the byte limit")
    data = json.loads(raw.decode("utf-8"))
    if not isinstance(data, list) or any(not isinstance(t, dict) for t in data):
        raise ValueError("a batch manifest must be a list of compiled document objects")
    return data


def _validate(trees: Sequence[Mapping[str, Any]]) -> str:
    if not 1 <= len(trees) <= 100:
        raise ValueError("a batch requires 1 to 100 documents")
    seen = set()
    total = 0
    for tree in trees:
        sections = _sections(tree)
        total += len(sections)
        doc_id = str(tree["doc_id"])
        if not doc_id.strip() or not str(tree["version"]).strip() or doc_id in seen:
            raise ValueError("batch document IDs/versions must be non-empty and IDs unique")
        seen.add(doc_id)
    if total > 10_000:
        raise ValueError("batch exceeds the 10000-section limit")
    payload = json.dumps(list(trees), sort_keys=True, ensure_ascii=False).encode("utf-8")
    if len(payload) > MAX_BYTES:
        raise ValueError("compiled batch exceeds the byte limit")
    return hashlib.sha256(payload).hexdigest()


@dataclass
class ImportPlan:
    head_seq: int
    plan_sha256: str
    tenant_id: str
    documents: list[dict[str, Any]]
    potential_dependents: list[str]
    potential_action_sequences: list[int]
    warning: str = "structural preflight only; ingest screening/approval still applies; dependency impact is an upper bound"

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


def plan_batch(fabric: "Amberlog", trees: Sequence[Mapping[str, Any]], *,
               tenant_id: str = DEFAULT_TENANT) -> ImportPlan:
    trees = json.loads(json.dumps(list(trees), ensure_ascii=False, allow_nan=False))
    digest = _validate(trees)
    if not tenant_id:
        raise ValueError("tenant_id must be explicit")
    documents = []
    withdrawn: set[str] = set()
    with fabric._transaction():
        for tree in trees:
            sections = _sections(tree)
            standing = _standing(fabric, str(tree["doc_id"]), tenant_id)
            kept: set[str] = set()
            added = []
            for path, (_, content_digest, _) in sections.items():
                same = [m for m in standing if m.id not in kept
                        and m.context["source"].get("sha256") == content_digest]
                if same:
                    match = next((m for m in same if m.context["source"].get("path") == path), same[0])
                    kept.add(match.id)
                else:
                    added.append(path)
            removed = {m.id for m in standing} - kept
            withdrawn.update(removed)
            documents.append({"doc_id": str(tree["doc_id"]), "version": str(tree["version"]),
                              "added_paths": added, "unchanged_ids": sorted(kept),
                              "withdrawn_ids": sorted(removed)})
        affected = set(withdrawn)
        while True:
            extra = {m.id for m in fabric.state.memories.values() if m.tenant_id == tenant_id
                     and any(pid in affected for pid, _ in m.provenance.parents)} - affected
            if not extra:
                break
            affected.update(extra)
        actions = [e.seq for e in fabric.log.read_types([EventType.ACTION_GATED])
                   if e.seq is not None and (e.payload.get("tenant_id") or DEFAULT_TENANT) == tenant_id
                   and any(ref[0] in affected for ref in e.payload.get("evidence", []))]
        return ImportPlan(fabric.log.head_seq, digest, tenant_id, documents,
                          sorted(affected - withdrawn), actions)


def apply_batch(fabric: "Amberlog", trees: Sequence[Mapping[str, Any]], *,
                tenant_id: str = DEFAULT_TENANT, activate: bool = False,
                expected_head: int | None = None, expected_plan: str | None = None) -> list[DocumentReport]:
    """Validate before writing; one existing log transaction commits all or none.

    Retrying a completed batch is idempotent through existing source digests.
    A stale reviewed head or changed input digest refuses before any write.
    """
    trees = json.loads(json.dumps(list(trees), ensure_ascii=False, allow_nan=False))
    digest = _validate(trees)
    if not tenant_id:
        raise ValueError("tenant_id must be explicit")
    if expected_head is not None and (type(expected_head) is not int or expected_head < 0):
        raise ValueError("expected_head must be a non-negative integer")
    if expected_plan is not None and digest != expected_plan:
        raise ValueError("batch content differs from the reviewed plan; preview again")
    with fabric._transaction():
        if expected_head is not None and fabric.log.head_seq != expected_head:
            raise ValueError("store changed since preview; preview again")
        return [import_document(fabric, tree, activate=activate, tenant_id=tenant_id) for tree in trees]
