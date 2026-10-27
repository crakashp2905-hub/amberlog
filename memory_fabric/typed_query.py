"""Exhaustive typed queries over what a reader may see, with a statement of their own completeness.

Search answers "what is most like this?" and stops at k. Some questions are
"which of them all?": every open item of a kind, every record with a field in
a range. Top-k cannot answer those, because nothing tells it when it has
found them all. This module filters the `structured` fields memories were
written with:

    from memory_fabric.typed_query import select
    sel = select(fabric, "agent-a", {"kind": "valve", "status": "open", "pressure": {"$gte": 10}})
    sel.ids            # every visible memory whose typed fields match
    sel.complete       # False if some visible memory has no typed fields to check
    sel.certificate()  # what was considered, what could not be

Three rules:

- **Same visibility as retrieval.** The candidate set is the reader's eligible
  set (tenancy, scope, lifecycle, hostile-source withholding), so a withdrawn
  memory drops out of every answer the moment it is withdrawn, and nothing
  derived from it survives a re-query.
- **Ids, not content.** A selection exposes nothing and logs nothing; reading
  the memories is a `retrieve(within=sel.ids)`, decided and logged like any
  recall.
- **Unknown is not no.** A visible memory without the queried fields is
  *unknown*, not a non-match. The certificate counts them, so an answer is
  only called complete when every visible memory could be checked.

Fields come from the writer (`remember(..., structured={...})`); nothing here
extracts or invents them. Operators: equality, `$ne`, `$in`, `$nin`, `$gt`,
`$gte`, `$lt`, `$lte`, `$exists`. `count`, `distinct`, `group_by` and `join`
build on `select`.
"""

from __future__ import annotations

__stability__ = "experimental"

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Iterable, Mapping

if TYPE_CHECKING:  # pragma: no cover
    from .fabric import MemoryFabric

OPERATORS = ("$ne", "$in", "$nin", "$gt", "$gte", "$lt", "$lte", "$exists")
_MISSING = object()


def _get(fields: Mapping[str, Any], dotted: str) -> Any:
    cur: Any = fields
    for part in dotted.split("."):
        if not isinstance(cur, Mapping) or part not in cur:
            return _MISSING
        cur = cur[part]
    return cur


def _test(value: Any, cond: Any) -> bool | None:
    """True/False, or None when the field is absent and the condition needs it."""
    if isinstance(cond, Mapping) and cond and all(k in OPERATORS for k in cond):
        if "$exists" in cond and bool(cond["$exists"]) != (value is not _MISSING):
            return False
        rest = {k: v for k, v in cond.items() if k != "$exists"}
        if not rest:
            return True
        if value is _MISSING:
            return None
        try:
            return all({
                "$ne": lambda a: value != a, "$in": lambda a: value in a, "$nin": lambda a: value not in a,
                "$gt": lambda a: value > a, "$gte": lambda a: value >= a,
                "$lt": lambda a: value < a, "$lte": lambda a: value <= a,
            }[op](arg) for op, arg in rest.items())
        except TypeError:
            return False   # incomparable types are a non-match, not an error
    if isinstance(cond, Mapping) and any(str(k).startswith("$") for k in cond):
        raise ValueError(f"unknown operator in {dict(cond)}; supported: {', '.join(OPERATORS)}")
    if value is _MISSING:
        return None
    return bool(value == cond)


@dataclass
class Selection:
    where: dict[str, Any]
    ids: list[str] = field(default_factory=list)
    considered: int = 0
    unknown: list[str] = field(default_factory=list)
    """Visible memories that could not be checked: no typed fields, or not the fields asked about."""

    @property
    def complete(self) -> bool:
        return not self.unknown

    def certificate(self) -> dict[str, Any]:
        return {"where": self.where, "matched": len(self.ids), "considered": self.considered,
                "unknown": len(self.unknown), "complete": self.complete,
                "statement": (f"all {self.considered} visible memories were checked"
                              if self.complete else
                              f"{len(self.unknown)} of {self.considered} visible memories have no "
                              "typed value for the queried fields; matches among them are unknown")}


def select(fabric: "MemoryFabric", agent_id: str, where: Mapping[str, Any],
           tenant_id: str | None = None, within: Iterable[str] | None = None) -> Selection:
    """Every visible memory whose `structured` fields satisfy `where` (all conditions)."""
    from .navigation import _visible

    allowed = frozenset(within) if within is not None else None
    sel = Selection(dict(where))
    memories = fabric.state.memories
    for mid in _visible(fabric, agent_id, tenant_id):
        if allowed is not None and mid not in allowed:
            continue
        sel.considered += 1
        fields = memories[mid].structured or {}
        verdicts = [_test(_get(fields, key), cond) for key, cond in where.items()]
        if any(v is False for v in verdicts):
            continue
        if any(v is None for v in verdicts):
            sel.unknown.append(mid)
            continue
        sel.ids.append(mid)
    return sel


def count(fabric: "MemoryFabric", agent_id: str, where: Mapping[str, Any], **kw: Any) -> tuple[int, bool]:
    sel = select(fabric, agent_id, where, **kw)
    return len(sel.ids), sel.complete


def distinct(fabric: "MemoryFabric", agent_id: str, key: str, where: Mapping[str, Any] | None = None,
             **kw: Any) -> tuple[list[Any], bool]:
    sel = select(fabric, agent_id, {**(where or {}), key: {"$exists": True}}, **kw)
    values = {repr(v): v for v in (_get(fabric.state.memories[m].structured or {}, key) for m in sel.ids)}
    return [values[k] for k in sorted(values)], sel.complete


def group_by(fabric: "MemoryFabric", agent_id: str, key: str, where: Mapping[str, Any] | None = None,
             **kw: Any) -> tuple[dict[str, list[str]], bool]:
    sel = select(fabric, agent_id, {**(where or {}), key: {"$exists": True}}, **kw)
    out: dict[str, list[str]] = {}
    for mid in sel.ids:
        out.setdefault(repr(_get(fabric.state.memories[mid].structured or {}, key)), []).append(mid)
    return out, sel.complete


def join(fabric: "MemoryFabric", agent_id: str, left: Mapping[str, Any], right: Mapping[str, Any],
         on: tuple[str, str], **kw: Any) -> tuple[list[tuple[str, str]], bool]:
    """Pairs (left id, right id) whose `on` fields are equal. Complete only if both sides are."""
    lsel, rsel = select(fabric, agent_id, left, **kw), select(fabric, agent_id, right, **kw)
    mem = fabric.state.memories
    index: dict[str, list[str]] = {}
    for rid in rsel.ids:
        v = _get(mem[rid].structured or {}, on[1])
        if v is not _MISSING:
            index.setdefault(repr(v), []).append(rid)
    pairs = []
    for lid in lsel.ids:
        v = _get(mem[lid].structured or {}, on[0])
        if v is not _MISSING:
            pairs += [(lid, rid) for rid in index.get(repr(v), [])]
    return pairs, lsel.complete and rsel.complete
