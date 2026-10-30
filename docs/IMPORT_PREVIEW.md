# Operator document preview and atomic batches (experimental)

Preview a normal compiled JSON document or any supported local format:

```bash
python -m memory_fabric --db project.db import-docs handbook.md --format markdown --doc-id handbook --source-version v2 --dry-run
```

The JSON plan includes the store head, compiled-input digest, added section
paths, unchanged/withdrawn source IDs, potential downstream IDs and related
authorization-event sequences within the selected tenant. It contains no source
content. A preview is structural: it does not approve sources or predict ingest
screen results. Related authorization attempts are not proof an effect occurred.
Potential descendants are an upper bound, not a claim all independent support
will be invalidated. This is an operator API, not an agent-facing read endpoint.

Apply with `--expected-head <head>` and `--expected-plan <digest>` from the
reviewed preview. A changed store or changed inputs refuses before source
writes. Re-preview after unrelated activity, including audit events. `--dry-run`
does not import/withdraw/validate records, even if `--activate` is present.
Opening an explicitly created new store still performs normal store initialization.

For a batch, prepare a JSON list of compiled document objects (the same
`doc_id/version/sections` contract used by ordinary `import-docs`). IDs must be
unique per batch, with 1–100 documents, at most 10,000 sections and 20 MB of input.
Use `--batch --dry-run`, then `--batch --expected-head ... --expected-plan ...`.
All batch entries use the selected `--tenant`; entries cannot override that
boundary. Compile mixed local formats through `document_formats.compile_file`
before assembling the manifest. CLI batch manifests themselves are JSON.

Every source still passes through the existing governed importer and remains a
candidate unless the operator explicitly uses `--activate`. Validation occurs
before writes, and one existing event-log transaction commits the whole batch.
A failed or interrupted transaction is rolled back by the existing store path;
retry the same compiled manifest. If a batch already committed, source digests
make retry idempotent. A stale reviewed-head guard intentionally requires a new
preview instead of guessing whether an earlier operation committed.

No prior events are deleted. To undo approved source changes, first preserve a
normal verified backup and key backup under the existing operational runbook.
Review and re-import the approved prior source as a new revision, or restore
the verified backup into an isolated store for incident review. Do not restore
erased keys or overwrite a live federation with an old snapshot. External model
screening costs, if explicitly configured, are not refunded by a DB rollback.

Preview scans current metadata and action receipts; large-store indexing and
preview UX remain separate performance work. The plan is not a completeness or
action-authority certificate. Python callers can use `plan_batch` and
`apply_batch` from `memory_fabric.import_preview`.
