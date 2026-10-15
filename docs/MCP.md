# Memory Fabric over MCP

Give any MCP host — Claude Code, Claude Desktop, Cursor, and the rest — a
governed memory: recall, write, flag disagreements, retract, and ask why a
memory exists. Adopting it means adding a server, not rewriting a memory
layer.

```bash
memory-fabric mcp --db ~/.memory/agent.db --agent-id my-agent --create
```

---

## 1. Connecting a host

Every host below launches the server as a local process and speaks to it over
stdio. One server process is bound to **one agent and one store**.

**Claude Code**

```bash
claude mcp add memory-fabric -- memory-fabric mcp --db ~/.memory/agent.db --agent-id claude-code --create
```

**Claude Desktop** — `claude_desktop_config.json` · **Cursor** — `.cursor/mcp.json` · **any `.mcp.json`**

```json
{
  "mcpServers": {
    "memory-fabric": {
      "command": "memory-fabric",
      "args": ["mcp", "--db", "/absolute/path/agent.db",
               "--agent-id", "my-agent", "--create"]
    }
  }
}
```

| flag | default | meaning |
|---|---|---|
| `--db` | required | the store; the event log in it is the source of truth |
| `--agent-id` | required | the agent this server acts as, fixed for its lifetime |
| `--create` | off | create the store if it does not exist |
| `--tenant` | all | restrict to one tenant |
| `--context` | `compact` | how recalled memories are rendered — see §4 |
| `--require-validation` | off | hold new memories as candidates until an operator validates them |
| `--retrieval` | `lexical` | the measured winner on external corpora, and it needs no model |

---

## 2. The tools

| tool | what it does | backed by |
|---|---|---|
| `memory_recall` | retrieve relevant memories, framed as evidence | exposure logged with its propensity on every call |
| `memory_remember` | write a memory; `derived_from` links it to its premises | sensitive-data quarantine, copy recognition, provenance |
| `memory_challenge` | declare that memories disagree; both are kept | **H4b**: P(correct) 0.905 → 1.000 |
| `memory_retract` | withdraw a memory **you** wrote | **PB2**: acting on retracted memory 17% → 0% |
| `memory_explain` | who wrote it, from what, what depends on it | scrubbed of sensitive values |
| `memory_begin_episode` / `memory_end_episode` | a server-minted handle linking a unit of work | the 2026-07-28 pattern for cross-call state |

Plus a `memory://{memory_id}` resource template, a `memory://overview`
resource, and a `recall_before_acting` prompt.

### What is deliberately not exposed

The library has 56 public operations and an agent gets seven tools. The
omissions are the most important design decisions here:

- **No tool records an outcome.** The project's glossary defines an outcome as *"provided by the environment or an evaluator, never self-reported"*. The caller of an MCP tool **is** the agent, so a tool that let it report its own success would let it write the evidence its memories are credited from. Outcomes go through the library API, from a verifier.
- **No quarantine tool.** Quarantine-on-failure was measured cutting the rate at which a correct memory reached the prompt from 60% to 18%. The CLI warns against it, and an agent does not get a one-call version.
- **No erasure tool.** It destroys a key and is irreversible: an operator's decision, not an agent's.

---

## 3. Governance at the boundary

**Identity is bound at the server, not passed per call.** No tool takes an
`agent_id`, and every input schema sets `additionalProperties: false`, so a
client that sends one is refused with an explanation rather than obeyed. A
host may run several models or users through one client, and letting it name
the agent per call would let it attribute work to an agent it is not.

**Retraction is for the origin; contesting is for everyone else.**
`memory_retract` refuses a memory this agent did not write. PB2 measured
*origin* retraction, and the basis it records — `retracted_at_origin` — is
strong precisely because it comes from the source. An agent that thinks another
agent's memory is wrong has a disagreement, not knowledge, and the refusal
names `memory_challenge` as the right tool.

**Derived memories go through `derive`.** It enforces that premises share a
tenant and that the conclusion inherits it, and retracting a premise makes the
conclusion contested — which the test suite pins at the tool boundary.

**Retrieved memory is untrusted input.** Recall wraps what it returns in a
prompt-injection preamble and delimiters (SECURITY.md T1), and the structured
result carries `trust: "untrusted-evidence"`. A poisoned memory is a payload
aimed at every later run, and a tool result lands in a model's context exactly
as a retrieval does.

**Sensitive content is never echoed.** A write that trips the detector is
stored quarantined, never recalled, and the response does not repeat the
content — repeating it would put the secret straight back into the model's
context.

**Activation on write, federation still gated.** The library holds new
memories as candidates until an operator validates them. Through MCP that makes
the server useless for its primary job — the first subprocess test recalled
nothing for exactly that reason — so memories activate on write unless
`--require-validation`. What that does **not** weaken is federation: memories
are written at private scope, and an unvalidated memory is never shared.

---

## 4. Rendering, and why `compact` is the default

[X5](../research/results/x5-context-rendering.md) rendered one retrieval four
ways over 640 paired episodes. The library's full rendering — per-memory
`[id | type | evidence | state]` headers plus an instruction to prefer
well-evidenced memories — cost **7.0 points of task success** against plain
text (95% CI +4.7 to +9.4). The security preamble and delimiters on their own
cost **0.6, indistinguishable from zero**.

