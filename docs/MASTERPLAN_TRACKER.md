# Masterplan tracker — "Memory Fabric next masterplan" (2026-10-28)

Every work item in the masterplan, with what was done and what was not. Status words:

- **DONE** — built and tested in this repository; the evidence is linked.
- **PARTIAL** — part is done; the rest is named.
- **FAIL** — run as registered and failed; kept, not hidden.
- **NOT_RUN** — not attempted, with the reason (usually a model budget, a licence review, or a decision only the owner can make).
- **BLOCKED** — cannot be done from this repository: it needs people, machines or accounts outside it.

Nothing here is a performance claim; claims live in `research/results/` with their registrations.
The generated companions are [STATUS_AT_HEAD.md](STATUS_AT_HEAD.md),
[the results manifest](../research/results/MANIFEST.json) and
[the benchmark scoreboard](../research/results/BENCHMARK_SCOREBOARD.md).

## Issue packets MF-001 – MF-050

| ID | Item | Status | Evidence / reason |
|---|---|---|---|
| MF-001 | Pin HEAD / release evidence | DONE | `tools/status_at_head.py` → [STATUS_AT_HEAD.md](STATUS_AT_HEAD.md); release bundle stamps the SHA (`tools/release_bundle.py`) |
| MF-002 | Run complete validation, record skips | DONE | CI matrix on every PR; skipped-test list generated in STATUS_AT_HEAD; release bundle `tests.json` |
| MF-003 | Reconcile SPEC / 0.13 release | DONE | SPEC header drift fixed and tested; [ADR 0001](adr/0001-version-semantics.md) |
| MF-004 | Document import / tenant regression | DONE | `tests/test_ingest_hardening.py` (randomised tenant property test) |
| MF-005 | Source span fidelity | DONE | sections carry `line_start/line_end/byte_start/byte_end`, parser version, MIME, source hash; span tests resolve every span to the exact source bytes |
| MF-006 | Markdown parser hardening | DONE | fence/CRLF/unicode/escape/size-limit/determinism matrix in `tests/test_ingest_hardening.py` |
| MF-007 | Format adapter contract (HTML/PDF/DOCX/CSV) | NOT_RUN | needs parser dependencies kept out of the zero-dependency core; the compiled-tree JSON contract (`import-docs`) is the seam |
| MF-008 | Evidence benchmark prereg + harness | PARTIAL | harness and E1 registration done; a cross-domain public evidence benchmark needs licensed data (PUB-07..10) |
| MF-009 | Retrieval profiles at fixed budget | PARTIAL | profiles exist (R3); fixed-budget downstream gain needs an answer model |
| MF-010 | Typed entity projection | PARTIAL | `typed_query` (experimental) over writer-typed fields; E1 **failed**; no extraction |
| MF-011 | Conflict display and review | PARTIAL | contested sets kept and shown in the Control Center; GOV-21 test; no new UI this round |
| MF-012 | Answerability audit | NOT_RUN | A1 found the prompt already saturated; a new ambiguous-evidence benchmark needs a model |
| MF-013 | Multi-agent MemoryWorld | PARTIAL | INT-01 (changing knowledge, bitemporal) runs; INT-02 (federation world) not built |
| MF-014 | Real-agent evaluation | NOT_RUN | hosted-model evaluation is on hold by owner instruction |
| MF-015 | Action-fence regression | DONE | GOV-12/13 map to existing fence and crash tests |
| MF-016 | Restore and retention audit | DONE | backup/restore and erasure tests (GOV-15/16 map) |
| MF-017 | Bitemporal query validation | PARTIAL | INT-01 shows both questions answered; `retrieve(known_at=)` API not built (replay helper only) |
| MF-018 | Minority belief experiment | NOT_RUN | needs real agent teams (model budget) |
| MF-019 | Source identity calibration | NOT_RUN | S2 result stands; recalibration needs new data |
| MF-020 | Governed skills | NOT_RUN | no skill asset type; GOV-23 PARTIAL |
| MF-021 | Multi-physical-host federation | BLOCKED | needs a second physical machine |
| MF-022 | External security review | BLOCKED | needs an independent reviewer |
| MF-023 | DX onboarding user study | BLOCKED | needs participants; automated fresh-machine install runs in CI |
| MF-024 | Commercial discovery | BLOCKED | interviews are the owner's to hold |
| MF-025 | Pilot infrastructure | PARTIAL | `pilot-report --check` and pilot kit exist; pilots need partners |
| MF-026 | Causal effect study | NOT_RUN | needs a fresh registration and budget |
| MF-027 | H2b constrained forgetting | NOT_RUN | H2 stays killed; H2b needs a registration |
| MF-028 | Independent longitudinal replication | BLOCKED | needs an outside team |
| MF-029 | Packaging / licensing | BLOCKED | owner decision; licence stays proprietary |
| MF-030 | Beta readiness | NOT_RUN | gated on 022–025 |
| MF-031 | Dataset / licence / version registry | DONE | `benchmarks/registry.json`, `python -m benchmarks.registry validate --offline` |
| MF-032 | Global manifest and trace schema | DONE | `benchmarks/manifest.py`; `research/results/MANIFEST.json` for past results |
| MF-033 | Strong baselines and oracle falsification | DONE | `benchmarks/checks.py` (8a–8d), used by E1 |
| MF-034 | Cost / token instrumentation | DONE | `benchmarks/cost.py` ledger; model calls already logged by the one client wrapper |
| MF-035 | PersonaMem adapter | NOT_RUN | answering needs a model; on hold |
| MF-036 | Harvey LAB adapter | NOT_RUN | licence review and budget (0.86–3.79M tokens/task, vendor figures) |
| MF-037 | τ-knowledge adapter | NOT_RUN | budget and release pin |
| MF-038 | Context offload / compression ablation | PARTIAL | INT-04 harness runs; the default summariser does not compress, so savings need a compressing summariser |
| MF-039 | Tree vs ontology factorial | PARTIAL | K1 (tree) and E1 (typed filter) both run and both failed their bars; no ontology extraction |
| MF-040 | Statistics and judge audit toolkit | DONE | `benchmarks/stats.py` (paired cluster bootstrap, Wilson, zero-event bound, Holm, sign test, κ) |
| MF-041 | WideSearch harness | NOT_RUN | live web + model |
| MF-042 | Continuous SWE-bench arm | NOT_RUN | Docker + coding model at billions of tokens |
| MF-043 | AA-LCR adapter | NOT_RUN | dataset rights + long-context model |
| MF-044 | Public QA retrieval expansion | NOT_RUN | licence reviews pending; PDF parsing absent |
| MF-045 | Security / fault long-horizon world | PARTIAL | GOV conformance suite; a long-horizon combined world is not built |
| MF-046 | Multi-physical-host stress | BLOCKED | needs machines |
| MF-047 | Scorecard + generated release report | DONE | `python -m benchmarks.scoreboard`; release bundle report |
| MF-048 | Public reproduction package | NOT_RUN | after licence decision |
| MF-049 | Pilot outcome instrument | PARTIAL | pilot report exists; needs pilots |
| MF-050 | External auditor / benchmark review | BLOCKED | needs an outside reviewer |

