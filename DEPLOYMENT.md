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
amberlog --db store.db backup /backups/store-$(date -u +%Y%m%dT%H%M%SZ).db
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
amberlog --db store.db migrate-keys /secure/keys      # once, for an existing store
amberlog --db store.db --keys /secure/keys overview   # or set AMBERLOG_KEYS
```

By default a store keeps content keys in its own file, which makes erasure
possible and does nothing against someone holding the file. `migrate-keys`
copies the keys out, proves a replay with the directory alone reads every
memory, and only then clears them from the database; a failed proof clears
nothing. Put the directory on a different volume or under different
credentials from the database. The container image does this by default.

### Restore

```bash
amberlog --db /backups/store-20261010T0900Z.db overview
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
amberlog --db store.db serve
```

Binds `127.0.0.1` and prints a one-time URL carrying a session token.

### Behind something

```bash
AMBERLOG_TOKEN=... amberlog --db store.db serve \
  --host 0.0.0.0 --allowed-host memory.internal.example.com
```

Four things are enforced rather than advised, and will refuse to start if you get
them wrong:

- **A non-loopback bind requires a token.** `--no-auth` on anything but loopback is refused outright, not warned about.
- **`Host` is validated** against the allowed list, which defeats DNS rebinding. Reaching the server by any name other than `localhost` means adding that name with `--allowed-host`; the refusal says so.
- **Cross-origin requests are refused.**
- **The token is compared with `hmac.compare_digest`.**

Pass the token through `AMBERLOG_TOKEN` rather than `--token`: an argument
is visible in the process list to every user on the box.

### In a container

```bash
docker build -t amberlog .
docker run -p 8765:8765 -v mf-data:/data -v mf-keys:/keys \
  -e AMBERLOG_TOKEN=... amberlog
```

Runs as uid 10001, not root, with the **production cryptography profile**:
content is sealed only with AES-256-GCM from the maintained `cryptography`
library, and the store refuses to open if that library is missing
(`AMBERLOG_CRYPTO_PROFILE=production`; [CRYPTOGRAPHY.md](docs/CRYPTOGRAPHY.md)).
Outside the container, install `amberlog[crypto]` and set the same
variable to get it. **Both volumes are required.** Without `/data` the
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

Measured on one laptop, pure Python, flat scan, no vector index:

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
store. Governance is not where your latency goes.

Near-identical notes stay cheap to write. Every write checks whether it
copies something already held, and on a store of 5,000 near-identical notes
("The purge time for P1 is 40 s.") a write takes about 0.9 ms, against
about 0.5 ms at 500.

### Many agents on one store

Measured on one machine (Windows, 8 CPUs) with agents issuing operations back
to back, which is the worst case: real agents wait on a model between
operations:

| Shape | Supported, with p95 ≤ 150 ms | Beyond it |
|---|---|---|
| A store handle per agent process, SQLite | **10 processes** (p95 84 ms; p99 1.2 s) | p95 0.5 s at 50, 3 s at 100 |
| A store handle per agent process, Postgres | **10 processes** (p95 128 ms; p99 222 ms) | p95 0.9 s at 50, 3 s at 100 |
| Agents behind one `agent-api` process | **10 agents** (p95 135 ms; p99 205 ms) | flat at ~130 ops/s; p95 1.3 s at 100 |

- **Aggregate ceiling: about 100–135 operations a second per store**, whatever
  the shape. Every write takes one lock that keeps the log ordered, and a
  retrieve is a write because exposures are logged.
- **Past 10 agents, prefer one `agent-api` process.** Throughput is the same;
  its p99 at 100 agents is 2.1 s against 12.1 s for a SQLite handle per
  process.
- **Postgres has the tighter tail** with a handle per process, at a higher
  median. Choose it for writers on several machines, not for speed.
- **Open-loop**: requests arrive on a schedule that does not wait for
  completions, and latency is measured from the scheduled arrival, so
  queueing counts. One store, a mix of 30% writes, 50% retrievals and 20%
  gated actions, on the same machine with nothing else running:

  | offered ops/s | 10 | 40 | 70 | 100 | **130** | 160 |
  |---|---|---|---|---|---|---|
  | p50 ms | 10 | 9 | 9 | 12 | **19** | 472 |
  | p99 ms | 20 | 27 | 33 | 38 | **91** | 1,984 |

  **Sustained to 130 ops/s; saturated at 160.** That is the limit to plan
  against: agents × memory operations per agent per second ≤ ~130 per store.

## 4. Upgrades

The version tracks the **memory schema**, not the Python API
([VERSIONING.md](VERSIONING.md)). Any event written by a released version
replays on every later version of the same major series.

```bash
amberlog --db store.db overview   # the `schema` row
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

`amberlog --db store.db attention` is the triage list, worst first, each
finding carrying the command that acts on it. The ones that need a human:

