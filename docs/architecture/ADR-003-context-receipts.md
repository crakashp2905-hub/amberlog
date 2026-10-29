# ADR-003: Context receipts

**Status:** accepted, implemented in `amberlog/context_receipt.py`.

## Context

Retrieval already logs `RetrievalPerformed` and one `ExposureDecided` per
candidate, with propensities. What it does not give is one record of the
*bundle* an agent received: which memory versions and summary nodes, under
which budget, mode, policy and configuration, and what was excluded and why.
Without it, "what did the agent see?" is answered by joining several events,
and summaries are invisible.

## Decision

- `ContextReceipt`: `receipt_id`, tenant, agent, branch and commit,
  `request_digest` (SHA-256 of the query, **never the query**), selected
  items (`memory_id@version` or summary node id with its source refs and
  digest), excluded items with a reason code, token budget and estimated
  use, mode, `policy_id`, `retrieval_config` digest, the log head it was
  built at, and the remaining nondeterminism (none for lexical retrieval;
  named when a model reranks).
- Recorded as a `ContextBuilt` event, so receipts are part of the log,
  survive restarts and are covered by the hash chain. No content, no query.
- Reason codes: `NOT_VISIBLE`, `SOURCE_WITHDRAWN`, `CONTESTED`,
  `BELOW_RELEVANCE`, `OVER_BUDGET`, `SUMMARY_STALE`, `SUMMARY_BLOCKED`,
  `COVERED_BY_SUMMARY`, `WITHHELD_BY_POLICY`.
- `explain_receipt(receipt_id)` re-reads it and reports, for each selected
  item, whether it would still be admissible now — history is not
  permission.

## Test strategy

`tests/test_context_receipt.py`: receipts carry no content or query text,
exclusions name a reason, a receipt explains a later withdrawal, receipts
are tenant-scoped.
