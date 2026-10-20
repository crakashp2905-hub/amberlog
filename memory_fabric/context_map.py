"""Governed Context Map: source-linked summaries as a derived cache, and a budgeted planner.

A store with years of memories has more admissible material than any context
budget. This module compresses it **without letting the compressed form become
an authority** (docs/architecture/ADR-002-governed-context-map.md):

- **L0** is the canonical memory versions. **L1** nodes bundle memories about
  one subject (the claim's identifier, else the structured subject, else the
  first content word). **L2** nodes are an index of L1 nodes for one topic
  (the memory's `topic` context, else its episode), pointers only.
- The builder is extractive and deterministic (`extractive-v1`): a memory
  that states an identifier, a number, a date or a negation is kept
  verbatim; restatements of one claim keep the shortest wording; memories
  that disagree are kept as a dispute line naming every value and author.
  Then a **coverage check** refuses the node unless every number, identifier
  and negation of every kept source appears in it (`SummaryRefused`).
- Every node records its exact `source_refs` (memory id @ version), a
  `source_digest` over them, the builder's `config_digest`, tenant and branch.
- **Staleness is checked at every use, never assumed**: a node is `valid`
  only if every source is still at its recorded version, not erased, and
  admissible for the requesting agent *now* (`MemoryFabric.use`, which
  checks tenant, scope, collection grants and lifecycle). Otherwise it is
  `stale` (a version moved) or `blocked` (a source is no longer
  admissible), and the planner falls back to the admissible canonical
  records. A cached summary is never served because its text happens to be
  available.

Nodes live in process memory only. They are rebuilt from the log on demand,
are never written to it, never shared or federated, and never count as
corroboration: they are not memories.

The planner (`plan`) applies hard governance first — it starts from
`retrieve`, which enforces tenant, scope, lifecycle and the exposure policy
— and only then selects under the token budget, greedily by relevance per
estimated token. Modes:

| mode | what it prefers |
|---|---|
| `compact` | L1 summaries wherever one covers two or more candidates |
| `balanced` | a summary only where it is cheaper than the records it covers |
| `evidence-first` | canonical records, then summaries for what does not fit |
| `exact` | canonical records only; chosen automatically for a query with numbers, ids or dates when `mode="auto"` |

Token costs are estimates (⌈characters / 4⌉), reported as such.

**What extractive-v1 saves, and what it does not.** It keeps every distinct
fact verbatim, so it compresses only restatements (one claim said several
ways keeps its shortest wording) and chatter with no fact in it. A bundle of
distinct facts costs about what its records cost; `balanced` mode then
prefers the records. Real compression of distinct facts needs an abstractive
builder, which would have to pass the same coverage check.
"""

from __future__ import annotations

__stability__ = "experimental"

import hashlib
import json
import math
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Iterable, Sequence

from .conflicts import author, claim, find_conflicts
from .identity import DEFAULT_TENANT

if TYPE_CHECKING:  # pragma: no cover
    from .fabric import MemoryFabric
    from .model import Memory

BUILDER_ID = "extractive-v1"
MAX_BUNDLE = 8
MODES = ("compact", "balanced", "evidence-first", "exact", "auto")
NEGATIONS = frozenset({"not", "no", "never", "none", "cannot", "without", "disabled",
                       "isn't", "aren't", "wasn't", "doesn't", "don't", "won't", "can't"})
_WORD = re.compile(r"[A-Za-z']+")
_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
_EXACT = re.compile(r"\d|\b[A-Z]{1,4}\d+|\b\d{4}-\d{2}-\d{2}\b")


class SummaryRefused(Exception):
    """A summary would lose a number, identifier or negation; nothing was cached."""


def estimate_tokens(text: str) -> int:
    """An estimate, not a tokenizer: about four characters per token."""
    return max(1, math.ceil(len(text) / 4))


def _negations(text: str) -> set[str]:
    return {w.lower() for w in _WORD.findall(text)} & NEGATIONS


def _facts(text: str) -> set[str]:
    ids, _, values = claim(text)
    return set(ids) | set(values) | _negations(text) | set(_DATE.findall(text))


def _carries_fact(text: str) -> bool:
    return bool(_facts(text))


