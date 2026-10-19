# SECURITY.md — Threat Model

Shared memory is a new attack surface. A memory is a persistent input that influences future decisions, and a federated procedural memory is effectively code.

## Assets
Memory content, value estimates, lineage, agent capability profiles, outcome records, the tools reachable by procedural memories.

## Threats and mitigations

| # | Threat | Mitigation | Status |
|---|---|---|---|
| T1 | **Memory poisoning**: a false or malicious memory is injected through normal interaction (AgentPoison / MINJA-style) | Provenance required; new memories start as `candidate` and are not retrievable; scope promotion requires proven value | **P1 done**; injection tests in RuleWorld at P4 |
| T2 | **Credit gaming**: an agent inflates a memory's value with false outcomes | Outcomes come only from the environment or an evaluator (`verifier_id`); an agent may not verify its own episode | **P1 done** |
| T3 | **Sybil confirmation**: many agents "independently" confirm a claim | Evidence independence computed from lineage (shared ancestry = correlated evidence), not from agent count | **P1 done** (`evidence_is_independent`); applied across agents at P6 |
| T4 | **Procedure-as-code**: a federated procedural memory calls tools the recipient should not run | `capabilities` field; the firewall denies procedures whose capabilities exceed the recipient's grant | **P1 done** |
| T5 | **Persistence after rollback**: descendants of a poisoned memory survive | TMS retraction: quarantine propagates `contested` to all descendants | **P1 done** (the P1 gate) |
| T6 | **Sensitive-data leakage**: secrets or PII enter memory and get shared | Sensitive-data detector on ingest and on share; `security_class`; restricted memories never leave private scope | **P1 done** (detector is coarse; see `governance/sensitive.py`) |
| T7 | **Directory leakage**: capability profiles reveal what an agent knows about whom | Access control on directory entries; aggregate profiles only | P6 |
| T8 | **Distributed failures**: partitions, stale metadata, replayed or forged messages, Byzantine nodes | Signed events; versioned memories; merge by lineage + evidence, never by majority vote alone; signed offers, retractions and notices, each verified with the key of the store that sent it; networked imports land as candidates under `peer:<store>`; refusal of echoes; a 16-hop limit no copy can outrun | **done** for retraction and replay; Byzantine peers out of scope |
| T9 | **Authority laundering**: an injected or untrusted note gains authority by being summarised, copied by a tool, or shared to another store | `authority.py`: trust and kind bound at first write and inherited through lineage, copies and federation (the origin's verdict travels as a floor); sources kept apart from transformers; elevation only by a different approver, per version, never past a hard reason; outcomes never confer authority. The action gate refuses evidence below `unverified` and any instruction | **0.12.0**, `tests/test_authority.py` |
| T10 | **Stale authorisation and replay**: an action runs on evidence, a grant or an approval that no longer holds, or a request is replayed or altered | Evidence re-verified inside the action fence; grants ≤ 300 s, bound to tool, agent, tenant, target, parameters and evidence versions, consumed once; approvals can carry the same binding; credentials re-verified per call | **0.12.0**, `tests/test_authority.py::ExactActionGrants` |
| T11 | **Resource exhaustion**: a loop, a client or a peer floods the store | Store limits (`limits.py`): bounded content, per-agent write quota, per-peer federation budget, on in servers; HTTP body limits and rate limits (agent API); bounded connect | **0.12.0**, `tests/test_limits.py`; capacity measured open-loop (DEPLOYMENT.md §3) |
| T12 | **Privilege concentration**: one credential can both change memory and act on it | Seven permissions (read, write, delete, correct, export, administer, execute); the operator role has no `execute`; an auditor reads and exports only | **0.12.0**, `tests/test_permissions.py` |

## Observability surfaces (P2)

The CLI and the dashboard are read-only by construction, and both run locally.

| Property | How |
|---|---|
| Browsing cannot change the store | No mutating HTTP endpoint exists; the read model performs no writes. Mutation is only in the SDK and in CLI commands that announce themselves as writing. |
| Browsing cannot contaminate the evidence | Search reads the index directly rather than through `retrieve()`, which would log exposure events and enter an operator's queries into the data value estimates are computed from. |
| Secrets are not displayed | Content is scrubbed before it reaches a screen, so a quarantined credential does not land in a terminal scrollback, a browser's memory, or a screenshot. The *kind* of secret is still reported so a reviewer can act. |
| No path traversal | Static assets come from a fixed allowlist by exact request path; no request path ever reaches a path join. |
| No third-party resources | The dashboard loads no external scripts, styles or fonts, and sends `default-src 'none'`. It works offline and leaks nothing to a CDN. |

### Server authentication (added after P2)

| Control | How |
|---|---|
| Shared session token | 256-bit, compared with `hmac.compare_digest`. Sent as a cookie, a `Bearer` header, or once through the URL. |
| Bootstrap without leaving the token behind | A valid `?token=` is traded for an `HttpOnly; SameSite=Strict` cookie and a redirect to the clean URL, so it leaves the address bar, history and any `Referer`. Request logs are redacted. |
| DNS rebinding | The `Host` header is validated against an allowlist. A loopback bind does not help here and neither does the cookie — the browser sends it — so this is the control that matters. Applies even with auth disabled. |
| Cross-site reads | `SameSite=Strict` plus an `Origin` check. |
| Unauthenticated exposure | Refused outright off loopback, rather than warned about. |
| Enumeration | Authentication runs before routing, so 404 and 401 cannot be told apart. |
| Who looked | With `--operators-file`, each operator has their own token and every request — allowed or refused — is appended to an access log outside the event log, with tokens redacted. Without it, access is attributable only to "whoever holds the shared token". |

No TLS: the cookie carries no `Secure` flag because that would stop it being stored over plain HTTP on loopback. Any non-loopback deployment needs TLS terminated in front of it.

## Agent integration (P3)

| Control | How |
|---|---|
| An adapter cannot write as another agent | `AgentSession` binds `agent_id` and `episode_id` at construction; `remember` takes no agent parameter. |
| Retrieved memories cannot hijack the prompt | Memories are delimited, labelled as evidence, and preceded by a standing instruction that they are data. A memory containing the closing delimiter cannot end the block early. |
| An agent's own writes are not trusted | Tool-written memories land as `candidate` and are not retrievable until reviewed, **unless the store runs with `auto_activate`**, which an operator turns on deliberately (`mcp --trusted-local` does, and marks each write `activation: trusted-local`). The ingest screen applies either way. |
| An agent cannot score itself | Unchanged from T2: the session refuses a verifier equal to the acting agent, including on imported transcripts. |

This is still scoping inside one process, not authentication: anything holding the raw `MemoryFabric` can write as any agent, which is correct — that is the host.

## Agent API (2026-10-16)

| Threat | Mitigation |
|---|---|
| An agent acts as another | Each request carries a credential signed with that agent's own key and is re-verified per call; the handler is an `AgentClient` bound to the verified principal. Exposure tokens are kept per agent, so one agent cannot verify on another's recall. |
| A revoked or expired credential keeps working | Verified on every request through `MemoryService`, whose revocations are durable. |
| Telling failure kinds apart | Unknown agent, bad signature, expired and revoked all return the same 401 body. |
| Credentials sniffed on the wire | Refuses a non-loopback bind over plain HTTP unless `--behind-tls` says TLS terminates in front. |
| A web page drives the API | Requests carrying `Origin` are refused; only browsers send it. No cookies, no CORS. |
| Self-scored outcomes | No outcome endpoint. |
| Resource exhaustion by body size | Bodies over 64 KiB are refused before parsing. There is **no rate limiting**; put it behind a proxy that has one. |

## Federation (Phase 2)

Crossing a store boundary is governed on both sides, and the boundary is now
authenticated.

| Control | How |
|---|---|
| Senders are authenticated | Per-peer HMAC on every retraction, verified **before** the message is parsed. An unknown peer is neither reachable nor authorised: `PeerRegistry` is the authorisation boundary, so a store cannot be made to accept retractions from somewhere it was never configured to trust. |
| A signature proves origin, not truth | It establishes who sent a retraction and that it was unmodified. Nothing downstream may treat it as evidence that the retracted claim was false. |
| Evidence is a digest, never the evidence | A retraction carries `evidence_digest` and an optional reference. Shipping the content would move memory text into a second system, which is what the governance layer exists to prevent. |
| Acknowledgements cannot overstate | A recipient reports `persisted` only after its own commit and `enforced` only once its projections stop exposing the version. The dispatcher refuses a claim with no state revision behind it. |
| Replays cannot forge | A reconciliation replay carrying another origin's events is dropped, or a compromised peer could retract on someone else's behalf. |

Crossing a store boundary is also governed by the original controls:

| Control | How |
|---|---|
| The recipient decides | The offer runs through the **recipient's** firewall, with its policies and its capability grants. A sender cannot push a memory past rules it does not control. |
| Imports are not trusted | An import arrives as a `candidate` and is not retrievable until the recipient activates it. This is explicit, not inherited: a recipient running with `auto_activate` would otherwise promote every import on arrival. |
| Provenance crosses | The import records the origin agent, memory id and store, so a federated store can still answer "why do we believe this?" and a retraction can follow a memory to where it travelled. |
| Metadata before content | `describe()` returns what a recipient needs to decide without the body, so an offer that will be refused never transfers the content. |

**Known gap:** the default firewall's value rule gates federation on value measured in the **sender's** context. Value measured in one context says little about another, so passing the sender's gate says little about whether a memory helps the recipient. The rule is a reasonable floor (it blocks memories with no evidence anywhere) but it is not the right question, and on a store without a contrastive estimator it refuses everything.

## Content governance (Phase 6)

Invariant 12 — *append-only audit history does not justify retaining sensitive
content indefinitely* — is a real tension, not a wording problem. The event log
is append-only and enforced by database triggers, and a log you can edit to
remove embarrassing entries is not an audit trail. But "it is in an immutable
log" is not an answer to a subject exercising a right to erasure, or to a
credential that has leaked into a memory.

**Crypto-erasure resolves it.** Memory content is encrypted per memory
(`governance/erasure.py`), the keys live in their own table rather than in the
log, and `erase_content` destroys one key. Every event stays byte-identical,
every projection still replays, lineage and the propagation record are
untouched, and the text is unrecoverable.

| What is erased | What survives |
|---|---|
| The memory's text, in the log, the projection and the vector index | Who wrote it, when, and under what provenance |
| | What it was derived from and what was derived from it |
| | That it was retracted, by whom, on what basis |
| | That it was erased, by whom, when and why |

An auditor can still answer "was this handled correctly?" about a memory nobody
can read. **Erasure removes the content, not the accountability.**

Four limits, stated rather than implied:

- **The cipher is authenticated.** New content is sealed with AES-256-GCM when `cryptography` is installed, and with HMAC-SHA256 counter mode plus an encrypt-then-MAC tag otherwise — the zero-dependency default. The original unauthenticated `enc:v1` envelope is read-only and never written again; details and history are in the bullets below and in SPEC.md §0.6.0.
- **By default the keys are in the same file as the ciphertext.** That makes erasure *possible* and does nothing against an attacker who has the file. Production deployments should keep keys outside the database — see *Key custody* below and [DEPLOYMENT.md](DEPLOYMENT.md).
- **Erasure is terminal for a memory's content.** `revise` is refused once content has been erased: writing a new version under the same id would make it readable again and defeat the erasure record. Record new information as a new memory. Found by a property-based walk, which hit the sequence (erase, then revise) and stored the new text in *plaintext*, because the destroyed key made the sealer fall back silently.
- **Crypto-erasure cannot reach a backup taken before the key was destroyed.** Backup retention is an operational control; a test pins this behaviour rather than leaving it to be discovered.
- **`fabric.erasure_scope(memory_id)` answers a subject-access request honestly**, in three parts. *Reached*, verified rather than asserted: the key destroyed, the log payload ciphertext, the content reading as the marker, and **both search indexes purged** — content left in an index is still matchable, which would make the erasure cosmetic exactly where a subject would notice. *Kept deliberately*: provenance, lineage, the withdrawal basis, the propagation record and the erasure event itself. *Outside this store*: backups taken before erasure hold both the ciphertext and the key; anything exported, logged or sent to a model provider left before erasure existed; and a federated copy at another store has **its own key** and must be erased there — a retraction withdraws it from use without destroying it. Those three are reported as **unknown rather than guessed**, because `doctor` cannot see them either.
- **This is not encryption at rest.** One destroyed key makes one memory unreadable. The rest of the file is still plaintext SQLite.
- **Content encryption is authenticated, and was not always.** `enc:v1` had no authentication tag, so a ciphertext could be edited and the plaintext became whatever the editor chose. It is now read-only and never written again; new content is AES-256-GCM where `cryptography` is installed and HMAC-based encrypt-then-MAC otherwise. A failed tag raises rather than returning anything — the old code decoded with `errors="replace"` and let tampered bytes travel into an agent's context as remembered facts.
- **A ciphertext is bound to its store, memory and version.** A tag alone would let authentic content be copied between memories, or an old version's bytes pasted over the current one to undo a correction by editing one column.
- **Key custody is a deployment choice and the default is the weakest one.** `SqliteKeyProvider` keeps keys beside the ciphertext: that makes erasure possible and does nothing against someone holding the file. `DirectoryKeyProvider` or `CallbackKeyProvider` move them out; `memory-fabric --keys <dir>` opens such a store. A missing key store raises `KeyUnavailable` rather than reporting erasure, because telling an operator their data was deliberately destroyed is the one answer that stops them looking for the volume they did not mount.

## Tamper evidence

Every appended event is hashed and chained into its predecessor
(`memory_fabric/integrity.py`). Editing, deleting or reordering any event
breaks every link after it, and verification names the first divergent sequence
number.

**This exists because two earlier security claims cited "the event digests"
when there were none** — the `seal` docstring justified a missing
authentication tag that way, and the federation handler claimed a refusal
before parsing. Both sentences predated the mechanism they named.

- **A chain is tamper-evident, not tamper-proof.** Anyone who can write both the log and the chain can rewrite both consistently, and `verify` cannot tell. A test drives exactly that attack.
- **The defence is a checkpoint kept elsewhere.** `memory-fabric checkpoint` prints `(seq, chain_digest)`: small enough to commit to another repository, write to append-only storage, paste into a ticket or read aloud. Stored beside the database it buys nothing. `--verify FILE` compares one back.
- **Coverage is explicit.** Chaining starts when the table first appears, so a store written earlier has an unchained prefix, reported as `unchained_before` rather than counted as verified. There is deliberately no backfill: hashing old events today proves only that they agree with themselves.
- **The chain's own table is append-only too**, by trigger — without that, a tamper could edit an event and fix its link in one transaction, which is the whole attack.

## Known gaps

- **Prompt injection carried by memory is screened at ingest, coarsely.** A memory whose content is an instruction to whatever model reads it later is a *persistent* injection: once validated and shared it reaches every agent that recalls it. `governance/injection.py` quarantines high-confidence cases (instruction overrides, chat-template role tokens, requests to reveal a system prompt) on write and again at share time, and warns on persona-override phrasing. Pattern-based like the secret screen, with a positive and a near-miss negative per pattern (`tests/test_injection_patterns.py`); paraphrased or encoded injections will get through. The read-side delimiting in `adapters/context.py` remains the main defence.
- **The sensitive-data detector is pattern-based**, so it misses novel secret formats and flags some harmless strings. It has now been red-teamed once (2026-10-16, `tests/test_sensitive_redteam.py`): of 13 obfuscations — invisible characters, spacing, base64/hex, full-width and look-alike letters, URL encoding, a password in a sentence, a mangled PEM header — it caught **0** at high severity before and **12** after variant scanning. A reversed key is still missed, and anything a fixed transformation cannot undo will be. It is one control among several, never the only one protecting a restricted memory. Its false-positive classes are documented in `tools/scan_secrets.py`.
- **Application code should hold a `MemoryService`, not a `MemoryFabric`.** The service owns the fabric, exposes no public route to it, and hands out only `Session` handles derived from a verified credential. A session re-verifies on **every** operation rather than once at creation — otherwise a credential revoked at 10:00 would still be acting at 11:00 through a handle minted at 09:00, which is revocation that does not revoke. Registering agents and issuing credentials are not reachable from a session: a session that could issue credentials could issue itself a better one.
- **That is an API boundary, not a sandbox.** Python has no private attributes and `service._fabric` is one underscore away. It makes the safe path the obvious one and the unsafe one visibly deliberate, which is all an in-process boundary can honestly offer. For a boundary that holds against the code on the other side, run the service in its own process; every operation already takes a credential and returns data, so that is a deployment change rather than a rewrite.
- **Credentials can be revoked individually, and a `MemoryService` keeps revocations on disk.** Each credential carries a signed `credential_id`, so one leaked token is revoked without rotating the agent's key and taking every other credential offline with it. `revoke_agent` is the blunt instrument for a compromised agent and refuses credentials issued after it. The service stores revocations in the database by default (`SqliteRevocations`, sharing the event log's connection and transaction), so they survive a restart and are shared by every process on that file — `service.revocations_are_durable` says which you have. A bare `PrincipalRegistry` keeps the cheap in-memory default, because a one-process tool should not be made to write a table it will never read again. Short credential lifetimes remain the primary control either way: revocation is the fast remedy inside a lifetime, not a substitute for bounding one.
- **Agent authentication exists at a handle, not inside the store.** `identity.PrincipalRegistry` issues HMAC-signed, expiring credentials and `fabric.as_principal` returns a handle bound to the verified principal. A caller holding the `MemoryFabric` itself can still act as anyone, and that is not a bug awaiting a patch: the check and the bypass would be on the same side of the boundary. Put the fabric behind a process that holds credentials, and hand agents views.
- **Credentials are bearer tokens.** Anyone holding one can use it until it expires or is revoked, so lifetimes should be short and transport must be confidential. Revocation is per credential (above); rotating an agent's key remains available as the blunt instrument.
- **Tenancy is an authorisation boundary, not a physical one.** Memories carry a `tenant_id` that the exposure path and the enforcement layer refuse to cross, which holds against a bug in a ranking policy, an index query or a federation import. It holds against nothing that can read the file: one SQLite database holding several tenants is one blast radius. Where isolation has to survive a compromised process, run one store per tenant — `memory-fabric tenants` and `doctor` both say which arrangement a store is actually in.
- **A tenant id is local to a store.** Nothing in the federation protocol makes `tn_acme` at one store the same customer as `tn_acme` at another, so `offer` takes the recipient's tenant explicitly. Letting a matching string decide would turn a naming coincidence into a cross-customer disclosure.
- **No encryption at rest for the database as a whole**, as above.
- **Contradictions are flagged, not resolved.** `conflicts.py` finds memories giving different values for one claim, by different authors, and marks them in the agent's context and in recall (which measurably reduces acting on an undetected poison). Resolving one is still a person's decision (`challenge()`, review).
- **Freshness across processes was not guaranteed until 2026-10-16.** A running fabric folded only its own writes, so a quarantine issued from the CLI did not reach an already-running MCP server, app or dashboard until restart. Every serving, enforcing and writing entry point now catches up on the log first (`MemoryFabric.refresh`, `tests/test_cross_process_freshness.py`). A deployment running a version before that should restart long-lived processes after any retraction.

## Principles
- Default-deny for cross-scope sharing.
- Every lifecycle or scope change is an event with an actor and a reason (a complete audit trail).
- There is a kill switch: quarantine by predicate (for example "everything from agent X after time t"), which propagates through lineage.

## Reporting
Report a vulnerability **privately, by email to the maintainer** listed in
`pyproject.toml`, never in an issue or a pull request. Include the version
(`memory-fabric --version` or `__version__`), what you did, what happened,
and whether memory content was exposed. Do not include real credentials or
customer data.

- Acknowledged within **5 working days**.
- Supported versions and the fix policy: [VERSIONING.md](VERSIONING.md#supported-versions).
- A fix lands on the latest minor first, and is described in the CHANGELOG
  once released.

The repository is private, so GitHub's private vulnerability reporting is not
available; email is the channel. This is alpha software with no independent
review ([docs/INDEPENDENT_EVALUATION.md](docs/INDEPENDENT_EVALUATION.md)).