| Finding | Why it matters |
|---|---|
| **Withdrawn on weak evidence** | A memory was withdrawn on co-occurrence with a failure, or on no stated basis. Withdrawing memories because they appeared in failed episodes removes correct memories far more often than wrong ones. Release it unless there is evidence about the memory itself. |
| **Quarantined** with a sensitive-data basis | A credential or personal datum reached the ingestion path. The *value* is never displayed — the reviewer sees the kind, which is what the decision needs. Rotate the credential; quarantining the memory does not un-leak it. |
| **Justification retracted** | An ancestor was withdrawn, so this no longer rests on anything. |
| **Restricted memory shared** | A scope promotion that should not have happened. |
| **Open disagreements** | Contested memories with no resolution. Left open deliberately, but someone should look. |

`overview`'s diagnostics are the other half, and they answer a question most
dashboards do not ask: *can this store support a value claim at all?* A new
deployment's honest answer is "not yet". If every logged exposure was
deterministic, the diagnostics say that no amount of further data will support a
causal estimate, because there is no way to tell a memory helping from it being
retrieved on easier tasks.

## 6. What this is not ready for

Stated plainly, because a list of features is not a deployment plan.

**Writers serialise; they do not run in parallel.** On SQLite (the default),
processes on one machine share a store safely — writers queue on the file lock,
tested with 4 processes × 20 appends landing gapless with a verifying chain —
but every process must reach the same file, so one machine. For writers on
**several machines**, use the optional PostgreSQL backend:

```bash
pip install "amberlog[postgres]"
amberlog --db postgresql://user@db.internal:5432/memory overview
```

Every module runs unchanged against it (every storage-touching test module
runs on Postgres in CI; only the research benchmarks are left out), with append-only enforced by database triggers and the hash chain
intact. It does **not** add write throughput: writers still serialise, on a
table lock instead of a file lock, because the chain needs a total order and
`seq` must stay gapless. Readers never block. Back it up with `pg_dump`;
`amberlog backup` refuses and says so. Passwords in the URL are never
printed — but prefer a `.pgpass` file or `PGPASSWORD` over putting one in a
command line, which other users on the host can see.

**Named operators, but no roles or expiry — on the HTTP surface.** By default
the dashboard has one shared bearer token. With `serve --operators-file FILE`
(one `name:token` per line, tokens of 32+ characters, each person their own)
every request is attributed, and an access log records who looked at what —
including refused requests — one JSON line each, in `<db>.access.jsonl` by
default. Tokens are never printed or logged. The log is deliberately a separate
file and not the event log, because browsing must not become evidence in value
estimates. What it still does not have: roles, token expiry, or revocation
short of editing the file and restarting. For those, put it behind something
with a user model.

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
databases is the real constraint. `amberlog tenants` says which
arrangement a store is actually in, and `doctor` reports a multi-tenant store
as a warning rather than as a clean bill of health.

**Tenant isolation patterns.** Choose by what the isolation has to survive:

| pattern | how | survives | does not survive | cost |
|---|---|---|---|---|
| **A. Shared store** | one store; principals carry a tenant (`agent-api` agents file `agent:tenant:key`) | a bug in ranking, an index query or an import (authorisation on every read path) | anyone who can read the database file or the process | one database |
| **B. Store per tenant, one process** | `tenancy.TenantRouter`: one store and one key directory per tenant, routed by the verified principal | a mis-scoped query or backup of another tenant's file; erasure stays per tenant | a compromised server process, which holds every tenant's handle | N databases, one process |
| **C. Process per tenant** | one `agent-api` per tenant, each with its own `--db`, `--keys`, agents file and port; anchors per store (`anchor --to`) | a compromised process for one tenant; per-tenant rate limits and restarts | a compromised host | N processes |
| **D. Host or container per tenant** | pattern C in separate containers or VMs (`deploy/multihost/docker-compose.yml` is the template), with keys on separate volumes | a compromised host for one tenant | shared infrastructure underneath | N hosts |

Whatever the pattern, anchor each store's checkpoint somewhere its own host
cannot rewrite (`amberlog anchor --to git:...`), and give each tenant its
own operator tokens. `amberlog tenants` and `doctor` report which pattern a
store is actually in.

**Content is encrypted; the database is not.** Memory content is sealed per
memory and `amberlog` can destroy a single memory's key, which makes that
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
`Embedder` protocol. Retrieval quality is most of the outcome: an agent shown
the right memory almost always answers correctly, and one that is not almost
always fails.

**Value estimates are for inspection, not for ranking.** The estimators that
work in simulation did not improve live retention or exposure, and the
exploration they need has its own cost. The default is `naive_usage`.
Ranking exposure on estimated value is available and is not recommended.

**Do not withdraw memories because they were in context when something failed.**
This is the one deployment rule that comes from a measurement rather than from
caution, and §5 says what to do instead.

## Kubernetes (Helm)

`deploy/helm/amberlog` runs the dashboard, and optionally the agent HTTP
API, on one pod with the store and its keys on separate volumes:

```bash
kubectl create secret generic mf-agents --from-file=agents.txt
helm install mf deploy/helm/amberlog \
  --set dashboard.token=$(openssl rand -hex 24) \
  --set mode=team --set agentApi.enabled=true --set agentApi.agentsSecret=mf-agents
```

One replica, because a SQLite store has one writer host; for writers on
several hosts open the store on PostgreSQL. Model and embedder keys go in a
Secret referenced by `extraEnvFrom`, never in values. CI lints and renders the
chart on every change.
