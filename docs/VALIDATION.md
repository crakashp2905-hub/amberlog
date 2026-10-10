# What was actually run, and what it showed

Every claim in [README.md](../README.md) about the engineering — as opposed to
the research, which lives in [research/SCORECARD.md](../research/SCORECARD.md)
— traces to one of the checks below. Recorded because "686 tests pass" is not
evidence of anything by itself: what matters is which checks could have failed
and did not.

- **Run:** 2026-10-11, commit at `HEAD` of `main`, Python 3.13.5 on Windows 11.
- **Automated in CI:** rows 1–5 and 11 on every push, across Python 3.11–3.13 on Linux and Windows. The rest are run by hand before a release, which is why they are written down.

| | Check | Result |
|---|---|---|
| 1 | `pytest tests` | **715 passed**, 127 subtests |
| 2 | `python -m experiments.faultsim` — deterministic multi-store fault matrix | **17/17 scenarios**, 7 invariant checks after every step |
| 3 | `tools/scan_secrets.py` | 58 high-severity findings, **0 unexpected** (every one allow-listed with a reason) |
| 4 | `compileall` over `memory_fabric`, `experiments`, `tests`, `tools` | clean |
| 5 | Wheel contents | `py.typed`, `identity.py` and `dashboard.html` present; `experiments/` and `tests/` excluded; LICENSE recorded in `dist-info/licenses/` |
| 6 | Install into a clean venv **outside the source tree**, then run the console script | `demo`, `tenants` and `doctor` all work; `doctor` reports **sound** with 9 ok and 0 warnings |
| 7 | Two-hop retraction over a **real socket** with tenancy on | origin → hop 1 → hop 2 all `quarantined`; tenant preserved at the far end; an unsigned request refused |
| 8 | Both `REFERENCE_DEPLOYMENT.md` Python blocks extracted and run **verbatim** in a clean directory | exit 0 |
| 9 | Observability surface | `GET` 200 on `/`, `/api/overview`, `/api/propagation`; **`POST` 405**; unauthenticated **401**; wrong token **401** |
| 10 | A rewritten **0.3.0-era store** — no `tenant_id`, old inbox primary key | replays; tenant defaults to `tn_default`; inbox migrates in place and carries its row with an empty `target_key`; `doctor` reports sound |
| 11 | Docker image built and served over the published port as a non-root user | CI job `docker` |

## Two results worth stating rather than scoring

**The new fault scenarios were falsified before being trusted.** A scenario that
passes whether or not the feature exists is worth nothing, so each was run
against a deliberately broken build:

- With forwarding disabled (`_forward_retraction` stubbed to 0), **all five** transitive scenarios fail, each naming the store that applied a retraction to a memory it had re-shared with no onward delivery recorded.
- With the deduplication key narrowed back to the campaign alone, **only `diamond_both_copies` fails** — `bob:via-alice@bob expected quarantined, found active`.

So the two changes are tested separately rather than by one scenario that would
have passed on either.

**Three checks found real bugs while being written**, which is recorded here
because it is the honest argument for the checks existing:

1. `doctor`'s retraction-delivery check could never fire. `pending()` excludes terminal states and `FAILED` is terminal, so the worst case this check exists for was invisible to it. It queries the table directly now.
2. `doctor`'s cross-tenant check degraded to a warning naming a *function* rather than a check, because it called `Enforcer.check` with an argument that method does not take — and only a store with blocked memories in it reached the line. The fixture is populated now, and a test asserts that no check crashes.
3. `derive` put a tenant's conclusion in `tn_default`, where any agent scoped there could read it, even though the acting agent and every premise were elsewhere. Found by the test for the ordinary within-tenant case, not by the one for the attack.

## What none of this establishes

- **Nothing here is a performance claim.** The accuracy thesis was tested properly and failed; [SCORECARD.md](../research/SCORECARD.md) has that, and these checks say nothing about it.
- **No concurrency testing.** One writer per store, which SQLite enforces and nothing here stresses.
- **No adversarial testing of the sensitive-data detector.** It is pattern-based and misses novel formats, as SECURITY.md says.
- **Tenancy is checked as authorisation, not as isolation.** Every test here runs in one process against one file. Nothing demonstrates — or could demonstrate — isolation against a caller holding the database.
- **A single run on one machine.** CI covers rows 1–5 and 11 across six interpreter/OS pairs; rows 6–10 were run once, by hand, here.
