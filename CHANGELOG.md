# Changelog

Format follows [Keep a Changelog](https://keepachangelog.com/). Versions track the
**memory schema**, not the Python API — see [VERSIONING.md](VERSIONING.md) for why.

## [Unreleased]

### Added: operator import preflight and atomic batches
- `import-docs --dry-run` previews one-tenant structural impact without source writes.
  `--expected-head`/`--expected-plan` guard reviewed input and state; `--batch`
  commits compiled JSON document lists atomically with idempotent retries.

### Added: local format adapters and federation regression world
- `import-docs --format csv|html|docx|pdf` uses the existing governed compiled-tree
  contract. PDF requires the optional `documents` extra; core dependencies remain empty.
- Text input preserves CRLF bytes, fixing source hashes and citation offsets in CLI imports.
- INT-02 exercises five stores, scheduled partitions, chain/star correction propagation,
  independent support survival and post-correction action authorization.
