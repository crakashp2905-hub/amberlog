# Pilot kit: try it with your own agents, share only the numbers

*Inviting a team? [PILOT_INVITE.md](PILOT_INVITE.md) is a one-page invitation to send them.*

A two- to four-week pilot with your real agents answers the question no
benchmark can: does Memory Fabric stop your agents acting on knowledge that
turned out to be wrong, and how quickly? This kit is everything needed to
run one and send back a result **without sharing any of your data**.

## 1. Set up (15 minutes)

```bash
pip install .
memory-fabric init ./pilot --mode team          # or personal / regulated
memory-fabric --db pilot/store.db --keys pilot/keys connect <your tool> --agent <id> --write
```

Connect every agent that should share knowledge, each with its own `--agent`
id. Choose your model and retriever if you want them
([any agent, any model](guides/any-agent-any-model.md)). For tools that change
something real, wrap them with `FabricTools.guarded` or `ActionGate` so the
evidence is re-checked at the moment they act.

## 2. Run as you normally would

Let agents work as usual. When someone finds a remembered fact is wrong,
withdraw it the normal way:

```bash
memory-fabric --db pilot/store.db --keys pilot/keys correct <memory id> --apply \
  --reason "<why>" --actor <your name>
```

Use the dashboard (`serve`) to review new memories, follow corrections and
watch what agents were blocked from doing.

## 3. Send back the report

First, check the pilot has produced enough to be worth sending:

```bash
memory-fabric --db pilot/store.db --keys pilot/keys pilot-report --check
```

It lists what is in place and what is missing (two agents sharing, a
correction, a protected action) in plain words. Then:

```bash
memory-fabric --db pilot/store.db --keys pilot/keys pilot-report > pilot-report.json
```

The report holds counts and durations only: no memory content, no queries,
and agent names replaced by hashes (keyed with a random value that is not
stored, so they cannot be reversed). Read it before sending; it is plain JSON, and its `content_free` field
records that it was checked for memory text before it was printed.

| field | what it tells us |
|---|---|
| `acted_on_evidence_later_withdrawn` | actions taken before a correction caught up: the harm still left |
| `blocked_on_evidence` | actions refused because their evidence no longer held: the harm prevented |
| `exposures_after_withdrawal` | withdrawn knowledge still shown to an agent: should be 0, anything else is a bug |
| `median_seconds_last_use_to_withdrawal` | how long wrong knowledge was in use before someone withdrew it |
| `median_seconds_withdrawal_to_last_blocked_try` | how long agents kept trying to use it afterwards |
| `agents` | per agent: writes, recalls, refusals, actions allowed and blocked |

## 4. What a good pilot looks like

- At least two agents (or two people's copies of one tool) sharing a store.
- At least a handful of real corrections: the interesting numbers only appear
  when something turns out to be wrong.
- Protected tools for anything with a cost, so blocked actions are counted.

Questions and reports: see [SECURITY.md](../SECURITY.md) for the contact
address.
