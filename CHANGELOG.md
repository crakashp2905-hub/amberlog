# Changelog

Format follows [Keep a Changelog](https://keepachangelog.com/). Versions track the
**memory schema**, not the Python API — see [VERSIONING.md](VERSIONING.md) for why.

## [0.2.0] — 2026-10-07

### Added
- **Packaging.** Installable wheel, a `memory-fabric` console script, and the dashboard bundled as package data. CI checks the wheel actually contains it, because a missing static file only fails in front of a user.
- **Duplicate suppression.** `remember` returns the existing memory and emits `MemoryDuplicateSuppressed` when an agent rewrites content it already wrote *in the same episode*, compared after normalising whitespace and case. Scoped to one episode deliberately: the same claim on two occasions is two observations, and that genuinely is more evidence.
- **Ollama adapter** — local models and real embeddings (`OllamaEmbedder`), with no new dependency since Ollama speaks HTTP over `urllib`. This replaces the hashed bag-of-words placeholder wherever a model is available.
- **Federation** across store boundaries: the recipient's firewall decides, imports arrive unvalidated, and provenance crosses with them.
- **`AgentSession`** — writes scoped to one agent and one episode, so an adapter cannot attribute work to another agent.
- **Schema version reporting.** `overview` names the installed schema version and every version that wrote into the log, and warns when the log is newer than the build reading it. A projection silently skips events it does not recognise, which is the right behaviour and a terrible failure mode to hit without being told. Versions compare numerically, because `0.10.0` sorts below `0.2.0` as a string.
- **Container image.** A wheel on `python:3.13-slim`, non-root, with the store on a volume because the event log is the source of truth. CI builds it and checks the server answers on the published port and refuses unauthenticated requests.
- **Secret scanner** (`tools/scan_secrets.py`) pointing the project's own detector at its own repository, wired into CI.
- [VERSIONING.md](VERSIONING.md) — the guarantee is on the event log, not the Python API, because a renamed argument costs a minute and an unreplayable log costs the data.
- CI across Python 3.11–3.13 on Linux and Windows, run with **no dependencies installed**, because the zero-dependency claim is only true if it is checked.

### Fixed
- **`explain()` leaked secrets.** Redaction lived in the observability layer, but an explanation is a display surface too: printing one to a terminal showed the exact credential the firewall had quarantined the memory for containing. Found by a live model run, not by the 384 tests that existed at the time. Scrub helpers now live beside the detector in `governance/sensitive.py` and both surfaces share them.
- **`auto_activate` promoted imports**, defeating the guarantee that value earned in one store does not cross to another.
- **Mutating HTTP methods desynchronised the connection.** An unhandled POST left its body unread, so the next request on a keep-alive connection parsed mid-body. They are now refused with `405` and an `Allow` header after draining.
- **Quadratic listings.** The IPS estimator rescanned every exposure record per memory; now indexed once per `fit`. 12× faster at 400 memories, and it scales.
- **Retention treated epoch 0 as "no timestamp"**, silently making every memory immortal.
- **Retrieval had no relevance floor**, so a query with nothing to match returned the least-bad rows in the store.
- **The API emitted invalid JSON.** `Infinity` for an unknown value estimate — which Python reads back happily and `JSON.parse` rejects outright, so every non-Python client broke while the test suite stayed green.
- **Signed hashing could cancel to zero**, crashing the embedder on `log(0)`.
- **The CLI crashed on Windows** consoles that cannot encode box-drawing characters, and silently created an empty store when `--db` was mistyped.

### Changed
- Schema `0.1.0` → `0.2.0`. Additive; old logs replay unchanged.

## [0.1.0] — 2026-09-27

Initial prototype: append-only event log as the source of truth, rebuildable projections, provenance and lineage, TMS-style retraction, governance (sensitive-data detection, firewall, retention), exposure logging with propensities, value estimation, and read-only observability behind token auth.
