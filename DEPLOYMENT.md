# Deployment

What it takes to run this for real, and what it is honestly not ready for.

Every number here comes from a run that is cited. Nothing is extrapolated
without saying so.

---

## 1. The one thing that matters

**The event log is the source of truth.** Memory records, value estimates,
profiles and both observability surfaces are projections that can be deleted and
rebuilt from it ([AGENTS.md](AGENTS.md) principle 3). That makes the deployment
question simpler than it looks:

> Back up the SQLite file. Everything else is derivable.

It also makes one failure mode worse than all the others. A lost event log cannot
be reconstructed from the projections, because the projections are lossy — they
hold current state, not how it was arrived at. A quarantine that was propagated,
a propensity that was logged, the exposure arm a memory was withheld in: those
exist only in the log, and an unbiased value estimate cannot be computed without
them ([AGENTS.md](AGENTS.md) principle 4).

### Backup

```bash
memory-fabric --db store.db backup /backups/store-$(date -u +%Y%m%dT%H%M%SZ).db
```

Not `cp`. The store runs in WAL mode, so a plain file copy taken mid-write gives
you a database plus an uncommitted write-ahead log, and whether that restores
depends on timing. `backup` takes a consistent snapshot while the store is live.

It then **replays the copy** and prints the event and memory counts it found
there, failing with a non-zero exit if they do not match the source. That check
is the point: a truncated backup opens perfectly well and reports fewer events,
and nothing else would tell you.

**With external keys, back up the key directory too.** The log backup holds no
keys when they live outside the database, and says so. Content in a backup is
readable only with the key directory as it was when the backup was taken — and
a key destroyed by erasure after that backup is still in an older key backup,
which is the backup-retention question in [SECURITY.md](SECURITY.md).

### Key custody: keep keys outside the database in production

```bash
memory-fabric --db store.db migrate-keys /secure/keys      # once, for an existing store
memory-fabric --db store.db --keys /secure/keys overview   # or set MEMORY_FABRIC_KEYS
```

By default a store keeps content keys in its own file, which makes erasure
possible and does nothing against someone holding the file. `migrate-keys`
copies the keys out, proves a replay with the directory alone reads every
memory, and only then clears them from the database; a failed proof clears
nothing. Put the directory on a different volume or under different
credentials from the database. The container image does this by default.

### Restore

```bash
memory-fabric --db /backups/store-20261010T0900Z.db overview
```

A restore is verified the same way a backup is — by folding the whole log. The
overview reports the event count, the memory count, and the schema versions that
wrote it.

## 2. Running the server

The dashboard and the JSON API are **read-only**: there is no mutating HTTP
endpoint at all, and browsing does not write exposure events, because an
observability tool that logged an operator's queries would feed its own browsing
into the data every value estimate is computed from.

### Locally

```bash
memory-fabric --db store.db serve
```

Binds `127.0.0.1` and prints a one-time URL carrying a session token.

### Behind something

```bash
MEMORY_FABRIC_TOKEN=... memory-fabric --db store.db serve \
  --host 0.0.0.0 --allowed-host memory.internal.example.com
```

Four things are enforced rather than advised, and will refuse to start if you get
them wrong:

- **A non-loopback bind requires a token.** `--no-auth` on anything but loopback is refused outright, not warned about.
- **`Host` is validated** against the allowed list, which defeats DNS rebinding. Reaching the server by any name other than `localhost` means adding that name with `--allowed-host`; the refusal says so.
- **Cross-origin requests are refused.**
- **The token is compared with `hmac.compare_digest`.**

Pass the token through `MEMORY_FABRIC_TOKEN` rather than `--token`: an argument
is visible in the process list to every user on the box.

### In a container

```bash
docker build -t memory-fabric .
docker run -p 8765:8765 -v mf-data:/data -v mf-keys:/keys \
  -e MEMORY_FABRIC_TOKEN=... memory-fabric
```

Runs as uid 10001, not root. **Both volumes are required.** Without `/data` the
first `docker rm` takes the event log, and §1 is why that is unrecoverable.
Without `/keys` it takes the content keys, and the content in `/data` becomes
unreadable — the same mechanism erasure relies on, triggered by accident.

A new store keeps its keys on `/keys`. A store created by an earlier image keeps
them in the database and still starts, with a warning naming the
`migrate-keys` command to run. CI builds this image and checks that it answers
on the published port, refuses an unauthenticated request, writes keys to
`/keys` and none to the database, and that the running dashboard sees writes
made by another process.

## 3. Capacity, as measured

From the [P9 decision](research/decisions/2026-10-07-p9-declined.md), one laptop,
pure Python, flat scan, no vector index:

| memories | events | retrieval | store |
|---|---|---|---|
| 80 | 11,140 | 2.65 ms | 3.6 MB |
| 400 | 35,935 | 2.98 ms | 13.0 MB |
| 2,000 | 120,089 | 4.39 ms | 47.9 MB |

25× the memories costs 1.7× the latency, because a query only scores memories
that share signal with it. At 4.39 ms one thread serves roughly 230 retrievals
per second. Storage extrapolates to about 400 MB per million events — that one
*is* an extrapolation and is the only one here.

The governed write path adds about 0.2 ms per episode over an ungoverned vector
store ([Phase A](research/results/phase-a-real-agent-benchmark.md)). Governance
is not where your latency goes.

## 4. Upgrades

The version tracks the **memory schema**, not the Python API
([VERSIONING.md](VERSIONING.md)). Any event written by a released version
replays on every later version of the same major series.

