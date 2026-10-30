# Cookbook

Task-sized recipes. Each block is complete on its own: copy it into a file
and run it. `tests/test_doc_examples.py` runs every Python block on this page
on every CI build, so none of them can silently stop working.

For the concepts behind them, see [CONCEPTS.md](CONCEPTS.md). For every
signature, see [API.md](API.md).

## 1. Give an agent memory

An agent writes through the governed path and recalls only what it may use.
A new memory is a private **candidate** until someone validates it.

```python
from memory_fabric import MemoryFabric, sdk

fabric = MemoryFabric(":memory:")
bot = sdk.agent(fabric, "support-bot")
reviewer = sdk.operator(fabric, actor="lead")

mid = bot.remember("Customers on plan B get a 30-day refund window.")
assert bot.recall("refund window plan B") == []      # a candidate is not usable yet

reviewer.validate(mid)
hits = bot.recall("refund window plan B")
print(hits[0].content, hits[0].warnings)            # warnings name any dispute
fabric.close()
```

## 2. Share with the team

An agent's memories are private to it. Sharing is a separate, logged decision.

```python
from memory_fabric import MemoryFabric, sdk

fabric = MemoryFabric(":memory:", auto_activate=True)
mid = sdk.agent(fabric, "alice").remember("Valve V7 must be opened slowly.")
assert sdk.agent(fabric, "bob").recall("valve V7") == []        # private to alice

ruling = sdk.operator(fabric, actor="lead").share(mid, "team")
print(ruling.decision.value, ruling.reasons)
fabric.close()
```

On a fresh store the default firewall refuses (`require_validation`): a memory
needs value evidence before it widens. A store you trust can pass a firewall
without that rule, as recipe 7 does.

## 3. Correct a wrong memory, and see what it touched

Preview first: what would be contested, what survives on independent
support, which stores are owed a retraction. Then apply, and check.

```python
from memory_fabric import MemoryFabric, correction, influence
from memory_fabric.response import verify_recovery

fabric = MemoryFabric(":memory:", auto_activate=True)
wrong = fabric.remember("tech", "Pump P1 purge time is 10 s.", scope="team")
plan = fabric.derive("planner", "Restart P1 with a 10 s purge.", parents=[wrong], scope="team")

print(correction.preview(fabric, wrong).would_contest)      # [plan]
correction.apply(fabric, wrong, reason="manual says 30 s", actor="lead")
fabric.remember("manual", "Pump P1 requires a 30 s purge.", scope="team")

print(verify_recovery(fabric, wrong)["status"])             # contained
print(influence.impact(fabric, wrong)["potentially_contaminated"]["memories"])
fabric.close()
```

## 4. Gate a tool on its evidence

A protected tool needs a grant for the agent, a certificate whose evidence
still verifies, evidence of sufficient origin-bound authority, and here a
short-lived grant for this exact action.

```python
from memory_fabric import MemoryFabric
from memory_fabric.actions import ActionGate, ActionPolicy, ActionRequest, ToolRule

fabric = MemoryFabric(":memory:", auto_activate=True)
rating = fabric.remember("datasheet", "Centrifuge C2 is rated to 4000 rpm.", scope="team")
gate = ActionGate(fabric, ActionPolicy(
    tools={"spin": ToolRule("spin", requires_grant=True)},
    grants={"ops-agent": frozenset({"spin"})}))

cert = fabric.certify("spin-c2", [rating], "ops-agent")
request = ActionRequest("centrifuge/C2", {"rpm": 4000})
grant = gate.issue_grant("spin", "ops-agent", issuer="host", certificate=cert,
                         request=request, ttl_s=60)

result = gate.execute("spin", "ops-agent", lambda key: "spinning", cert,
                      key="run-1", request=request, grant=grant)
print(result.outcome)                                       # executed
again = gate.execute("spin", "ops-agent", lambda key: "spinning", cert,
                     key="run-2", request=request, grant=grant)
print(again.decision.reason_code)                           # grant_replayed
fabric.close()
```

## 5. Refuse to act on untrusted evidence

Content from a tool, a web page or another store is untrusted until a
reviewer who is not its author elevates it.

