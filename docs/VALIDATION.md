# What was actually run, and what it showed

Every claim in [README.md](../README.md) about the engineering — as opposed to
the research, which lives in [research/SCORECARD.md](../research/SCORECARD.md)
— traces to one of the checks below. Recorded because "686 tests pass" is not
evidence of anything by itself: what matters is which checks could have failed
and did not.

## Current baseline

**2026-10-18, branch `claude/workplan`** (on top of PR #5), Windows 11,
Python 3.13.5. The README cites the numbers here, not its own. The test count
is checked against the suite on every run; the other rows are as of this date.
Linux and macOS are covered by CI, which has not run since 2026-10-16 (account
billing; see [WORKPLAN.md](WORKPLAN.md), X-CI).

| Check | Command | Result |
|---|---|---|
| Unit, integration, property | `python -m unittest discover -s tests -t .` | **2040 tests**, OK, 15 skipped (Postgres-only file without a server; live-model arms without Ollama or an API key). The count is checked against the suite by `tests/test_suite_hygiene.py`; `python tools/count_tests.py --write` updates it |
| Fault matrix | `python -m experiments.faultsim` | **17/17** |
| Secret scan | `python tools/scan_secrets.py` | 103 high-severity findings, **0 unexpected** |
| Compile | `python -m compileall -q memory_fabric experiments tests examples tools` | clean |
| Lint and types | `python -m ruff check` and `python -m mypy`, as configured in `pyproject.toml` (CI job `lint`) | **clean**: 0 findings, 0 errors in 66 files |
| Package | `python -m build`, then CI's wheel-content checks | wheel and sdist build; dashboard, `py.typed`, LICENSE and the new modules present; experiments and tests excluded |
| Installed copy | venv outside the tree: `memory-fabric demo`, then `doctor` | **sound**, no warnings |
| Examples | each of `examples/*.py` | `action_gate`, `agent_on_the_fabric`, `poisoning_and_rollback` exit 0. `live_memory_os` exits 2: it needs a running Ollama server, which this host does not have |
| End-to-end, real processes | `python -m experiments.e2e_validation` ([result](../research/results/e2e-validation.md)) | **22/22** after a fix: an action gate in a long-running process verified against a stale projection and **allowed** an action on evidence another process had retracted |
| Claude adapter contract | `tests/test_claude_contract.py` with `anthropic` 1.15 installed (CI job `claude-contract`) | 5/5: the real SDK accepts every argument and the loop runs append-only. **Not a live call**: there are no direct-API credentials here |
| Live Claude over the agent HTTP API | `python -m experiments.live_claude_http --trials 3` ([result](../research/results/live-claude-http.md)) | 3/3 control and 3/3 retracted recalled and verified; the store refused all 3 retracted `verify` calls over HTTP; $0.07 total. Found the credential-expiry bug on the way |
| CI | GitHub Actions on `3c76bd8` (the PR #4 head that was squashed into `1978d2b`) | all 14 jobs green |

Later runs in this file are kept as history.

## History

- **Run:** 2026-10-11, commit at `HEAD` of `main`, Python 3.13.5 on Windows 11.
- **Automated in CI:** rows 1–5 and 11 on every push, across Python 3.11–3.13 on Linux, macOS (since 2026-10-16) and Windows, plus the storage-touching suite on PostgreSQL 16. The rest are run by hand before a release, which is why they are written down.
- **Re-run:** 2026-10-16 on Linux, Python 3.13.16, after fixing the two causes of a red `main` (below): row 1 as `python -m unittest discover -s tests -t .` — **1086 tests OK, 30 skipped** (no Ollama, so the real-embedder arms skip and say so); row 2 **17/17**; row 3 71 findings, **0 unexpected**; row 4 clean; row 6 repeated from the README verbatim — `demo`, `attention`, `doctor` (sound), the Python quick start, the multi-tenant snippet and both `examples/` scripts, all exit 0 from a clean venv; row 16 added.
- **CI was red on `main` for seven consecutive pushes** (from 1b35fbd) and the rows above kept saying it ran green. Six test jobs failed on a benchmark arm that needs Ollama; from 1d20bf5 the fault matrix failed too, on a real truth-maintenance disagreement. Neither was flaky. "Automated in CI" is only evidence while someone reads the result.

| | Check | Result |
|---|---|---|
| 1 | `pytest tests` | **1065 passed**, 924 subtests |
| 2 | `python -m experiments.faultsim` — deterministic multi-store fault matrix | **17/17 scenarios**, 7 invariant checks after every step |
| 3 | `tools/scan_secrets.py` (now scoped to files git will commit) | 70 high-severity findings, **0 unexpected** (every one allow-listed with a reason) |
| 4 | `compileall` over `memory_fabric`, `experiments`, `tests`, `tools` | clean |
| 5 | Wheel contents | `py.typed`, `identity.py` and `dashboard.html` present; `experiments/` and `tests/` excluded; LICENSE recorded in `dist-info/licenses/` |
| 6 | Install into a clean venv **outside the source tree**, then run the console script | `demo`, `tenants` and `doctor` all work; `doctor` reports **sound**, 9 ok and 0 warnings, on a store created fresh for the run |
| 7 | Two-hop retraction over a **real socket** with tenancy on | origin → hop 1 → hop 2 all `quarantined`; tenant preserved at the far end; a well-formed unsigned request refused **401** with a body of exactly `{"rejection_code": "unauthorized"}` |
| 8 | Both `REFERENCE_DEPLOYMENT.md` Python blocks extracted and run **verbatim** in a clean directory | exit 0 |
| 9 | Observability surface | `GET` 200 on `/`, `/api/overview`, `/api/propagation`; **`POST` 405**; unauthenticated **401**; wrong token **401**; `build_server` refuses its own no-auth default off loopback |
| 10 | A rewritten **0.3.0-era store** — no `tenant_id`, old inbox primary key | replays; tenant defaults to `tn_default`; inbox migrates in place and carries its row with an empty `target_key`; `doctor` reports sound |
| 11 | Docker image built and served over the published port as a non-root user | CI job `docker` |
| 12 | **Multi-process concurrency** — 4 processes × 20 appends on one store | all 80 land; sequence a gapless run; hash chain verifies; a zero-timeout writer fails cleanly rather than corrupting |
| 13 | **Version skew** — a 0.2.0/0.3.0 store on current code | replays; every added field's absent-meaning preserves old behaviour; the new retrieval filters do not exclude old data; `doctor` sound. A 99.0.0 store is refused with a schema failure |
| 14 | **Protocol skew** — a hop-0 retraction round-tripped through the 0.3.0 field set | byte-compatible: no new fields serialised, and the minimal payload still applies and enforces |
| 14a | **External benchmark** — SciFact (BEIR/MTEB), 300 judged queries over 5,183 abstracts, third-party labels | the parameter-free lexical arm scores 0.621 nDCG@10 against published BM25's ~0.665 — a little under properly-tuned BM25, which is where it should be. The shipped hashing embedder scores **0.315**; a trained embedder scores 0.701 and **0.726** fused, above published BM25 |
| 14b | **Downstream (R6)** — a real model over the benchmark, 3 seeds, blind substring grading | inconclusive against its registered bar (20% of headroom against 40%); retrieval beat stuffing the corpus at a third of the tokens; zero gate violations across every arm and seed |
| 15a | **Data-access audit** — every public member of `MemoryFabric` classified, enforced by test | 50 members classified; adding one fails the test until it is. Found 2 real misuses of the unenforced read in shipped code |
| 16 | **MCP interop** — `memory-fabric mcp` driven by the official MCP Python SDK client over stdio | negotiates `2025-06-18`; lists exactly `recall`, `fetch`, `verify`, `remember`; a `remember` lands as a private `candidate`; `verify` on a memory not recalled this session is a tool error |
| 17 | **Live Claude over MCP** — Sonnet 5.5 and Opus 5.5, 5 trials per arm each, retraction issued by a separate CLI process mid-session ([result](../research/results/live-claude-mcp.md)) | 20/20 recalled and verified; retracted arm refused by the store **10/10** and no model recommended the withdrawn fix; $0.43 total |
| 18 | **Secret-screen red team** — 13 obfuscated credentials and 9 near-miss negatives (`tests/test_sensitive_redteam.py`) | **0/13 → 12/13** caught at high severity; 0 near-miss false positives; display scrubbing removes the disguised value. One known miss (a reversed key), recorded with its reason |
| 15 | **Tamper detection** — edited payload/timestamp/actor, deleted event, reordered pair, missing link, truncated log, wholesale chain rewrite | each caught, at the right sequence; the rewrite caught only by an external checkpoint |

## Two results worth stating rather than scoring

**The new fault scenarios were falsified before being trusted.** A scenario that
passes whether or not the feature exists is worth nothing, so each was run
against a deliberately broken build:

- With forwarding disabled (`_forward_retraction` stubbed to 0), **all five** transitive scenarios fail, each naming the store that applied a retraction to a memory it had re-shared with no onward delivery recorded.
- With the deduplication key narrowed back to the campaign alone, **only `diamond_both_copies` fails** — `bob:via-alice@bob expected quarantined, found active`.

So the two changes are tested separately rather than by one scenario that would
have passed on either.


## What the by-hand rows found that the suite did not

Rows 6–10 are run by hand, and on the first pass three of them reported
failures. Two were the harness's fault and one was not — which is roughly the
ratio worth expecting, and the reason the distinction is written down rather
than smoothed over.

**My harness, not the code.** Row 8 failed with an `OSError` from Windows
socket initialisation because the probe cleared `PATH`. Row 9 printed "FAIL
unauthenticated accepted" because the probe called `build_server(auth=None)`,
which explicitly means no authentication. Row 7's first attempt posted `{}` and
got **400**, not the documented 401, because an empty object is rejected on
protocol version before authentication is ever reached; a *well-formed* unsigned
retraction does get 401, as the documentation claims.

**Three real defects, all on the fail-closed path**, found by chasing those
false alarms rather than by the 715 tests that were passing at the time:

1. **A refusal returned the store's internal state.** The full `Acknowledgement` was the 401 body, carrying `recipient_store_id`, `state_revision` — this store's event-log head — and `origin_sequence_seen`. An unauthenticated caller learned the identity of the store it had just failed to authenticate to, and could poll the head sequence as a live activity oracle. Now a rejection code and nothing else. It is still audited locally: saying nothing to the caller is not the same as recording nothing, and a fix that traded a disclosure for a blind spot would not be one.
2. **`build_server` could publish the whole store unauthenticated.** `auth=None` built a tokenless config with **no host check**, so `build_server(fabric, host="0.0.0.0")` served every memory to the network while `build_config` sat one call away raising `InsecureConfiguration` for exactly that combination. The docstring said "`serve` refuses that off loopback" — true, and beside the point, since `build_server` is public and is the function a caller reaches for. Its default now goes through the same refusal. Unauthenticated on loopback still works, because a test and a local one-off both want it.
3. **A documented guarantee was false and unachievable.** The handler's docstring and INVARIANTS.md row 11 both said an unauthenticated request is refused "before the message is even parsed". It is not, and it cannot be: the key is looked up by the *claimed* origin store and that claim lives in the body. What actually holds is that nothing is applied until the MAC verifies. Both documents now say that, and the parse-failure reply no longer echoes the parser's own message about the bytes it was handed.

Each has a test that **fails against the previous behaviour** — verified by
reverting the handler and re-running, the same discipline applied to the
transitive fault scenarios. None of these had a test before, which is exactly
why the leak survived a green suite: the assertions looked at the status code
and never at the body.

**Three checks found real bugs while being written**, which is recorded here
because it is the honest argument for the checks existing:

1. `doctor`'s retraction-delivery check could never fire. `pending()` excludes terminal states and `FAILED` is terminal, so the worst case this check exists for was invisible to it. It queries the table directly now.
2. `doctor`'s cross-tenant check degraded to a warning naming a *function* rather than a check, because it called `Enforcer.check` with an argument that method does not take — and only a store with blocked memories in it reached the line. The fixture is populated now, and a test asserts that no check crashes.
3. `derive` put a tenant's conclusion in `tn_default`, where any agent scoped there could read it, even though the acting agent and every premise were elsewhere. Found by the test for the ordinary within-tenant case, not by the one for the attack.

## What none of this establishes

- **Nothing here is a performance claim.** The accuracy thesis was tested properly and failed; [SCORECARD.md](../research/SCORECARD.md) has that, and these checks say nothing about it.
- **Concurrency is now tested, and the first account of it was wrong.** I added an explicit `busy_timeout` pragma and wrote that it fixed concurrent writers failing instantly, believing SQLite's default to be zero. That is true of the C library and false of Python: `sqlite3.connect` sets 5 seconds of its own accord, so writers had always serialised. The falsification run — remove the pragma, expect the contention tests to fail — passed instead, which is what caught it. The pragma stays because it makes the value visible and configurable, not because it repaired anything.
- **The multi-process contention tests are weaker than they look, and `experiments/p4_envelope.py` is the answer to that.** The sweep runs 10, 25 and 50 real processes over 4.16 s, where overlap is no longer in doubt, and reports 500 appends landing with no sequence gaps and per-write cost rising 22% for 5× the writers ([result](../research/results/p4-envelope.md)). The original note stands for the tests themselves:
- **The multi-process contention tests are weaker than they look.** They pass with the pragma removed, because the writers do not reliably overlap on a fast disk. They are strong evidence nothing is lost or corrupted under real load, and no evidence about timeout behaviour; the two deterministic tests that hold a write lock open are the ones that isolate that. The first version of *those* was also weak — `child.poll()` being None only proved the child had not finished importing — so the child now signals readiness before contending.
- **The sensitive-data detector now has an adversarial corpus, and it is still pattern-based.** `tests/test_sensitive_patterns.py` gives every one of the 26 classes a synthetic positive *and* a near-miss negative — prose naming the same vendor or prefix — plus seven ordinary benchmark memories that must not fire at all. A test asserts no pattern can be added without both cases. What that does **not** fix is the underlying limit SECURITY.md names: a pattern cannot catch a format nobody anticipated, and the thirteen classes added were the ones this project happened to think of second rather than a survey of what exists.
- **Tenancy is checked as authorisation, not as isolation.** Every test here runs in one process against one file. Nothing demonstrates — or could demonstrate — isolation against a caller holding the database.
- **The secret scan was auditing files that cannot be committed.** Downloading LongMemEval produced ten high-severity findings inside a 277 MB chat corpus — simulated conversations about passwords and tokens, one containing a `-----BEGIN` block. All real matches, all in a gitignored file. The scan's purpose is that nothing secret reaches the repository, and a file git will not take cannot; auditing it buries the 59 allow-listed fixtures under noise. It now skips gitignored paths, and falls back to scanning everything if git is unavailable, because the safe failure for a secret scanner is to look at more rather than less.
- **The internal benchmark is still mine**, but it is no longer the only one. SciFact's labels were written by third parties years earlier, and it immediately showed `relevance_v1` flattering the hashing embedder by a factor of four in the size of the gap.
- **The test count in row 1 has been wrong once, by 9.** Three documents said 974 where the suite collects and passes **965**; re-running the documented command is what found it. The 974 cannot be reproduced at the commit that recorded it (959 collected there), so it was a transcription error, not a regression — and a table row is exactly where "no numbers in docs without a run" is easiest to violate without noticing.
- **A single run on one machine.** CI covers rows 1–5 and 11 across six interpreter/OS pairs; rows 6–10 were run by hand, here.
- **The by-hand rows are not regression-proof.** The three defects above now have tests, so those specific failures are caught in CI from now on. The rows themselves are still a human running commands, which is why the harness mistakes in them are recorded above rather than quietly re-run until green.
