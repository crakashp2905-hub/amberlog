# Security review, 2026-10-18 (release gate G5)

The pre-release security review for [WORKPLAN.md](WORKPLAN.md) G5. It
supplements the threat register in [SAFETY_AND_SECURITY.md](SAFETY_AND_SECURITY.md),
which stays the single list of threats; this records what was reviewed, what
was found, and the state of every item at the end. It is an internal review by
the project's own developer, not an external audit, and claims nothing beyond
the checks it names.

**Result: no open critical or high finding.** Five high findings were found
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
- **A pattern sweep of `amberlog/`** for the shapes that produce critical
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
| F12 | **A memory shared around a cycle came home as a new import.** A re-share names only the intermediary as origin, so A -> B -> A gave A an import of its own memory. B never forwards A's retractions back to A, so after a **correction** A kept serving its own superseded versions beside the current one (CorrectionSim saw an origin serving three values of one setting). After a plain retraction the echo was left `contested`, not active (reproduced at `0e90696`), so the withdrawal itself held. Found by S1's harness. | Medium | **Fixed** (`8521eeb`): imports record the provenance chain hop by hop and an offer into any store already on it is refused. `test_echo_import.py`; S1 final convergence 20/20 |
| F13 | **Every acknowledgement told the origin about the recipient's own activity.** `state_revision` was the recipient's log head, so two acknowledgements gave its activity between them (leave-one-out R² 0.994 in S5's harness); `detail` said how many copies it held and how many peers it re-shared to (+0.64 and +0.71 accuracy over guessing). Sent to every origin, authenticated. Found by S5. | Medium (confidentiality) | **Fixed**: `state_revision` counts this origin's retractions only (still falls on a regressed restore, which is its job), and `detail` carries no counts; wire format unchanged (PROTOCOL.md §6). `receipts.py` adds an opt-in receipt that reveals nothing and binds at audit |
| F14 | **The background manager read the shared database connection without the store lock.** Parts of a cycle read the log directly while a server's request threads used the same SQLite connection: F1's bug class, in new code. Found when CI's MCP test crashed at shutdown (exit −11) with the manager mid-call. | High | **Fixed** (`10e9f05`): every cycle holds the store lock, and servers stop their manager before returning; CI green on all jobs |
| F15 | **An exposure token stayed usable after its memory stopped being visible to the agent.** The action-time re-check (`Enforcer.verify_at_action`) called the enforcer without the agent, and `visible_to(memory, None)` is the operator's view, so scope was never re-checked at action time. A private memory an agent read through a collection still verified as usable after the agent's grant was revoked or the memory was removed from the collection, through the store API and the SDK's `verify`. Evidence certificates were not affected. Found by checking the audit's action-time authorization concern directly. | High | **Fixed**: the re-check passes the agent, and a `not_visible` refusal is returned as it stands. `test_visibility_at_action.py` (failed 3 of 5 before the fix) |
| F16 | **A forwarded retraction was refused at every second hop over HTTP.** The recipient verified it with the key it shares with the *origin*, not the store that forwarded it (and had no key at all if it never met the origin), so a correction stopped one store short. The in-process transport checks no signatures, so every earlier multi-hop test passed. Found by `experiments/multihost.py`. | High | **Fixed** (`0d42e4a`): verified with the forwarder's key; `forwarded_by` is inside the signed payload. `test_multihop_http.py` fails without the fix |
| F17 | **27 public entry points read a stale view in multi-process deployments**, `receive_retraction`, `request_retraction`, `record_share` and `firewall_check` among them. A federation server did not see a share recorded by another process, so it applied a retraction and forwarded it to nobody. | High | **Fixed** (`0d42e4a`): each catches up on the log first (`_fresh`); the multi-host harness converges |
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

Each is a documented exception, time-bounded: it is re-reviewed by the date
given, and either closed or re-justified in this table then. None is
critical or high.

| # | Item | Severity | Status (2026-10-20) | Why not a blocker | Review by |
|---|---|---|---|---|---|
| O1 | Paraphrased prompt injection can pass the write-time screens | Medium | Narrowed: directive detector on by default (10/12 own held-out, 20/60 third-party, 0 benign flagged); optional model screen (46–54/60, 3–6/56 benign flagged) | A memory never grants a tool: untrusted or instruction-kind evidence is refused at the action gate whatever the screens miss | 2027-01-31 |
| O2 | Window between verifying evidence and the side effect (S14) | Low | **Closed for `ActionGate.execute`** (the fence: verification and the tool in one transaction, 0/1,229 violations). Open only for callers who `authorize` and then act themselves | Documented; `execute` is the supported path | 2027-01-31 |
| O3 | A writer with full database access can rewrite the log and chain consistently | Medium | Detected against an independently stored checkpoint (`--checkpoint-dir`); see `test_checkpoint_rewrite.py` | Inherent to a log the attacker can write; detection, not prevention, is what is claimed | 2027-01-31 |
| O4 | Tenancy within one store is an authorisation boundary only | Medium | Physical isolation available: `tenancy.TenantRouter`, one store and key directory per tenant | Documented; the physical option exists | 2027-01-31 |
| O5 | Federation keys rotate manually | Low | Overlap window implemented and drilled (`test_key_rotation_drill.py`) | Manual but rehearsed; no automatic rotation | 2027-03-31 |
| O6 | The dashboard access log is a plain append-only file, not chained | Low | **Closed 2026-10-24**: each line carries the SHA-256 of the one before it; `amberlog access-log-verify PATH` names the first edited, deleted or reordered line (`test_access_log_chain.py`). A consistent rewrite of the whole file is still only detectable against a copy kept elsewhere | — | — |
| O7 | No external audit, penetration test or independent cryptographic review | — | Unchanged; the brief for one is [INDEPENDENT_EVALUATION.md](INDEPENDENT_EVALUATION.md) and the cryptographic decisions are written down for it in [CRYPTOGRAPHY.md](CRYPTOGRAPHY.md) | Cannot be closed internally. **Blocks a production (1.0) release**, not an alpha | Before 1.0 |

## 4. Release-blocker criteria

A finding blocks a release if it is critical or high and not fixed, or if it is
medium and makes a documented guarantee false without the documentation saying
so. By those criteria nothing open blocks: every medium item above is a
documented limit, not a false claim. The release gate G6 additionally requires
a green CI run. CI ran again on 2026-10-24 and every job passed (PR #6), so the
billing blocker (WORKPLAN X-CI) no longer holds. **This review clears G5. The
independent review (O7) still blocks a 1.0 release.**
