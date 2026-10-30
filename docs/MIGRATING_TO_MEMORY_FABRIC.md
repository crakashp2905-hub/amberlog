# Migrating to Memory Fabric

This is a complete namespace rename, explicitly authorized to break former
imports and launch commands. It is not a backward-import compatibility release.
Update integrations together before deployment. Existing stored data remains
on schema 0.14.0; do not edit its event rows or encryption metadata.

## Install and update callers

Build an approved artifact locally until index publication is confirmed:

```
python -m build
python -m pip install dist/memory-fabric-0.14.0-py3-none-any.whl
memory-fabric --help
```

Use the canonical namespace and class:

```python
from memory_fabric import MemoryFabric

with MemoryFabric("memory.db") as store:
    mid = store.remember("agent", "Dispatch requires review.", scope="team")
    store.validate(mid, actor="reviewer")
    result = store.retrieve("agent", "dispatch review")
```

Replace the former package imports with `memory_fabric` and the former store class
with `MemoryFabric`, including type annotations, dynamic imports and patch targets.
Replace launch commands with `memory-fabric` or `python -m memory_fabric`. No retired
namespace aliases ship. Historical Python pickles are not a supported migration
format; re-create client objects using the supported store API.

## Configuration and deployments

Use `MEMORY_FABRIC_DB`, `MEMORY_FABRIC_KEYS`, `MEMORY_FABRIC_TOKEN`, `MEMORY_FABRIC_MODEL`,
`MEMORY_FABRIC_CRYPTO_PROFILE`, `MEMORY_FABRIC_LOG_FORMAT`, `MEMORY_FABRIC_LOG_LEVEL` and
`MEMORY_FABRIC_SHARE_POLICY` where the corresponding setting is needed. Values and
security defaults are unchanged; retired variable names are not read.
Update service units, containers, Helm values, secret references and monitoring
commands. Re-register MCP through `memory-fabric --db memory.db connect <tool>`;
review the output before using `--write`. The MCP server identifier and cookie
namespace are now Memory Fabric-specific, so browser sessions require sign-in again.

Keep a verified backup of the database and a separate backup of its content
keys. Open the same database/key locations; do not initialize over them or
restore erased keys. Run `memory-fabric --db memory.db doctor` before production use.
No automatic event rewrite or schema bump is part of this rename.

## Compatibility boundaries

The prior-source synthetic SQLite fixture was opened and decrypted after the
rename with its event digest and hash chain unchanged. Authenticated pre-rename
content vectors are pinned in the regression suite. Key-derivation and AAD
domain bytes are fixed format constants represented in hex, not new branding.

New-to-new federation uses the renamed transport header. Mixed-version peer
interoperability has not been qualified; upgrade communicating peers together
or keep them isolated until tested. Import aliases, environment aliases,
historical pickles and unchanged MCP configurations are not supported.

Historical reports in this tree have normalized terminology only. Their
original source commits remain immutable in Git. Relabelled artifacts and
regenerated file digests are not new benchmark runs or improved results.

Rollback by reinstalling the previous approved code and restoring its launch
configuration. Do not rewind a live event log or restore destroyed content keys.
