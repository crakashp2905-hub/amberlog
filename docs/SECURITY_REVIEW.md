# Security review, 2026-10-18 (release gate G5)

The pre-release security review for [WORKPLAN.md](WORKPLAN.md) G5. It
supplements the threat register in [SAFETY_AND_SECURITY.md](SAFETY_AND_SECURITY.md),
which stays the single list of threats; this records what was reviewed, what
was found, and the state of every item at the end. It is an internal review by
the project's own developer, not an external audit, and claims nothing beyond
the checks it names.

**Result: no open critical or high finding.** Four high findings were found
-- two during the review, and F10 and F11 after it first closed, each of
which reopened it -- and all four are fixed and tested. The open items are
medium or low, each accepted with a stated reason, and none is a release
blocker by the criteria in §4.

## 1. Scope and method

Code at branch `claude/workplan`, which contains `main` plus PR #5 and the
release work. Reviewed:

- **Every surface an agent or peer can reach:** the MCP server
  (`adapters/mcp.py`), the agent HTTP API (`agent_api.py`), the federation
  server (`transport.py`), the dashboard (`observability/`), and the service
  sessions they sit on.
- **The paths changed in this release cycle:** cross-process refresh, the
  fabric lock, authentication ordering, erasure, the copy index, the CLI's new
  revocation and agent filter.
- **A pattern sweep of `memory_fabric/`** for the shapes that produce critical
  bugs: SQL built from strings; secret comparisons that are not constant-time;
  non-cryptographic randomness for tokens; shell, `eval`, `exec`, `pickle`,
  `yaml.load`, `marshal`; file paths taken from requests; outbound requests to
  caller-chosen addresses.
- **Concurrency under load,** by running the deployment shapes at 10–100
  agents ([P12b](../research/results/p12b-catch-up.md)), which is how the
  first high finding was found. A review that only reads code would not have
  seen it.

## 2. Findings

Severity: **critical** — remote compromise or loss of a core guarantee without
preconditions. **High** — a core guarantee fails under realistic use.
**Medium** — a guarantee weakened under specific conditions, or a significant
availability loss. **Low** — correctness or assurance gaps with no direct
security consequence.

