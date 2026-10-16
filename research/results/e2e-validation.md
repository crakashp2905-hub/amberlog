# End-to-end validation across process boundaries

Produced by `python -m experiments.e2e_validation` at commit `ba303b1`.
**22/22 checks passed.**

- **E1**: an `agent-api` server in its own process, agents in two tenants over
  HTTP, a separate CLI process that quarantines, and an action gate in a third
  process holding a certificate issued before the retraction.
- **E2**: a child killed with `os._exit` inside, then just after, the
  transaction that records a retraction. The store is then reopened and the
  delivery recovered.
- **E3**: the `backup` command, then the copy opened as a store.

| scenario | check | result | detail |
|---|---|---|---|
| E1 | agent-api server starts in its own process | PASS |  |
| E1 | own tenant: recall finds the memory over HTTP | PASS |  |
| E1 | own tenant: verify says usable | PASS |  |
| E1 | other tenant: recall returns nothing | PASS |  |
| E1 | other tenant: fetch is refused without content | PASS |  |
| E1 | gate allows before the retraction | PASS |  |
| E1 | a separate CLI process quarantines | PASS |  |
| E1 | server process sees the retraction: verify not usable | PASS | None |
| E1 | gate in a third process refuses the stale certificate | PASS | evidence_withdrawn |
| E1 | recall no longer returns it | PASS |  |
| E2 | killed inside the retraction transaction: nothing survives | PASS | exit 70 |
| E2 | killed after commit: withdrawn locally and the delivery is still owed | PASS | exit 70, 1 owed |
| E2 | the recipient has not seen it yet | PASS |  |
| E2 | a restarted dispatcher delivers it | PASS | enforced 1 |
| E2 | nothing remains owed | PASS |  |
| E2 | origin hash chain verifies after the crash | PASS |  |
| E2 | recipient hash chain verifies after the crash | PASS |  |
| E3 | backup command succeeds | PASS |  |
| E3 | restored copy has the same memories and states | PASS |  |
| E3 | restored copy keeps the store identity | PASS |  |
| E3 | restored copy verifies against the original's checkpoint | PASS |  |
| E3 | doctor reports the restored copy sound | PASS |  |
