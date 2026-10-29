# P3b — four memory systems, one agent team

**SUPPORTED. Amberlog closes 86% of the measured headroom against a
registered 40%, and holds at 85% with ten times the agents.**

- `local` 0.060 · `shared` 0.780 · `shared_blanket` 0.720 · **`fabric` 0.970** · `oracle` 1.000
- Registered in [p3b-agent-teams.md](../prereg/p3b-agent-teams.md) before `experiments/teamworld.py` existed
- 5 seeds, 10 agents, 60 rounds; the agent-count sweep runs to 100
- **The agent is deterministic.** Nothing here is evidence about model behaviour, and §6 says why that is a choice rather than a shortcut

---

## 1. The numbers, 10 agents, 5 seeds

| metric | `local` | `shared` | `shared_blanket` | `fabric` | `oracle` |
|---|---|---|---|---|---|
| **task success** | 0.120 | 0.780 | 0.730 | **0.960** | 1.000 |
| correct evidence in context | 0.770 | 1.000 | 1.000 | 0.990 | 1.000 |
| **acted on withdrawn knowledge** | 0.050 | **0.180** | 0.000 | **0.000** | 0.000 |
| valid evidence withheld | 0.000 | 0.000 | 0.000 | 0.010 | 0.000 |
| abstained | 0.400 | 0.000 | 0.000 | 0.020 | 0.000 |
| **had to re-measure** | 0.430 | 0.000 | **0.250** | **0.000** | 0.000 |
| correct eventually (no deadline) | 0.550 | 0.780 | 0.980 | 0.960 | 1.000 |
| **duplicate discoveries** | **13.6** | 5.0 | **10.0** | **5.0** | 5.0 |
| model calls | 20.0 | 20.0 | 20.0 | 20.0 | 20.0 |
| context tokens a task | 36.6 | 53.0 | 52.7 | 52.9 | 10.5 |
| retrieval latency ms | 0.0 | 0.1 | 0.1 | **0.7** | 0.0 |

```
best baseline        B = 0.780   (shared)
ceiling              C = 1.000   (oracle)
headroom                 +0.220
threshold            B + 0.40 x headroom = 0.868
fabric                   0.960   ->  SUPPORTED (86% of headroom)
```

Seed spread on the primary: `fabric` 0.900–1.000 (sd 0.037), `shared`
0.750–0.850, `local` 0.050–0.150. No arm's range overlaps the fabric's except
the oracle's.

## 2. The six questions, answered

1. **How often do agents use the correct evidence?** `fabric` 0.990, the shared stores 1.000, `local` 0.770. The shared stores *retrieve* the right statement reliably and still fail the task, because they also retrieve the withdrawn one and the agent takes the top-ranked. Having the evidence is not the same as the evidence deciding.
2. **How often does an agent act on withdrawn knowledge?** `shared` **0.180**, `fabric` **0.000**. A correction in a plain store is just another write, so the superseded statement stays retrievable for ever and ranks exactly as well as it did. This is the single clearest difference in the table.
3. **How often is valid independent evidence incorrectly invalidated?** 0.000 everywhere except `fabric` at **0.010** — one task in a hundred, discussed in §5. `shared_blanket`'s wrongful invalidation does not show here because it *repairs itself*: it destroys the neighbouring fact, the agent re-measures, and the metric is clean by task time. The cost appears instead as a **0.250 re-measure rate** and **twice the duplicate discoveries**. A metric can be satisfied by a system that did the wrong thing and then paid to undo it.
4. **How many duplicate discoveries?** `local` **13.6**, `shared_blanket` **10.0**, `fabric` **5.0** — against 5.0 scheduled. Isolation costs 2.7× the field work; blanket invalidation costs 2×.
5. **Task completion rate and time.** Above. A task the agent could answer only by going out to re-measure is scored as a failure, which is the modelling decision §4 is about.
6. **Added model calls, tokens, latency.** Model calls are identical by construction — 20, one per task, for every arm. Context tokens are flat across the three shared systems (52.6–53.0) and lower for `local` (36.6) only because it holds less. Retrieval latency is **0.7 ms for the fabric against 0.1 ms** for a dict-and-sort, a **7× multiple on a sub-millisecond operation**.

## 3. The envelope: 10 to 100 agents

| agents | facts | tasks | `local` | `shared` | `shared_blanket` | `fabric` | closed | verdict | fabric latency | fabric sd |
|---|---|---|---|---|---|---|---|---|---|---|
| 10 | 20 | 20 | 0.060 | 0.780 | 0.720 | **0.970** | 86% | SUPPORTED | 0.67 ms | 0.040 |
| 25 | 50 | 50 | 0.024 | 0.764 | 0.756 | **0.980** | 92% | SUPPORTED | 0.79 ms | 0.025 |
| 50 | 100 | 100 | 0.026 | 0.806 | 0.688 | **0.970** | 85% | SUPPORTED | 0.86 ms | 0.014 |
| 100 | 200 | 200 | 0.012 | 0.757 | 0.716 | **0.964** | 85% | SUPPORTED | 1.09 ms | 0.012 |

**Retrieval latency rises 1.6× for ten times the agents and ten times the
facts**, and the verdict holds at every size. The seed spread *narrows* as the
team grows, which is what more tasks a run should do and is worth stating
because it is the only thing here that behaves as naively expected.

