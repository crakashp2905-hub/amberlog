"""Experimental exhaustive selection with enforced, budgeted fallback reads.

Certificates attest bounded query coverage, conditional on writer fields and
the supplied evaluator. They are not evidence certificates or action authority.
"""
from __future__ import annotations

__stability__ = "experimental"

from dataclasses import dataclass, field
import hashlib
import json
from typing import TYPE_CHECKING, Any, Callable, Iterable, Mapping

from .navigation import _visible
from .typed_query import select
from .identity import DEFAULT_TENANT

if TYPE_CHECKING:
    from .fabric import Amberlog
    from .model import Memory


@dataclass
class Coverage:
    matches: list[str]
    nonmatches: list[str]
    unknown: list[str]
    considered: int
    reads: int = 0
    fallback_matches: list[str] = field(default_factory=list)
    fallback_nonmatches: list[str] = field(default_factory=list)
    changed: bool = False
    evaluator: str | None = None
    where: dict[str, Any] = field(default_factory=dict)
    tenant_id: str = ""
    corpus_sha256: str = ""

    @property
    def ids(self) -> list[str]:
        return self.matches + self.fallback_matches

    @property
    def complete(self) -> bool:
        return not self.unknown and not self.changed

    def certificate(self) -> dict[str, Any]:
        return {"schema": "evidence-coverage/1", "considered": self.considered,
                "where": self.where, "tenant_id": self.tenant_id, "corpus_sha256": self.corpus_sha256,
                "typed_matches": len(self.matches), "typed_nonmatches": len(self.nonmatches),
                "fallback_matches": len(self.fallback_matches),
                "fallback_nonmatches": len(self.fallback_nonmatches),
                "unknown": len(self.unknown), "reads": self.reads,
                "complete": self.complete, "snapshot_changed": self.changed,
                "evaluator": self.evaluator, "scope": "eligible records within the requested IDs at query time",
                "assumption": "writer-typed fields and fallback evaluator judgments are correct",
                "authority": "coverage only; never authorizes an action"}


def classify(fabric: "Amberlog", agent_id: str, where: Mapping[str, Any], *,
             tenant_id: str | None = None, within: Iterable[str] | None = None) -> Coverage:
    """Partition every eligible scoped ID: typed match, definite nonmatch, unknown."""
    # Hold the existing transaction fence only for metadata classification,
    # never across arbitrary evaluator callbacks or the full fallback scan.
    with fabric._transaction():
        return _classify(fabric, agent_id, where, tenant_id=tenant_id, within=within)


def _classify(fabric: "Amberlog", agent_id: str, where: Mapping[str, Any], *,
              tenant_id: str | None, within: Iterable[str] | None) -> Coverage:
    allowed = frozenset(within) if within is not None else None
    tenant_id = tenant_id or DEFAULT_TENANT
    fabric.refresh()
    selection = select(fabric, agent_id, where, tenant_id=tenant_id, within=allowed)
    visible = _visible(fabric, agent_id, tenant_id)
    ids = [mid for mid in visible if mid not in fabric.state.erased
           and (allowed is None or mid in allowed)]
    included = set(ids)
    classified = set(selection.ids) | set(selection.unknown)
    result = Coverage([m for m in selection.ids if m in included],
                    [mid for mid in ids if mid not in classified],
                    [m for m in selection.unknown if m in included], len(ids))
    result.where, result.tenant_id = dict(where), tenant_id
    result.corpus_sha256 = hashlib.sha256(json.dumps(sorted(
        (mid, fabric.state.memories[mid].version) for mid in ids)).encode()).hexdigest()
    return result


def exhaustive(fabric: "Amberlog", agent_id: str, where: Mapping[str, Any], *,
               query: str, evaluate: Callable[["Memory", Mapping[str, Any]], bool | None],
               evaluator_id: str, max_reads: int, tenant_id: str | None = None,
               within: Iterable[str] | None = None) -> Coverage:
    """Read only unknowns, up to the content-read budget, through logged retrieval.

False requires a justified nonmatch; ambiguous parsing must return None.
Evaluator failures propagate (no fabricated completeness). No extracted field
is persisted or promoted. The caller supplies an operator-controlled evaluator,
not an agent's assertion of truth. Stable APIs and event schemas are unchanged.
    """
    if isinstance(max_reads, bool) or not isinstance(max_reads, int) or max_reads < 0:
        raise ValueError("max_reads must be a non-negative integer")
    if not evaluator_id.strip():
        raise ValueError("evaluator_id must be non-empty")
    allowed = tuple(within) if within is not None else None
    tenant_id = tenant_id or DEFAULT_TENANT
    coverage = classify(fabric, agent_id, where, tenant_id=tenant_id, within=allowed)
    coverage.evaluator = evaluator_id
    # Retrieve separately to recheck policy before each callback. This also
    # avoids handing the callback a batch of content revoked by its first call.
    unresolved = []
    for mid in coverage.unknown:
        if coverage.reads >= max_reads:
            unresolved.append(mid)
            continue
        result = fabric.retrieve(agent_id, query, k=1, within=[mid], tenant_id=tenant_id,
                                 min_relevance=0.0, expand_lineage=0, group_by_source_root=False)
        if not result.exposed:
            unresolved.append(mid)
            continue
        coverage.reads += 1
        answer = evaluate(result.exposed[0], where)
        if answer is not None and type(answer) is not bool:
            raise ValueError("fallback evaluator must return bool or None")
        if answer is True:
            coverage.fallback_matches.append(mid)
        elif answer is False:
            coverage.fallback_nonmatches.append(mid)
        else:
            unresolved.append(mid)
    coverage.unknown = unresolved
    with fabric._transaction():
        visible_now = set(_visible(fabric, agent_id, tenant_id)) - fabric.state.erased
        if allowed is not None:
            visible_now.intersection_update(allowed)
        after_digest = hashlib.sha256(json.dumps(sorted(
            (mid, fabric.state.memories[mid].version) for mid in visible_now)).encode()).hexdigest()
    coverage.changed = coverage.corpus_sha256 != after_digest
    # Never return IDs that ceased to be eligible during evaluation.
    coverage.matches = [m for m in coverage.matches if m in visible_now]
    coverage.fallback_matches = [m for m in coverage.fallback_matches if m in visible_now]
    return coverage
