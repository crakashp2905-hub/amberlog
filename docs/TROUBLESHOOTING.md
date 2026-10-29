# Troubleshooting

Start with `amberlog --db <store> doctor`. Every warning and failure it
prints carries the fix. The exit codes are meant for scripts: **0** sound,
**1** sound with warnings, **5** not sound. Below are the symptoms people
actually report, each with the cause and the fix. Incident procedures (an
integrity failure, an erasure request) are in
[OPERATIONS.md §3](OPERATIONS.md#3-incidents).

## "I wrote a memory and recall does not return it"

Check these in order:

1. **It is a candidate.** New writes wait for review unless the store
   auto-activates. Find it with `amberlog --db <store> review`, then
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
  `AMBERLOG_PEERS`. `maintain --status` shows `"skipped": "no peers
  configured"` and the count still pending.
- **The peer is offline.** Delivery retries with backoff. A failed delivery
  shows in `doctor` and in `attention`. The peer catches up when it
  reconnects.
- **No manager is running.** `doctor` reports "background manager … has
  stopped". Start `amberlog maintain`, or any server, for the store.

## "The database is locked" / writes time out

A long fenced action or another writer holds the write lock. Writers wait up
to the busy timeout (5 s). Under continuous fenced actions a writer can wait
about 2 s. Run one `agent-api` process instead of a store handle per
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
them first: `amberlog --db <store> retention`.

## "Two answers for the same thing / DISPUTED notes"

The store holds memories that give different values for one claim, by
different authors. They are surfaced together rather than ranked
(`conflicts.py`), and listed in `maintain --status` for review. Resolve them
by validating the right one and withdrawing the other, with a reason.

## "My MCP client shows no tools / the server exits"

- Run the exact command from the client's configuration in a terminal: it
  must print nothing to stdout before the first request.
- `amberlog init` prints a working configuration.
- `--agent` is required. The store path in the configuration is relative to
  the client's working directory, so prefer an absolute path.

## "The action gate refused" (reason codes)

`ActionDecision.reason_code` names the first check that failed, in this
order. `tests/test_troubleshooting.py` fails if a code is missing here.

| code | what failed | what to do |
|---|---|---|
| `credential_invalid` | the session's credential is expired, revoked or forged | issue a new credential |
| `execute_permission_missing` | the principal has no `execute` permission (operators do not) | act as an agent, or grant `perm:execute` |
| `unknown_tool` | the tool is not in the policy | add a `ToolRule` |
| `tool_not_granted` | the agent is not granted this tool | add it to `ActionPolicy.grants` |
| `unprotected_tool` | allowed: the tool needs no evidence | nothing |
| `certificate_required` | a protected tool was called without a certificate | `fabric.certify(...)` the evidence first |
| `malformed_certificate`, `unknown_certificate_version`, `certificate_too_large`, `unknown_required_check` | the certificate cannot be read | rebuild it with this version's `certify` |
| `wrong_store`, `wrong_agent`, `wrong_tenant` | the certificate was issued elsewhere or for someone else | certify in this store, as this agent |
| `certificate_expired`, `policy_changed` | the certificate is stale | certify again |
| `no_supporting_evidence`, `evidence_not_found`, `evidence_not_usable` | there is no usable evidence | check the memories exist and are active |
| `evidence_withdrawn`, `dependency_withdrawn`, `dependency_not_found` | evidence, or something it rests on, was withdrawn | **working as intended**: the premise is gone |
| `evidence_version_moved`, `dependency_version_moved` | the evidence was revised after certification | re-read it and certify the new version |
| `insufficient_independent_support` | fewer independent sources than the rule needs | add independent evidence |
| `authority_insufficient` | a piece of evidence came from a tool, a web page, an import, or descends from something withdrawn | review it and `fabric.elevate(...)` as someone other than its author, or lower `ToolRule.min_authority` deliberately |
| `evidence_suspicious` | a piece of evidence contradicts what the store knows: it restates a corrected value, is far out of range, or contradicts an established fact (`validation.assess` gives the signals) | check the claim; validate it if it is right, or withdraw it. `ToolRule(refuse_suspicious=False)` turns the check off |
| `evidence_provisional` | the tool has `ToolRule(refuse_provisional=True)` and a piece of evidence is provisional: a first claim from a new source, untrusted origin, or its author's own change to a fact a reviewer had validated (`revises_validated`) | have a reviewer validate the new claim, or act on evidence that is already vouched for |
| `evidence_not_fresh` | the tool has `ToolRule(require_fresh=True)` and a piece of imported evidence has no valid, unexpired lease from its origin at the held version (`freshness.py`): the peer is offline, the lease expired, the origin withdrew it, or the lease's signature or version does not match | renew the lease from the origin (`issue_lease`, accepted into the gate's `LeaseBook`), or act on native evidence |
| `instruction_is_not_evidence` | a piece of evidence is an instruction | use the observation it is about, not the instruction |
| `human_approval_required`, `approval_invalid` | the tool needs a human approval bound to this certificate (and action) | have an approver approve this exact action |
| `grant_required` | the tool needs a short-lived grant | `gate.issue_grant(...)` from the host |
| `grant_unknown`, `grant_revoked`, `grant_expired` | the grant does not exist, was revoked, or its time ran out (≤ 300 s) | issue a new grant |
| `grant_binding_mismatch` | target, parameters, evidence or agent differ from what was granted | issue a grant for this action |
| `grant_replayed` | the grant was already used | grants are single-use: issue another |
| `state_unavailable` | the store could not be read, or the audit write failed | fix the store; a protected action fails closed |
| `retry_required` | the last attempt with this key timed out or failed with unknown effect | check the tool's side effect, then `execute(..., retry=True)` |

