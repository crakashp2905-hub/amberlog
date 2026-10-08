# Versioning

The version number on this project tracks the **memory schema**, not the Python API.

## Why that way round

The event log is the source of truth (AGENTS.md principle 3). Everything else —
memory records, value estimates, agent profiles, the dashboard's read model — is a
projection that can be thrown away and rebuilt. That inverts the usual stability
question. A caller who upgrades and finds a renamed keyword argument gets a
`TypeError` on the first run and fixes it in a minute. A caller who upgrades and
finds that a four-month-old event no longer replays has lost the data itself,
and no amount of care at the call site would have warned them.

So the guarantee is placed where the irreversible damage is:

> **Any event ever written by a released version replays on every later version of
> the same major series.**

`SCHEMA_VERSION` in `memory_fabric/model.py` is the authority on the schema;
the version in `pyproject.toml` is what `pip` sees. They are equal today, at
`0.2.0`, and the invariant that is actually tested
(`test_package_version_is_not_behind_the_schema`) is the weaker one:

> the package version is never *behind* the schema version.

It is allowed to run ahead, because a release can contain only Python-API or
packaging changes and those should not claim a new schema. The direction that is
forbidden is the one that would lie: a build advertising an older version than
the events it writes.

## What each position means

| Change | Example | Bump |
|---|---|---|
| A new event type, or a new optional field on an existing one | `MemoryDuplicateSuppressed` in 0.2.0 | minor |
| A new projection derived from existing events | the triage read model | minor |
| An event type's meaning changes, or a required field is added, removed or retyped | — | major, with a migration |
| Projection output changes while events stay the same | a value estimate's formula | minor; rebuild from the log |
| Python API: a public function's signature | `remember(..., episode_id=)` | minor, noted in CHANGELOG |

Additive schema changes are the normal case and are safe by construction: a
projection folds events it recognises and ignores the rest, so an old log simply
never produces the new event. That is why 0.1.0 logs replay unchanged on 0.2.0.

A **breaking** schema change requires all three of: a major bump, a migration
script under `tools/`, and a note in SPEC.md recording what the old events meant
(AGENTS.md principle 10). There has not been one yet.

## Pre-1.0

While the major version is 0, the Python API is explicitly unstable, and the
CHANGELOG is the place changes to it are recorded. The schema guarantee above
holds anyway — it is not waiting for 1.0, because the logs being written now are
the ones that would be lost.

What 1.0 will mean: the API surface in SPEC.md §API v0 settles, and the estimator
whose output drives retention and federation decisions has been validated against
live agents rather than only RuleWorld. Neither is true today.

## Checking a store

```bash
memory-fabric --db store.db overview
```

The `schema` row names the installed version and, when they differ, every version
that actually wrote into the log — events are never rewritten, so a store that has
outlived an upgrade carries both. `--json` gives the same thing as
`schema_version` and `log_schema_versions`.

A store written by a *newer* version than the installed package will usually still
open, because a projection folds the events it recognises and ignores the rest.
That is the right behaviour and a bad failure mode to hit unannounced, so the
overview's diagnostics say it outright rather than quietly reporting figures that
are missing part of the history.