So `compact` keeps the security control and drops the labels, and names a
declared disagreement in one line when one exists — because dropping every
label would also drop *"contradicts …"*, which is H4b's mechanism. That last
part is a design choice informed by X5, not a finding of it, and is labelled as
such in the code.

---

## 5. Efficiency, measured rather than claimed

Against a naive memory server — append on write, IDF overlap on read, raw text
returned — implemented **through the same protocol layer**, so the comparison
is of the memory behind the tools rather than of two JSON-RPC implementations.
In-process, no model, 200 recalls per size ([raw](../research/results/mcp-efficiency.json)):

| store | arm | recall median | recall p95 | words per recall | vs naive |
|---|---|---|---|---|---|
| 100 | naive | 0.13 ms | 0.25 ms | 63.6 | 1.00× |
| 100 | **governed, compact** | 1.11 ms | 1.94 ms | 103.7 | **1.63×** |
| 100 | governed, full | 0.99 ms | 1.45 ms | 155.7 | 2.45× |
| 1,000 | naive | 1.04 ms | 1.72 ms | 63.5 | 1.00× |
| 1,000 | **governed, compact** | 2.40 ms | 4.13 ms | 103.5 | **1.63×** |
| 1,000 | governed, full | 4.37 ms | 8.30 ms | 155.5 | 2.45× |
| 5,000 | naive | 7.89 ms | 11.87 ms | 56.2 | 1.00× |
| 5,000 | **governed, compact** | 11.51 ms | 15.70 ms | 96.2 | **1.71×** |
| 5,000 | governed, full | 11.76 ms | 15.05 ms | 148.2 | 2.64× |

**The governed server is not more efficient than a naive one, and it cannot
be.** It does strictly more work per call, and the numbers say so: 1.0 to 3.6 ms
more per recall, and more words.

**The word overhead is exactly 40 per recall at every store size** — the
prompt-injection preamble and delimiters. The memory content returned is the
same. So the whole token cost reduces to one trade: a constant 40-word security
frame on each recall, which X5 measured as costing nothing in accuracy.

Two things put that in proportion, stated after the raw numbers rather than
instead of them. A model call costs seconds and thousands of tokens, so 1–4 ms
and 40 words are around 1–2% of a turn. And **among governed renderings,
`compact` is the efficient one**: 37% fewer words than `full` and, per X5, 7
points more accurate.

What would cut the 40 words is moving the preamble into the server's
`instructions`, sent once rather than per recall. That trades a security
property — the framing would no longer sit next to the memories it protects —
and it is the obvious next measurement, not a change to make on argument alone.

---

## 6. Protocol

Built against **MCP 2026-07-28**, the current revision, which made the protocol
stateless. Older clients are served too.

- **2026-07-28:** no `initialize`. Version, capabilities and client identity ride in each request's `_meta` (`io.modelcontextprotocol/protocolVersion`, `…/clientCapabilities`, `…/clientInfo`); results carry `resultType` and `_meta["io.modelcontextprotocol/serverInfo"]`; `server/discover` is implemented and answers a versionless probe; list and read results carry `ttlMs` and `cacheScope`; tools are returned in deterministic order.
- **2025-11-25, 2025-06-18, 2025-03-26:** the legacy `initialize` handshake, with version negotiation as those revisions define it. Results are shaped to the negotiated revision — no `resultType` or cache fields for a legacy client, and no `outputSchema`, `annotations` or `structuredContent` for a 2025-03-26 client, since each revision's clients validate against its own schema.
- **A request with no version and no handshake is refused**, with the supported list, rather than guessed at.
- **Memory content is never cacheable**: `cacheScope: "private"`, `ttlMs: 0`. A memory's lifecycle can change at any moment — that is what a retraction is — and a cached read would go on serving a memory its origin has withdrawn. Tool definitions carry no user data, so they are `public` with a long TTL.
- **A failed tool is a result, not a protocol error**: `isError: true` with a message, so the model sees the failure and can recover. Error codes follow the 2026-07-28 allocation: `-32022` unsupported version, `-32602` for a missing resource (it was `-32002`).
- **stdout carries the protocol and nothing else.** The server redirects `sys.stdout` to stderr while serving, so a stray `print` anywhere cannot corrupt the stream.

**Zero dependencies**, like the rest of the core: JSON-RPC, the transport and
a JSON Schema validator for the subset the tools use are all standard library.

## 7. Not yet

- **Streamable HTTP.** stdio only. A host that wants a remote server needs the 2026-07-28 HTTP transport, its `Mcp-Method` / `Mcp-Name` headers and its authorization rules.
- **Change notifications.** `listChanged` is `false`: the tool list is fixed, and memory changes are not pushed, because `subscriptions/listen` is only meaningful over a long-lived stream.
- **Multi round-trip requests.** No tool needs to ask the client for more input mid-call, so `input_required` is never returned.
- **Answer quality through MCP is unmeasured.** X5 measured the rendering; nothing yet measures whether an agent using these tools decides better than one using a naive server.
