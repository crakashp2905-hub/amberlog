# Baseline and gap report (blueprint Phase 0)

Audit of the repository against `amberlog_end_to_end_blueprint.md`,
20 October 2026. The capability registry
([CAPABILITY_REGISTRY.md](CAPABILITY_REGISTRY.md), generated from
`product/capabilities.json` and checked against the code by
`tests/test_capability_registry.py`) is the authoritative inventory; this page
records the baseline and what the audit found missing.

## Baseline

| item | value |
|---|---|
| Starting commit | `84103b1` |
| Python | 3.13.5 (CI: 3.11, 3.12, 3.13 on Linux, macOS, Windows) |
| Install | `pip install -e .` (no runtime dependencies; extras `crypto`, `postgres`, `anthropic`) |
| Unit and integration | `python -m unittest discover -s tests -t .` |
| Full local gate | `python tools/check.py --full` (lint, types, tests, docs freshness, secret scan, adversarial gate) |
| Docs generation | `tools/gen_reference.py`, `tools/gen_stability.py`, `tools/gen_capabilities.py`, `tools/count_tests.py --write` |
| Security | `tools/scan_secrets.py`, `tools/adversarial_gate.py`, `tools/mutation_check.py` |
| CI at the starting commit | **failed**: every test job, on one cause — README.md and docs/VALIDATION.md cited 1,801 tests where the suite had 1,808, because the count update was left out of the two previous commits. Not a product defect; fixed in the commit that adds this page. |

Classification of the CI failure: documentation drift caught by its own test
(`tests/test_suite_hygiene.py`). No flaky test or product defect was found.

## What already existed

Most of the blueprint's Phase 1 backend was present before this work:
provenance explanation (`explain.py`), lineage (`lineage.py`), event and
version history, correction preview and apply (`correction.py`), retraction
propagation to descendants and peers, status labels with stated limits
(`status.py`), preserved contradictions (`conflicts.py`), the action fence,
tenant isolation, erasure, the hash-chained log, a read-only dashboard
(`observability/`), and session compaction (`compaction.py`, one summary per
episode, experimental).

## Gaps found, and what was done

| # | gap | blueprint | status |
|---|---|---|---|
| G1 | No capability registry; feature status was prose | §4 step 2, §10.3 | **done**: `product/capabilities.json`, generated page, test. It caught compaction listed as available while its module is experimental. |
| G2 | Correction preview not revalidated at apply | §5.5 step 5 | **done**: preview digest; `apply(preview_digest=)` refuses `STALE_PREVIEW` under the write lock; CLI `correct --preview` |
| G3 | No record of the bundle an agent received | §5.6, §8.3 | **done (experimental)**: `context_receipt.py`, `ContextBuilt` event, no content or query |
| G4 | No hierarchical, invalidatable summaries or budgeted planner | §6 | **done (experimental)**: `context_map.py` (L1/L2, extractive-v1, coverage check, staleness at use, four modes) |
| G5 | No branches, commits, diff or merge | §7 | **done (experimental)**: `branching.py` (CAS heads, three-way classification, policy, stale preview, idempotency, revert, snapshot) |
| G6 | A rolled-back write stayed in the copy index | found while building G5 | **fixed** in `_fabric/core.py` `_replay`; regression test in `tests/test_transactions.py` |
| G7 | CLI, HTTP, MCP and dashboard surfaces for G3–G5 | §9, §10 | see the commit that adds them |
| G8 | Benchmark matrix A–G | §11 | see `research/prereg/gme-matrix.md` and its result |
| G9 | Usability sessions with developers who did not build it | §11.2 #12, Sprint 8 | **not done**: needs outside participants |
| G10 | Legal and privacy review of deletion semantics | §12.3 | **not done**: needs counsel; no compliance claim is made |
| G11 | Literature review establishing novelty | §2.3 | **not done**: the GME contributions remain hypotheses, as the blueprint says |
| G12 | Independent evaluation | §11.4, §16 | **not done**: needs an outside evaluator (docs/INDEPENDENT_EVALUATION.md) |

## Decisions recorded

- [ADR-001: branch and commit model](../architecture/ADR-001-branch-commit-model.md)
- [ADR-002: Governed Context Map](../architecture/ADR-002-governed-context-map.md)
- [ADR-003: context receipts](../architecture/ADR-003-context-receipts.md)
