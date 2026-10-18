# P12b raw measurements

Raw output kept so the capacity write-up can cite runs that cannot be
reproduced exactly: some of the code they measured was never
committed. All on one machine: Windows 11, 8 CPUs, Python 3.12.13 (the
`D:/pg-trial` venv, for psycopg), local PostgreSQL 16. Each JSON's own
`commit` field is what `git rev-parse` printed, **which is not always the code
that ran** -- the table says what did.

| File | Produced by | Code that ran |
|---|---|---|
| `sweep-before.json` | `python -m experiments.p12_load`, SQLite and Postgres, 1/10/50/100 agents | a clean worktree at `8ffba19`: full `_replay` on every cross-process refresh |
| `sweep-after-worktree.json` | the same command | `8ffba19` **plus the uncommitted** `_catch_up` change, later committed in `ec1fa43` without the thread lock that commit also added |
| `sweep-poll-arm.json` | the same command with `MF_WRITER_WAIT=poll`, SQLite only | as above, plus the polling-BEGIN arm, which was measured, not adopted and removed |
| `profile-before.json` | `python -m experiments.p12_profile --agents 10` | `8ffba19` working tree before `_catch_up` |
| `profile-after.json` | the same | with `_catch_up` |
| `http-before-lock-fix.json` | `python -m experiments.p12_http --agents 1 10` | before the fabric lock: 39 of 200 requests failed with `sqlite3.InterfaceError` |

The before/after comparison is valid because the two runs used the same
machine and harness on the same day; the commit hashes alone would not show
it. The numbers that go in the published tables are re-measured in a worktree
pinned to a commit, so that their `commit` field is the code that ran.
