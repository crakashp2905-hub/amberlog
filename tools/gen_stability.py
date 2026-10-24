"""Regenerate STABILITY.md from each module's `__stability__` (tests/test_stability.py checks it).

    python tools/gen_stability.py
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
root = ROOT / "memory_fabric"
tiers = {"stable": [], "beta": [], "experimental": []}
for path in sorted(root.rglob("*.py")):
    m = re.search(r'^__stability__ = "(\w+)"', path.read_text(encoding="utf-8"), re.M)
    if m:
        tiers[m.group(1)].append("memory_fabric." + path.relative_to(root).with_suffix("").as_posix().replace("/", "."))


def table(tier):
    return "\n".join(f"- `{name}`" for name in tiers[tier])


doc = f"""# Stability, compatibility and capacity

What you can rely on, and in what way. Every product module declares its tier
in code (`__stability__`). `tests/test_stability.py` fails if this document and
the code disagree.

## The three tiers

| tier | promise | may change |
|---|---|---|
| **stable** | Public functions, classes and CLI commands keep their names and meaning within a minor series. Removals are deprecated for one minor version first and noted in the CHANGELOG. **Events written by any released version replay on every later version** ([VERSIONING.md](VERSIONING.md)). | Internals, private names (`_x`), wording of messages |
| **beta** | Used in production paths and tested, but new. Names may change in a minor version, always with a CHANGELOG entry. Events they write are covered by the replay guarantee like any other. | Signatures, defaults, output shapes |
| **experimental** | New mechanisms. **All opt-in**: nothing in the default path calls them unless you turn it on. | Anything, or removal |

Promotion needs evidence that the change in default behaviour helps,
and the owner's decision (AGENTS.md principle 9).

## Stable ({len(tiers['stable'])})

{table('stable')}

## Beta ({len(tiers['beta'])})

{table('beta')}

## Experimental ({len(tiers['experimental'])})

{table('experimental')}

## Compatibility, as tested

These are what CI runs on every commit to `main`, and what the 0.11.0
release acceptance ran ([RELEASE_EVALUATION.md](docs/RELEASE_EVALUATION.md)).
Anything else is untested, not unsupported.

| dimension | tested |
|---|---|
| Python | 3.11, 3.12, 3.13 |
| OS | Ubuntu, macOS, Windows (GitHub-hosted runners); Windows 11 locally |
| Storage | SQLite (stdlib, the default); PostgreSQL 16 (`postgresql://` URL, needs `psycopg>=3.1`) |
| Runtime dependencies | none for the core; optional extras for Postgres, the Claude adapter and the LangChain retriever |
| Container | the repository's `Dockerfile` (non-root, uid 10001), built and smoke-tested in CI |
| Store schema | every released schema opens on this version; a newer schema is refused by `doctor` (exit 5) rather than half-read |
| Federation protocol | version 1. Peers on different schema versions interoperate; an unsupported protocol version is refused |
| MCP | protocol versions 2025-06-18 and earlier negotiated versions (`tests/test_mcp.py`) |

## Capacity, as measured

From [DEPLOYMENT.md §3](DEPLOYMENT.md), measured on one machine:

- **About 100–135 operations a second per store**, whatever the shape.
- **p95 under 150 ms** up to about 10 agent processes per store, or 10 agents
  behind one `agent-api` process.
- **Past that, run one `agent-api` process** rather than giving every agent
  its own store handle.
- **The action fence makes writers wait** while a fenced action runs: up to
  about 2 s under continuous action, 12–16% fewer actions a second.

These are measurements, not limits the code enforces. Measure your own
workload before relying on them.
"""
(ROOT / "STABILITY.md").write_text(doc, encoding="utf-8")
print({k: len(v) for k, v in tiers.items()})