| # | Finding | Severity | Status |
|---|---|---|---|
| F1 | **Concurrent requests shared one SQLite connection.** The agent API authenticated outside its lock, so the revocation read ran concurrently with another request's statements; 39 of 200 requests failed at 10 agents, one with "no more rows available". A read corrupted that way can answer "not revoked". The federation server had no lock at all. | High | **Fixed** (`ec1fa43`): one fabric-owned lock for every server; S17. `test_concurrent_requests.py` reproduced it before the fix |
| F2 | **Crypto-erasure left earlier versions' plaintext in a running process,** in `state.history`, served by `history()` and the dashboard's version list. Invariant 12 says the text goes. | High | **Fixed** (`ec1fa43`); S18, `test_erasure_residue.py` |
| F3 | **Erasure left the erased text's term set in the copy index** of a running process, used to match incoming writes against it. | Medium | **Fixed** (`0985008`); S18 |
| F4 | **Write contention collapsed throughput** to 4.4 ops/s at 100 agents because every refresh replayed the whole log: one busy agent degraded every other on the store (S9). | Medium (availability) | **Fixed** (`ec1fa43`): 103 ops/s at 100 agents. Residual ceiling ~100–135 ops/s per store, documented in DEPLOYMENT.md §3 |
| F5 | **No command revoked a credential.** Revocation was a Python API only, so an operator answering a leak had to write code. | Medium (operability) | **Fixed** (`ac02009`): `agent-api-revoke`, tested against a live server; runbook §1 |
| F6 | An oversized request was refused without reading its body, so the client saw a connection reset instead of 413, 1 run in 5 on Windows. | Low | **Fixed** (`8ffba19`) |
| F7 | A memory unindexed by `forget` and validated back stayed unretrievable in that process; `revise` could index superseded text after a concurrent revision. | Low (correctness) | **Fixed** (`ec1fa43`); `test_catch_up.py` |
| F8 | `sdk._wrap` could hand an agent a memory without the exposure token `verify` needs. | Low | **Fixed** (`3c27c35`): refused instead |
| F10 | **Scope was not enforced on reads.** Retrieval and the enforced read checked lifecycle and tenant only, so a validated `private` memory -- restricted ones included -- was returned to every agent in its tenant, although the specification and glossary define scope as visibility. Found while building the console's reach view, after this review first closed. | High | **Fixed**: private is the writing agent only, on retrieval, the enforced read, certificates and the SDK; restricted memories cannot be written or shared wider; `derive` is capped by its premises; the value gate moved to `federated` so team sharing works. S19, `test_scope_visibility.py`. Breaking, with an upgrade command |
| F11 | **A retraction delayed by an outage could be silently dropped.** Supersession compared each arriving retraction against one cursor per *origin store*, so once a later retraction of a *different* memory had arrived first, the delayed one was rejected as "superseded": its memory stayed active at the recipient, and the origin recorded the delivery as settled, so neither `doctor` nor the delivery status showed it. Found while designing S1 (federated correction), by reasoning about reordering and then reproducing it. | High | **Fixed**: supersession is per origin memory *and version* -- stale means a retraction of the same copy with a higher sequence was already applied (version too, so a correction's retractions of the v1 and v2 copies cannot discard each other). Regression test `test_retraction_protocol.py::ReorderedDeliveryAcrossMemories`. The reconciliation cursor's remaining limit is documented on `Outbox.missed_since` |
| F9 | `tests/test_memeval.py` never ran in CI, and its `import pytest` would have errored the job: CI runs `unittest` with nothing installed. | Low (assurance) | **Fixed** (`8ffba19`); `test_suite_hygiene.py` forbids pytest-only files |

**The pattern sweep found nothing.** String-built SQL appears only in a
migration, over constant table names. Every secret comparison (credential
signatures, the dashboard token, peer signatures, cipher tags) uses
`hmac.compare_digest`; the one `!=` compares a certificate digest, a public
identifier. No shell, `eval`, `exec` or unsafe deserialisation. The dashboard
serves files from a fixed route table. Outbound requests go only to peers an
operator registered. The agent API's plain-HTTP refusal is an allowlist of
loopback addresses, so `0.0.0.0` and `::` are refused without `--behind-tls`,
and the dashboard's bootstrap token is stripped from the URL by a redirect and
replaced with an `HttpOnly; SameSite=Strict` cookie.

## 3. Open items

Each is in the threat register with its control and gap; listed here with the
severity this review assigns and why it is not a release blocker.

| # | Item | Severity | Why not a blocker |
|---|---|---|---|
| O1 | Paraphrased prompt injection passes the write-time pattern screen (S2) | Medium | Retrieved memories are delimited and labelled as data, and a memory never grants a tool: in P5 high-impact actions on false evidence were 0 against 0.93 for a shared store. D1 measured Claude models obeying an injected note 1 time in 20 (Sonnet) and 0 in 20 (Haiku), unscreened, with an instruction that evidence may be wrong; not registered, and small. The screen is defence in depth, not the control. G4 measures this against real models |
| O2 | Residual race between `verify` and the action itself (S14) | Medium | Verification is pinned to the log head and re-checked immediately before acting; the window is the caller's own code between the two. WORKPLAN S6 is the research task on closing it |
| O3 | A writer with full database access can rewrite the whole log and chain consistently (S6) | Medium | Inherent to a log the attacker can write. Detected by an external checkpoint; runbook §6 and OPERATIONS say how to keep one |
| O4 | Tenancy is logical, not physical (S3 limit) | Medium | An authorisation boundary that holds against bugs in ranking, querying and federation; documented as not holding against code with database access. A store per tenant is the physical option |
| O5 | Federation peer keys do not rotate automatically (S11) | Low | A coordinated manual rotation is written down (runbook §3); in-flight retractions retry |
| O6 | The dashboard access log is a plain append-only file, not chained (S10) | Low | It records who looked, not what changed; changes are in the chained event log |
| O7 | No external audit, no formal verification | — | Stated in the register; not something an internal review can close |

## 4. Release-blocker criteria

A finding blocks a release if it is critical or high and not fixed, or if it is
medium and makes a documented guarantee false without the documentation saying
so. By those criteria nothing open blocks: every medium item above is a
documented limit, not a false claim. The release gate G6 additionally requires
a green CI run, which is blocked by the account's billing (WORKPLAN X-CI), so
**this review clears G5 and does not by itself clear a release**.
