# Release evaluation: 0.9.0 (plan Task 13)

Covers the work from the [safety plan](AI_SAFETY_CYBER_RESEARCH_IMPLEMENTATION_PLAN.md),
Tasks 0–12, on branch `claude/wonderful-newton-t55gww`. **Not a release.**
Nothing is tagged and nothing is published to PyPI. "0.9.0" is the schema and
package version string only.

## 1. Suites run

| Suite | Command | Result |
|---|---|---|
| Unit and integration, SQLite | `python -m unittest discover -s tests -t .` | **1273 tests OK, 36 skipped** (baseline was 1152) |
| New and changed modules on Postgres 16 | the same modules with `MF_TEST_POSTGRES_URL` | **195 OK**. CI runs every storage module on Postgres |
| Fault matrix | `python -m experiments.faultsim` | 17/17 |
| Secret scan | `python tools/scan_secrets.py` | exit 0 |
| Compile | `python -m compileall -q memory_fabric experiments tests examples tools` | exit 0 |

The 36 skips are unchanged from the baseline: the Postgres-only file, and live
model harnesses without Ollama or an API key.

## 2. Frozen and measured evaluations

| Evaluation | Kind | Outcome |
|---|---|---|
| [P5 PoisonWorld](../research/results/p5-poisonworld.md) | Pre-registered before the harness existed. 10 seeds, 7 arms, oracle and degenerate arm | H5b, H5c and H5d supported. **H5a not supported** as registered. One disclosed harness ordering fix |
| [P9 incidents](../research/results/p9-incidents.md) | Measurement against live withdrawal | Precision 0.996, recall 1.000 after a 20% false-attribution evaluator bug was found and fixed |
| [P10 auditing](../research/results/p10-audit.md) | Measurement | Triggered policies find every planted problem; periodic sampling finds 32% |
| [P12 load](../research/results/p12-load.md) | Operational measurement | Throughput falls as agent processes are added. See below |
| [P1 chains](../research/results/p1-evidence-chain-reconstruction.md) | Earlier, pre-registered | Still NOT SUPPORTED. `retrieve` remains the default |

All of these benchmarks are internal and hand-built. **No independent scenario
family exists**, so the plan's gate "do not claim general effectiveness without
frozen held-out results and at least one independent scenario family" is
**not met**, and no general-effectiveness claim is made.

## 3. Review

| Area | What was checked | Finding |
|---|---|---|
| Authorization | Every new entry point: `certify`, `verify_certificate`, the gate, mental models, incident, auditor | `certify` leaked another tenant's versions and roots. Fixed before commit and tested. The gate checks the grant before evidence. A session re-verifies its credential |
| Ingest screens | Every write path | **Two bypasses found and fixed**: metadata unscreened, `revise` unscreened |
| Derived content | Security class through `derive` | **Downgrade found and fixed**: a summary of `restricted` content was written `internal` |
| Cryptography | Certificates are hashed (SHA-256) for identity and are not signed. They carry no authority, so a signature would add nothing the re-verification does not. Suite selection was changed for one failure mode | **A broken `cryptography` install crashed every write** (pyo3 panic, a `BaseException`, found on this host under Python 3.11). It now falls back to encrypt-then-MAC, warns, and `doctor` reports it. AES-GCM content stays unreadable there and is refused, never mistaken for erasure |
| Persistence | One additive event type (`ActionGated`). Schema 0.9.0. No migration needed | Rollback tested (§5) |
| Action-time checks | TOCTOU | The residual race after `verify` returns is documented (S14), not solved |
| Determinism | Every benchmark is seeded. Time budgets are opt-in | P5 rerun to identical metrics. `tests/test_poisonworld.py` checks a seed reproduces |

## 4. Known limitations

- Paraphrased injections pass the pattern screen: 65% of fabric's residual P5 harm.
- Before a compromise is detected, validated poison is indistinguishable from truth.
- Tenancy is logical. Existence concealment is opt-in.
- Write contention collapses throughput beyond a few concurrent writer processes (P12).
- Lineage-gated actions and action certificates have close prior art (MemLineage, PCAA), and no comparison was run ([RESEARCH_ROADMAP.md](RESEARCH_ROADMAP.md)).
- Lint and type checking are still not configured (baseline gap 7).

## 5. Rollback

The change is additive, so rolling back is a code rollback with no data step.

1. Reinstall the previous version (0.8.0, commit `d05ab2d`).
2. Stores written by 0.9.0 open and replay. **Tested:** 0.8.0 read a 0.9.0
   store with mental models and an `ActionGated` event, loaded every memory,
   and verified the hash chain. `doctor` reports `schema version` as **FAIL**
   ("events it does not understand are being skipped"). That is expected and
   is the only finding.
3. Behaviour that reverts with the code: metadata screening, screening on
   `revise`, class inheritance in `derive`, certificates, the gate and the
   auditor. Memories quarantined by the new screens **stay quarantined**,
   because the decision is in the log. Release them through review if needed.
4. No migration has to be undone.