A correction to an earlier version of this table: at 8 units × 6 sites the pair
space capped at 48, so the 50- and 100-agent runs covered an identical 96 facts
and the larger one measured contention over a fixed fact space rather than a
larger world. The vocabularies were widened to 192 pairs. Both regimes are
worth measuring; only one of them was.

## 4. The world was wrong three times, and principle 8c caught each one

Every iteration happened **before** the verdict, and each was forced by the 8c
check — *is the primary metric trivially maximised by a registered baseline?*
— rather than by the result being unwelcome.

1. **One attribute per unit and site.** A correction and its replacement concerned the same statement, so `shared_blanket`'s rule — suppress everything about this unit and site — destroyed only what was already superseded, and scored a perfect 0.000 wrongful invalidation. The failure that rule commits is destroying *neighbouring valid knowledge*, and a world with one attribute per pair has none to destroy. Two attributes now, and corrections land on only one of them.
2. **An agent that answered from anything.** The reader took the first retrieved statement containing a value, so an isolated agent with no knowledge of the asked fact confidently returned another unit's figure. Every arm then showed exactly the 5 scheduled duplicate discoveries and metric 4 could not discriminate. The reader now checks the subject — unit, site, attribute — and nothing else.
3. **Free rediscovery.** With re-measurement available and unpenalised, `local` reached 0.950 and `shared_blanket` 0.980, above the fabric, while paying 21.6 and 10.0 duplicate discoveries against 5.4. Suppression plus rediscovery equalled repair, a baseline sat on the ceiling, and the clause abandoned the comparison. Two changes: half the facts are not reproducible — the surveyor has gone, the document is unavailable — and a task the agent could answer only by re-measuring is **not** a success for the memory system. The field crew's work is not the store's achievement.

The third is the one worth generalising. **A memory system's value is invisible
in task success when the task can simply be redone**, and nothing in the
registration anticipated that. `correct eventually` is reported in §1 precisely
so the difference the deadline makes stays visible: on that metric
`shared_blanket` scores 0.980 against the fabric's 0.960, and it is the wrong
metric.

## 5. Where the fabric is not perfect

**0.010 wrongful invalidation and 0.020 abstention** — roughly one task in a
hundred where a currently-valid statement the store held was not returned.
Both come from the contradiction injection: two agents measure different values
for one tuple, the fabric holds them as competing hypotheses, and a contested
memory is withheld from retrieval by default. That is the designed behaviour —
principle 6, contradictions stay representable — and for a deterministic agent
with no way to choose between two standing hypotheses it costs a task.

Prediction 4 said the fabric would not reach the oracle for exactly this
reason, and the measured gap (0.030–0.040) is close to the share of tasks under
active contradiction. It is the honest price of not silently picking a winner,
and a real agent might do better than abstain, which this harness cannot say.

## 6. What this does not establish

1. **Nothing about model behaviour.** The agent is deterministic: it takes the value from the first retrieved statement about its subject. Every difference above is about whether the right evidence arrives. [R6](r6-downstream.md) measured the other half and its dev finding did not replicate, which is why the two are not mixed here. A real-model arm needs its own registration.
2. **The coordination policy is fixed and dull** — round-robin, no delegation, no review — so that memory is the only variable. Nothing here is evidence about coordination design.
3. **`shared` and `shared_blanket` are my implementations of a baseline**, not real products. They are a dict with lexical top-k and the naive correction rule. A real shared store might do better; the point of `shared_blanket` is that the obvious correction rule has a cost, not that every implementation pays it.
4. **One process, in-memory stores.** Concurrency, crash recovery, cross-store failure and authorisation under load are priority 4's question and are measured separately; the latency figures here are single-threaded.
5. **The world is mine**, including what counts as a correction, how often facts contradict, and that half of them cannot be re-measured. That last number is a modelling assumption with no empirical basis, and the result is sensitive to it: at 100% reproducible the comparison abandons.
6. **Latency is sub-millisecond throughout**, so the 7× multiple over a dict is real and may not matter. At 200 facts the fabric is doing lexical IDF over a store with gates and provenance; nothing here says what it costs at 200,000.

## 7. The honest summary

> **Amberlog closes 86% of the headroom against a registered 40%, and 85%
> with ten times the agents.** The clearest single difference is metric 2: a
> plain shared store lets agents act on withdrawn knowledge in **18% of
> tasks** and the fabric in **none**, because a correction in a plain store is
> just another write that ranks as well as it always did.
>
> The naive fix is worse than it looks. `shared_blanket` eliminates stale
> actions and pays for it by destroying the fact next door — which does not
> show up as wrongful invalidation, because it **repairs itself** by sending
> someone out to re-measure. It is visible only as a 0.250 re-measure rate and
> twice the duplicate discoveries. A metric can be satisfied by a system that
> did the wrong thing and then paid to undo it.
>
> Isolation is a real defence and a real cost: `local` acts on withdrawn
> knowledge least among the baselines and does 2.7× the field work.
>
> The fabric is not perfect and the imperfection is the design: one task in a
> hundred loses a valid statement because two agents measured different things
> and a contested memory is withheld rather than resolved by guessing.
>
> And the world was wrong three times before it could pose the question, each
> time caught by principle 8c's check rather than by the answer being
> unwelcome. The most useful of the three: **a memory system's value is
> invisible in task success when the task can simply be redone.** With free
> rediscovery every baseline reached the ceiling. The deadline is what makes
> the question answerable, and it is a modelling choice this result depends on.
