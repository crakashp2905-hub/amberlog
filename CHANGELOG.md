# Changelog

Format follows [Keep a Changelog](https://keepachangelog.com/). Versions track the
**memory schema**, not the Python API — see [VERSIONING.md](VERSIONING.md) for why.

## [Unreleased]

### Added: optional exact phrase-dictionary compaction
- Lossless, bounded phrase factoring for repetitive session text with verified
  reconstruction and extractive fallback; no model-token or task-success claim.
- Compaction enforces current source scope/tenant, prevents visibility widening
  and refuses stale-source commits. Erasure now also reaches compaction summaries.
