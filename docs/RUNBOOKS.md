# Runbooks

What to do, in order, for the situations an operator meets. Every command here
exists and is tested; where a step is still a Python call rather than a
command, it says so. Procedures already written elsewhere are linked, not
copied, so the two cannot drift:

| Situation | Where |
|---|---|
| Install and first run | [README](../README.md#quick-start), [DEPLOYMENT.md §2](../DEPLOYMENT.md#2-running-the-server) |
| Backup and restore | [DEPLOYMENT.md §1](../DEPLOYMENT.md#backup), [OPERATIONS.md §2](OPERATIONS.md#backup) |
| Upgrade and rollback | [OPERATIONS.md §4–5](OPERATIONS.md#4-upgrades) |
| Erasure or subject-access request | [OPERATIONS.md §3](OPERATIONS.md#answering-a-subject-access-or-erasure-request) |
| "The event chain does not verify" | [OPERATIONS.md §3](OPERATIONS.md#the-event-chain-does-not-verify) |
| "A store will not open: KeyUnavailable" | [OPERATIONS.md §3](OPERATIONS.md#a-store-will-not-open-keyunavailable) |
| "The database is locked" | [OPERATIONS.md §3](OPERATIONS.md#the-database-is-locked) |

The rest are below.

---

## 1. A credential has leaked

**Goal:** the leaked credential stops working before anything else is done.

1. Revoke it. Paste the token on stdin so it does not reach shell history:
   ```bash
   memory-fabric --db store.db agent-api-revoke --agents-file agents.txt --token -
   ```
   If you do not have the token itself, cut the agent off entirely:
   ```bash
   memory-fabric --db store.db agent-api-revoke --agents-file agents.txt --agent <agent-id>
   ```
   Revocations are rows in the store. A running `agent-api` on the same store
   refuses the credential **on its next request**; nothing needs restarting
   (`tests/test_cli_revoke.py`).
2. If the agent's *signing key* leaked, not only one credential, rotate it (§2).
   Revoking credentials does not stop the key minting new ones.
3. Find what it wrote. Every memory records the agent that created it:
   ```bash
   memory-fabric --db store.db list --agent <agent-id> --limit 0
   ```
   and the full event history of any one of them with
   `memory-fabric --db store.db audit <memory-id>`.
4. Treat its writes as suspect: §4.

## 2. Rotating an agent's signing key

Credentials are verified against the key registered for the agent, so
replacing the key invalidates every credential signed with the old one at
once.

1. Generate a key (32 random bytes, hex) and replace the agent's line in the
   agents file (`agent_id:tenant_id:hex_key`). The file must stay readable only
   by the server's user.
2. Restart `agent-api`. Registrations are read at start; revocations persist
   across the restart.
3. Issue the agent a new credential:
   ```bash
   memory-fabric --db store.db agent-api-issue --agents-file agents.txt --agent <agent-id>
   ```
4. Old credentials now fail signature verification and are refused with the same
   401 as any other failure.

## 3. Rotating a federation peer key

Each pair of stores shares one HMAC key, configured by the host program in a
`PeerRegistry`. **There is no automatic rotation** (threat S11), so it is a
coordinated swap:

1. Drain retractions owed to that peer first, so none is in flight under the old
   key ([OPERATIONS.md, draining](OPERATIONS.md#draining-retractions)).
2. Change the key on **both** stores, then restart both.
3. Anything signed in the gap is refused by the recipient and retried by the
   origin's outbox; it delivers once both sides agree. A delivery that exhausts
   its retries shows as `failed` in `doctor` and `attention`. Re-drain.

## 4. A memory was poisoned, or a source turned out to be wrong

**Goal:** stop it being used, everywhere it reached, without destroying the
conclusions that have independent support.

1. Quarantine it, with the reason:
   ```bash
   memory-fabric --db store.db quarantine <memory-id> --reason "<what is wrong>" --actor <you>
   ```
   Quarantine propagates: conclusions that rest *only* on it become contested
   and are withheld; conclusions with independent support stay active. A
   retraction is queued to every store it was shared with.
2. See what it touched:
   ```bash
   memory-fabric --db store.db lineage <memory-id>
   memory-fabric --db store.db attention
   ```
3. Confirm the retraction left: `doctor` reports any delivery that has failed
   permanently; `attention` lists what is still pending.
4. Follow the guided workflow, which does steps 1–3 in order and records them:
   ```bash
   memory-fabric --db store.db incident                    # candidates, with why
   memory-fabric --db store.db incident <memory-id>        # spread, blast radius, actions that used it
   memory-fabric --db store.db incident <memory-id> --contain --reason "<why>" --actor <you>
   memory-fabric --db store.db incident <memory-id> --record incident.md
   ```
   The assessment lists the author's other active memories (a bad source
   rarely writes one bad memory) and every gated action that used this one,
   with whether it was a necessary source. The record is generated from the
   log, so it cannot drift from what happened.
5. **Do not** quarantine everything that was in context when something failed.
   [Phase A](../research/results/phase-a-real-agent-benchmark.md) measured that
   policy withdrawing correct memories about unrelated faults; `attention` flags
   a withdrawal made on weak evidence.

## 5. Content keys

- **Moving keys out of the database** (the production default):
  `memory-fabric --db store.db migrate-keys <dir>`. It copies, proves a full
  replay reads every memory with only the directory, and only then clears the
  database copy. If the proof fails nothing is cleared.
- **Backing up keys:** the key directory needs its own backup, separate from the
  log's. A log without its keys is unreadable by design.
- **Lost keys:** content under them is unrecoverable; the store opens only if the
  directory is present ([KeyUnavailable](OPERATIONS.md#a-store-will-not-open-keyunavailable)).
  Provenance, lineage and audit survive.
- **Per-memory erasure** is destroying one key: see the erasure runbook.

## 6. PostgreSQL stores

- **Backup:** `pg_dump`, which is consistent under concurrent writers. The
  `backup` command is SQLite's and does not apply.
- **Append-only:** triggers refuse `UPDATE`, `DELETE` and `TRUNCATE` on the
  event log and the hash chain. A role that can disable triggers can still
  rewrite history; the defence against that is an external checkpoint
  (`memory-fabric --db <url> checkpoint`), kept somewhere that role cannot write.
- **Credentials in URLs:** displayed and logged forms are redacted. Prefer a
  password file or the `PGPASSWORD` environment of the service over a URL on
  a command line.

## 7. Agents are slow

1. Count agent **processes** per store. Each process with its own handle on the
   store serialises its writes with every other through one write lock.
2. Compare with the measured limits in
   [DEPLOYMENT.md §3](../DEPLOYMENT.md#3-capacity-as-measured). Above them,
   expect tail latency in seconds.
3. Move agents behind one `agent-api` process instead of one store handle each.
4. If p50 rises with *one* process, it is not contention: check the store's size
   against the retrieval figures in the same section.

## 8. Restoring from a backup

Take backups with custody of everything needed to read them:

```bash
memory-fabric --db store.db --keys ./keys backup /backups/store.bak --with-keys   --include agents.txt --include ./checkpoints
```

This writes `store.bak`, `store.bak.keys/`, `store.bak.config/` and
`store.bak.manifest.json` (the sha256 of every file, the event count and the
chain head). Keep the key copy as protected as the original.

To restore:

```bash
memory-fabric restore /backups/store.bak ./restored
```

It refuses a backup whose files do not match the manifest (exit 5), refuses
to write into an existing directory (exit 4), and replays the restored log
to check the event count and chain head. Then:

1. `memory-fabric --db ./restored/store.db --keys ./restored/keys doctor`
2. Compare the chain head with your latest off-host checkpoint
   (`--checkpoint-dir`). A restored store *behind* the checkpoint has lost
   events since the backup: say so in the incident record.
3. Peers may hold retractions the restored store no longer remembers
   sending. Run `memory-fabric maintain --once` with `--peers` so the
   outbox is re-dispatched; delivery is idempotent at the recipient.

The drill is `tests/test_backup_custody.py`, which runs on every CI build.

