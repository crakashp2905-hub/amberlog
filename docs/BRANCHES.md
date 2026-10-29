# Branches

One line of development. `main` is the integrated line. Everything below it
either has been merged into it or is kept deliberately as a record.

| branch | role | state |
|---|---|---|
| `main` | The integrated line. Every merged result, the release candidate's fixes, and research that is registered and opt-in | current |
| `claude/workplan` | Where the work in [WORKPLAN.md](WORKPLAN.md) happens. Merged into `main` as it lands | active; `main` contains it |
| `rc/0.11.0` | The frozen 0.11.0 release candidate, with its acceptance record ([RELEASE_EVALUATION.md](RELEASE_EVALUATION.md)). Gets fixes only. The tag waits on CI (WORKPLAN X-CI) | frozen; merged into `main` |
| `claude/integrate-local-research` | PR #5, which integrated the local research line onto the remote one | fully contained in `main` |
| `claude/wonderful-newton-t55gww` | PRs #1–#4: CI, MCP, the safety plan | fully contained in `main` |
| `archive/local-main-2026-10-15` | The local line before integration, kept as found | **archive**, never merged |
| `wip/local-fabric-on-postgres` | The archive plus one parked WIP commit (Fabric on Postgres through a sqlite3-dialect adapter) | **archive**, never merged |

**Why the two archives are not merged.** They hold the local line's
*alternative* implementations: its own MCP server (`amberlog/mcp/`), a
storage layer (`amberlog/storage/`) and a Postgres event log. The
integration (PR #5) decided that the remote implementations win, which are
`adapters/mcp.py` and `pgcompat.py`, and that only measured wins are ported.
Merging the archives would bring back two parallel implementations of the
same things. They stay so that the history and the numbers measured on them
remain checkable.

**Conventions.**

- New work branches from `main`.
- Long measurements run in a `git worktree` pinned to a commit, and the
  commit is cited in the result.
- A release candidate is cut as `rc/<version>` and receives fixes only. They
  are cherry-picked from `main` or made there and merged back.

## Protection

Verified on 30 October 2026: this repository is public and `main` has
server-side branch protection. All 31 job contexts from its last successful
CI run are required, bound to the GitHub Actions app. Branches must be current
with `main`, administrators are included, force pushes and deletion are
blocked, and review conversations must be resolved. Pull requests are required;
the approving-review count is zero because no independent reviewer has been
assigned. This does not satisfy the independent security-review gate.

The added official MCP-client check must also become required once its first
candidate CI run succeeds. Release and package workflows separately require
name clearance, release approval and an approved exact source SHA. Those
approval variables remain unset or false; branch protection is not permission
to publish.

Install `tools/hooks/pre-push` with `sh tools/install-hooks.sh` as a local
additional guard for other branches. `tools/backup.sh` creates a verified Git
bundle outside the checkout; test restoration separately from CI protection.

API reference: [GitHub branch protection](https://docs.github.com/en/rest/branches/branch-protection).
