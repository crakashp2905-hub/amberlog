# Live Claude over the agent HTTP API

Produced by `python -m experiments.live_claude_http` at commit `0ae070a`; raw
trials in [live-claude-http.json](live-claude-http.json). Model(s): claude-sonnet-5-5
(Claude Code's default), driven headless with **only** `curl` allowed.

Scored from the store's event log, not from the model's account: *recalled* is
an `ExposureDecided` for the seed memory, *refused* an `AccessDenied` for it
(the verify that came back unusable), *remembered* a `MemoryCreated` by the
agent. *Followed* is a text check on the final answer, reported but not
trusted.

| arm | trials | recalled | called verify | refused by the store | recommended the seed's fix | remembered | cost |
|---|---|---|---|---|---|---|---|
| control | 3 | 3 | 3 | 0 | 3 | 3 | $0.03 |
| retracted | 3 | 3 | 3 | 3 | 1 | 3 | $0.04 |

Trials excluded for a harness error: 0.

**What it shows.** A model that knows nothing of this system can use the
HTTP API from a shell, and a retraction issued by a separate process reaches
its `verify` over HTTP. **What it does not.** It is a handful of trials of one
model on one scripted task, so it is an integration check, not a measurement
of how often models comply. That question is the MCP run's
([live-claude-mcp.md](live-claude-mcp.md)), and with this few trials, this
run cannot answer it either.

**Reading the answers.** The table's *recommended the seed's fix* column is a
text check, and it flags retracted trial 2. Read in full, all three retracted
answers decline the withdrawn fix. Trial 2 says "failed verification
(`blocked_lifecycle`), so I didn't rely on it" and treats the cable only as
something to inspect. "didn't rely" is not in the check's phrase list, so the
check misfired. The check is left unchanged rather than tuned after seeing the
result. The log columns are the measurement: the store refused all three
`verify` calls over HTTP.

**Bug found by running it.** The first attempt reached the API and was refused
every time. Credentials expired 1000x early, because seconds were added to a
millisecond clock. It is fixed in the same branch (see CHANGELOG, "Fixed").
These trials ran after the fix.
