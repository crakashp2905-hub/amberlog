# Amberlog migration report

The implementation package, distribution and command are `amberlog`; the public
store class is `Amberlog`. The owner explicitly chose a complete namespace
rename with breaking imports/commands and preserved stored data. No aliases ship.
The package remains version 0.14.0, schema 0.14.0, alpha and proprietary. This is
a new distribution identity, not a new stability or research claim.

The implementation directory was renamed once, with relative imports retained.
Absolute imports, public type references, CLI/MCP setup, variables, cookies,
peer header, package metadata, Docker/Helm, dashboard, examples, tests, tooling,
generated references and documents were updated. Existing owner/license rights
are unchanged. Historical artifacts were relabelled; original commits remain
available and regenerated digests do not claim a rerun.

Baseline: 56 crypto/profile/governance tests passed before renaming. An initial
baseline command named a nonexistent plural test module; the corrected command
passed. After migration, 60 focused tests passed. A first resource smoke test
used an incorrect asset filename; the assertion was corrected to the actual
dashboard asset. No production resource or security check was weakened.

A prior-source encrypted SQLite store passed identity, plaintext decryption,
unchanged event digest and hash-chain checks after migration. Two authenticated
content envelope vectors captured before the rename are retained in tests; the
optional AES suite is checked when available. Fixed key-derivation/AAD bytes are
unchanged. Mixed-version federation and historical Python pickles are not
qualified; communicating peers must be upgraded together.

Broader regression, build, archive inspection, clean installs and exact-head CI
results will be recorded after execution. No unrun check is a pass.

Publication is **NO-GO**: name clearance, target repository URLs, index account
setup, trusted publishers, protected environments, independent review, pilot and
all other required release gates remain owner/external actions. No upload,
external rename or tag has been performed. The recommended local migration
candidate remains 0.14.0; choose a final published version only after those gates.

See [migration plan](AMBERLOG_MIGRATION_PLAN.md),
[migration guide](MIGRATING_TO_AMBERLOG.md),
[release checklist](AMBERLOG_RELEASE_CHECKLIST.md) and
[publishing procedure](PYPI_PUBLISHING.md).
