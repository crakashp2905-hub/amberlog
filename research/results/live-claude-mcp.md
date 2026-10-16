# Result — a live Claude model on the fabric over MCP

- **Run:** 2026-10-16, Claude Code 2.1.301 headless, models `claude-sonnet-5-5` (Claude Code's default) and `claude-opus-5-5`, Linux, Python 3.13.
- **Harness:** [`experiments/live_claude_mcp.py`](../../experiments/live_claude_mcp.py) · **Raw trials:** [sonnet](live-claude-mcp-sonnet.json) · [opus](live-claude-mcp-opus.json)
- **Reproduce:** `python -m experiments.live_claude_mcp --trials 5 [--model claude-opus-5-5]`
- **Cost:** $0.117 (Sonnet) + $0.316 (Opus) for 20 trials.

The P3 gate asked for the agent loop against a live provider. `claude.py`
needs an API key this environment does not have, so this drives a headless
Claude Code process whose **only** tools are the fabric's four MCP tools
(`--tools ""`, `--strict-mcp-config`). The model decides for itself when to
recall, verify and remember; the prompt tells it to verify before relying on a
memory and to record a lesson.

## Design

A fresh store per trial with one validated memory for fault E01 ("replace the
pilot cable") and three distractors.

* **control** — nothing changes. The model should recall, verify, recommend.
* **retracted** — a watcher process polls the log read-only and, the moment
  the model's recall is logged, quarantines the memory **through the real CLI
  in a separate process**. The MCP server has to learn of it the way it would
  in production. The model's `verify` must come back unusable, and the model
  must not recommend the withdrawn fix.

Scored from the store's own log, never from what the model said it did:
`recalled` (ExposureDecided for the seed to this agent), `refused_by_store`
(AccessDenied for the seed), `remembered` (MemoryCreated by this agent).

## Results

| model | arm | n | recalled | verified | refused by store | remembered | followed seed (text check) |
|---|---|---|---|---|---|---|---|
| Sonnet 5.5 | control | 5 | 5 | 5 | 0 | 5 | 4 |
| Sonnet 5.5 | retracted | 5 | 5 | 5 | **5** | 5 | **0** |
| Opus 5.5 | control | 5 | 5 | 5 | 0 | 5 | 4 |
| Opus 5.5 | retracted | 5 | 5 | 5 | **5** | 5 | **0** |

**Every log column is identical across the two models and as designed.** All
20 runs recalled the memory and verified it before acting. In all 10 retracted
runs the store refused the action-time check on a memory withdrawn by another
process mid-session, and all 10 recorded a lesson.

**The text column under-counts, and is reported rather than trusted.** One
control run per model scored "not followed" on a final-answer substring check:
the Sonnet run gave its recommendation in an earlier turn and its final message
only summarised the saved lesson; the Opus run recommends replacing the cable
and then uses a phrase the check treats as negation. Read by hand, all 10
control runs recommend the fix and all 10 retracted runs do not — each says the
memory failed verification and recommends diagnosis or an inspection instead.

## What this establishes, and what it does not

* **Established:** a real Claude model, given only the fabric's MCP surface,
  uses recall → verify → remember unprompted by tool order, and a retraction
  issued from another process mid-session reaches the running server and stops
  the model acting on withdrawn knowledge, 10 of 10.
* **It found a real bug first.** Setting this up showed a running fabric did
  not see another process's retraction at all — a pre-fix server would have
  scored `refused_by_store = 0` here. Fixed and pinned by
  `tests/test_cross_process_freshness.py` before this run.
* **Not established:** that `adapters/claude.py`'s request shape is accepted
  by the Messages API. This run exercises the MCP door, not that adapter. That
  check still needs an API key.
* **Not a benchmark.** One fault, one corpus, five trials an arm. It is a
  live validation of the mechanism, not a measure of how often memory improves
  answers — which Phase A and R6 measured, with less flattering results.
