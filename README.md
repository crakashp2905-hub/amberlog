# Memory Fabric

**Governed memory for AI agents: auditable, retractable across stores, and safe to share.**

[![CI](https://github.com/crakashp2905-hub/memory-fabric/actions/workflows/ci.yml/badge.svg)](https://github.com/crakashp2905-hub/memory-fabric/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13-blue)
![Dependencies](https://img.shields.io/badge/runtime%20dependencies-0-brightgreen)
![MCP](https://img.shields.io/badge/MCP-stdio%20server-purple)
![License](https://img.shields.io/badge/license-proprietary-lightgrey)

> **Working name.** "MemOS" and "MemoryOS" are taken, and so is `memory-fabric`
> on PyPI. A final name is an open decision ([ROADMAP.md](ROADMAP.md), decision 6).

---

## Overview

Memory Fabric is a memory layer for LLM agents that answers the questions a
vector store cannot: *where did this memory come from, why does the agent
believe it, who may see it, and how do we pull it back?*

Every memory carries provenance and a lifecycle. The source of truth is an
append-only, tamper-evident event log, and everything else is a projection that
can be rebuilt from it. When a memory turns out to be wrong, its retraction
follows it into every store it was shared with, and conclusions built on it are
re-checked rather than deleted.

It is aimed at teams running agents where memory has to be **accountable**:
multi-agent systems that share knowledge, regulated settings that need audit
and erasure, and anyone who has watched one bad memory spread.

## Key features

| | Capability | Evidence |
|---|---|---|
| 🔁 | **Retraction that crosses stores.** A withdrawn memory is withdrawn wherever it travelled, including stores two hops away. | Acting on withdrawn knowledge fell **17% → 0%** ([PB2](research/results/phase-b-federated-agents.md)); holds under outage, crash, diamond and cycle ([fault matrix](docs/INVARIANTS.md)) |
| 🧠 | **Truth maintenance, not cascading deletes.** Losing one premise leaves independently justified conclusions standing. | [Phase 4 invariants](docs/INVARIANTS.md) |
| ⚖️ | **Contradictions are preserved.** Disagreement becomes flagged uncertainty instead of a confident wrong answer. | Confidently wrong **80% → 0%** with real models ([live](research/results/live-multi-agent.md)) |
| 🔐 | **Erasure with accountability.** Crypto-erasure removes content and keeps provenance, lineage and audit trail. | Authenticated encryption, external key custody ([SECURITY.md](SECURITY.md)) |
| 🧾 | **Tamper-evident log.** A hash chain over every event, with external checkpoints. | [SECURITY.md](SECURITY.md) |
| 🚫 | **Never serves an invalid version**, including at action time, via exposure tokens re-checked before use. | [INVARIANTS.md](docs/INVARIANTS.md) |
| 🛂 | **Evidence-gated actions.** A protected tool needs a grant *and* a certificate whose evidence still verifies at the moment of use. Valid memory never grants a tool. | Ten-agent benchmark: acted on invalid evidence **0.099** vs **0.285–0.375** for acting baselines; registered safety threshold **not met** ([P5](research/results/p5-poisonworld.md)) |
| 🏢 | **Multi-tenant by construction.** Tenant scope is bound to the handle, not passed per call. | [SECURITY.md](SECURITY.md) |
| 🔌 | **Works with any MCP client**, alongside the Python SDK and a Claude API adapter. | [From an MCP client](#from-an-mcp-client) |
| ⚡ | **Cheap.** **+0.2 ms** per episode and **1.16×** tokens against an ungoverned vector store. | [Phase A cost gate](research/results/phase-a-real-agent-benchmark.md) |

**1273 tests**, 17 deterministic multi-store fault scenarios and 14 integrity
invariants ([matrix](docs/INVARIANTS.md)), all run in CI with nothing
installed. What was run and what it showed: [docs/VALIDATION.md](docs/VALIDATION.md).

## Quick start

### Install

```bash
git clone https://github.com/crakashp2905-hub/memory-fabric.git
cd memory-fabric
pip install .                 # core: zero runtime dependencies
pip install ".[claude]"       # optional: Claude API adapter
```

Python 3.11–3.13 on Linux, macOS and Windows, all tested in CI with nothing
installed. Installing provides the `memory-fabric` command, which is also
available as `python -m memory_fabric`.

### Try the demo

Seed a deliberately messy store, with a poisoning and its retraction, an
unresolved disagreement, a leaked secret and a rare-but-critical procedure.
Then inspect it:

```bash
memory-fabric --db demo.db --create demo
memory-fabric --db demo.db attention     # triage: what needs a human, worst first
memory-fabric --db demo.db serve         # the same, as a local dashboard
```

### Use it from Python

```python
from memory_fabric import MemoryFabric

fabric = MemoryFabric("memory.db")

episode = fabric.start_episode("agent-a", task_id="onboard-42", context={"team": "sales"})
mid = fabric.remember(
    "agent-a",
    "Email follow-up beats calling after a failed onboarding.",
    source_episodes=[episode.id],
)
fabric.validate(mid, actor="reviewer")            # candidates are not retrievable

hits = fabric.retrieve("agent-a", "how to follow up?", episode_id=episode.id)
fabric.record_outcome(episode.id, outcome=1.0, verifier_id="env")   # never self-reported

print(fabric.explain(mid).narrative())            # why does the system remember this?
fabric.share(mid, "team")                         # default-deny; returns a reasoned ruling
```

## Usage

### From an MCP client

```bash
memory-fabric --db memory.db --create mcp --agent my-assistant
```

This serves one store to one agent over MCP on stdio, for Claude Code, Claude
Desktop, IDE assistants or TypeScript agents. Client configuration:

```json
{
  "mcpServers": {
    "memory-fabric": {
      "command": "memory-fabric",
      "args": ["--db", "/path/to/memory.db", "--create", "mcp", "--agent", "my-assistant"]
    }
  }
}
```

| Tool | What it does |
|---|---|
| `recall` | Search memory; returns only memories that pass enforcement |
| `fetch` | Read one memory by id; a withdrawn memory is an error, never content |
| `verify` | Re-check a memory immediately before a consequential action |
| `remember` | Record a lesson as a private, unvalidated memory |

The identity is fixed at launch. The model cannot read withdrawn memories,
choose who sees a memory, or act as another agent. There is deliberately **no
outcome tool**, because the model is the agent being scored.

> [!NOTE]
> A memory the agent `remember`s is a private **candidate** and is not returned
> by `recall` until someone validates it. This review step is the governance:
>
> ```bash
> memory-fabric --db memory.db attention                       # what is waiting
> memory-fabric --db memory.db validate <id> --actor <you>     # promote one
> ```
>
> For a single user's local assistant, where you are both the user and the
> reviewer, `mcp --trusted-local` makes the agent's clean writes active at once.
> Each is marked `trusted-local` in its provenance, and the sensitive-data
> screen still applies. Never use it for a shared or federated store.

### Over HTTP, for agents anywhere

```bash
# agents.txt (server-only, owner-readable): agent_id:tenant_id:hex_key per line
memory-fabric --db memory.db agent-api --agents-file agents.txt          # serves on 127.0.0.1:8766
memory-fabric --db memory.db agent-api-issue --agents-file agents.txt --agent my-bot
curl -s -X POST http://127.0.0.1:8766/v1/recall \
  -H "Authorization: Bearer <credential>" -d '{"query": "pump fault E01"}'
```

The same four operations as MCP, for agents in other processes, languages or
machines. Every request is verified from a signed, expiring credential, so
revocation and expiry take effect at the next call. It is a separate server
from the read-only dashboard, refuses browser-originated requests, and will not
bind beyond loopback over plain HTTP unless told TLS terminates in front of it
(`--behind-tls`).

### Multiple tenants

```python
import secrets
from memory_fabric import MemoryService

ACME_KEY = secrets.token_bytes(32)                   # per-agent signing key; keep it out of the store
service = MemoryService(path="memory.db")            # owns the fabric; does not expose it
service.register_agent("acme-bot", key=ACME_KEY, tenant_id="tn_acme")

acme = service.session(service.issue("acme-bot"))    # verified: signed, unexpired, not revoked
acme.remember("valve 7 is upstream of the pump")
acme.retrieve("valve")                               # cannot be asked to read outside tn_acme

service.revoke(acme.credential)                      # effective on the very next call
```

Session methods take no `tenant_id`, so there is no call site where it can be
omitted, and the credential is re-checked on every operation. The tenant filter
runs before the index is queried, and a cross-tenant refusal reveals nothing
about the other tenant's data.

> [!IMPORTANT]
> Tenancy is an **authorisation** boundary, not a physical one. It holds against
> bugs in ranking, querying or federation, not against anything that can read
> the database file. See [SECURITY.md](SECURITY.md).

### Health checks

```bash
memory-fabric --db memory.db doctor
```

`doctor` reports whether an installation's answers can be believed: **ok**
(verified), **warn** (a real condition that does not invalidate answers) or
**fail** (do not use for decisions), with exit codes 0, 1 and 5 for use in
scripts. A check that cannot run reports a warning, never `ok`. Among its
checks: a retraction that has permanently failed to reach a recipient, which
nothing else would surface.

### Running in production

```bash
docker build -t memory-fabric .
docker run -p 8765:8765 -v mf-data:/data -v mf-keys:/keys \
  -e MEMORY_FABRIC_TOKEN=<token> memory-fabric
```

The container runs as a non-root user and serves the read-only dashboard with
token authentication. **Mount both volumes:** `/data` holds the event log, the
source of truth, and `/keys` holds the content keys, kept apart so a copy of the
database alone cannot read content. Back up both: `memory-fabric backup` copies
and verifies the log, and the key directory needs its own backup. A store
created before keys moved out can be migrated with `memory-fabric migrate-keys`;
the container tells you how at startup. See [DEPLOYMENT.md](DEPLOYMENT.md) for backup, serving, capacity, upgrades
and current limits. Writers on more than one machine need the optional
PostgreSQL backend (`pip install ".[postgres]"`, then `--db postgresql://...`).

### Examples

```bash
python examples/poisoning_and_rollback.py   # the governance story, offline
python examples/agent_on_the_fabric.py      # an agent end to end, with a stub model
python examples/action_gate.py              # a tool call gated on its evidence
```

## How it works

```
 agents ──► SDK / MCP / Claude adapter ──► enforcement ──► retrieval
                         │                                    │
                         ▼                                    ▼
              governed write path                  exposure + propensity
       (sensitive-data screen, firewall,                 logged
            lifecycle, provenance)                         │
                         │                                 │
                         └──────────►  append-only, hash-chained event log
                                                 │
                         projections (memories, lineage, value, profiles)
                                                 │
                    CLI · read-only dashboard · federation to other stores
```

Design principles, each enforced in code:

- **The event log is the source of truth.** All state is a projection that can be rebuilt byte-identically.
- **Every exposure decision logs its propensity**, so unbiased value estimates are possible later. This cannot be retrofitted.
- **Outcomes need a third-party verifier.** An agent cannot score its own episodes.
- **Contradictions stay representable.** Nothing silently overwrites a conflicting memory.
- **Observability is read-only and never displays secrets.** Browsing does not write exposure events, and a quarantined credential is shown by kind, never by value.

Full detail: [ARCHITECTURE.md](ARCHITECTURE.md), [SPEC.md](SPEC.md), and the
repository constitution in [AGENTS.md](AGENTS.md).

## Research findings

Every claim in this project was pre-registered with thresholds, a baseline and
an oracle ceiling, then tested. **The accuracy claim failed**, and the negative
results are among the most useful things here.

| Phase | Claim | Outcome |
|---|---|---|
| A | Governed memory beats an ungoverned vector store | ❌ Killed: 0.283 against 0.583 |
| A′ | Leave-one-out attribution recovers most of naive blame's damage | ✅ Supported: 71% of the gap |
| B1 | Selective sharing beats sharing all or none | ❌ Killed |
| B2 | Retraction propagation works under both sharing policies | ✅ Supported: 17% → 0% |
| C | A population learns what to propagate | 🔬 Exploratory; made outcomes worse |

**The key insight:** success tracked one quantity, whether a correct memory
reached the prompt (coverage-to-success correlation **+0.975**). Withdrawing
memories blamed for failures withdrew correct ones. The product acted on this:
withdrawals record their evidence basis, and the triage list flags a
withdrawal made on weak evidence.

What the project offers is therefore **governance, not accuracy**: provenance,
retraction and audit that work across store boundaries
([PRIOR_ART.md](research/PRIOR_ART.md)). Lineage-gated actions and action
certificates have close 2026 prior art (MemLineage, Proof-Carrying Agent
Actions), so they are not claimed as new. A limited search found no prior
cross-store retraction. See [docs/RESEARCH_ROADMAP.md](docs/RESEARCH_ROADMAP.md).

The safety work adds a pre-registered ten-agent poisoning benchmark
([P5](research/results/p5-poisonworld.md)). Fabric met three of four
hypotheses. **H5a failed as registered**: the best baseline on the safety
metric barely acts. 65% of fabric's remaining harm is paraphrased injection
that its pattern screen does not catch. The agent is deterministic, so the
benchmark says nothing about real models.

More: [SCORECARD.md](research/SCORECARD.md) (every claim and its outcome) and
[FINDINGS.md](research/FINDINGS.md) (the full narrative).

## Project status

**Alpha (0.9.0).** The governance core, observability, adapters, federation and
MCP server are built and tested. Open items:

- The Claude adapter has not yet been run against the live API (P3 gate).
- Developer-experience (R8) and release-qualification (R9) gates are in progress.
- Not yet published to PyPI, pending a name.

See [ROADMAP.md](ROADMAP.md) for milestones, gates and kill criteria, and
[CHANGELOG.md](CHANGELOG.md) for what changed.

## Documentation

| Topic | Document |
|---|---|
| Running it for real | [DEPLOYMENT.md](DEPLOYMENT.md), [docs/OPERATIONS.md](docs/OPERATIONS.md) |
| Two-store federation in five minutes | [docs/REFERENCE_DEPLOYMENT.md](docs/REFERENCE_DEPLOYMENT.md) |
| Architecture and data model | [ARCHITECTURE.md](ARCHITECTURE.md), [SPEC.md](SPEC.md) |
| Federation protocol | [docs/PROTOCOL.md](docs/PROTOCOL.md) |
| Security and threat model | [SECURITY.md](SECURITY.md), [docs/SAFETY_AND_SECURITY.md](docs/SAFETY_AND_SECURITY.md), [docs/SECURITY_TEST_PLAN.md](docs/SECURITY_TEST_PLAN.md) |
| What is implemented, task by task | [docs/IMPLEMENTATION_STATUS.md](docs/IMPLEMENTATION_STATUS.md), [docs/RELEASE_EVALUATION.md](docs/RELEASE_EVALUATION.md) |
| Which guarantees are implemented | [docs/AUDIT.md](docs/AUDIT.md), [docs/INVARIANTS.md](docs/INVARIANTS.md) |
| What was validated, and how | [docs/VALIDATION.md](docs/VALIDATION.md) |
| Relevance contract | [docs/RELEVANCE_SPEC.md](docs/RELEVANCE_SPEC.md) |
| Research results | [research/SCORECARD.md](research/SCORECARD.md), [research/FINDINGS.md](research/FINDINGS.md) |
| Research design and evaluation | [RESEARCH.md](RESEARCH.md), [EVALUATION.md](EVALUATION.md) |
| Versioning policy | [VERSIONING.md](VERSIONING.md) |

## Development

```bash
python -m unittest discover -s tests -t .   # full suite, no dependencies needed
python -m experiments.faultsim              # deterministic multi-store fault matrix
python tools/scan_secrets.py                # sensitive-data scan of the repository
```

Read [AGENTS.md](AGENTS.md), the rules for everyone changing this repository,
humans and AI agents alike, and [CONTRIBUTING.md](CONTRIBUTING.md) before
opening a pull request.

## License

Copyright © 2026 CR Ramesh. All rights reserved. This is proprietary software;
see [LICENSE](LICENSE) for terms.
