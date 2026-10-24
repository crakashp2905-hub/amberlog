# Memory Fabric 0.13.0 — release notes (in qualification)

**Not yet tagged and not published.** Released through the same gate as
0.11.0 and 0.12.0: CI green on the exact commit, acceptance on a fresh
machine, the release evaluation, and then the tag and publication, which wait
for the owner's decision. Every change is listed in the
[CHANGELOG](../CHANGELOG.md).

## Upgrading

Schema 0.13.0 opens 0.12.0 stores unchanged ([MIGRATION.md](MIGRATION.md)).

**Behaviour that changes on upgrade:**

| change | effect | to keep 0.12.0 behaviour |
|---|---|---|
| `min_independent_sources` above one is enforced on its own | A tool rule or certificate asking for two independent sources now refuses one (`insufficient_independent_support`) | ask for 1 |
| Agent API `verify` answers for memories not yet recalled | A withdrawn memory comes back `usable: false` with its reason, not as a 409 | none needed |
| Claim checks read codes with separators (`H-14`, `K/31`) | Contradicting "updates" to such equipment are held for review | `MemoryFabric(hold_suspicious=False)` |

## New

- **Answerability verdicts** next to retrieval results, separate from retrieval scores.
- **Retrieval profiles** per workload, and a ranking method per call.
- **Strict freshness**: signed leases for imported evidence, with `ToolRule(require_fresh=True)`.
- **One-command checkpoint anchoring** (`anchor`) and its verification.
- **Signed action receipts** that anyone with the public key can verify (`receipt-verify`).
- **Decision dependence** and **consensus by independent source**.
- **The Memory Control Center** in the dashboard, and `memory-fabric sandbox`.
- **Operations**: tenant isolation patterns, a PostgreSQL failover runbook, supported scale up to 400 agents per `agent-api`, and alerting via `doctor --webhook`.

## Known limits

See [LIMITATIONS.md](LIMITATIONS.md), which the dashboard also shows. The
largest is unchanged: no independent security review has taken place, and that
review blocks 1.0.
