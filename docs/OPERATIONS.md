# OPERATIONS.md — running a store, and recovering one

What to do, in what order, when something is wrong. Every procedure here has
been run; where a step is untested that is said rather than implied.

Companions: [DEPLOYMENT.md](../DEPLOYMENT.md) for choosing a topology,
[SECURITY.md](../SECURITY.md) for the threat model,
[docs/VALIDATION.md](VALIDATION.md) for what has actually been verified.

---

## 1. The one command to run first

```bash
memory-fabric --db store.db doctor
```

Ten checks, three outcomes, and exit codes meant for a script: **0** sound,
**1** sound with warnings, **5** not sound. `ok` means verified rather than
"nothing raised", and a check that *cannot* run reports a warning with the
reason — never `ok`.

| Check | A failure means |
|---|---|
| append-only enforcement | the log's triggers are gone or not refusing writes |
| **event chain** | the log has been modified; the detail names the first bad sequence |
| replay from the log | the live projection and the log disagree; the log wins |
| schema version | the log was written by a newer release than this install |
| retraction delivery | a correction has permanently failed to reach a recipient |
| withdrawal evidence | a memory is withdrawn on co-occurrence or no stated basis |
| content keys | content is unreadable with no erasure event to explain it |
| content cipher | unauthenticated `enc:v1` ciphertext remains, or encryption is off |
| withdrawn knowledge is not exposed | a blocked memory passes the enforcement check |
| tenant isolation | a memory is readable from another tenant |

## 2. Routine operations

### Backup

```bash
memory-fabric --db store.db backup /backups/store-$(date +%F).db
```

Takes a consistent snapshot **and replays it** before reporting success — a
backup that cannot be replayed is not a backup. It refuses `:memory:` with exit
6 rather than reporting success for copying nothing.

**Replaying one store's events into another is not a backup.** A fresh store
mints a `StoreIdentified` event of its own, so the result holds two identities,
and content sealed under the source store's identity fails its authentication
check — surfacing as "content failed authentication (AES-GCM)", which reads as
a tamper that never happened. Opening such a store is now refused with an
explanation instead. `backup` copies the *file*, and therefore the identity and
the keys with it.

What a backup does **not** contain:

