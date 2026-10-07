"""Observability: the read model behind both the CLI and the web dashboard.

The P2 gate is that someone outside the project can answer "why did this agent
remember this?" unaided (ROADMAP.md). Two surfaces serve that question, and both
read through `report.py` rather than querying the fabric themselves, so they
cannot drift into telling different stories about the same store.

Both surfaces are read-only. Mutation stays in the SDK and in the CLI's own
explicit commands, so nothing an operator does while *looking* at the store can
change it.
"""

from .report import (
    AttentionItem,
    LineageNodeView,
    MemoryRow,
    Overview,
    SearchHit,
    attention,
    episode_rows,
    lineage_tree,
    memory_detail,
    memory_rows,
    overview,
    preview_search,
    retention_preview,
)

__all__ = [
    "AttentionItem",
    "LineageNodeView",
    "MemoryRow",
    "Overview",
    "SearchHit",
    "attention",
    "episode_rows",
    "lineage_tree",
    "memory_detail",
    "memory_rows",
    "overview",
    "preview_search",
    "retention_preview",
]
