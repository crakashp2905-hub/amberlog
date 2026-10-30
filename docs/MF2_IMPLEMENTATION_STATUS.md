# Memory Fabric 2 implementation status

The [masterplan](MEMORY_FABRIC_2_PRODUCT_RESEARCH_MASTERPLAN.md) is a roadmap,
not a completed release specification. Unchecked requirements remain open.

## Baseline

Baseline source commit: `e20f18124261b49102b523d29bbb6ff9ac700b1b`.
Runtime: Python 3.13.5 on Windows. Core runtime dependencies remain empty.
Local checks do not reproduce the complete CI OS/Python, Docker, PostgreSQL,
packaging and optional-provider matrix.

Performance command:

```powershell
python -m experiments.product_bench --quick --seed 7 --out research/results/mf2-baseline-performance.json
```

Raw results are in `research/results/mf2-baseline-performance.json`. This is
a single-seed baseline, run concurrently with tests; it is neither an isolated
capacity measurement nor evidence of improved retrieval. No model API was used.

## Existing implementation inventory

Authoritative module tiers are in [STABILITY.md](../STABILITY.md).

| Requirement | Existing code and interface | Remaining work |
| --- | --- | --- |
| Governed source import | `docsource.import_document`, `current_sections`; experimental | PDF/CSV parsers, page/table anchors, transactional ingestion review |
| Browse and search | `navigation.topics`, `open_topic`; experimental; stable `Memory Fabric.retrieve` | Source-tree browser, bounded coverage contracts |
| Retrieval adapters | `retrievers`, `retrieval_profiles`, `answerability` | Paired evaluation and calibrated abstention for the target corpus |
| Corrections and provenance | Stable lifecycle, lineage, federation and certificates | Compiler-derived projection integration tests across peers |
| Actions | `actions.ActionGate.execute`, freshness leases | Workload-specific latency and deployment verification |
| Team access | Identity, collections, agent API and existing dashboard | Reviewed skill cards, bundles and multi-user product acceptance |
| Reconciliation | Consensus, conflicts, dependence, typed claims | Common-origin experiments with independent minority support |
| Research | RuleWorld, TeamWorld, PoisonWorld, retention and temporal experiments | MemoryWorld protocol, locked splits and preregistered comparisons |
| Operations | CI, deployment docs, backup/restore, audit and HTTP surfaces | Independent review, multi-host measurements and pilot acceptance |

Existing modules are reusable building blocks, not evidence that their matching
roadmap acceptance criteria have passed.

## Delivered first increment

- Original masterplan checked into the repository.
- Optional local Markdown compiler, connected to `import-docs`.
- Hierarchical section anchors, fenced-code preservation and verbatim tables.
- Candidate-by-default import through existing screening and governance.
- Regression tests for correction propagation and default-tenant isolation.
- Local performance baseline with reproducible command and raw output.

## Remaining engineering gates

- Full CI matrix and isolated multi-seed performance runs.
- Hybrid retrieval improvements and calibrated abstention, with paired baselines.
- PDF/page and typed-table extraction; ontology filters, joins, aggregates,
  source reads and explicitly bounded completeness reporting.
- Source-tree, correction fan-out and policy outcome UI acceptance.
- Verified versioned procedural skills, scoped bundles and approval workflow.
- Migration/import/export acceptance and identity integration tests.
- MemoryWorld, temporal claims, causal harness, retention and poisoning studies.
- Deployment decisions, operating-cost measurement and pilot runbooks.

## External gates (not performed)

Discovery interviews, design partner recruitment, customer willingness-to-pay,
license/brand decisions, paid pilots, independent security review and approved
case studies require real participants or owner decisions. Templates or tests
cannot count as their completion. No public pricing or license change is made.

## ADR: compiler uses the existing document boundary

The compiler returns the existing `doc_id/version/uri/sections` interchange
shape. It neither writes a second database nor approves extracted claims.
`import_document` remains the event-writing boundary; event replay reconstructs
the governed source memories. No event-schema migration is required.

Markdown support reads ATX (`#`) and one-line setext (`===`/`---`) headings; it
is not a complete CommonMark parser. Headings with no text of their own produce
no section. Tables remain literal content; no semantic extraction, PDF parsing or
completeness claim is provided. Duplicate sibling headings use occurrence
suffixes, so inserting a duplicate or re-parenting a heading changes anchors;
re-import matches sections by text first, so such edits withdraw nothing.
Unchanged sections retain their original source revision, as existing imports
do. Line positions in compiler output are advisory and are not persisted by
the current importer. Empty-document import withdraws existing sections.
