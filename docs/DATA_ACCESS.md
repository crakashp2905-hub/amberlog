# DATA_ACCESS.md — every public way to reach a memory

`Memory Fabric` has fifty public members. **Three return memory content**, and
only two of those are safe for an agent — while the unsafe one is the shortest
to type.

The classification lives in `tests/test_data_access_paths.py`, not here, and
that is deliberate: a document listing a surface drifts the moment someone adds
a method, and a test does not. Adding a public member to `Memory Fabric` now
fails that test until it is classified. This page explains the categories; the
test is the authority.

## The categories

| Category | Meaning | Safe for an agent? |
|---|---|---|
| **Enforced** | returns content, through the enforcement layer | **yes** |
| **Metadata** | reads *about* a memory, never its content | yes |
| **Inspection** | reads, bypassing enforcement | **no** — operators only |
| **Mutation** | changes state | depends on the operation |
| **Plumbing** | the store object's own lifecycle | n/a |

## The three that return content

| Member | What it does |
|---|---|
| `retrieve` | filters on lifecycle and tenant **before the index is consulted**, so an ineligible memory cannot be ranked, scored, logged or leaked by a bug in a policy |
| `use` | the single enforced read; returns no memory when the decision refuses, and audits the refusal **without the content** |
| `get` | **returns a withdrawn memory.** Inspection only |

`get` behaves that way on purpose: an operator judging whether a withdrawal was
justified has to read what was withdrawn. The cost is that an adapter holding
it is one autocomplete from serving retracted knowledge to a model, and it
would look exactly like working code.

## What the audit found

Writing the enforcing test flagged every `fabric.get(` in the shipped examples
and adapters. Two were real:

- **`adapters/claude.py` and `adapters/ollama.py`** called `get()` to tell a model what happened to its own write — needing only the lifecycle state, not the content. They now use `lifecycle_of()`, a content-free accessor added for exactly this.
- **`examples/agent_on_the_fabric.py`** printed an operator view with `fabric.get()`. It now uses `operator(fabric, actor).inspect()`, which says "I mean the unenforced read" out loud. An example is the thing adapter authors copy.

The rest were false positives from a detector matching any line containing both
`.get(` and `fabric`, which caught ordinary dict lookups like
`state.withdrawal_basis.get(...)`. The detector is a regex on a fabric-like
receiver now.

## Rules for an adapter

1. **Read through `AgentClient`**, which has no `get`, no `state`, no `history`, no `audit_trail` and no `quarantine` — asserted by test.
2. **Ask for metadata with `lifecycle_of`**, never by fetching a memory and reading one field off it.
3. **Operator views go through `operator(fabric, actor)`** or `Session.inspect`, which requires the operator role *and* stays inside the session's tenant.
4. **Hold a `MemoryService`, not a `Memory Fabric`**, in application code. The service exposes no public route to the fabric and hands out only credential-derived sessions that re-verify per call.
