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
| T8 | **Distributed failures**: partitions, stale metadata, replayed or forged messages, Byzantine nodes | Signed events; versioned memories; merge by lineage + evidence, never by majority vote alone | P9 |

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

No TLS: the cookie carries no `Secure` flag because that would stop it being stored over plain HTTP on loopback. Any non-loopback deployment needs TLS terminated in front of it.

## Agent integration (P3)

| Control | How |
|---|---|
| An adapter cannot write as another agent | `AgentSession` binds `agent_id` and `episode_id` at construction; `remember` takes no agent parameter. |
| Retrieved memories cannot hijack the prompt | Memories are delimited, labelled as evidence, and preceded by a standing instruction that they are data. A memory containing the closing delimiter cannot end the block early. |
| An agent's own writes are not trusted | Tool-written memories land as `candidate` and are not retrievable until reviewed; the ingest screen still quarantines secrets. |
| An agent cannot score itself | Unchanged from T2: the session refuses a verifier equal to the acting agent, including on imported transcripts. |

This is still scoping inside one process, not authentication: anything holding the raw `MemoryFabric` can write as any agent, which is correct — that is the host.

## Federation (P6)

Crossing a store boundary is governed on both sides.

| Control | How |
|---|---|
| The recipient decides | The offer runs through the **recipient's** firewall, with its policies and its capability grants. A sender cannot push a memory past rules it does not control. |
| Imports are not trusted | An import arrives as a `candidate` and is not retrievable until the recipient activates it. This is explicit, not inherited: a recipient running with `auto_activate` would otherwise promote every import on arrival. |
| Provenance crosses | The import records the origin agent, memory id and store, so a federated store can still answer "why do we believe this?" and a retraction can follow a memory to where it travelled. |
| Metadata before content | `describe()` returns what a recipient needs to decide without the body, so an offer that will be refused never transfers the content. |

**Known gap:** the default firewall's value rule gates federation on value measured in the **sender's** context. H3's premise — confirmed by its result — is that value does not cross a context boundary, so passing the sender's gate says little about whether a memory helps the recipient. The rule is a reasonable floor (it blocks memories with no evidence anywhere) but it is not the right question, and on a store without a contrastive estimator it refuses everything.

## Known gaps at P1

- **The sensitive-data detector is pattern-based**, so it misses novel secret formats and flags some harmless strings. It is one control among several, never the only one protecting a restricted memory.
- **No agent authentication.** `agent_id` and `actor` are caller-supplied strings. `AgentSession` (P3) stops an adapter attributing work to the wrong agent, but a caller holding the fabric can still write as anyone. Real identity needs a service boundary, which arrives at P6.
- **No encryption at rest.** The SQLite file is plaintext.
- **The contradiction detector does not exist yet** (P7), so `challenge()` is manual.

## Principles
- Default-deny for cross-scope sharing.
- Every lifecycle or scope change is an event with an actor and a reason (a complete audit trail).
- There is a kill switch: quarantine by predicate (for example "everything from agent X after time t"), which propagates through lineage.

## Reporting
This is a research prototype with no production deployments. Report issues to the maintainers directly *(contact to be set)*.
