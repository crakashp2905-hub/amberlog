# Historical explicit-ID reads (experimental)

```python
from amberlog.history_query import query

receipt = query(fabric, "reader", [memory_id], known_at=log_sequence,
                valid_at=event_time, max_events=10_000)
for row in receipt.rows:
    print(row.version, row.content, row.superseded)
```

`known_at` is an inclusive event-log sequence, not a wall-clock timestamp.
`valid_at` is optional fact-validity time. Stable `retrieve(as_of=...)` retains
its existing meaning. This initial API reads explicit IDs, not arbitrary search.
The requested agent and tenant must be non-empty; omitted tenant means the
default tenant, never an operator view spanning all tenants.

Both the historical snapshot and the current store must permit access. Current
withdrawal, contested state, source withholding, erasure or loss of collection
permission suppresses the row. A grant made after the snapshot cannot reveal a
record that was historically private to another agent. No inaccessible record
counts or omission reasons are returned. Authorized lineage pointers may be
redacted when their own permissions do not hold.

Receipts include snapshot sequence, valid time, current head, replay count,
elapsed time and archival-only rows. Each row identifies the original version,
actual recording-event time/sequence, validity window, current version and
whether it has been superseded. Historical text is decrypted only after current
and historical authorization checks, using existing keys. Erased content and
keys are never restored. Reads log existing retrieval/exposure events with an
explicit deterministic historical policy and propensity; no new event schema
or index is introduced.

Archival results carry neither an action token nor an action certificate.
Current protected effects must still go through the normal action gate with
current evidence, grants, policy and freshness checks. An old version does not
become current evidence by being historically readable.

Replay is capped at 10,000 events by default (configurable between 1 and 100,000),
and at most 100 requested IDs. Exceeding the bound refuses the entire request;
there is no silent partial replay. Replay/authorization/output materialization
use the existing store fence, so large requests can delay writers. No checkpoint
acceleration, hosted historical endpoint or workload SLO is claimed. Use smaller
requests until representative replay costs justify an acceleration design.

Tests: `tests/test_history_query.py`; descriptive seeded qualification:
`python -m benchmarks.history_reads`. The raw qualification report records its
own producing commit. Additional partition/import/legacy checkpoint cases remain
open in the checklist tracker.
