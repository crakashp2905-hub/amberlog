# Troubleshooting

Start with `memory-fabric --db <store> doctor`. Every warning and failure it
prints carries the fix. The exit codes are meant for scripts: **0** sound,
**1** sound with warnings, **5** not sound. Below are the symptoms people
actually report, each with the cause and the fix. Incident procedures (an
integrity failure, an erasure request) are in
[OPERATIONS.md §3](OPERATIONS.md#3-incidents).

## "I wrote a memory and recall does not return it"

Check these in order:

1. **It is a candidate.** New writes wait for review unless the store
   auto-activates. Find it with `memory-fabric --db <store> review`, then
   approve it: `review <id> --approve --actor <you>`.
2. **It is private to the agent that wrote it** (0.10.0 and later). A
   private memory is visible to its writer only, and to agents with `read`
   on a collection that contains it. Share it with
   `share <id> team --actor <you>`, or attach it to a collection
   (`collection`). A store upgraded from 0.9.x needs the one-off
   `share --all-private-active --actor <you>` ([MIGRATION.md](MIGRATION.md)).
3. **It was withdrawn.** `show <id>` shows a quarantined, deprecated or
   contested memory, and why. A withdrawn memory is never recalled, by
   design.
4. **Another tenant.** An agent recalls only from its own tenant.
5. **Nothing matched.** Retrieval returns nothing below `min_relevance`.
   Try the words the memory uses.

## "doctor fails: schema version"

The store was written by a newer version than the code reading it, typically
after a rollback. This is a refusal, not damage. Either run the newer code,
or restore the backup taken before the upgrade
([OPERATIONS.md §5](OPERATIONS.md#5-rollback)). The procedure is drilled in
CI (`experiments/rollback_drill.py`).

## "A retraction was requested and the other store still serves the memory"

- **No peers are configured.** Since 0.12.0 the background manager delivers
  retractions, but only with a peer list: `--peers peers.json` or
  `MEMORY_FABRIC_PEERS`. `maintain --status` shows `"skipped": "no peers
  configured"` and the count still pending.
- **The peer is offline.** Delivery retries with backoff. A failed delivery
  shows in `doctor` and in `attention`. The peer catches up when it
  reconnects.
- **No manager is running.** `doctor` reports "background manager … has
  stopped". Start `memory-fabric maintain`, or any server, for the store.

## "The database is locked" / writes time out

A long fenced action or another writer holds the write lock. Writers wait up
to the busy timeout (5 s). Under continuous fenced actions a writer can wait
about 2 s (S6). Run one `agent-api` process instead of a store handle per
agent ([STABILITY.md](../STABILITY.md#capacity-as-measured)).
[OPERATIONS.md](OPERATIONS.md#the-database-is-locked) has the details.

## "A store will not open: KeyUnavailable"

The content keys are not where the store expects them: a different `--keys`
path, or a missing key volume in a container. See
[OPERATIONS.md](OPERATIONS.md#a-store-will-not-open-keyunavailable).

## "Connecting to Postgres hangs, then fails"

Since 0.11.0 a connect gives up after 10 s, unless the URL sets its own
`connect_timeout`. Check the host, the port and the server's `pg_hba.conf`.
A password in the URL is never printed in errors.

## "`attention` exits with status 1"

By design: it exits 1 when at least one high-severity item needs a person,
so a script can alert on it. 0 means nothing high.

## "The manager reports deletions waiting for opt-in"

Retention found memories its policy would delete. Deletion is terminal, so
the background manager applies it only with `--retention-delete`. To review
them first: `memory-fabric --db <store> retention`.

## "Two answers for the same thing / DISPUTED notes"

The store holds memories that give different values for one claim, by
different authors. They are surfaced together rather than ranked
(`conflicts.py`), and listed in `maintain --status` for review. Resolve them
by validating the right one and withdrawing the other, with a reason.

## "My MCP client shows no tools / the server exits"

- Run the exact command from the client's configuration in a terminal: it
  must print nothing to stdout before the first request.
- `memory-fabric init` prints a working configuration.
- `--agent` is required. The store path in the configuration is relative to
  the client's working directory, so prefer an absolute path.

## Still stuck

`memory-fabric --db <store> overview` and `doctor --json` are what to attach
to a report. Neither contains memory content. Security problems go through
GitHub's private **Report a vulnerability** page ([SECURITY.md](../SECURITY.md)).
