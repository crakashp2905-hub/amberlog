# Release evaluation: 0.11.0 (release gate G6)

**Tagged as `v0.11.0` from `rc/0.11.0`.** The code under test is `7d3fc25`. The
only commit after it is this document, and CI is required to pass on the
tagged commit itself (the release workflow refuses otherwise). Release note:
[RELEASE_NOTES_0.11.0.md](RELEASE_NOTES_0.11.0.md).

## Acceptance at `7d3fc25ea582`

| suite | where | result |
|---|---|---|
| CI, 18 jobs | GitHub Actions | **green**: 9 OS × Python test jobs (Windows, macOS and Linux; 3.11–3.13), Postgres, **Docker container smoke test** (builds, serves the dashboard on the published port, runs as uid 10001, keys on the key volume), package, lint, e2e, faults, secrets, LangChain contract, **Claude contract** |
| Unit and integration, SQLite | Windows 11, Python 3.13, benchmark fixtures built | **1,637 OK**, 15 skipped (Postgres-only 6, anthropic SDK 5, POSIX entrypoint 3, one more) |
| New and changed modules on Postgres 16.2 | 25 modules, the adapters included | **268 OK** |
| Fault matrix | `experiments.faultsim` | **17/17** |
| Live integration path | `experiments.live_ollama --quick`, qwen2.5:3b, through `session.recall` → `build_context` → model → verified outcome (at `22a7d30`; only tests changed since) | no memory 0%, correct memory **100%**, wrong memory 0% (misled every time), contested **67%** |

**Found by acceptance and fixed before the tag:**

- the Claude contract fixture predated F10 (scope enforced on reads);
- a Postgres connect had no timeout (a 131 s hang);
- the fence tests compared clock ticks, not log order;
- a concurrency test lost worker errors with the thread;
- two tests were still asserting behaviour that F12 and the 0.11.0 bump had
  changed.

**Not validated:** the live Claude API. There is no credential or CLI in this
environment, so it is covered only by the SDK contract test (WORKPLAN X-API).

## Gates

| gate | status |
|---|---|
| G1 | ✅ CI green on `main` (`12f0fd1`) and on this RC |
| G2 | ✅ except the live Claude call (X-API) |
| G3 | ✅ |
| G4 | ✅ run and published; **not supported** on qwen2.5:3b |
| G5 | ✅ 13 findings, 0 open critical or high |
| G6 | ✅ this document |

## Rollback

The schema is additive. Rolling back to 0.9.x is a code rollback; a store
upgraded with `share --all-private-active` stays shared, which is the
intended direction.

---

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
| [P12 load](../research/results/p12-load.md) | Operational measurement | SQLite: 214 ops/s at 1 agent, 31 at 10, 4 at 100 (p50 19 s). Postgres: 63, 5, 1. No errors, only queueing. Cause not isolated |
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
- **Many agent processes on one store do not work at usable latency** (P12: p50 263 ms at 10 SQLite agents, 19 s at 100). The supported deployment is a few processes per store.
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
