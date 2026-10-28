# Changelog

Format follows [Keep a Changelog](https://keepachangelog.com/). Versions track the
**memory schema**, not the Python API — see [VERSIONING.md](VERSIONING.md) for why.

## [Unreleased]

### Added: experimental historical explicit-ID reads
- `history_query.query` replays a bounded log snapshot, intersects historical and
  current authorization, and returns archival receipts with logged exposures.
  Current erasure/withdrawal wins; no historical action credentials are issued.

### Fixed: experimental typed-query completeness and privacy
- Missing join and aggregate keys no longer yield falsely complete results.
  Aggregates preserve caller filters; incomparable predicate values remain unknown.
- Default queries stay in the default tenant and exclude crypto-erased records.
  Scalar join semantics distinguish booleans/strings from numbers and do not join nulls.
- Generated status reports no longer depend on locally fetched tags; result
  digests use explicitly documented LF-normalized bytes across platform checkouts.