- **Content keys, when they live outside the database.** A `DirectoryKeyProvider` or KMS store is a separate backup with separate retention, and a database restored without its keys is unreadable. `doctor` reports `KeyUnavailable` rather than erasure for exactly this case, so the message points at the volume you did not mount.
- **Nothing, when the service is used.** Revocations live in the database (`SqliteRevocations`, sharing the event log's connection), so a backup carries them. A bare `PrincipalRegistry` keeps them in memory, and a backup cannot carry what was never written — `service.revocations_are_durable` says which you have.

### Integrity checkpoint

```bash
memory-fabric --db store.db checkpoint            # print it
memory-fabric --db store.db checkpoint --verify saved.json
```

Prints `(seq, chain_digest)`. **Store it where the database cannot reach it** —
another repository, append-only object storage, a ticket. A hash chain is
tamper-evident, not tamper-proof: anyone who can write both the log and the
chain can rewrite both consistently, and only an external digest catches that.
A checkpoint kept beside the database buys nothing.

Suggested cadence: one per deploy, and one per backup, committed alongside the
backup's checksum.

### Draining retractions

A retraction is owed until delivered. After an outage:

```python
Dispatcher(fabric, transport).drain()
```

`doctor` fails on a permanently failed delivery, because the origin's own copy
is withdrawn and the recipient is still exposing withdrawn knowledge with
nothing raising anywhere.

## 3. Incidents

### "The event chain does not verify"

1. **Stop writing to the store.** Further appends bury the divergence point under valid links.
2. Note `first_bad_seq` from `doctor` or `checkpoint`. Everything *before* it verifies; everything after is suspect.
3. Compare against your most recent external checkpoint: `checkpoint --verify`. A matching checkpoint at a sequence below the break tells you history up to there is intact.
4. Restore from the newest backup that verifies, then replay whatever you can reconstruct from upstream sources.
5. The chain cannot tell you *who* altered the log, only that it was altered and where. Host-level audit is the only answer to who.

### Answering a subject-access or erasure request

A runbook, because erasure is the one operation where "done" has to be true in
places this store cannot see.

**1. Find every memory about the subject.**

```bash
memory-fabric --db store.db list -q "<name, email or id>" --limit 500
memory-fabric --db store.db search "<name, email or id>" --limit 50
```

`list -q` is a substring match over content and ids; `search` uses the index
and finds paraphrases. Neither is exhaustive for a subject described only
indirectly — record the queries you ran as part of the request.

**2. Withdraw before erasing, if the content was wrong.** Erasure removes
content, not the fact that agents may have acted on it. If the memory was
also incorrect, `quarantine` it first so its descendants are recomputed and the
retraction propagates to every store it was shared with.

**3. Erase each one.**

```bash
memory-fabric --db store.db erase <memory-id> --reason "<ticket id>" --actor <you>
```

This destroys the memory's content key and prints the scope report: what the
erasure **reached** (key destroyed, log payload is ciphertext, content reads as
the marker, both indexes purged — verified, not asserted), what it **kept
deliberately** (provenance, lineage, withdrawal basis, propagation record, the
erasure event with your reason), and what is **outside this store**. Re-print it
any time with `erasure-scope <memory-id>`. If the report says the provider
cannot destroy keys, the content is unreadable here but the key still exists in
your KMS: destroy it there.

**4. Act on what is outside this store** — the report lists it as unknown
because nothing here can see it:

| Outside the store | What to do |
|---|---|
| Federated copies | The report names the recipient stores. Each holds its **own** key: ask each operator to run step 3 on their copy. A retraction withdrew the copy from use; it did not destroy it. |
| Backups taken before the erasure | They hold the ciphertext **and** the key (or, with external custody, the key-directory backup does). Expire them on your retention schedule, or restore-erase-rebackup if the request cannot wait. Record which. |
| Key-directory backups (external custody) | A backup of the key directory taken before step 3 still holds the key. Same treatment as above. |
| Exports, logs, model traces | Anything that left before the erasure: prompts sent to a model provider, exported reports, application logs. Out of crypto-erasure's reach; handle under your provider and logging policies. |

**5. Record the outcome.** The erasure events (`audit <memory-id>`) and the
scope report together are the evidence that the request was handled; the
store keeps them by design. Attach both to the ticket.

### "A store will not open: KeyUnavailable"

The content keys are not where the store expects them. This is **not** erasure,
and the distinction is why the error is separate: erasure is recorded and
expected, a missing key store is an operational fault.

1. Is this store configured for external keys? Pass `--keys <dir>`.
2. Mounted the right volume? The message names the provider it tried.
3. Keys genuinely lost: content is unrecoverable. Provenance, lineage, retraction basis and the whole audit trail survive — an auditor can still answer "was this handled correctly?" about memories nobody can read.

### "Acting on withdrawn knowledge"

1. `memory-fabric --db store.db attention` lists what needs a human, worst first.
2. For a federated memory, check the propagation view: `OperatorClient.propagation()` or `/api/propagation`. A recipient stuck in `retrying` or `failed` is the cause.
3. A withdrawal recorded on a weak basis (`co_occurrence`, `unstated`) is more likely to be a mistake than the memory is to be wrong — PA′ measured 57 of 87 naive withdrawals as being about a completely different fault. The remedy is usually `release`, not deeper propagation.

### "This log contains N store identities"

Events from one store were replayed into another. There is no correct identity
to pick: whichever is chosen, the other store's content cannot be decrypted.

1. Do not try to merge the logs. Take the backup of whichever store you actually want.
2. To move a store, copy the file (`backup`), not its events.
3. To move *knowledge* between stores, use federation — `offer` re-seals the content under the recipient's identity, which is the whole point of the AAD binding.

### "The database is locked"

SQLite is single-writer. Writers serialise behind a 5-second busy timeout
(`busy_timeout_ms`), so this means contention exceeded it rather than two
writers being unsupported.

1. Is a long transaction open? Backups and replays hold read locks; a stuck dispatcher can hold a write lock.
2. Raise `busy_timeout_ms`, or lower it if you would rather fail fast and retry at your own layer.
3. If sustained concurrent writers are a real requirement, this is the measured trigger for a different backend — not a tuning problem. See [ROADMAP.md](../ROADMAP.md).

## 4. Upgrades

**Upgrading across the scope change (2026-10-18).** Scope is now enforced on
reads: a `private` memory is visible only to the agent that wrote it. Before,
every active memory was readable by its whole tenant. To keep that visibility
for memories written before the upgrade, decide it once, explicitly:

```bash
memory-fabric --db store.db share --all-private-active --actor <you>
```

It shares each active private memory to `team` through the firewall, so a
restricted memory is refused and listed rather than widened. Skip it if
per-agent privacy is what you wanted all along.

**Older store, newer code: supported.** Every field added since 0.2.0 is
nullable with a defined absent-meaning, and `tests/test_version_skew.py` checks
each one — absent tenant means `tn_default`, absent validity means "applies
always", absent lifecycle means `candidate`.

**Newer store, older code: not supported, and cannot be.** A 0.5.0 install
pointed at a 0.7.0 store does not recognise `enc:v2` envelopes and would hand
one back as content. `doctor` fails with a schema finding. This is a one-way
door; do not roll the *code* back past a store's schema version.

Migrations run on open, are idempotent, and need no command:

| Version | Change | Migration |
|---|---|---|
| 0.4.0 | per-hop retraction target | `inbox`/`outbox` rebuilt with `target_key`; existing rows carry `''` |
| 0.5.0 | tenant identity | additive; absent means `tn_default` |
| 0.6.0 | authenticated content | additive; `enc:v1` stays readable, never rewritten |
| 0.7.0 | bitemporal validity | additive; absent means open-ended |
| 0.8.0 | copy recognition | additive; one event type, two projection maps |
| 0.9.0 | action gating | additive; one event type (`ActionGated`) |

`tests/test_version_skew.py::EveryShippedVersionUpgradesThenBacksUp` runs the
whole sequence for each version from 0.2.0 to 0.8.0: build a store at that
version, open it with current code, write current-version events (including a
retraction and an `ActionGated`), back it up with the CLI, and open the copy to
the same states.

**There is no bulk re-encryption and there will not be.** Revising a memory
re-seals it under the current suite; `doctor` counts what remains. Rewriting
the log is the one thing this design forbids.

## 4a. Supported scale and rate limits

Measured on one 4-CPU Linux machine with SQLite, 20 mixed operations per agent:

| deployment | agents | ops/s total | p99 latency | status |
|---|---|---|---|---|
| one `agent-api` process serving the agents | 1 → 100 | 159–195 | 7 ms → 1.2 s | **supported** |
| one `agent-api` process serving the agents | 200 / 400 | 198 / 166 | 1.4 s / 3.1 s | **supported**, if your agents tolerate the latency |
| one process per agent, all opening the store | 10 / 100 | 31 / 4 | 0.7 s / 56 s | **not supported** beyond a few writers |

The store serialises writes (one lock, a gapless hash-chained log), so latency
grows with the number of agents waiting on it. Throughput stays flat as agents are added; latency grows by about 7 ms per
agent waiting. Above 400 concurrent agents per store is unmeasured. For more,
split agents across stores (`tenancy.TenantRouter`) rather than queueing more
agents on one. Postgres was slower than SQLite at every point measured.

**Rate limits** (`agent-api`): each agent gets a token bucket, by default 20
requests a second with a burst of 40 (`--rate-limit`, `--burst`;
`--rate-limit 0` turns it off). Failed authentications are limited per remote
address. A refused request gets `429` with `Retry-After`. Size the per-agent
rate so that agents × rate stays below the measured total. Otherwise requests
queue on the lock rather than being refused.

## 5. Rollback

- **Code only, same schema:** reinstall the previous wheel. Safe.
- **Code back past a schema version:** restore the store from a backup taken on that version too. The store is not downgradeable.
- **A retraction you regret:** `release` returns a quarantined memory to candidate. The retraction event stays — history is not rewritten — and the release is itself an attributable event.
- **A content erasure:** not reversible. That is the point. A backup taken before the key was destroyed still holds it, which is a retention decision rather than a recovery path.

## 6. What is not covered

Said plainly rather than left for an incident to discover.

- **No concurrency beyond serialised single-writer.** Measured, not assumed: 4 processes × 20 appends land all 80 with a gapless sequence and a verifying chain. Throughput is bounded by that one writer (§4a).
- **No multi-host story.** Distribution was declined on measurement — 25× the memories cost 1.7× the latency.
- **No automated erasure across caches, exports or model traces.** Crypto-erasure covers the store. Anything you exported, logged, or sent to a model provider is outside it, and `doctor` cannot see those — `erasure_scope` reports them as unknown rather than pretending otherwise, which is the most a store can honestly do.
- **Alerting is one webhook.** `memory-fabric doctor --webhook URL` POSTs a JSON alert when the store is not sound (`--webhook-on warn` for warnings too). Run it from cron or a systemd timer. Escalation, deduplication and paging rules are still yours.
- **Revocation durability depends on which surface you use.** A `MemoryService` writes revocations to the database; a bare `PrincipalRegistry` keeps them in memory. `service.revocations_are_durable` answers it rather than leaving it to be inferred.
- **Untested here:** restore onto a different OS, stores above a few hundred thousand events, and recovery from filesystem-level corruption rather than logical tampering.

## Background maintenance (0.12.0)

The store maintains itself. `serve`, `agent-api` and `mcp` each start the
background manager. Run it alone with `memory-fabric --db <store> maintain`,
or for one cycle with `--once`.

**What it does, every `--maintain-interval` seconds (60 by default):**

- delivers owed retractions to peers (`--peers peers.json`, or
  `MEMORY_FABRIC_PEERS`; the file holds keys, so keep it readable by the
  service user only);
- applies retention: deprecations always, deletions only with
  `--retention-delete`;
- scans for audit triggers and contradictions;
- records an integrity checkpoint: give `--checkpoint-dir` a path on other
  storage, or it is only recorded in the log;
- runs the doctor's checks.

**Seeing what it did:** `memory-fabric maintain --status` shows the last
cycle and everything it found that needs a person. Conflicts and audit
findings are never resolved automatically. `doctor` warns when the manager
has not run for an hour.

**Several processes on one store:** they coordinate through a lease, so
exactly one maintains the store. Turn it off in a process with
`--no-maintain`.

