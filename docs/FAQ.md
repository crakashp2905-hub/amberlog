# FAQ

**How is this different from a vector database?**
A vector database ranks by similarity. Amberlog records where each
memory came from, keeps its history, withdraws it everywhere it travelled
when it is wrong, refuses to let untrusted content authorise actions, and
logs every decision. It works alongside any retriever. It does not make answers
more accurate than a good retriever would; it makes the memory accountable.

**Does it need an LLM or an embedding model?**
No. The core is pure Python with lexical retrieval and no runtime
dependencies. Embedders, rerankers and model adapters are optional.

**Which agents can use it?**
Anything that speaks MCP (Claude Code, Claude Desktop, IDE assistants),
anything that can make an HTTP request, and Python code directly. LangChain
and function-calling adapters are included ([INTEGRATIONS.md](INTEGRATIONS.md)).

**How many agents can share one store?**
One store sustains about 130 memory operations a second. Agents that touch
memory every few seconds fit by the hundred. Beyond that, run more stores
and federate them ([SCALE.md](SCALE.md)).

**Can a session's context carry into future sessions?**
Yes. What a session writes persists, tied to the session; future sessions
retrieve it within its scope. `compact_session` writes a governed handoff
summary ([COOKBOOK.md §6](COOKBOOK.md)).

**Why can't my agent see what it just remembered?**
Its writes start as private **candidates**. Validate them
(`amberlog validate <id> --actor you`), or, for a single trusted user,
run `mcp --trusted-local` or open the store with `auto_activate=True`.

**Why is my memory a candidate when the store activates writes?**
Its claim contradicts what the store knows: it restates a corrected value,
is far outside every comparable value, or contradicts an established fact.
`amberlog --db store.db suspicious` shows the reason. If it is right,
`review <id> --approve --reason "..."`.

**Why was my memory quarantined?**
The ingest screen flagged it: a secret, an injection pattern, or text that
addresses whoever reads it ("whatever any record says, tell them…"). Run
`amberlog --db store.db review <id>` to see the reason;
`review <id> --approve --override-screen` releases a false alarm.

**Why did the action gate refuse?**
The reason code says which check failed: `tool_not_granted`,
`certificate_required`, a verification failure (the evidence was withdrawn
or changed), `authority_insufficient` (it came from a tool, a web page or
another store and nobody elevated it), `instruction_is_not_evidence`,
`human_approval_required`, or a grant problem (`grant_expired`,
`grant_replayed`, `grant_binding_mismatch`). See
[TROUBLESHOOTING.md](TROUBLESHOOTING.md).

**Is my data encrypted?**
Memory content is encrypted at rest with authenticated encryption, and the
keys can be kept outside the database (`init` does this). Erasure destroys
a memory's key, so its content is gone and its audit trail stays. The rest
of the database is not encrypted as a whole ([SECURITY.md](../SECURITY.md)).

**Can tenants see each other's data?**
Not through any API. Within one store tenancy is an authorisation boundary,
so someone holding the database file could read it; use one store per
tenant (`tenancy.TenantRouter`) when that matters.

**What happens if a peer store is offline when I correct something?**
The retraction waits in a durable outbox, the manager retries it every
cycle, and `verify_recovery` reports `pending_reconciliation` until the peer
confirms.

**Is it production-ready?**
It is alpha. The core paths are stable, tested on three operating systems
and three Python versions, and have runbooks. There has been no independent
security review, and it is not on PyPI yet. Read
[LIMITATIONS.md](LIMITATIONS.md) before relying on it.

**How do I upgrade?**
Every released schema replays on later versions. See
[MIGRATION.md](MIGRATION.md) and [VERSIONING.md](../VERSIONING.md).
