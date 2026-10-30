# Failure policy and external side effects

This matrix describes current behavior, not a claim that a database transaction
can atomically commit an arbitrary external service's side effect. The decision
and execution paths are in `src/amberlog/actions.py`, `enforcement.py`, and
`certificates.py`; regression evidence includes `tests/test_action_fence.py`,
`tests/test_action_crash.py`, `tests/test_visibility_at_action.py`,
`tests/test_certificates.py`, `tests/test_sdk.py` and `tests/test_identity.py`.

| Operation or failure | Policy | Caller responsibility |
|---|---|---|
| Unknown tool or absent tool grant | Refuse before evidence lookup | Obtain an explicit host-owned policy/grant |
| Protected action missing a certificate | Refuse | Gather eligible evidence and issue the required certificate |
| Retracted, erased, revised, expired or currently unauthorized evidence | Refuse the protected action | Re-read current evidence; do not reuse an old decision |
| Required action check or store unavailable | Fail closed with an unavailable/refusal result | Repair availability, then re-verify |
| Explicitly unprotected tool during a memory outage | Can run without memory evidence | The host must deliberately mark it unprotected; agents cannot grant this |
| High-risk enforced read with unavailable required checks | Refuse/defer rather than claim usable | Resolve uncertainty or abstain |
| Lower-risk/selective read policy | Optional checks may be omitted under its configured policy | Do not treat omitted checks as passed, or as action authorization |
| Raw operator inspection | Can show withdrawn records for diagnosis | Keep it outside untrusted agent surfaces |
| Federation peer offline or delivery failure | Record pending/failure state; never invent acknowledgment | Retry/reconcile through the durable queue and inspect delivery status |
| Unknown side-effect outcome after crash or timeout | Do not silently retry as a fresh action | Reconcile the external system and use explicit idempotent retry |

## What the execution fence guarantees

For a callback that completes within the configured lease, `execute` verifies
evidence and runs the callback while holding the store write transaction. A
concurrent retraction writer waits until that fenced execution finishes. The
action therefore linearizes before the retraction or is refused after it; it
does not promise the callback can be undone.

The callback must not call back into the same store. An overlong callback has
the fence released after its lease, and its external effect may still complete.
A process crash or a failed final database commit can leave an external effect
without a durable local receipt. An `authorize` result alone is already stale
once returned. None of these cases is a distributed exactly-once transaction.

Give the external system the action's idempotency key and require that system
to deduplicate it. On an unknown outcome, inspect the external state before
explicit retry; retry re-verifies evidence and cannot reuse the prior verdict.
Use `unfenced_changes` to investigate evidence invalidated after a released
fence. Preserve the unknown state in incident records rather than declaring
success or claiming rollback of the external system.

During partitions, strict freshness policies can refuse actions when a required
origin lease is absent or expired. Lenient policies can accept stale evidence;
they trade safety for availability and are not equivalent to strict freshness.
Local simulated partitions do not establish a physical-network staleness SLO.
