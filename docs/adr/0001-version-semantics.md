# ADR 0001 — What the version numbers mean, and what is released

**Status:** accepted 2026-10-28 (masterplan MF-003).

**Context.** The masterplan review found three numbers that read as if they
disagreed: `pyproject.toml` 0.13.0, `SPEC.md`'s header 0.12.0, and release
notes for 0.13.0 that pin commit `125f838` while `main` has moved on.

**Findings.**
- `SPEC.md`'s header was stale: its newest section is already 0.13.0 and
  `model.SCHEMA_VERSION` is 0.13.0. Fixed, and now checked on every run by
  `tools/status_at_head.py --check` and `tests/test_status_at_head.py`.
- The package version tracks the schema (VERSIONING.md); it may run ahead,
  never behind. That invariant was already tested.
- Nothing is tagged or published. "0.13.0" names a schema and a candidate
  baseline, not a release; work merged after `125f838` is not part of it.

**Decision.**
1. A *release* is a tag on a commit whose release-evidence bundle
   (`tools/release_bundle.py`) has every check green, including the new
   `versions consistent` check. Until a tag exists, docs say "candidate".
2. Schema changes keep requiring a SPEC section, a `SCHEMA_VERSION` bump and a
   migration (AGENTS.md principle 10); the SPEC header must equal
   `SCHEMA_VERSION`, enforced by test.
3. Python-API changes after a release follow STABILITY.md tiers: stable APIs
   are covered by `tests/test_fabric_structure.py`'s recorded public surface.

**Consequences.** Version drift becomes a failing test rather than a review
finding. Tagging remains a maintainer decision and is not done by automation.
