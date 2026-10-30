# Invitation: a two-to-four-week pilot of Memory Fabric

*For you to send to a team you would like to pilot with. Edit freely.*

**What it is.** Memory Fabric is shared memory for AI agents that keeps track
of where each piece of knowledge came from. When something an agent learned
turns out to be wrong, it is withdrawn everywhere it spread, and any agent
about to act on it is stopped and told why.

**What we are asking.** Connect two or more of your agents (Claude Code,
Cursor, LangGraph, the OpenAI Agents SDK, CrewAI, your own code, with any
model) to one shared store for two to four weeks, and work as usual. When
someone notices a remembered fact is wrong, withdraw it with one command.

**Time.** About 15 minutes to set up (`docs/PILOT_KIT.md`), then nothing
beyond normal work. One command at the end.

**What you send back.** A single JSON file of counts and durations, nothing
else. It contains:

- how many actions ran on knowledge that was later withdrawn;
- how many were stopped because their evidence no longer held;
- how long wrong knowledge stayed in use, and how long agents kept trying
  to use it afterwards.

It contains **no memory text, no questions, and no agent names** (those are
replaced by hashes that cannot be reversed). The report checks itself for
memory text before you send it (`content_free`), and you can read every line.

**What you get.** A measured answer, on your own work, to "how often do our
agents act on something we already know is wrong, and does this stop it?",
plus our written summary of your numbers against the other pilots,
anonymised.

**How to know you are done.**

```bash
memory-fabric --db pilot/store.db --keys pilot/keys pilot-report --check
```

It says in plain words whether the pilot has produced enough to send (two
agents sharing, at least one correction, at least one protected action) and
what is still missing.

**Your data stays with you.** The store runs on your machines, encrypted at
rest. Nothing is sent anywhere unless you choose a hosted model, in which
case it goes only to that provider under your own account.
