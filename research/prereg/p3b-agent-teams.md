# Pre-registration — P3b: does Memory Fabric improve an agent team?

**Registered 2026-10-12, before `experiments/teamworld.py` exists.**

## 1. The question, and the honest decomposition

"Does a team of agents do better with Memory Fabric than without" is two
questions, and only one of them is answerable cheaply:

- **(a) Does the right evidence reach the agent?** A property of the memory system.
- **(b) Does the agent then use it?** A property of the model.

**R6 measured (b) and its dev finding did not replicate** — on a corpus a model
could simply read, perfect selection was worth +0.000. So this experiment
measures **(a)**, with a **deterministic agent**, and says so everywhere the
numbers appear. A deterministic agent extracts whatever value the retrieved
evidence states and answers with it; it has no reading comprehension to add and
none to lose.

That is a deliberate narrowing, not an oversight. With a real model the
measurement would mix the memory system's contribution with the model's, and R6
already showed the model's half is the noisier one. A real-model arm is left for
a separate registration.

## 2. The four systems, on identical task sequences

Every arm sees the **same** world, the same discovery schedule, the same
injections and the same task assignment, driven by one seeded RNG. The only
thing that varies is where memory lives and what it does.

| arm | memory |
|---|---|
`local` | each agent has its own store. It knows only what it discovered itself |
`shared` | one plain append-only store, lexical top-k over everything ever written. No lifecycle, no provenance, no gates. The ordinary shared store |
`shared_blanket` | `shared`, plus the naive correction rule: when a fact is corrected, withhold everything whose content overlaps the withdrawn fact |
`fabric` | Memory Fabric at its defaults |
`oracle` | handed the currently-correct fact. The ceiling |

`shared_blanket` exists because without it metric 3 cannot fire: neither
`local` nor `shared` ever invalidates anything, so "incorrectly invalidated"
would be 0.000 for every baseline and the metric would look satisfied by doing
nothing. It is also the implementation a team would most plausibly write.

## 3. Injections

Four, all of which the memory system is supposed to handle and a plain store is
not:

1. **Outdated facts** — a value is superseded at a known time; the old statement stays in the log.
2. **Contradictory discoveries** — two agents discover conflicting values for one tuple.
3. **Duplicate sources** — the same document is ingested by several agents.
4. **Corrections** — a fact is withdrawn, and conclusions drawn from it must be reassessed while independent corroboration survives.

## 4. Metrics

Primary: **task success** — the share of tasks answered with the value the
world currently holds.

```
B = max(task_success) over {local, shared, shared_blanket}
C = task_success(oracle)
support fabric iff  task_success >= B + 0.40 * (C - B)
```

**Abandonment clause**: if `C - B <= 0.05`, abandoned rather than
reinterpreted.

**8c check — is the primary trivially maximised by a baseline?** To be run and
reported *before* the comparison, as principle 8c now requires. If any baseline
reaches the oracle, the world is too easy and the fix is more injection, not a
different threshold.

Secondary, the six the question asked for, reported always and decisive for
none:

1. `correct_evidence_rate` — the share of tasks where the currently-valid fact was in the retrieved context.
2. `stale_action_rate` — the share where the agent answered from a withdrawn fact.
3. `wrong_invalidation_rate` — the share where valid independent evidence was withheld.
4. `duplicate_discoveries` — discovery actions spent on a fact the team already held.
5. `task_time` — rounds to completion, and wall-clock.
6. `model_calls`, `context_tokens`, `latency_ms`.

`must_not_expose_rate` is reported and **any non-zero value fails the run**.

## 5. Predictions

1. **`local` will lose on duplicate discoveries and win on stale actions.** An agent that only knows what it found itself cannot act on another agent's withdrawn fact. Isolation is a real defence, and the cost is rediscovery.
2. **`shared` will have the worst `stale_action_rate`.** Corrections are just new writes, so the old value stays retrievable forever.
3. **`shared_blanket` will beat `shared` on stale actions and lose on `wrong_invalidation_rate`**, exactly as `blanket_invalidation` did in P3 — and that is the point of including it.
4. **`fabric` will not reach the oracle**, because contradictory discoveries are *supposed* to leave two standing hypotheses and a deterministic agent has no way to choose between them. I expect the gap to be roughly the share of tasks under active contradiction.
5. **`fabric` will cost the most per task in latency** and the least in context tokens, because gating and grouping remove candidates a plain store returns.

## 6. What a pass would not establish

Nothing about real agents: the agent is deterministic by construction, so this
measures whether the right evidence arrives and not whether a model uses it.
Nothing about scale — the agent count is a parameter and the envelope is
priority 4's question, with its own gates. Nothing external: the world is mine.
And nothing about coordination quality, since the coordination policy is fixed
across arms so that memory is the only variable.

Deterministic given a seed; **5 seeds minimum**, with the spread reported
alongside every mean.
