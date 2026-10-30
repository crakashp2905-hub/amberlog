# Capability registry

Generated from `product/capabilities.json` by `tools/gen_capabilities.py`; do not edit. Every module, test and surface named here is checked against the code by `tests/test_capability_registry.py`.

| status | meaning |
|---|---|
| **available** | implemented, tested, documented and supported (module tier stable or beta) |
| **experimental** | implemented behind an explicit flag or experimental API, with known limitations |
| **planned** | designed, not implemented |
| **unsupported** | out of scope or not guaranteed |

## Available

### Write a memory through the ingest screens

`memory.write.screened` — I need memories stored with provenance, and secrets or injections kept out.

- **Surfaces:** sdk: `Amberlog.remember`, mcp: `remember`
- **Code:** `src/amberlog/_fabric/writes.py`, `src/amberlog/governance/firewall.py`, `src/amberlog/governance/sensitive.py`
- **Tests:** `tests/test_fabric.py`, `tests/test_governance.py`, `tests/test_sensitive_patterns.py`
- **Limitation:** Screens catch known patterns only; a novel injection can pass.
- **Limitation:** A plausible first claim about something the store has never seen cannot be checked (staging run).

### Retrieve with tenant, scope and lifecycle enforced

`memory.retrieve.governed` — An agent must only see memories it may use now.

- **Surfaces:** sdk: `Amberlog.retrieve`, mcp: `recall`, cli: `search`, dashboard: `search`
- **Code:** `src/amberlog/_fabric/retrieval.py`, `src/amberlog/model.py`
- **Tests:** `tests/test_scope_visibility.py`, `tests/test_access_matrix.py`, `tests/test_properties_authz.py`
- **Limitation:** Lexical ranking by default; recall@1 is low when many notes share a tag (research/results/product-bench.md).

### Explain where a memory came from

`memory.provenance.inspect` — I need to know why the system remembers this.

- **Surfaces:** sdk: `Amberlog.explain`, mcp: `trace_provenance`, cli: `show`, dashboard: `memories/{id}`
- **Code:** `src/amberlog/explain.py`, `src/amberlog/lineage.py`
- **Tests:** `tests/test_observability.py`, `tests/test_transitive_retraction.py`
- **Limitation:** Only provenance the system recorded can be shown.

### Lineage of ancestors and descendants

`memory.lineage.graph` — I need to see what was derived from a memory.

- **Surfaces:** sdk: `Amberlog.lineage`, cli: `lineage`, dashboard: `memories/{id}/lineage`
- **Code:** `src/amberlog/lineage.py`, `src/amberlog/observability/report.py`
- **Tests:** `tests/test_observability.py`
- **Limitation:** Depth-bounded; lineage recorded by callers through parents only.

### Version and event history of a memory

`memory.history.audit` — I need to see how a memory changed and who changed it.

- **Surfaces:** cli: `audit`, dashboard: `memories/{id}/audit`
- **Code:** `src/amberlog/observability/report.py`, `src/amberlog/eventlog.py`
- **Tests:** `tests/test_observability.py`, `tests/test_integrity_chain.py`

### Preview and apply a withdrawal, with stale-preview protection

`governance.correction.preview` — Before withdrawing a memory I need to see what it touches, and the preview must still hold when applied.

- **Surfaces:** sdk: `correction.preview`, mcp: `preview_correction`, cli: `correct`, dashboard: `memories/{id}/correction`
- **Code:** `src/amberlog/correction.py`, `src/amberlog/incident.py`
- **Tests:** `tests/test_correction.py`
- **Limitation:** Recipients outside this store report on themselves; delivery is verified only by their acknowledgement.

### Retraction propagates to descendants and peers

`governance.retraction.propagation` — A withdrawn memory must not survive in copies or conclusions.

