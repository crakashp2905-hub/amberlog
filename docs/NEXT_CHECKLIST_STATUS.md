# Next checklist execution status (28 October 2026)

Baseline main: `7c34c18f5fea97fe1f1f90c9bc98e0a0f8056d14`.
OPEN is unfinished work, not a passing result. IMPLEMENTED means code and local
tests exist; exact-head CI and review remain merge gates. PRs are not releases.

| Items | State | Evidence / remaining requirement |
|---|---|---|
| N01–N05 | IMPLEMENTED, review/CI pending | `typed_query.py`, `test_typed_query_soundness.py`: reproduced missing join key, scalar/null semantics, missing/incomparable uncertainty, aggregate filter preservation, tenant/erasure/privacy and replay fixtures; experimental only |
| N06–N07 | OPEN | PR #18 froze a synthetic key/value study, not the required independent multilingual/table/implicit-qualifier E2 corpus. Its development headroom gate failed. A new study requires new independent data and a fresh registration. |
| N08 | PARTIAL | Three-valued record evaluation exists; explicit per-predicate reason/provenance result API remains open. |
| N09 | IMPLEMENTED in PR #18 | Unknown-only enforced/logged reads, explicit budget, ambiguity and snapshot-change certificates; no superiority claim |
| N10–N13 | OPEN | Typed extraction schema, verification flow, indexed/paginated scale runs and full E2 metrics still required |
| N14 | DESIGN COMPLETE | [ADR 0002](adr/0002-historical-belief-reads.md) separates valid time, transaction sequence and current authorization; defines safe receipts and bounded replay. |
| N15 | IMPLEMENTED, CI pending | `history_query.query`: separate opt-in explicit-ID read with inclusive transaction sequence and optional valid time; stable `as_of` unchanged |
| N16 | PARTIAL | Current/historical authorization intersection, canonical erasure checks, original sealed replay and hard replay/ID limits; checkpoint acceleration remains open |
| N17 | IMPLEMENTED, CI pending | Archival receipts include original/current versions, recording event time/sequence, valid interval, permitted lineage, supersession/redaction, replay work and latency; no action credential |
| N18 | PARTIAL | Six focused tests and five seeded latent-oracle scenarios cover late correction, current retraction/erasure, private/foreign scope, time windows and old certificate refusal. More partition/import/rollback/independent-source scenarios remain open. |
| N19 | PARTIAL | Existing compiled-tree contract records format/span/digest/version; versioned nodes, permissions and unresolved-block contract remains open. |
| N20 | IMPLEMENTED in PR #17 | Local CSV/HTML/DOCX, optional PDF; real fixtures, no core runtime dependencies |
| N21 | PARTIAL | CSV physical rows and PDF page anchors; merged cells, footnotes, OCR and full layout fidelity remain open and documented. |
| N22 | IMPLEMENTED in PR #17 | Existing screened candidate importer, revision invalidation and cross-tenant regression; more cross-format collision fixtures remain useful. |
| N23 | OPEN | Batch preview, resume, dependent-action impact and rollback/repair workflows |
| N24–N27 | OPEN | Existing compaction is not evidence of actual compression savings. Optional compressor and paired cost/safety study required. |
| N28 | DRAFT COMPLETE | [Procedural asset contract](adr/0003-procedural-asset-draft.md); schema review and implementation remain gated on pilot demand. |
| N29–N30 | GATED / OPEN | Verified asset flow, execution/publication and comparisons wait for the stated pilot-demand gate. |
| N31 | PARTIAL in PR #17 | INT-02 five-store chain/star correction world exists; role-specific conflicts, source laundering, contradictory timestamps and longitudinal decisions remain open. |
| N32 | PROTOCOL DRAFTED | `research/prereg/int05-continuous-design.md`: frozen seed allocation and 50-task protocol; generator/baseline pilot and improvement-threshold registration remain open. |
| N33–N34 | OPEN | Full role/task metrics and minority studies remain required. |
| N35 | DESIGN COMPLETE | `research/prereg/causal-intervention-design.md` separates intervention identification from lineage, includes randomized assignments and negative controls; no study run or product claim. |
| N36 | GATED / OPEN | H2b needs independently registered binding-budget evidence; H2 remains negative. |
| N37 | ON HOLD | Hosted model arms require explicit budget authorization; scripted tests do not count as model evaluations. |
| N38–N42 | OPEN / resource-gated | Dataset-specific rights, pinned revisions, adapters, local model resources and paid-evaluation approvals; vendor scores remain vendor scores. |
| N43 | IMPLEMENTED | Existing registry, raw run manifests and generated scoreboard; no duplicate framework introduced |
| N44–N47 | OPEN | Portable tombstones, unified collateral report, governed skills and additional distributed/upgrade scenarios remain required. GOV-20 requires additional physical hosts. |
| N48 | PARTIAL | Local release checks and full suites; exact-head CI failures in #17/#18 repaired for tag/ref availability and LF-normalized result digests. Complete alpha qualification, bundle and integration evidence still required. |
| N49 | EXTERNAL | Independent security reviewer and independent replicating team are required. Internal passing tests are not substitutes. |
| N50 | EXTERNAL | Usability participants and pilot partners are required; no adoption or willingness-to-pay numbers invented. |
| N51 | OPEN / owner decisions | Existing product/pilot materials are inputs, not finalized license/pricing/hosting/SLA decisions. No license or compliance claim changed. |

## Correctness contract

All five original E1 seed/arm tables were reproduced without changing the
historical artifacts: `research/results/n01-e1-regression.json` records an
identical comparison and the exact source commit. This is a compatibility
regression check, not a new retrieval improvement claim.

For this experimental API, complete means every currently eligible, unerased
record in the selected tenant/ID corpus can be included or excluded under the
query and aggregation key semantics. It does not certify real-world truth,
inaccessible data, authority, or future readability. A missing or incomparable
required value is unknown; a definite false conjunct can justify exclusion.
An absent join key is unknown, not a silently dropped row. Explicit null is a
known aggregate value but never joins. Numbers compare numerically; strings
and booleans remain distinct. Composite/nonfinite join keys are unresolved.
Short metadata transactions prevent torn selection/aggregation snapshots.

## Evidence reproducibility repair

Original PR #17/#18 CI found two environmental dependencies: local tags were
included in a committed status page, and Windows CRLF result bytes were hashed
before Git normalized them to LF. The status tree report now leaves checkout
tag enumeration to stamped runtime evidence. Result hashes explicitly use LF
file bytes, with regression tests for both problems. This changes evidence
serialization only, not stored memory events or benchmark observations.
