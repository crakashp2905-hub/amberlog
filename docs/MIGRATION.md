# Migration

Upgrades run on open, are idempotent, and need no command, with **one
exception, 0.10.0**. Read the row for every version you cross. Take a backup
first (`amberlog --db <store> backup <file>`): it is the only way back
past a schema version ([OPERATIONS.md §5](OPERATIONS.md#5-rollback)). The
whole path is drilled in CI against the last release
(`experiments/rollback_drill.py`).

## Version by version

| to | what changed | what you do |
|---|---|---|
| 0.4.0 | per-hop retraction target | nothing: `inbox` and `outbox` are rebuilt on open |
| 0.5.0 | tenant identity | nothing: absent means `tn_default` |
| 0.6.0 | authenticated content (`enc:v2`) | nothing: `enc:v1` stays readable and is never rewritten |
| 0.7.0 | bitemporal validity | nothing: absent means open-ended |
| 0.8.0 | copy recognition | nothing |
| 0.9.0 | action gating (`ActionGated`) | nothing |
| **0.10.0** | **scope is enforced on reads**; collections | **Decide once.** To keep the old visibility (every active memory readable by its tenant), run `amberlog --db <store> share --all-private-active --actor <you>`. Restricted memories are refused and listed rather than widened. Skip it if per-agent privacy is what you want |
| 0.11.0 | the action fence (`ActionExecuted`); exposure records; the import provenance chain | nothing. Imports made earlier have no chain and fall back to their immediate origin. `Acknowledgement.state_revision` now counts the origin's own retractions (wire format unchanged) |
| 0.12.0 | the background memory manager (`ManagerLease`, `MaintenanceRan`) | Nothing is required. Servers now **start the manager**: pass `--no-maintain` to keep maintenance manual. Give it `--peers` to deliver retractions, and `--checkpoint-dir` to keep checkpoints off-host. Retention deletions need `--retention-delete`. Protected tools now refuse evidence below `unverified` origin-bound authority (tool outputs, imports, instructions, anything descending from a withdrawn memory) unless it is elevated: set `ToolRule(min_authority="untrusted")` to restore the 0.11.0 behaviour |

## Code calling the Python API

- **Stable** modules keep their names within a minor series. **Beta** and
  **experimental** ones may change ([STABILITY.md](../STABILITY.md)). The
  CHANGELOG lists every change.
- **0.10.0** is the one behaviour change callers notice: a memory written
  `private` by one agent is invisible to the others. Pass `scope="team"` for
  knowledge the team shares, or use a collection.
- `derive(scope=…)` caps a conclusion at its narrowest premise's scope.

## Moving in from another memory system

```bash
amberlog --db store.db import export.jsonl --source mem0 --agent importer
```

- **Accepted formats:** a JSON list or JSONL of Mem0 records, LangChain
  documents, or plain `{"content": …}` records.
- **Every record lands as a private candidate waiting for review**, with its
  origin recorded. Nothing imported is trusted until someone approves it:
  `amberlog --db store.db review`.
- **The ingest screens (secrets, prompt injection) run on every record.**
  Flagged records are quarantined, not imported silently.

## Moving between backends

SQLite and PostgreSQL hold the same event log. To move a store, take a
`backup` and replay it into the new backend with the same keys. Check the
result with `doctor` before switching traffic. There is no live dual-write.
