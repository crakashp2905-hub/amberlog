# Public SDK contract — 0.14 series

Memory Fabric remains alpha. This contract describes the existing 0.14 surface; it
does not turn experimental modules into stable APIs. The exact public method
signatures are pinned in `tests/data/memory-fabric_api.json` and checked by
`tests/test_data_access_paths.py`. [API.md](API.md) is generated from the code;
[STABILITY.md](../STABILITY.md) defines the promises of each module tier.

## Supported behavior

- `from memory_fabric import MemoryFabric` is the canonical store entry point. Construct
  it with an existing SQLite file or the documented optional PostgreSQL URL.
- `memory_fabric.sdk.agent` returns an agent-scoped client. Agent reads use `recall`,
  `fetch` and `verify`; they must not be replaced by raw operator inspection.
- Raw store `get`, history and inspection can expose withdrawn records to an
  authorized operator. They are not agent authorization or action credentials.
- Writes carry provenance, validation/lifecycle changes are logged, and replay
  rebuilds projections. Existing stored data and fixed cryptographic labels do
  not change in the packaging-layout migration.
- Protected actions require an action policy and fresh evidence checks.
  `authorize` is a point-in-time decision; use the documented `execute` fence
  for the bounded local concurrency guarantee.
- Model wrappers and integrations remain optional. The wheel has no required
  runtime dependencies. Optional protocol clients used in CI are development
  dependencies, not new core requirements.

The 0.14 stable-tier compatibility promise is unchanged: preserve names and
meaning within the minor series and deprecate removals before a later minor
release. Beta and experimental surfaces have the narrower promises in
STABILITY.md. Unknown attributes, private helpers, message wording, implementation
paths, experimental certificates and inferred semantic truth are not stable
contracts. Keep schema compatibility separate from Python API compatibility.

## Qualification

The source layout is `src/memory_fabric`; the installed import remains `memory-fabric`.
`tools/check_typed_consumer.py` installs a built wheel outside the checkout,
clears `PYTHONPATH`/`PYTHONHOME`, verifies the import comes from that installation,
accepts a strictly typed consumer and rejects an incompatible assignment.
The package CI job runs this positive/negative check with mypy.

`tests/test_mcp_official.py` uses the official MCP Python client over a real
stdio subprocess. It negotiates the protocol, lists the expected agent tools,
refuses a foreign-tenant record and stops accepting evidence after a correction
committed through another connection. It uses no model or paid API. This proves
that tested client/version path, not all clients, transports or agent frameworks.

Legacy import aliases remain deliberately excluded under the owner's complete
rename decision. The prior distribution identity is not controlled by this
project; a shim could shadow unrelated software. Existing data compatibility,
authenticated pre-migration vectors and the upgrade/rollback drill remain the
migration contract. See [MIGRATING_TO_MEMORY_FABRIC.md](MIGRATING_TO_MEMORY_FABRIC.md).