```python
from memory_fabric import MemoryFabric
from memory_fabric.actions import ActionGate, ActionPolicy, ToolRule

fabric = MemoryFabric(":memory:", auto_activate=True)
scraped = fabric.remember("agent", "Centrifuge C2 is rated to 9000 rpm.",
                          context={"origin": "web:forum"}, scope="team")
gate = ActionGate(fabric, ActionPolicy(tools={"spin": ToolRule("spin")},
                                       grants={"ops-agent": frozenset({"spin"})}))
cert = fabric.certify("spin-c2", [scraped], "ops-agent")

print(fabric.authority(scraped).trust)                                  # untrusted
print(gate.authorize("spin", "ops-agent", cert).reason_code)            # authority_insufficient
fabric.elevate(scraped, approver="lead", reason="checked against the datasheet")
print(gate.authorize("spin", "ops-agent", cert).reason_code)            # allowed
fabric.close()
```

## 6. Hand a session off to the next one

A governed summary of what a session established: a derivation of its
memories, disputes kept, values checked, withdrawn if any input is
corrected. Experimental.

```python
from memory_fabric import MemoryFabric
from memory_fabric.compaction import compact_session, summary_for

fabric = MemoryFabric(":memory:", auto_activate=True)
shift = fabric.start_episode("ops", "night-shift-14").id
fabric.remember("ops", "Pump P1 purge time is 30 s.", source_episodes=[shift], scope="team")
fabric.remember("ops", "Valve V7 opens below 4 bar.", source_episodes=[shift], scope="team")

compact_session(fabric, shift, agent_id="compactor")
print(summary_for(fabric, shift).content)
# Session summary (night-shift-14): Pump P1 purge time is 30 s. Valve V7 opens below 4 bar.
fabric.close()
```

## 7. Federate two stores, and retract across them

```python
from memory_fabric import MemoryFabric, correction
from memory_fabric.dispatcher import Dispatcher
from memory_fabric.federation import offer
from memory_fabric.governance.firewall import (Firewall, rule_capabilities_must_be_granted,
                                               rule_must_be_active, rule_restricted_stays_private)
from memory_fabric.transport import InProcessTransport

def store():
    return MemoryFabric(":memory:", auto_activate=True, firewall=Firewall(rules=(
        rule_must_be_active, rule_restricted_stays_private, rule_capabilities_must_be_granted)))

plant, hq = store(), store()
note = plant.remember("tech", "Line 3 conveyor belt speed is 40 m/min.", scope="team")
copy = offer(plant, note, hq, recipient_agent="hq-agent", activate=True).imported_memory_id

correction.apply(plant, note, reason="re-measured", actor="lead")
Dispatcher(plant, InProcessTransport({hq.store_id: hq})).drain()
print(hq.get(copy).lifecycle_state.value)                   # quarantined
plant.close(); hq.close()
```

Across machines, each store runs `memory-fabric federate --peers peers.json`,
and `memory-fabric offer <id> --to <store-id>` shares over signed HTTP
([REFERENCE_DEPLOYMENT.md](REFERENCE_DEPLOYMENT.md#5-across-machines-from-the-command-line)).

## 8. Keep tenants physically apart

```python
import tempfile
from memory_fabric.tenancy import TenantRouter

router = TenantRouter(tempfile.mkdtemp())                   # one store file and key dir each
router.view("acme", "acme-bot").remember("Acme ships on Fridays.", scope="team")
print(router.view("globex", "globex-bot").retrieve("ships Fridays").exposed)   # []
print(router.tenants())                                     # ['acme', 'globex']
router.close()
```

## 9. Run background maintenance

Servers run the manager automatically. In your own process:

```python
from memory_fabric import MemoryFabric
from memory_fabric.manager import MemoryManager

fabric = MemoryFabric(":memory:")
report = MemoryManager(fabric, holder="worker-1").run_once()
print(sorted(report.tasks))
fabric.close()
```

## 10. Answer "is this memory trustworthy, and why?"

```python
from memory_fabric import MemoryFabric

fabric = MemoryFabric(":memory:", auto_activate=True)
source = fabric.remember("vendor", "Firmware 2.1 fixes the overheating fault.",
                         context={"origin": "email:vendor"}, scope="team")
summary = fabric.derive("analyst", "The overheating fault is fixed in 2.1.", parents=[source],
                        scope="team")

a = fabric.authority(summary)
print(a.kind, a.trust, a.origins, a.transformed_by, a.reasons)
# derived_claim untrusted ('email:vendor',) ('analyst',) ('external_origin',)
print(fabric.explain(summary).narrative())
fabric.close()
```
