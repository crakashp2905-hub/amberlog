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

What a backup does **not** contain:

- **Content keys, when they live outside the database.** A `DirectoryKeyProvider` or KMS store is a separate backup with separate retention, and a database restored without its keys is unreadable. `doctor` reports `KeyUnavailable` rather than erasure for exactly this case, so the message points at the volume you did not mount.
- **The revocation list**, which is in memory only and does not survive a restart. Short credential lifetimes are the control; see [SECURITY.md](../SECURITY.md).

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

### "The database is locked"

SQLite is single-writer. Writers serialise behind a 5-second busy timeout
(`busy_timeout_ms`), so this means contention exceeded it rather than two
writers being unsupported.

1. Is a long transaction open? Backups and replays hold read locks; a stuck dispatcher can hold a write lock.
2. Raise `busy_timeout_ms`, or lower it if you would rather fail fast and retry at your own layer.
3. If sustained concurrent writers are a real requirement, this is the measured trigger for a different backend — not a tuning problem. See [ROADMAP.md](../ROADMAP.md).

## 4. Upgrades

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

**There is no bulk re-encryption and there will not be.** Revising a memory
re-seals it under the current suite; `doctor` counts what remains. Rewriting
the log is the one thing this design forbids.

## 5. Rollback

- **Code only, same schema:** reinstall the previous wheel. Safe.
- **Code back past a schema version:** restore the store from a backup taken on that version too. The store is not downgradeable.
- **A retraction you regret:** `release` returns a quarantined memory to candidate. The retraction event stays — history is not rewritten — and the release is itself an attributable event.
- **A content erasure:** not reversible. That is the point. A backup taken before the key was destroyed still holds it, which is a retention decision rather than a recovery path.

## 6. What is not covered

Said plainly rather than left for an incident to discover.

- **No concurrency beyond serialised single-writer.** Measured, not assumed: 4 processes × 20 appends land all 80 with a gapless sequence and a verifying chain.
- **No multi-host story.** P9 declined distribution on measurement — 25× the memories cost 1.7× the latency.
- **No automated erasure across caches, exports or model traces.** Crypto-erasure covers the store. Anything you exported, logged, or sent to a model provider is outside it, and `doctor` cannot see those.
- **No alerting.** `doctor` and `attention` exit non-zero; wiring that to a pager is yours.
- **The revocation list does not survive a restart.** In-memory by design, with short lifetimes as the control.
- **Untested here:** restore onto a different OS, stores above a few hundred thousand events, and recovery from filesystem-level corruption rather than logical tampering.
