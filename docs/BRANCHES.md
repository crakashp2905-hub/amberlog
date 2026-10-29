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

**GitHub cannot protect branches here.** Branch protection and rulesets
return "Upgrade to GitHub Pro or make this repository public" for a private
repository on the free plan, so the server refuses nothing. The repository
stays private, and protection is enforced from the clone instead:

- **`tools/hooks/pre-push`** refuses to delete `main`, `rc/*`, `archive/*` or
  `wip/*` on the remote, and refuses any push to them that is not a
  fast-forward. A forced rewind is caught too, because the hook checks
  ancestry itself. Install it in every clone with `sh tools/install-hooks.sh`.
  An intended exception needs `--no-verify`, visibly.
- **`tools/backup.sh`** writes every branch and tag into one verified
  `git bundle` outside the repository, by default `../Memory-backups/`. To
  restore: `git clone <bundle>`. A bundle survives the loss of the GitHub
  repository, which no hook can.

If the account moves to GitHub Pro, server-side protection on `main` and
`rc/*` should replace the hook: no force-push, no deletion. Do not require
status checks while CI billing is broken (WORKPLAN X-CI), or nothing could
merge.
