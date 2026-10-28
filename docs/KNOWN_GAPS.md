# Known gaps

What the masterplan asks for that this repository does not yet do, in one place. Each line links to
the tracker row that says why. Product limitations for users are in [LIMITATIONS.md](LIMITATIONS.md).

## Engineering

- **No HTML, PDF, DOCX or CSV import.** Documents arrive as Markdown or as a compiled JSON tree (MF-007).
- **Historical reads are bounded explicit-ID queries.** Experimental `history_query.query` intersects current and historical authorization; no historical semantic search, checkpoint acceleration, or `retrieve(known_at=τ)` overload is supplied. Stable valid-time `as_of` is unchanged (MF-017).
- **Typed queries cover writer-typed fields only.** No extraction of entities or relations; the exhaustive-filter study failed (MF-010, MF-039).
  Join/aggregate completeness now includes missing or malformed scalar keys rather than silently dropping them. These experimental queries do not establish real-world truth.
- **The default compaction summariser does not compress** a log whose lines all carry values; it keeps every value by design (MF-038).
- **No export/import of a store that carries tombstones across stores** beyond backup/restore (GOV-16).
- **No procedural-skill asset type** (MF-020, GOV-23).

## Evidence

- **No public agent benchmark has been run with a model**: Harvey LAB, τ-knowledge, WideSearch, SWE-bench, AA-LCR, PersonaMem and the rest are NOT_RUN with reasons in the [scoreboard](../research/results/BENCHMARK_SCOREBOARD.md).
- **33 of 100 recorded results do not name the commit** that produced them; none records a dataset digest or prompt hash ([manifest](../research/results/MANIFEST.json)).
- **Multi-host behaviour is measured on one physical host** (GOV-20, MF-021, MF-046).

## Outside the repository

External security review, independent replication, onboarding study with outside developers,
design partners, pricing and licence strategy (MF-022–MF-029, MF-050).

See [MASTERPLAN_TRACKER.md](MASTERPLAN_TRACKER.md) for every item.