def subject(memory: "Memory") -> str:
    structured = memory.structured or {}
    if isinstance(structured.get("subject"), str):
        return f"s:{structured['subject'].lower()}"
    ids, words, _ = claim(memory.content)
    if ids:
        return f"id:{sorted(ids)[0]}"
    return f"w:{sorted(words)[0] if words else 'misc'}"


def topic(memory: "Memory") -> str:
    value = memory.context.get("topic") if isinstance(memory.context, dict) else None
    if isinstance(value, str) and value:
        return value
    return memory.provenance.source_episodes[0] if memory.provenance.source_episodes else "all"


def _digest(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":"))
                          .encode("utf-8")).hexdigest()


CONFIG_DIGEST = _digest({"builder": BUILDER_ID, "max_bundle": MAX_BUNDLE,
                         "negations": sorted(NEGATIONS)})


@dataclass(frozen=True)
class SummaryNode:
    node_id: str
    level: int
    key: str
    content: str
    source_refs: tuple[tuple[str, int], ...]
    source_digest: str
    tenant_id: str
    branch: str
    children: tuple[str, ...] = ()
    disputes: tuple[tuple[str, ...], ...] = ()
    builder: str = BUILDER_ID
    config_digest: str = CONFIG_DIGEST

    @property
    def tokens(self) -> int:
        return estimate_tokens(self.content)

    @property
    def memory_ids(self) -> list[str]:
        return [m for m, _ in self.source_refs]

    def to_json(self) -> dict[str, Any]:
        return {"node_id": self.node_id, "level": self.level, "key": self.key,
                "source_refs": [f"{m}@v{v}" for m, v in self.source_refs],
                "source_digest": self.source_digest, "tenant_id": self.tenant_id,
                "branch": self.branch, "children": list(self.children),
                "disputes": [list(d) for d in self.disputes], "builder": self.builder,
                "config_digest": self.config_digest, "tokens_estimated": self.tokens}


def build_l1(memories: Sequence["Memory"], key: str, tenant_id: str,
             branch: str = "main") -> SummaryNode:
    """One L1 node over memories about one subject. Refused if it would lose a fact."""
    memories = sorted(memories, key=lambda m: (m.created_at, m.id))
    disputes = find_conflicts(memories)
    disputed = {m.id for g in disputes for m in g}
    best: dict[Any, str] = {}
    order: list[Any] = []
    for memory in memories:
        text = memory.content.strip()
        if memory.id in disputed or not _carries_fact(text):
            continue
        ids, _, values = claim(text)
        k = (ids, values, frozenset(_negations(text)))
        if k not in best:
            order.append(k)
            best[k] = text
        elif len(text) < len(best[k]):
            best[k] = text
    lines = [best[k] for k in order]
    for group in disputes:
        lines.append("Disputed, unresolved: " + "; ".join(
            f"{m.content.strip()} (from {author(m)})" for m in group))
    content = " ".join(lines)
    missing = set().union(*(_facts(m.content) for m in memories)) - _facts(content)
    if missing:
        raise SummaryRefused(f"summary of {key} would drop {sorted(missing)[:5]}")
    refs = tuple((m.id, m.version) for m in memories)
    sdigest = _digest([tenant_id, branch, [list(r) for r in refs]])
    return SummaryNode(node_id=f"sum1_{_digest([sdigest, CONFIG_DIGEST])[:20]}", level=1,
                       key=key, content=content, source_refs=refs, source_digest=sdigest,
                       tenant_id=tenant_id, branch=branch,
                       disputes=tuple(tuple(m.id for m in g) for g in disputes))


def build_l2(nodes: Sequence[SummaryNode], key: str) -> SummaryNode:
    """An index of L1 nodes: one pointer line each, no evidence of its own."""
    nodes = sorted(nodes, key=lambda n: n.key)
    content = f"Topic {key}: " + "; ".join(
        f"{n.key.split(':', 1)[1]} ({len(n.source_refs)} notes, see {n.node_id})" for n in nodes)
    refs = tuple(r for n in nodes for r in n.source_refs)
    sdigest = _digest([nodes[0].tenant_id, nodes[0].branch, [list(r) for r in refs]])
    return SummaryNode(node_id=f"sum2_{_digest([sdigest, CONFIG_DIGEST])[:20]}", level=2,
                       key=f"t:{key}", content=content, source_refs=refs,
                       source_digest=sdigest, tenant_id=nodes[0].tenant_id,
                       branch=nodes[0].branch, children=tuple(n.node_id for n in nodes))


