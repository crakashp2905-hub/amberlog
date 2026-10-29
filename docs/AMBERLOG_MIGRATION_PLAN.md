# Amberlog migration plan

Status: implementation authorized for the current source tree; no publication,
remote rename, history rewrite, or account changes are part of this change.
The user's complete-removal request takes precedence over the attached brief's
transition aliases. Canonical distribution, import, command, class and
environment prefix become `amberlog`, `amberlog`, `amberlog`, `Amberlog` and
`AMBERLOG_`. Legacy imports/commands/environment names are intentionally not
retained. If a compatibility transition is later requested, review it separately.

## Dependency map and order

1. Inventory tracked text, package paths, scripts, dashboard, Docker/Helm,
   MCP setup, optional adapters, tests, fixtures, generators and CI.
2. Record a pre-migration store and hash-chain checkpoint outside distributions;
   run pre-migration integrity/governance/crypto tests as a baseline.
3. Keep event JSON/schema, record IDs, encryption envelope versions, key
   derivation labels and associated-data bytes unchanged. Store the fixed
   pre-existing cryptographic labels as explicit hex byte constants. They are
   data-format identity, not a product name to be substituted.
4. Rename the implementation package once and update relative/absolute imports,
   class exports, resource lookup, distribution metadata, commands and variables.
5. Update tracked text/path branding, developer tooling and source snapshots.
   Historical artifacts receive terminology-only normalization; their original
   versions remain at the recorded Git commits. No numerical result or claim is
   improved by renaming. Regenerate derivative hashes with an explicit note.
6. Test prior-store replay/decryption without rewriting events, negative
   governance paths, new imports/CLI, clean wheel/sdist installation and assets.
7. Prepare protected manual publishing with no automatic release/tag. Keep
   publication NO-GO until naming, account setup, all tests and human approval.

## Compatibility matrix

| Surface | Migration contract |
|---|---|
| Public Python/CLI/environment namespace | Breaking rename; update clients/deployments |
| Existing SQLite events and sealed content | Preserve exact stored bytes; verify baseline fixture |
| Event schema version | Unchanged; no storage migration disguised as branding |
| Mixed-version federation | Not claimed until explicit interoperability tests run |
| Backup manifests and peer headers | Audit separately; preserve versioned identity where required |
| Pickles of historical Python classes | Not supported by the complete namespace removal |
| Research artifacts | Reworded presentation, original immutable Git blobs retained |
| Repository URLs | Target URLs require owner-controlled remote rename before publication |

## Risks and rollback

The namespace change deliberately breaks imports, launch scripts, environment
configuration and MCP registrations. Cryptographic label substitution would
make existing ciphertext unreadable and is prohibited. Changing research labels
changes file hashes; document that normalization rather than treating regenerated
hashes as proof of a new experiment. Preserve licensing and alpha status.

Rollback source by returning to the pre-migration branch/commit; reinstall its
wheel and restore deployment configuration. Do not roll back a live database or
restore erased keys. Existing data should not need alteration for either code
version. Keep separate verified database/key backups under the existing runbook.

## External gates

No paid calls or publishing credentials. Amberlog has existing software/domain
usage, so a search is not clearance. Owner must resolve name rights, PyPI and
TestPyPI project acceptance, remote target URLs, protected environments and
trusted publishers before publication. No substitute name is chosen here.