```bash
memory-fabric --db store.db overview   # the `schema` row
```

It names the installed schema version and, when they differ, every version that
actually wrote into the log — events are never rewritten, so a store that has
outlived an upgrade carries both. If the log is *newer* than the installed
package, the diagnostics say so outright, because a projection folds the events
it recognises and silently ignores the rest. That is correct behaviour and a bad
failure mode to hit unannounced.

Upgrade procedure: back up, install, run `overview`, read the diagnostics. There
is no migration step for a minor version, because additive schema changes need
none.

## 5. What to watch

`memory-fabric --db store.db attention` is the triage list, worst first, each
finding carrying the command that acts on it. The ones that need a human:

| Finding | Why it matters |
|---|---|
| **Withdrawn on weak evidence** | A memory was withdrawn on co-occurrence with a failure, or on no stated basis. [Phase A](research/results/phase-a-real-agent-benchmark.md) measured that policy cutting the rate at which a *correct* memory reached the prompt from 60% of episodes to 18%. Release it unless there is evidence about the memory itself. |
| **Quarantined** with a sensitive-data basis | A credential or personal datum reached the ingestion path. The *value* is never displayed — the reviewer sees the kind, which is what the decision needs. Rotate the credential; quarantining the memory does not un-leak it. |
| **Justification retracted** | An ancestor was withdrawn, so this no longer rests on anything. |
| **Restricted memory shared** | A scope promotion that should not have happened. |
| **Open disagreements** | Contested hypothesis sets with no resolution. Left open deliberately, but someone should look. |

`overview`'s diagnostics are the other half, and they answer a question most
dashboards do not ask: *can this store support a value claim at all?* A new
deployment's honest answer is "not yet". If every logged exposure was
deterministic, the diagnostics say that no amount of further data will support a
causal estimate, because there is no way to tell a memory helping from it being
retrieved on easier tasks.

## 6. What this is not ready for

Stated plainly, because a list of features is not a deployment plan.

**One writer.** SQLite with WAL. Concurrent readers are fine; concurrent writers
to one store are not supported and are not tested. The storage seam exists
([ARCHITECTURE.md](ARCHITECTURE.md) §4) and Postgres belongs with the first
deployment that actually needs it — adding a driver now would cost the
zero-dependency property for no measured gain
([ROADMAP.md](ROADMAP.md)).

**One token, no users — on the HTTP surface.** The observability server's auth
is a single shared bearer token with no identity, roles, expiry or revocation
beyond restarting with a new one. There is no audit of *who looked*, only of
what the store did. Put it behind something with a user model.

That is separate from the library's own identity, which does have one:
`PrincipalRegistry` issues signed, expiring per-agent credentials and
`fabric.as_principal` returns a handle bound to the verified principal. The two
have not been joined up — the dashboard does not know about principals — so a
multi-tenant HTTP deployment still needs a front end that does.

**Choosing between one store per tenant and one store for several.** Per-tenant
authorisation is enforced on every read path, so several tenants in one store
is safe against a bug in a ranking policy, an index query or a federation
import. It is not safe against anything that can read the file: one database is
one blast radius, and the content keys sit beside the ciphertext. Pick one
store per tenant when isolation has to survive a compromised process, a
mis-scoped backup or a support engineer with shell access; pick one store when
the tenants are teams inside one trust boundary and the operational cost of N
databases is the real constraint. `memory-fabric tenants` says which
arrangement a store is actually in, and `doctor` reports a multi-tenant store
as a warning rather than as a clean bill of health.

**Content is encrypted; the database is not.** Memory content is sealed per
memory and `memory-fabric` can destroy a single memory's key, which makes that
content unrecoverable while leaving the audit trail intact — see
[SECURITY.md](SECURITY.md) for exactly what erasure does and does not reach. But
the database as a whole is a plain SQLite file: the keys sit beside the
ciphertext, which makes erasure *possible* and does nothing against an attacker
holding the file. Use an encrypted volume if the content warrants it, and rotate
any credential that reached the store rather than relying on the quarantine.

**Erasure cannot reach an older backup.** Destroying a key makes the content
unreadable in that store and in every copy taken afterwards. A backup taken
*before* the erasure still holds the key and the ciphertext, so backup retention
is an operational control you have to run, not something the store can enforce.
A test pins both halves of that behaviour.

**Embeddings are a dependency you choose.** The core is zero-dependency and
ships a hashing embedder that exists so tests are reproducible, not because it
retrieves well. Anything real wants `OllamaEmbedder` or another model behind the
`Embedder` protocol — and retrieval quality is most of the outcome: Phase A found
every arm converting a correct memory into a correct answer about 95% of the time
and failing about 95% of the time without one.

**The value estimators are not validated for live exposure decisions.**
[H1](research/results/h1-causal-credit.md) showed the amortized estimator
recovers true memory value in simulation; [H2](research/results/h2-credit-driven-retention.md)
found that did not transfer to retention, where a smoothed success rate matched
it; [Phase A](research/results/phase-a-real-agent-benchmark.md) found it did not
transfer to live exposure either, and that the exploration it requires was itself
a cost at a 24-episode horizon. The product default is `naive_usage` for that
reason. Ranking exposure on estimated value is available and is not recommended
on current evidence.

**Do not withdraw memories because they were in context when something failed.**
This is the one deployment rule that comes from a measurement rather than from
caution, and §5 says what to do instead.
