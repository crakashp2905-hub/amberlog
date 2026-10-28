# Known gaps

What the masterplan asks for that this repository does not yet do, in one place. Each line links to
the tracker row that says why. Product limitations for users are in [LIMITATIONS.md](LIMITATIONS.md).

## Engineering

- **No PDF import.** Markdown, HTML, CSV and .docx compile with the standard library; PDF needs a third-party parser (MF-007).
- **Typed queries cover writer-typed fields only.** No extraction of entities or relations; the exhaustive-filter study failed (MF-010, MF-039).
- **The default compaction summariser does not compress** a log whose lines all carry values; it keeps every value by design (MF-038).
- **Encrypted stores move only with backup/restore** (SQLite) or the database's tools: `export-events` keeps every tombstone, but encrypted content is sealed to its store and `import-events` refuses it (GOV-16).

## Evidence

- **Only one public benchmark has been run with a model, and only a small local one** (PersonaMem, qwen2.5:3b, descriptive). Harvey LAB, τ-knowledge, WideSearch, SWE-bench, AA-LCR and the rest are NOT_RUN or BLOCKED with reasons in the [scoreboard](../research/results/BENCHMARK_SCOREBOARD.md).
- **33 of 100 recorded results do not name the commit** that produced them; none records a dataset digest or prompt hash ([manifest](../research/results/MANIFEST.json)).
- **Multi-host behaviour is measured on one physical host** (GOV-20, MF-021, MF-046).

## Outside the repository

External security review, independent replication, onboarding study with outside developers,
design partners, pricing and licence strategy (MF-022–MF-029, MF-050).

See [MASTERPLAN_TRACKER.md](MASTERPLAN_TRACKER.md) for every item.