@dataclass
class PlannedItem:
    kind: str  # "memory" or "summary"
    id: str
    version: int | None
    tokens: int
    content: str
    sources: list[str] = field(default_factory=list)

    def ref(self) -> dict[str, Any]:
        out: dict[str, Any] = {"kind": self.kind, "id": self.id, "tokens_estimated": self.tokens}
        if self.version is not None:
            out["version"] = self.version
        if self.sources:
            out["expanded_sources"] = self.sources
        return out


@dataclass
class ContextPlan:
    mode: str
    budget: int
    items: list[PlannedItem] = field(default_factory=list)
    excluded: list[dict[str, str]] = field(default_factory=list)
    policy_id: str = ""

    @property
    def tokens(self) -> int:
        return sum(i.tokens for i in self.items)


class ContextMap:
    """Summary nodes for one fabric, keyed by everything they depend on."""

    def __init__(self, fabric: "MemoryFabric") -> None:
        self.fabric = fabric
        self._nodes: dict[tuple[str, str, str, str], SummaryNode] = {}
        self.refused: list[str] = []
        self.stats = {"built": 0, "reused": 0, "stale": 0, "blocked": 0}

    # --- building ------------------------------------------------------

    def _admissible(self, memory_id: str, agent_id: str, tenant_id: str) -> bool:
        if memory_id in self.fabric.state.erased:
            return False
        return self.fabric.use(memory_id, agent_id=agent_id, tenant_id=tenant_id,
                               audit=False).usable

    def build(self, agent_id: str, tenant_id: str = DEFAULT_TENANT, branch: str = "main",
              memories: Iterable["Memory"] | None = None) -> list[SummaryNode]:
        """L1 and L2 nodes over what `agent_id` may read now. Reuses identical nodes."""
        pool = list(memories) if memories is not None else [
            m for m in self.fabric.state.memories.values() if m.tenant_id == tenant_id]
        pool = [m for m in pool if self._admissible(m.id, agent_id, tenant_id)]
        groups: dict[str, list["Memory"]] = {}
        for m in sorted(pool, key=lambda m: (m.created_at, m.id)):
            groups.setdefault(subject(m), []).append(m)
        l1: list[SummaryNode] = []
        for key, members in sorted(groups.items()):
            for start in range(0, len(members), MAX_BUNDLE):
                chunk = members[start:start + MAX_BUNDLE]
                if len(chunk) < 2:
                    continue
                try:
                    node = self._cache(build_l1(chunk, key, tenant_id, branch))
                except SummaryRefused as exc:
                    self.refused.append(str(exc))
                    continue
                l1.append(node)
        by_topic: dict[str, list[SummaryNode]] = {}
        for node in l1:
            first = self.fabric.state.memories[node.source_refs[0][0]]
            by_topic.setdefault(topic(first), []).append(node)
        l2 = [self._cache(build_l2(nodes, key)) for key, nodes in sorted(by_topic.items())
              if len(nodes) > 1]
        return l1 + l2

    def _cache(self, node: SummaryNode) -> SummaryNode:
        key = (node.tenant_id, node.branch, node.source_digest, node.config_digest)
        if key in self._nodes:
            self.stats["reused"] += 1
            return self._nodes[key]
        self._nodes[key] = node
        self.stats["built"] += 1
        return node

    def node(self, node_id: str) -> SummaryNode | None:
        return next((n for n in self._nodes.values() if n.node_id == node_id), None)

    @property
    def nodes(self) -> list[SummaryNode]:
        return list(self._nodes.values())

    # --- governance at use ---------------------------------------------

    def status(self, node: SummaryNode, agent_id: str, tenant_id: str) -> str:
        """`valid`, `stale` (a source version moved) or `blocked` (a source is not admissible)."""
        if node.tenant_id != tenant_id:
            return "blocked"
        state = self.fabric.state.memories
        for memory_id, version in node.source_refs:
            if not self._admissible(memory_id, agent_id, tenant_id):
                return "blocked"
        for memory_id, version in node.source_refs:
            if state[memory_id].version != version:
                return "stale"
        return "valid"

    def invalidated_by(self, memory_id: str) -> list[SummaryNode]:
        """Every cached node whose source set includes this memory."""
        return [n for n in self._nodes.values() if memory_id in n.memory_ids]

    def drop_stale(self, agent_id: str, tenant_id: str = DEFAULT_TENANT) -> int:
        gone = [k for k, n in self._nodes.items()
                if n.tenant_id == tenant_id and self.status(n, agent_id, tenant_id) != "valid"]
        for k in gone:
            del self._nodes[k]
        return len(gone)

    # --- planning ------------------------------------------------------

    def plan(self, agent_id: str, query: str, budget: int = 2000, mode: str = "auto",
             tenant_id: str = DEFAULT_TENANT, branch: str = "main", k: int = 20) -> ContextPlan:
        if mode not in MODES:
            raise ValueError(f"mode must be one of {MODES}")
        if mode == "auto":
            mode = "exact" if _EXACT.search(query) else "balanced"
        result = self.fabric.retrieve(agent_id, query, k=k, tenant_id=tenant_id)
        plan = ContextPlan(mode=mode, budget=budget, policy_id=result.policy_id)
        for m in result.withheld:
            plan.excluded.append({"id": m.id, "reason_code": (
                "CONTESTED" if m.lifecycle_state.value == "contested" else "WITHHELD_BY_POLICY")})
        candidates = list(result.exposed)
        score = {m.id: result.scores.get(m.id, 1.0) for m in candidates}
        records = [PlannedItem("memory", m.id, m.version, estimate_tokens(m.content), m.content)
                   for m in candidates]
        options: list[tuple[float, PlannedItem, set[str]]] = []
        if mode != "exact":
            self.build(agent_id, tenant_id, branch)
            wanted = {m.id for m in candidates}
            for node in self.nodes:
                if node.level != 1 or node.tenant_id != tenant_id or node.branch != branch:
                    continue
                covers = set(node.memory_ids) & wanted
                if len(covers) < 2:
                    continue
                status = self.status(node, agent_id, tenant_id)
                if status != "valid":
                    self.stats[status] += 1
                    plan.excluded.append({"id": node.node_id,
                                          "reason_code": f"SUMMARY_{status.upper()}"})
                    continue
                item = PlannedItem("summary", node.node_id, None, node.tokens, node.content,
                                   sources=[f"{m}@v{v}" for m, v in node.source_refs])
                cost_of_records = sum(r.tokens for r in records if r.id in covers)
                if mode == "balanced" and node.tokens >= cost_of_records:
                    continue
                options.append((sum(score[c] for c in covers), item, covers))
        for record in records:
            options.append((score[record.id], record, {record.id}))

        def rank(option: tuple[float, PlannedItem, set[str]]) -> tuple[int, float]:
            utility, item, _ = option
            first = {"compact": item.kind == "summary", "evidence-first": item.kind == "memory",
                     "balanced": True, "exact": True}[mode]
            return (0 if first else 1, -utility / item.tokens)

        covered: set[str] = set()
        for utility, item, covers in sorted(options, key=rank):
            if covers <= covered:
                continue
            if plan.tokens + item.tokens > budget:
                plan.excluded.append({"id": item.id, "reason_code": "OVER_BUDGET"})
                continue
            if item.kind == "memory" and item.id in covered:
                continue
            plan.items.append(item)
            covered |= covers
        chosen = {i.id for i in plan.items}
        plan.excluded = [e for e in plan.excluded if not (
            e["reason_code"] == "OVER_BUDGET" and (e["id"] in covered or e["id"] in chosen))]
        for m in candidates:
            if m.id in covered and not any(i.kind == "memory" and i.id == m.id
                                           for i in plan.items):
                plan.excluded.append({"id": m.id, "reason_code": "COVERED_BY_SUMMARY"})
        return plan
