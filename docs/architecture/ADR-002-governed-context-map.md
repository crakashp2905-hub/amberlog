# ADR-002: Governed Context Map — source-linked summaries as a derived cache

**Status:** accepted, implemented in `memory-fabric/context_map.py`.

## Context

A long-lived store has more admissible memories than any context budget.
`compaction.py` already writes one governed summary *memory* per episode;
it has no hierarchy, no budgeted selection, and becomes a durable memory in
its own right. The blueprint asks for hierarchical, source-linked,
invalidatable summaries that are never an authority.

## Options considered

1. **Summaries as memories** (extend compaction). Durable and governed, but
   every rebuild adds versions to the log, and a summary becomes something
   that can be retrieved, shared and federated as if it were evidence.
2. **Summaries as a derived cache (chosen).** Built from a pinned source
   set, keyed by everything they depend on, checked for staleness at every
   use, rebuildable from the log at any time, never written to the log and
   never shared.

## Decision

- Levels: **L0** canonical memory versions; **L1** a bundle of related
  memories (grouped deterministically by subject: the structured claim
  subject if present, else the leading capitalised entity and tag tokens);
  **L2** a topic summary of L1 bundles for one grouping key prefix.
- **Builder:** extractive and deterministic (`extractive-v1`). It keeps
  every sentence that carries a number, unit, date, identifier or negation
  verbatim, and keeps disagreeing values as an explicit dispute line. No
  model is called. A model-assisted builder can be added under a new
  builder id; its output passes the same coverage check.
- **Coverage check:** every number, negation and identifier in the sources
  must appear in the summary, or the node is refused — the same rule
  `compaction.py` enforces.
- **Node identity:** `source_refs` (memory id @ version), `source_digest`
  (SHA-256 over the sorted refs), `config_digest` (builder id and
  parameters), tenant, branch. The cache key is all of them together; a
  topic name or a mutable branch name alone is never a key.
- **Staleness at use:** a node is **valid** only if every source is still at
  the recorded version, still admissible for the requesting agent (tenant,
  scope, lifecycle), not erased. Otherwise it is **stale** (a version moved)
  or **blocked** (a source is no longer admissible) and is never served; the
  planner falls back to the admissible canonical records.
- **Planner:** hard governance filters first, then a greedy
  utility-per-token selection under the budget. Modes: `compact` (prefer
  L2/L1), `balanced`, `evidence-first` (canonical records and dispute lines
  first), `exact` (canonical records only for queries with numbers, ids or
  dates). Token cost is estimated as ⌈characters / 4⌉ and labelled as an
  estimate.
- Summaries do **not** count as corroboration: they are not memories and
  never enter independence or consensus calculations.

## Security and privacy

Summaries hold source text, so they live only in process memory, are keyed
by tenant, and are dropped when any source is erased or loses admissibility.
Retrieved text inside a summary is still untrusted data and is rendered
through the same `<retrieved_memories>` sanitiser.

## Test strategy

`tests/test_context_map.py`: negation, similar entity names, units, dates,
conflicts, a revised source, a withdrawn source, a permission change, an
injection in a source, cross-tenant isolation, budget respected, every mode.

## Rollback

It is a cache; turning it off returns to plain retrieval.
