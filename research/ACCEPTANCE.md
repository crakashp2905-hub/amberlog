# Product acceptance report

**2026-10-24, branch `claude/wonderful-newton-t55gww` at `62a6ca1`, before merging `main`.** This
covers plan Phases 1–5. Every number below links to the run that produced it.
Where something was not done or did not pass, this report says so.

## Verdict

**Accepted for the supported deployment, with the release blockers in §6
open.** The supported deployment is one `agent-api` process (or the library
in one process) per store, up to 100 concurrent agents, on SQLite. The
blockers concern evidence this environment could not produce (a direct
Claude API call, CI on these commits, a Docker build). They do not concern
the product's behaviour. No PyPI release was made and none is intended until
the owner says so.

## 1. Release qualification (Phase 1 and Phase 4)

Run on `62a6ca1`, Linux, Python 3.13:

| check | result |
|---|---|
| unit, integration, property (`python -m unittest discover -s tests -t .`) | **1318 OK, 27 skipped** (Postgres-only without a server; live-model arms without credentials) |
| fault matrix (`experiments.faultsim`) | **17/17** |
| end-to-end across real processes (`experiments.e2e_validation`) | **22/22** |
| secret scan (`tools/scan_secrets.py`) | 97 high-severity findings, **0 unexpected** |
| compile, examples | clean; the three offline examples exit 0 |
| package | wheel and sdist build; installed outside the tree, `demo` then `doctor`: **sound**; no tests or experiments in the wheel |
| upgrade from every shipped schema, then backup and restore | passes for 0.2.0–0.8.0 (`tests/test_version_skew.py`) |
| CI | **not run on these commits.** CI triggers on pull requests, and none is open for this work. The last CI run on this branch (`3c76bd8`) was green on all 14 jobs |

Metadata: author and copyright holder C R Akash Preetham, proprietary
licence, recorded in `pyproject.toml`, `LICENSE`, the README and the image
labels.

## 2. Correctness (Phase 2)

Found and fixed, each with a regression test:

- An action gate in a long-running process verified against a stale
  projection and **allowed** an action on evidence another process had
  retracted.
- Raw exception text leaked over the agent API and MCP. Concealed
  cross-tenant `derive` confirmed that an id exists.
- Credentials expired 1000× early (seconds were added to milliseconds).
- Encoding noise (zero-width characters, ligatures, non-ASCII hyphens) let a
  withdrawn document be re-ingested as independent evidence.
- Found while hardening in Phase 4: authentication read SQLite outside the
  store lock (a regression introduced by the rate limiter), and the socket
  backlog of 5 reset connections at 100 agents.

Live integrations: Claude through Claude Code over MCP
([result](results/live-claude-mcp.md)) and over the agent HTTP API
([result](results/live-claude-http.md)). The direct-SDK adapter is
contract-tested through the real `anthropic` SDK with HTTP stubbed. It has
**not** made a live API call (§6).

## 3. Real-world value (Phase 3)

All pre-registered, with an oracle arm that no arm exceeded, and with raw data
committed. Full rows are in [SCORECARD.md](SCORECARD.md) §2c.

- **D1: a real model behind a governed store** ([result](results/d1-downstream.md)).
  `sonnet`, 5 seeds. Task success went from 0.492 to **0.867** (oracle
  1.000). Harmful answers went from 0.508 to **0.133**. Valid evidence blocked:
  0.000. Critical omissions: 0.000 in both arms. Two harness corrections are
  disclosed in the result. The size of the gain is set by the registered case
  mix. The residual harm is **undetected poison**, which no governance
  mechanism here addresses.
- **P2b: sufficiency at a fixed 400-token budget** ([result](results/p2b-budget.md)).
  It passed narrowly, on one family. `multi_hop_4` is still unsolved.
- **Injections:** current models acted on 1 of 40 injected notes with no
  screen at all. P5's obedient-agent injection figures are an upper bound.

## 4. Production hardening (Phase 4)

- **Scale:** one API process holds 159–195 ops/s from 1 to 100 agents, with
  p99 of about 1.2 s at 100 ([P12b](results/p12b-api-load.md)).
  One process per agent collapses to 4 ops/s and is not supported
  ([P12](results/p12-load.md)).
- **Rate limits:** per-agent token bucket, per-address limit on failed
  authentications, `429` with `Retry-After`. The token cache is bounded.
- **Recovery, backup and restore, migration:** crash in mid-retraction, then
  recovery (e2e E2); backup and restore (E3, `tests/test_backup.py`); upgrade
  from every shipped schema, then backup (above).
- **Operations:** [OPERATIONS.md](../docs/OPERATIONS.md) §4a states the supported scale
  and how to size rate limits.

## 5. Advanced research (Phase 5)

**Proof-carrying memory: not built, because no gap demands it.** The plan
made it conditional on closing a demonstrated gap. The product already
carries the useful part. An `EvidenceCertificate` names the evidence an action
relied on, and the action gate re-verifies it at action time, across
processes (e2e E1). The gaps that the measurements actually show are
different:

- undetected poison (D1: 15 of 15 harmed);
- paraphrased injections passing the screen (P5);
- a missing hop on `multi_hop_4` (P2b).

A proof that a memory was validated does not help when the validation itself
was fooled, which is the undetected-poison case. Building it now would add a
mechanism with nothing to measure it against.

**Causal incident reconstruction: evaluated.** P9 replays the log read-only
and predicts which sources an action depended on. Against live withdrawal it
scored precision **0.996** and recall **1.000**, after a 20% false-attribution
bug was found and fixed ([result](results/p9-incidents.md)). Its
limit: it reconstructs dependence that is recorded in the log, and it cannot
see reasoning a model did not cite.

**Independent-evidence preservation: evaluated.**
- Selective reassessment blocks less valid evidence than blanket withdrawal
  at the same safety: 0.064 against 0.133 (P5 H5c).
- Copy recognition stops a re-ingested withdrawn document from counting as
  independent support. The product matches the oracle on both splits
  ([result](results/p2b-copy-recognition.md)). Since Phase 2 this
  also holds through encoding noise.

## 6. Release blockers and open items

| item | status | what closes it |
|---|---|---|
| CI on these commits | **open** | open a pull request; CI runs on pull requests |
| direct Claude API live call | **open**: no API credentials in this environment | a run of `examples/` or the adapter with a key |
| Ollama arm (`live_memory_os`, R6 reproduction) | **open**: network policy blocks the model download | allow ollama.com in the environment |
| Docker image | **unverified here**: no Docker daemon | CI's image job |
| PyPI release | **withheld by the owner's decision** | owner's go-ahead |
| undetected poison | **known limit**, documented | none here; it needs a detection signal outside the store |
| paraphrased injections | **known limit** of a pattern screen, measured | a model-based screen, if a model is in the loop |
| `multi_hop_4` chains | **open research** | P1 §4 and the relations ceiling describe the route |
| more than 100 agents per store; multi-host | **unmeasured / unsupported** | P9 declined distribution on measurement |