## Governance conformance GOV-01 – GOV-24

Mapped test by test in `tests/test_gov_conformance.py` (which fails if a mapped test disappears).
**20 COVERED, 3 PARTIAL (GOV-16 export/import of tombstones, GOV-18 single collateral report,
GOV-23 skills), 1 BLOCKED (GOV-20 multi-physical-host).** Writing it found a **tenant-isolation bug**
(GOV-07): copy recognition linked identical text across tenants, so a withdrawal in one tenant
contested another's memory. Fixed in schema 0.14.0.

## Benchmark suites PUB-01 – PUB-15, INT-01 – INT-10

See [the scoreboard](../research/results/BENCHMARK_SCOREBOARD.md): each suite's source, licence
state, the vendor's number kept as theirs, and our run or the reason there is none. Run this round:
INT-01 (descriptive), INT-03 (E1, **FAIL**), INT-04 (descriptive). Vendor-table arithmetic: two of
TencentDB's stated token reductions disagree with their own displayed totals (WideSearch 61.38% vs
61.30%, SWE-bench 33.09% vs 31.63%), as the masterplan noted.

## Engineering epics E0 – E8

| Epic | Status | Done | Not done |
|---|---|---|---|
| E0 baseline and debt | DONE | status page, manifest, ADR, release-bundle stamp, version-consistency check | — |
| E1 knowledge ingestion v2 | PARTIAL | spans, parser version, MIME, size limit, crash-recoverable re-import, tenant property test | HTML/PDF/DOCX/CSV adapters, tables as cells, batch import with preview |
| E2 typed knowledge | PARTIAL | typed filter / count / distinct / group / join with completeness certificate | entity/relation/qualifier types, extraction, promotion workflow; E1 failed |
| E3 retrieval and evidence | NOT_RUN | — | fixed-budget downstream evaluation needs a model |
| E4 collective belief | NOT_RUN | (existing hypothesis sets kept) | real-agent experiments |
| E5 causal / procedural | NOT_RUN | — | registrations and budget |
| E6 security and privacy | PARTIAL | GOV suite, tenant fix | external pen test (BLOCKED) |
| E7 reliability and ops | PARTIAL | existing fault matrix and multihost (one host) jobs | multi-physical-host (BLOCKED), 1M-memory ladder |
| E8 developer experience | PARTIAL | existing quickstarts, fresh-machine CI | independent onboarding study (BLOCKED) |

## Research questions RQ1 – RQ10

RQ3 (bitemporal) has a working harness (INT-01); RQ1 has its first study (E1, failed). RQ2, RQ4–RQ10
are **NOT_RUN**: each needs real model runs, which are on hold, or outside participants.

## Product, operations, legal (§8, §11–§13)

Discovery interviews, design partners, pricing research, editions, licence strategy, compliance
assessment and an external security review are **BLOCKED**: they are decisions or relationships that
belong to the owner, not changes to this repository. Nothing here claims SOC 2, ISO 27001, GDPR or
sector compliance.
