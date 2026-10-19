# Concepts

The ideas you need to use Memory Fabric well, in the order you meet them.
Each links to where it is specified.

## A memory

A versioned record: content, a **type** (semantic, episodic, procedural…),
and **provenance**: who wrote it, how (observed, derived, imported,
consolidated), from which sessions, and from which earlier memories at which
versions. Memories are never edited in place. `revise` writes a new version
and keeps the old one in history ([SPEC.md §2](../SPEC.md)).

## The event log

Every write, retrieval, decision and correction is an event in an
append-only, hash-chained log. Everything else is a **projection** rebuilt
from the log: the current memories, lineage, values, authority. This is why
a correction can follow a memory's history, and why an audit can be trusted
([ARCHITECTURE.md](../ARCHITECTURE.md)).

## Lifecycle

| state | shown to agents? | meaning |
|---|---|---|
| `candidate` | no | new, not yet validated (the default for an agent's own writes) |
| `active` | **yes** | validated, usable |
| `contested` | only on request | something it rests on was withdrawn, or it is disputed |
| `quarantined` | no | withdrawn: wrong, unsafe or caught by a screen |
| `deprecated` | no | retired by retention or an operator |
| `deleted` | no | content erased; the audit trail remains |

A store opened with `auto_activate=True` makes clean writes active at once.
Use it for a single trusted user, not for a shared store.

## Scope and tenant

**Scope** is how far a memory may travel: `private` (its writer and
collection readers), `team` (its tenant), `federated` (other stores).
Widening scope is a logged decision through the **firewall**. A **tenant**
is whose data it is; no query crosses it. Tenants can share a store
(an authorisation boundary) or each get their own (`tenancy.TenantRouter`).

## Retrieval and exposure

`retrieve` decides which memories to show. Each decision, shown or
withheld, is logged with the **probability** it was made with. That is what
lets the store later estimate which memories actually helped, without the
bias of only ever seeing what it chose to show.

## Authority

Separate from relevance and from lifecycle. Every memory has a **kind**
(`observation`, `derived_claim`, `instruction`) and a **trust** level
(`untrusted` < `unverified` < `elevated`), bound to its **origin** and
inherited through summaries, copies and other stores. A tool output or a
web page is untrusted until a reviewer who did not write it **elevates** it.
An instruction is never evidence. A successful outcome never raises trust
([authority.py](../memory_fabric/authority.py)).

## Correction

Withdrawing a memory (`correction.apply`) quarantines it, **contests**
everything derived from it unless it has independent support, and owes a
**retraction** to every store it was shared with. Retractions are signed,
delivered by the background manager and retried until each store confirms.
`verify_recovery` checks, from state, whether it is contained
([PROTOCOL.md](PROTOCOL.md)).

## Contradictions

Two memories by different authors that give different values for one claim
are flagged as **disputed** in the agent's context and in recall. The store
does not pick a winner; a person resolves it (`challenge`, review).

## Actions

A **protected tool** runs only when four things hold at the moment of
action, inside one transaction: the agent is granted the tool; a
**certificate** names the evidence and every piece still verifies; the
evidence has sufficient authority; and, if required, a short-lived **grant**
covers this exact target and parameters ([actions.py](../memory_fabric/actions.py)).

## Outcomes and value

An episode's outcome comes from a **verifier** that is not the agent. Values
are estimated from outcomes and the logged exposure probabilities, and each
carries uncertainty. Value is not relevance: a memory similar to the
question is not thereby useful.

## Sessions and handoff

A session is an **episode**. What it learned can be summarised with
`compact_session`: a governed derivation of its memories, disputes kept,
withdrawn if an input is corrected, and rewritten by the manager from what
still stands ([COOKBOOK.md §6](COOKBOOK.md)).

## The background manager

Runs inside `serve`, `mcp` and `agent-api` (or `memory-fabric maintain`).
Each cycle: hostile-source notices, retraction delivery, retention, audit
triggers, contradiction scan, re-compaction, integrity checkpoints, health.
One manager per store at a time, under a lease.

## Words used precisely

The glossary the code and the research use is in [AGENTS.md](../AGENTS.md#glossary-use-these-terms-consistently).
