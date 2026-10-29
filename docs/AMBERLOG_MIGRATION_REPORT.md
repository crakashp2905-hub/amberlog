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

Full local regression: 2,231 tests ran in 851.180 seconds, 46 skipped, no failures
or errors. Two historical-namespace tests added afterward passed separately;
the current collected suite is 2,233. Lint, typing of 152 source files, secret
scanning (zero unexpected findings), documentation checks and the adversarial
gate passed. An initial documentation run raced the rename's index staging;
the link checks passed after staging and in the full regression. This does not
claim that a single full local invocation ran all 2,233 current tests.

Wheel and source archive built and passed strict twine validation. The wheel
contains 141 members including the dashboard, typing marker and license, with
no tests, benchmark datasets, databases or bytecode. Independent wheel and
sdist environments outside the source checkout passed import, assets, CLI,
initialization and doctor checks. Wheel removal left no import or launcher.

The actual v0.11.0 upgrade/backup/rollback/re-upgrade drill passed after repairing
its launcher to read each checkout's own declared namespace. Historical screen
comparisons also resolve modules from the selected checkout and reject ambient
modules from elsewhere, avoiding an invalid current-code-as-baseline result.
The initial CI rollback failure was caused by the renamed launcher targeting
the historical checkout; it was not hidden or waived. Corrected-head CI remains
a separate merge gate. No unrun check is a pass.

Publication is **NO-GO**: name clearance, index account
setup, trusted publishers, protected environments, independent review, pilot and
all other required release gates remain owner/external actions. The owner later
approved and completed the remote rename and About update; destination URLs now
match `crakashp2905-hub/amberlog`. No index upload or tag has been performed.
The recommended local migration
candidate remains 0.14.0; choose a final published version only after those gates.

See [migration plan](AMBERLOG_MIGRATION_PLAN.md),
[migration guide](MIGRATING_TO_AMBERLOG.md),
[release checklist](AMBERLOG_RELEASE_CHECKLIST.md) and
[publishing procedure](PYPI_PUBLISHING.md).