`execute` outcomes: `executed`, `failed` (the tool raised), `timed_out` (it
overran its lease; see `actions.unfenced_changes`), `already_executed` (this
key ran before) and `refused` (see the decision's code). A process that died
mid-action leaves the key `uncertain`: the side effect may or may not have
happened, so the next call is refused with `retry_required`. Check the
tool's effect (the tool received the key for exactly this), then call again
with `retry=True`.

## "LimitExceeded" / HTTP 429 or 413

| code | limit | what to do |
|---|---|---|
| `payload_too_large` | content over 1 MiB (library) or 256 KiB (servers) | split it |
| `write_quota_exhausted` | an agent wrote more than its quota in the window (servers: 600 a minute) | usually a loop; otherwise raise `Limits.writes_per_window` |
| `federation_budget_exhausted` | one peer imported more than its budget (servers: 300 a minute) | wait, or raise `Limits.imports_per_window` for a trusted peer |

## "Permission denied: lacks the 'x' permission"

The session's roles do not include that permission. Agents have read,
write and execute; operators everything except execute; auditors read and
export ([CONCEPTS.md](CONCEPTS.md)). Grant one directly with the role
`perm:<name>`.

## "Offer refused: this memory is N hops from its origin"

A copy may not travel further than a retraction can follow (16 hops).
Share from a store nearer the origin.

## "CompactionRefused"

`compact_session` would have lost something, and wrote nothing:

- *drops values the session recorded*: a custom summariser left a number out;
- *resolves a dispute instead of keeping it*: it picked one side;
- *no usable memories*: everything the session wrote is withdrawn or still a candidate.

## "restore" exits 2, 4 or 5

- **2**: no `.manifest.json` beside the backup. Take backups with this version.
- **4**: the destination exists. Restore into a new directory.
- **5**: the files do not match the manifest, or the replayed log's event
  count or chain head differs. **Do not use this backup.**

## "My memory was quarantined on write"

An ingest screen flagged it. `amberlog --db store.db review <id>`
shows the screen and its signals. For a false alarm:
`review <id> --approve --override-screen --reason "<why>"`.

## Still stuck

`amberlog --db <store> overview` and `doctor --json` are what to attach
to a report. Neither contains memory content. Security problems go to the maintainer by
email, privately ([SECURITY.md](../SECURITY.md#reporting)).