- **Surfaces:** sdk: `Amberlog.request_retraction`, cli: `correct`, dashboard: `propagation`
- **Code:** `src/amberlog/lineage.py`, `src/amberlog/justification.py`, `src/amberlog/outbox.py`, `src/amberlog/transport.py`
- **Tests:** `tests/test_retraction.py`, `tests/test_transitive_retraction.py`, `tests/test_retraction_protocol.py`, `tests/test_multihop_http.py`, `tests/test_restatements.py`
- **Limitation:** A peer that never acknowledges stays pending; it is shown, not forced.
- **Limitation:** Restatements of a value (notes not linked by lineage) are contested only on a revision or a withdrawal recorded as contradicted.

### Status labels with stated limits

`governance.status.labels` — I need to know what the store has and has not established about a memory.

- **Surfaces:** sdk: `status.labels`, cli: `show`, dashboard: `memories/{id}`
- **Code:** `src/amberlog/status.py`
- **Tests:** `tests/test_status.py`
- **Limitation:** No label says a memory is true.

### Contradictions kept as competing claims

`governance.conflicts.preserved` — When sources disagree I need both claims, not a silent overwrite.

- **Surfaces:** sdk: `adapters.context.build_context`, mcp: `recall`
- **Code:** `src/amberlog/conflicts.py`, `src/amberlog/adapters/context.py`
- **Tests:** `tests/test_conflicts.py`
- **Limitation:** Detected for structured claims and value statements; free-text disagreement can be missed.

### Action-time re-check of every memory an action relies on

`governance.action.fence` — A memory withdrawn after it was read must not drive an action.

- **Surfaces:** sdk: `actions.ActionGate`, mcp: `verify`
- **Code:** `src/amberlog/actions.py`, `src/amberlog/enforcement.py`, `src/amberlog/certificates.py`
- **Tests:** `tests/test_action_fence.py`, `tests/test_visibility_at_action.py`, `tests/test_action_crash.py`
- **Limitation:** Covers tools run through the gate only.

### Tenant isolation on every access path

`tenancy.isolation` — One tenant must never read or infer another's memories.

- **Surfaces:** sdk: `Amberlog.for_tenant`, cli: `tenants`
- **Code:** `src/amberlog/tenancy.py`, `src/amberlog/identity.py`
- **Tests:** `tests/test_tenancy.py`, `tests/test_access_matrix.py`, `tests/test_metadata_leakage.py`
- **Limitation:** Single store; tenants share a process and its keys.

### Context receipts: what an agent was given, and what was excluded and why

`context.receipt` — I need to reproduce and explain exactly what context an agent received.

- **Surfaces:** sdk: `context_receipt.build_context`, mcp: `build_context`, cli: `context`, dashboard: `receipts`
- **Code:** `src/amberlog/context_receipt.py`
- **Tests:** `tests/test_cli_versioning.py`, `tests/test_context_map.py`, `tests/test_dashboard_versioning.py`, `tests/test_mcp_extended.py`
- **Limitation:** Token counts are estimates (characters / 4), not a tokenizer.
- **Limitation:** Exclusions list candidates retrieval returned; memories below the relevance floor are not listed.

### Branches, commits, diff and governance-aware merge

`versioning.branches` — I need to try memory changes in isolation and merge them with conflicts surfaced.

- **Surfaces:** sdk: `branching.Branches`, mcp: `branch_create`, cli: `branch`, dashboard: `branches`
- **Code:** `src/amberlog/branching.py`
- **Tests:** `tests/test_branching.py`, `tests/test_cli_versioning.py`, `tests/test_dashboard_versioning.py`, `tests/test_mcp_extended.py`
- **Limitation:** No branch of a branch; merges go into main only.
- **Limitation:** Branch retrieval is the overlay view; it is not ranked by the store's retrieval arms.

### Signed federation between stores, with key rotation

`federation.signed` — Stores on different machines must share validated memories and retractions safely.

