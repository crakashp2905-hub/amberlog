# PostgreSQL failover: primary killed mid-write, replica promoted

Produced by `python -m experiments.pg_failover` at commit `bea61a0`; raw numbers in
[pg-failover.json](pg-failover.json). PostgreSQL 16, a primary and a streaming
replica on one machine. 120 writes, primary killed (`-m immediate`) at the halfway
point, replica promoted, the client reopened through a multi-host URL
(`target_session_attrs=read-write`). An operational test, not pre-registered.

| replication | acknowledged | failed writes | acknowledged and lost | chain verifies | seq gapless | doctor sound | writes after failover | promote / reconnect |
|---|---|---|---|---|---|---|---|---|
| sync | 120/120 | 0 | **0** | True | True | True | 60 | 0.11 s / 0.11 s |
| async | 120/120 | 0 | **0** | True | True | True | 60 | 0.11 s / 0.11 s |

Writes blocked on the promoted node before the runbook step:
sync: True, async: False.

## Reading (written after the run)

**The store comes through a real failover intact.** In both modes:
- every acknowledged write is on the promoted node;
- the hash chain verifies and sequence numbers have no gap;
- `doctor` is sound;
- the client reconnects in about 0.1 s through a multi-host URL, and writes
  resume and chain on.

The event log needs no repair after a failover, because its transaction
already carries the chain (append and chain commit together).

**One trap, found by this harness hanging, and now in the runbook.**
`pg_basebackup` copies the primary's `synchronous_standby_names` to the
replica. Once promoted, the new primary waits at **every commit** for a
standby it does not have. `statement_timeout` does not interrupt that wait,
so writes hang without error, and even opening the store blocks. The fix is
one statement on the promoted node, `ALTER SYSTEM SET
synchronous_standby_names = ''` and a reload, or attaching a new standby.

**What this does not show.** Asynchronous mode lost nothing here because the
write rate was low and WAL streamed in time. Under load, an async failover can
lose the last acknowledged commits, which is Postgres's documented
trade-off. Use `synchronous_commit = on` with a standby where losing an
acknowledged write matters. This is one machine, so there is no network
latency or partition between nodes, and the test covers crash and promotion,
not split-brain.
