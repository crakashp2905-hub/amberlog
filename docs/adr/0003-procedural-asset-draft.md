# ADR 0003: draft governed procedural asset contract

Status: draft schema only (N28); no publication or execution API is enabled.
Implementation remains behind the checklist's pilot-demand gate.

Use the existing procedural memory type and versioned derivation provenance.
An optional structured payload has schema `procedural-asset/1` with:

| Field | Contract |
|---|---|
| procedure_id, revision | Stable identity and immutable positive revision |
| parameters | Named typed inputs, bounds and required/optional status |
| preconditions, postconditions | Explicit assertions with external evaluators |
| steps | Ordered declarative tool requests; never arbitrary executable source |
| required_capabilities | Requirements only, never grants |
| originating_runs | Source episode IDs and independent verified outcomes |
| verifier, owner, reviewer | Identities bound through existing tenant policy |
| evaluation | Test corpus/config digest, results, failed tests and evidence |
| approval | Version-bound reviewer decision; absent means candidate |
| trust, scope, tenant | Inherited governance constraints, never inferred promotion |
| dependencies | Versioned source memories and upstream procedures |
| invalidation | Revocation/expiry policy and regression triggers |
| rollback | Reviewed compensating steps, affected targets and idempotency policy |

Lifecycle: propose candidate → human/independent review → externally verified
tests → explicit publication → action-gated use → deprecate/withdraw. A new
revision is a new candidate, not inherited approval. The author cannot verify
its own outcome. A successful run is insufficient to authorize every fact or
tool in a procedure. Withdrawal and erasure reach derived assets via existing
lineage; imported candidates never self-activate. Execution checks identity,
target, parameters, current grants and evidence immediately before each effect.

Qualification needs comparisons against static instructions and plain snippets,
permission revocation mid-procedure, tool/schema drift, partial effects, retries,
rollback failures and cross-tenant imports. No learning or safety claim follows
from merely adopting this payload schema.