- **Surfaces:** sdk: `Amberlog.share`, cli: `federate`
- **Code:** `src/amberlog/federation.py`, `src/amberlog/transport.py`, `src/amberlog/protocol.py`
- **Tests:** `tests/test_federation.py`, `tests/test_federation_transport.py`, `tests/test_remote_offer.py`, `tests/test_key_rotation_drill.py`
- **Limitation:** No consensus; each store decides for itself.

### Cryptographic erasure of content

`privacy.erasure` — Deleted personal data must not be recoverable from history.

- **Surfaces:** sdk: `Amberlog.erase_content`, cli: `erase`
- **Code:** `src/amberlog/governance/erasure.py`, `src/amberlog/governance/cipher.py`
- **Tests:** `tests/test_erasure.py`, `tests/test_erasure_residue.py`
- **Limitation:** Backups taken before erasure hold their own copy until they expire (docs/LIMITATIONS.md).

### Hash-chained log with checkpoints

`integrity.chain` — I need to detect a rewritten or truncated history.

- **Surfaces:** cli: `checkpoint`, dashboard: `posture`
- **Code:** `src/amberlog/integrity.py`, `src/amberlog/eventlog.py`
- **Tests:** `tests/test_integrity_chain.py`, `tests/test_checkpoint_rewrite.py`
- **Limitation:** Detects rewrites against a checkpoint held elsewhere; does not prevent them.

### Read-only operator dashboard

`operations.dashboard` — An operator needs to see the store without changing it.

- **Surfaces:** cli: `serve`, dashboard: `overview`
- **Code:** `src/amberlog/observability/server.py`, `src/amberlog/observability/report.py`
- **Tests:** `tests/test_observability.py`, `tests/test_auth.py`
- **Limitation:** Read-only by design; changes go through the CLI or SDK.

### Release evidence and product benchmark for the exact commit

`evaluation.release_evidence` — Release numbers must come from the commit being released.

- **Code:** `tools/release_bundle.py`, `tools/release_report.py`, `experiments/product_bench.py`
- **Tests:** `tests/test_release_report.py`
- **Limitation:** Synthetic corpus; one process.


## Experimental

### Session compaction into one governed summary

`context.compaction.session` — A later session cannot read every turn of an earlier one.

- **Surfaces:** sdk: `compaction.compact_session`
- **Code:** `src/amberlog/compaction.py`
- **Tests:** `tests/test_compaction.py`, `tests/test_context_compact.py`
- **Limitation:** One summary per episode; no hierarchy.

### Governed Context Map: source-linked summaries, invalidation and a budgeted planner

`context.map` — Long histories must fit a token budget without losing their sources or using stale summaries.

- **Surfaces:** sdk: `context_map.ContextMap`
- **Code:** `src/amberlog/context_map.py`
- **Tests:** `tests/test_context_map.py`
- **Limitation:** extractive-v1 keeps every distinct fact verbatim, so it saves tokens only on restatements and chatter.
- **Limitation:** Summary nodes live in process memory and are rebuilt per process.

### Governed decay view: recent memories whole, older ones summarised, agent-written summaries

`context.decay` — A session needs what is currently known within a fixed budget, without withdrawn or superseded values.

- **Surfaces:** sdk: `decay.DecayView`, mcp: `wake`, cli: `context`
- **Code:** `src/amberlog/decay.py`
- **Tests:** `tests/test_decay.py`, `tests/test_mcp_extended.py`, `tests/test_cli_versioning.py`
- **Limitation:** Pre-registered bars narrowly not met (research/results/decay-view.md), though the view beat recency on every seed.
- **Limitation:** Inspired by OptMem's published design; no OptMem code is used (upstream has no licence).
- **Limitation:** With real local models the registered bar was missed (qwen2.5:7b 0.12, llama3.1:8b 0.53 of the headroom); model summaries can pick an older real value, which the check cannot catch.


## Unsupported

### Compliance certification

`compliance.certification` — A regulator asks for a certificate.

- **Limitation:** No external audit has been done (docs/SECURITY_REVIEW.md O7). No legal review of deletion semantics.
