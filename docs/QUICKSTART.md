# Quickstart: ten minutes, from install to a verified correction

Every step below is in [examples/quickstart.py](../examples/quickstart.py),
which `tests/test_quickstart.py` runs on every CI build, on Linux, macOS and
Windows with Python 3.11 to 3.13.

## 1. Install (1 minute)

```bash
git clone https://github.com/crakashp2905-hub/memory-fabric.git
cd memory-fabric
pip install .
memory-fabric init ./memory --mode personal     # or team (default), or regulated
```

`init` creates a store, keeps its keys outside it, registers one agent,
prints an MCP client configuration and runs `doctor`. It never overwrites an
existing store.

**Pick a mode, not a dozen settings.** `personal`: one person and their
agents; what they write is usable at once. `team`: shared knowledge; new
memories wait for review. `regulated`: protected tools need two independent
sources and fresh evidence. In Python: `presets.open_store(path, "team")` and
`presets.tool_rule("team", "issue_refund")`.

**Removal is clean.** The package writes nothing outside the directories you
name:

```bash
pip uninstall memory-fabric
```

Then delete `./memory` (the store and its keys) if you no longer want the
data. There are no services, registry entries or files elsewhere.

## 2. Store, retrieve, inspect, correct, verify (5 minutes)

```bash
python -m examples.quickstart
```

| step | call | what to look at |
|---|---|---|
| store | `remember`, `derive` | every memory records who wrote it and how; `derive` records its premises |
| retrieve | `retrieve(...).exposed` | what an agent is shown; each exposure is logged with its probability |
| inspect evidence | `explain(id).narrative()`, `authority(id)` | why it is remembered, where it came from, and how far it may be trusted |
| correct | `correction.preview`, then `correction.apply` | what withdrawing it would touch, *before* you decide; then the withdrawal and the retractions owed |
| verify | `retrieve` again, `verify_recovery`, `influence.impact` | the wrong memory and the plan built on it are no longer shown; recovery is `contained`, checked from state |

## 3. Use it from your agent (4 minutes)

- **An MCP client** (Claude Code, Claude Desktop, IDE assistants): paste the
  configuration `init` printed.
- **Python:** [examples/reference_agent.py](../examples/reference_agent.py)
  is the reference agent: it retrieves before it acts, cites what it used, gets a
  grant for the exact action, executes through the fence and records the verified outcome.
- **Anything else:** see [INTEGRATIONS.md](INTEGRATIONS.md).

If something fails, `memory-fabric --db ./memory/store.db doctor` names the
failing check and the next command, and [TROUBLESHOOTING.md](TROUBLESHOOTING.md)
lists every error message. Add `--log-format json` for structured logs.

## 4. See what an agent was given, and try changes on a branch (optional)

```bash
python examples/wrong_memory_demo.py
```

It walks one story: a policy stored and used, a corrected source, a preview
of what the correction touches (applied only if nothing changed since the
preview), the next context leaving the stale rule out, and an alternative
proposed on a branch that main never sees until a reviewer merges it. From
the command line:

```bash
memory-fabric --db demo.db context build --agent support-bot --query "refund window"
memory-fabric --db demo.db branch create trial --actor you --reviewer lead
memory-fabric --db demo.db merge preview trial --actor lead
```

Context receipts, the context planner and branches are **experimental**; the
dashboard's Capabilities tab lists what is available, experimental or not
offered, and why.
