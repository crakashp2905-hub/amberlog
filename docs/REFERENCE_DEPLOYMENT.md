# Reference deployment

A two-store federation you can run end to end in about five minutes, to see the
one claim this project has actually earned: **when shared knowledge is retracted,
the correction propagates, the recipient enforces it, and the system can show
what has and has not been verified.**

Everything below is tested. The sequence is
`tests/test_sdk.py::TestEndToEndDemonstration`, and the fault behaviour is
`experiments/faultsim.py`.

---

## 1. Install

```bash
pip install .
```

Zero runtime dependencies, Python 3.11–3.13 on Linux, macOS and Windows — all
checked in CI with nothing installed, because a zero-dependency claim is only true if it
is tested that way.

```bash
python -m unittest discover -s tests -t .    # 661 tests
python -m experiments.faultsim               # 12 fault scenarios
```

Both should pass before you trust anything else here.

## 2. Two stores

```bash
memory-fabric --db origin.db --create demo
memory-fabric --db recipient.db --create demo
```

Each store mints an opaque identity on first open and records it in its own log,
so it survives a restore from backup:

```bash
memory-fabric --db origin.db --json overview | python -c "import json,sys; print(json.load(sys.stdin)['schema_version'])"
```

Identities are `st_`-prefixed ULIDs. **Never a path** — two containers each
holding `./store.db` would otherwise be indistinguishable, and `:memory:` would
identify every in-memory store.

## 3. The demonstration, in Python

```python
from memory_fabric import MemoryFabric, WithdrawalBasis
from memory_fabric.dispatcher import Dispatcher, reconcile
from memory_fabric.federation import offer
from memory_fabric.governance.firewall import (
    Firewall, rule_capabilities_must_be_granted,
    rule_must_be_active, rule_restricted_stays_private,
)
from memory_fabric.justification import JustificationKind, justification_context
from memory_fabric.sdk import NotUsable, agent, operator
from memory_fabric.transport import InProcessTransport, Peer, PeerRegistry

firewall = Firewall(rules=(
    rule_restricted_stays_private, rule_must_be_active,
    rule_capabilities_must_be_granted,
))
origin = MemoryFabric("origin.db", firewall=firewall)
recipient = MemoryFabric("recipient.db", firewall=firewall)

# 1. The origin records a fact.
a, op_a = agent(origin, "ag_a"), operator(origin, "sup_a")
fact = a.remember("Yard tug tyre pressure is 3.5 bar in winter.")
op_a.validate(fact)

# 2. The recipient imports it and derives a conclusion.
imported = offer(origin, fact, recipient, recipient_agent="ag_b")
b, op_b = agent(recipient, "ag_b"), operator(recipient, "sup_b")
op_b.validate(imported.imported_memory_id)
plan = recipient.derive(
    "ag_b", "Inflate the yard tug to 3.5 bar before the frost.",
    parents=[imported.imported_memory_id],
    context=justification_context(
        [(imported.imported_memory_id, JustificationKind.REQUIRED)]
    ),
)
op_b.validate(plan)

usable = b.fetch(plan)          # enforced read, with a token
print(usable.content)

# 3. The recipient goes offline. 4. The origin retracts, durably.
registry = PeerRegistry({origin.store_id: Peer(origin.store_id, "unused", b"key")})
offline = InProcessTransport(
    {recipient.store_id: recipient}, registry=registry,
    offline={recipient.store_id},
)
op_a.retract(
    fact, reason="manufacturer bulletin: 2.8 bar",
    recipients=[recipient.store_id],
    basis=WithdrawalBasis.CONTRADICTED.value,
)
Dispatcher(origin, offline).run_once()
print(op_a.propagation())       # still owed; the recipient is not 'verified'

# 5. It reconnects and reconciles from its own cursor.
since = recipient.outbox.missed_since(origin.store_id)
reconcile(recipient, origin.retractions_since(since), origin.store_id)

# 6-8. Enforced, blocked, and the conclusion contested on remaining support.
print(b.recall("tyre pressure winter"))        # []
print(recipient.get(plan).lifecycle_state)      # contested
print(op_b.support(plan).reason)

# 9. The stale consequential action is blocked at action time.
print(b.verify(usable).reason_code)

# 10. The operator can see why.
print(op_b.explain(imported.imported_memory_id).narrative())
```

Run it twice. Step 5 is idempotent, so the second run changes nothing — which is
the property that lets a recipient replay more than it needs rather than less.

## 4. Over a real socket

The in-process transport above exercises the protocol semantics. For the network
path, serve the recipient and point an `HttpTransport` at it:

```python
from memory_fabric.transport import HttpTransport, Peer, PeerRegistry, serve

key = b"a-key-shared-between-these-two-stores"
recipient_registry = PeerRegistry({origin.store_id: Peer(origin.store_id, "unused", key)})
served = serve(recipient, recipient_registry)          # 127.0.0.1, ephemeral port

origin_registry = PeerRegistry({recipient.store_id: Peer(recipient.store_id, served.endpoint, key)})
Dispatcher(origin, HttpTransport(origin_registry, origin.store_id)).run_once()
```

Four things are enforced rather than advised, and each has a test:

- An **unsigned** retraction is refused with 401 and applied to nothing.
- A retraction signed with the **wrong key** is refused, and the failure is marked permanent so it is not retried forever.
- An **unknown peer** cannot reconcile: `PeerRegistry` is the authorisation boundary, so a store cannot be made to trust somewhere it was never configured for — and it cannot tell a refusal apart from a store that does not exist, or the boundary would be an enumeration oracle.
- A **malformed body** is refused with a rejection code rather than a stack trace, and without echoing the parser's own message about the bytes it was given.
- A **refusal says nothing else.** Not this store's id, not its event-log head sequence, not how far it has read an origin's sequence. The full acknowledgement used to be the 401 body, which made the head sequence a pollable activity oracle for anyone who could reach the port. It is still recorded locally — saying nothing to the caller is not the same as recording nothing.

A signature proves who sent a retraction and that it was unmodified. It proves
**nothing** about whether the retracted claim was false.

## 5. Operating it

```bash
memory-fabric --db origin.db attention      # what needs a human, worst first
memory-fabric --db origin.db overview       # can this store support a value claim?
memory-fabric --db origin.db serve          # read-only dashboard on 127.0.0.1
memory-fabric --db origin.db backup /backups/origin-$(date -u +%Y%m%dT%H%M%SZ).db
```

`backup` takes a consistent snapshot while the store is live, then **replays the
copy** and fails if the event count does not match — a truncated backup opens
perfectly well, which is why the check exists.

The dashboard and the JSON API are **read-only**, including the propagation view
at `/api/propagation`. The federation write path is a separate server on its own
port with its own credentials; an observability tool that wrote exposure events
while an operator browsed would feed its own browsing into the data every value
estimate is computed from.

See [DEPLOYMENT.md](../DEPLOYMENT.md) for backup, capacity, upgrades and the
list of unsupported modes.

## 6. Troubleshooting

| Symptom | Cause |
|---|---|
| `memory-fabric: error: unrecognized arguments: --json` | `--json` is a global flag and goes **before** the subcommand. |
| `backup` refuses with exit 6 | The store is `:memory:`. There is nothing on disk and `--db :memory:` opens an empty one. |
| A retraction stays `queued` forever | Nothing is draining the outbox. Run a `Dispatcher`; it is a loop you drive, not a background thread. |
| `TransportError ... permanent=True` | No peer configured for that store id, or a bad key. Retrying will not help. |
| Recipient reports `rejected` / `unknown_memory` | It holds no import of that exact memory **version**. A retraction of v1 does not apply to v3. |
| Recipient reports `superseded` | The retraction's `origin_sequence` is below the recipient's cursor for that origin: a delayed older correction, correctly not applied. |
| `PolicyViolation: ... has been content-erased` | Erasure is terminal for a memory's content. Record new information as a new memory. |
| A memory is `contested` and you expected `active` | Support was recomputed after a premise was withdrawn. `operator.support(id).reason` says which premise and why. |
| `NotUsable: ... withdrawn_on_weak_evidence` | It was withdrawn on co-occurrence with a failure or with no stated basis. Phase A measured that policy destroying more correct memory than wrong; consider releasing it. |

## 7. What this deployment is not

Stated here because a working demo invites the wrong conclusion. From
[docs/AUDIT.md](AUDIT.md):

- **One writer.** SQLite. Concurrent writers are unsupported and untested.
- **No agent or tenant identity.** Store identity is real and authenticated across the federation boundary; `agent_id` is still a caller-supplied string.
- **No TLS.** Use a reverse proxy or a private network.
- **No encryption at rest** for the database as a whole. Content is sealed per memory and a single memory's key can be destroyed, but the keys sit beside the ciphertext.
- **No transitive re-sharing.** An importer may not re-share onward, so an origin always knows its recipients. Lifting that is what would force a peer-to-peer substrate, and it is deliberately out of scope.
- **Value-ranked exposure is not recommended.** Three live attempts lost to cheap baselines, and the ranking has a [known defect](../research/decisions/2026-10-10-value-ranking-ignores-uncertainty.md).

On the readiness ladder in the product roadmap this is **step 5 of 7** — a
fault-tested reference system. Step 6 needs agent and tenant identity, TLS and
key management, none of which exist.
