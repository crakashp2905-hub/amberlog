"""Browse what an agent may see by topic, as well as search it.

Search answers a question an agent already knows how to ask. A topic tree
answers "what is there?": the store's memories grouped by a word most of them
share, each group split again the same way. An agent can list the topics,
open one, and read what is in it, the way a person scans a table of contents.
(The idea is Sarvam's knowledge fabric, which compiles documents into a
navigable tree for its agents; here the tree is built from what agents wrote.)

Two rules keep it honest:

- **It shows only what the reader may see.** The tree is built from the same
  eligible set `retrieve` uses for that agent: tenancy, scope, lifecycle and
  hostile-source withholding all apply before a memory can lend a word to a
  topic name.
- **Opening a topic is a retrieval.** `open_topic` calls `retrieve(within=…)`,
  so what it returns is ranked, decided and logged exactly like any recall:
  every exposure carries its propensity.

    from memory_fabric.navigation import topics, open_topic
    topics(fabric, "agent-a")                       # [{"path": ["valve"], "label": "Valve · pressure", "size": 12}, …]
    topics(fabric, "agent-a", path=["valve"])       # its subtopics
    open_topic(fabric, "agent-a", ["valve"], query="relief setting")

Whether entering through a topic finds what search misses is measured, not
assumed (`research/prereg/k1-topic-navigation.md`).
"""

from __future__ import annotations

__stability__ = "experimental"

import math
import re
from typing import TYPE_CHECKING, Any, Iterable, Sequence

if TYPE_CHECKING:  # pragma: no cover
    from .fabric import MemoryFabric
    from .retrieval import RetrievalResult

STOP = frozenset(
    "the a an is are was were be been being it its of for to in on at and or not no do does did "
    "should would will shall may might must can could what which how why when who whom with from "
    "this that these those there here than then also only just very more most less into onto over "
    "under after before about above below between each every any all some such same other again "
    "we i me my our us you your they them their he she his her has have had having use used uses "
    "using one two three new note notes per via set sets get gets got make made run runs ran "
    "if else so but yet because while once whenever where still now today yesterday always never "
    "agent agents memory memories user users redacted assistant "
    # units and quantities name no topic
    "bar bars psi kpa rpm degrees degree celsius hours hour minutes minute seconds second "
    "days day weeks week percent times mbps gb mb kb".split())


def terms(text: str) -> set[str]:
    """The words of `text` that could name a topic."""
    return {w for w in re.findall(r"[a-z][a-z0-9-]{2,}", text.lower()) if w not in STOP}


def group(ids: Sequence[str], words: dict[str, set[str]], max_topics: int,
          exclude: Iterable[str] = ()) -> list[tuple[str, list[str]]]:
    """Memories grouped by a shared word; the rest under "".

    Each memory joins the commonest word it contains that at least two
    memories share and not nearly all do (a word in everything names nothing). Ties go to the longer word, usually the more specific one.
    Deterministic for the same input.
    """
    skip = set(exclude)
    df: dict[str, int] = {}
    for mid in ids:
        for t in words[mid] - skip:
            df[t] = df.get(t, 0) + 1
    n = len(ids)
    # In a large store a word in over 60% of memories names nothing; in a small
    # one only a word in every memory is that uninformative.
    ceiling = int(0.6 * n) if n >= 20 else n - 1
    candidates = sorted((t for t, c in df.items() if 2 <= c <= ceiling),
                        key=lambda t: (-df[t], any(ch.isdigit() for ch in t), -len(t), t))
    taken: set[str] = set()
    out: list[tuple[str, list[str]]] = []
    for t in candidates:
        if len(out) >= max_topics:
            break
        members = [mid for mid in ids if mid not in taken and t in words[mid]]
        if len(members) < 2:
            continue
        taken.update(members)
        out.append((t, members))
    rest = [mid for mid in ids if mid not in taken]
    if rest:
        out.append(("", rest))
    return out


def label(key: str, members: Sequence[str], words: dict[str, set[str]],
          exclude: Iterable[str] = ()) -> str:
    """"Valve · pressure": the topic word and the word most of its memories also share."""
    if not key:
        return "Other"
    skip = set(exclude) | {key}
    co: dict[str, int] = {}
    for mid in members:
        for t in words[mid] - skip:
            co[t] = co.get(t, 0) + 1
    second = max(co, key=lambda t: (co[t], len(t), t)) if co else ""
    if second and co[second] >= 2 and co[second] * 2 >= len(members):
        return f"{key.capitalize()} · {second}"
    return key.capitalize()


