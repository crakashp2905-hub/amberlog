# Alongside a document knowledge fabric

A document knowledge fabric (Sarvam's, or your own pipeline) compiles manuals and
policies into a section tree that agents navigate. Memory Fabric is the layer that
records what agents *did* with those sections, and stops what rests on a section
when the document changes.

## 1. Import the compiled tree

```json
{"doc_id": "sop-12", "version": "2026-10", "uri": "https://intranet/sop-12",
 "sections": [{"path": "4.2", "title": "Relief valve", "text": "Set P-14 relief to 12 bar."}]}
```

    memory-fabric --db store.db import-docs sop-12.json --activate

Each section becomes a memory authored by `docs:sop-12`, carrying
`source = {doc_id, version, path, uri, sha256}`. Without `--activate` sections wait for review.

## 2. Re-import when the document changes

Run the same command on the new version. Unchanged sections are left as they are;
revised and removed sections are **withdrawn** ("source document changed",
basis `retracted_at_origin`). Withdrawal propagates: conclusions derived from the
old section are contested, and an action whose evidence certificate cites it is
refused by the action gate with `evidence_withdrawn`.

## 3. Let agents browse as well as search

    memory-fabric mcp --extended-tools ...

adds `browse_topics` and `open_topic`, a topic tree over what the agent may see.
Opening a topic is a logged retrieval. K1 measured that it does not find more than
search on LongMemEval (`research/results/k1-topic-navigation.md`); use it to see
what is there.

## 4. Free-text contradictions

In the `personal` and `team` presets, `TypedClaimChecker` holds a new claim that
plainly negates another author's ("the east wing is not safe" against "the east
wing is safe") for review, with no model call (O1).

Python: `memory_fabric.docsource.import_document`, `memory_fabric.navigation`,
`memory_fabric.typedclaims`.

## 5. Compile local Markdown

The optional experimental compiler accepts local Markdown without downloads,
model calls or additional dependencies:

```bash
python -m memory_fabric --db project.db --create import-docs examples/project-handbook.md --format markdown --doc-id project-handbook --source-version v1
```

Sections wait for review. Use the existing `review` workflow; `--activate` is an
explicit operator approval and should only be used for approved source material.
Re-import a changed file with the same document ID and a new source version to
withdraw revised or removed sections and contest dependent conclusions.
Use `--tenant` to select a tenant and `--source-uri` for an optional citation URI
(the URI is never fetched).

Python callers can use `knowledge_compiler.compile_markdown` then pass its tree
to `docsource.import_document`. Heading paths are deterministic and hierarchical.
Fenced code and tables are preserved as text. This does not extract typed entities,
interpret tables, support PDF pages, or establish corpus completeness. See the
[implementation status and ADR](../MF2_IMPLEMENTATION_STATUS.md).