def _visible(fabric: "MemoryFabric", agent_id: str, tenant_id: str | None) -> list[str]:
    """What `retrieve` would consider for this agent: same chokepoints, same order of application."""
    base = fabric._eligible_ids(include_contested=False, tenant_id=tenant_id, agent_id=agent_id)
    eligible = fabric._without_hostile_sources(base, reader=agent_id)
    memories = fabric.state.memories
    return sorted(eligible, key=lambda mid: -memories[mid].created_at)


def _words(fabric: "MemoryFabric", ids: Iterable[str]) -> dict[str, set[str]]:
    cache: dict[tuple[str, int], set[str]] = fabric.__dict__.setdefault("_topic_terms", {})
    out = {}
    for mid in ids:
        m = fabric.state.memories[mid]
        key = (mid, m.version)
        if key not in cache:
            cache[key] = terms(m.content if isinstance(m.content, str) else "")
        out[mid] = cache[key]
    return out


def members(fabric: "MemoryFabric", agent_id: str, path: Sequence[str] = (),
            tenant_id: str | None = None, max_topics: int = 12) -> list[str]:
    """The memory ids under `path` ([] is everything this agent may see)."""
    ids = _visible(fabric, agent_id, tenant_id)
    words = _words(fabric, ids)
    for depth, key in enumerate(path):
        groups = dict(group(ids, words, max_topics, exclude=path[:depth]))
        ids = groups.get("" if key == "_other" else key, [])
    return ids


def topics(fabric: "MemoryFabric", agent_id: str, path: Sequence[str] = (),
           tenant_id: str | None = None, max_topics: int = 12) -> list[dict[str, Any]]:
    """The topics directly under `path`, largest first, with how many memories each holds.

    Names and counts only: no memory text, and nothing is logged, because
    nothing is shown. Reading a topic is `open_topic`.
    """
    ids = members(fabric, agent_id, path, tenant_id, max_topics)
    words = _words(fabric, ids)
    out = []
    for key, mems in group(ids, words, max_topics, exclude=path):
        out.append({"path": [*path, key or "_other"], "label": label(key, mems, words, exclude=path),
                    "size": len(mems), "has_subtopics": len(mems) >= 4 and bool(key)})
    return out


def topic_query(fabric: "MemoryFabric", ids: Sequence[str], path: Sequence[str] = ()) -> str:
    """What to rank a topic by when the reader gave no query: its path and its commonest words."""
    words = _words(fabric, ids)
    count: dict[str, int] = {}
    for mid in ids:
        for t in words[mid]:
            count[t] = count.get(t, 0) + 1
    common = sorted(count, key=lambda t: (-count[t], t))[:6]
    return " ".join([p for p in path if p != "_other"] + common)


def open_topic(fabric: "MemoryFabric", agent_id: str, path: Sequence[str], query: str = "",
               k: int = 10, tenant_id: str | None = None, **retrieve_kwargs: Any) -> "RetrievalResult":
    """Read a topic: a retrieval limited to its memories, ranked by `query` (or by the topic's words).

    Goes through `retrieve(within=…)`, so exposure is decided and logged as
    for any recall.
    """
    ids = members(fabric, agent_id, path, tenant_id)
    q = query or topic_query(fabric, ids, path)
    return fabric.retrieve(agent_id=agent_id, query=q, k=k, within=ids, tenant_id=tenant_id,
                           min_relevance=0.0, **retrieve_kwargs)


def navigate(fabric: "MemoryFabric", agent_id: str, query: str, k: int = 10, topics_to_open: int = 2,
             tenant_id: str | None = None, **retrieve_kwargs: Any) -> list[str]:
    """K1's deterministic navigator: open the topics that best match the query, rank inside them.

    Scores each top-level topic by the query words its memories contain,
    weighted by how rare each word is across the store, opens the best
    `topics_to_open`, and returns up to `k` memory ids ranked by `retrieve`
    inside them. Measured against plain search before any claim is made.
    """
    ids = _visible(fabric, agent_id, tenant_id)
    words = _words(fabric, ids)
    q = terms(query)
    if not q or not ids:
        return []
    df = {t: sum(1 for mid in ids if t in words[mid]) for t in q}
    idf = {t: math.log(1 + len(ids) / (1 + c)) for t, c in df.items()}
    scored = []
    for key, mems in group(ids, words, 12):
        if not key:
            continue
        score = sum(idf[t] * sum(1 for mid in mems if t in words[mid]) / len(mems) for t in q)
        scored.append((score, key, mems))
    scored.sort(key=lambda s: -s[0])
    chosen = [mid for _, _, mems in scored[:topics_to_open] for mid in mems]
    if not chosen:
        return []
    result = fabric.retrieve(agent_id=agent_id, query=query, k=k, within=chosen,
                             tenant_id=tenant_id, min_relevance=0.0, **retrieve_kwargs)
    return [m.id for m in result.exposed]
