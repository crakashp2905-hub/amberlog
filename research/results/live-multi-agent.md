# Result — multiple agents, real disagreement: preserving it stops confident error

- **Run:** 2026-10-07, three local models as independent observer agents, each with its own store. Raw output: [live-multi-agent-run.txt](live-multi-agent-run.txt)
- **Reproduce:** `python -m experiments.live_multi_agent`

[H4b](h4-topology-and-diversity.md) found in simulation that preserving contested hypotheses rather than collapsing to the majority lifts P(correct) from 0.905 to 1.000. The [first live runs](live-ollama-validation.md) did not test it: they used several agent *identities* but a single model in a scripted sequence. This is the first test with agents that genuinely disagree.

## Setup

Three observer agents, **one per model**, each with its own store, each given a different piece of evidence about the same fault. Two get the wrong lead and one the right one, so **the majority is wrong** — the premature-consensus trap. Each writes its own memory, in its own words, into its own store. All federate into a consolidator. A reader then answers under two arms:

| arm | the consolidator keeps |
|---|---|
| `collapse` | only the majority memory; the dissent is forgotten |
| `preserve` | all of them, marked contested by the fabric |

Both arms read **identical** observer memories, so the only difference is what survives consolidation.

## Result

10 usable trials (2 skipped — see below).

| arm | confidently wrong | hedged | followed majority | correct |
|---|---|---|---|---|
| collapse | **0.80** [0.50, 1.00] | 0.20 | 90% | 0% |
| preserve | **0.00** [0.00, 0.00] | 1.00 | 0% | 0% |

**Difference −0.80 [−1.00, −0.50]**, interval clear of zero.

Collapsing to the majority made the reader confidently assert a wrong action in 8 of 10 trials. Preserving the disagreement eliminated that entirely.

The reader's own words show the mechanism, not just the metric:

> **collapse** — "The evidence provided suggests that when the depot charger reports fault code E31, the issue is a broken pilot cable, and the response is to swap the pilot cable. Therefore, the correct response is to swap the pilot cable."

> **preserve** — "The evidence provided is in conflict, and there is insufficient evidence to determine the correct response. The memories suggest different actions… with 01M4BK1EBYENP7X87682SZVWWX recommending swapping the pilot cable, 01M4BK1E3ABV09WQDG46G04G5F recom…"

It cites the conflicting memories **by id**. The hypothesis-set machinery reached a real model's reasoning.

## What this does *not* show

**`correct` is 0% in both arms.** The reader never picks the minority, and preserving the disagreement does not make it right. What it does is convert **confident error into flagged uncertainty**.

For a system that acts on its answers that is the property worth having — a wrong action taken confidently is worse than a hedge that asks for verification. But it is a narrower claim than "preserving disagreement improves accuracy", and the simulated H4b result (which *did* show accuracy gains) does not transfer on this evidence. In H4b the agents could re-test the contested belief and gather new evidence; here the reader has only what it was given, and the honest response to conflicting evidence is to say so.

## Three assumptions this broke

The first version of this experiment was wrong in three ways, all found by running it:

**1. One agent wrote nothing; another wrote four memories.** `qwen2.5:3b` produced one memory; `llama3.2:3b` called the `remember` tool **four times in a single run**, producing two distinct memories and two exact duplicates. The designed 2-vs-1 majority was silently a 4-vs-1.

**2. The fabric had no deduplication.** That is a product gap, not an experiment artifact, and duplicates inflate apparent consensus exactly the way several agents repeating one source do (SECURITY.md T3) — except from a *single* agent, which the evidence-independence check never examines. Fixed in schema 0.2.0: `remember` now returns the existing memory and emits `MemoryDuplicateSuppressed` when an agent rewrites content it already wrote **in the same episode**. Scoped to one episode deliberately — the same claim on two separate occasions is two observations, and that genuinely is more evidence.

**3. The memories could not answer the question.** Observers described fixes in their own words — *"requires replacement of faulty conductor"* — while the reader had to choose from a fixed list of action names. The memories named none of the options, so **both arms scored 0% correct for a reason that had nothing to do with the hypothesis**: the reader was being asked a question its own memories could not answer. Fixed by requiring observers to name a canonical action.

A fourth, smaller one: the answer parser matched only `swap_pilot_cable` and not "swap the pilot cable", so confidently wrong answers were scored as *no answer* — biasing against the very effect being measured.

**The numbers from the first run (30% → 0%) should be discounted.** They measured a muddled setup. The figures above come from the corrected design.

## Agents are unreliable at writing memories

Even when told explicitly to name an exact action, observers failed to produce a usable memory some of the time:

| model | usable memories |
|---|---|
| qwen2.5:3b | 12/12 |
| llama3.2:3b | 11/12 |
| qwen2.5:7b | 10/12 |

Two trials were skipped because the observers did not produce both sides of the disagreement. This is worth stating plainly: **a memory-fabric fed by agents will receive incomplete and malformed writes as a matter of course**, and the governance path has to treat that as normal rather than exceptional. Here it is handled by filtering and reporting; a deployment would need the same.

## Cost

Interleaving three models cost a cold load on every switch — the first version paid ~190s per trial. Generating all of one model's memories before moving to the next loads each model once: observer generation took 183s + 336s + 512s total, and each trial then ran in 12–41s. **That is the real cost of multi-agent work on one machine, and it is a scheduling problem, not a modelling one.**

## Limitations

1. **10 usable trials, one reader model.** Enough for an 80%-vs-0% contrast, not for fine distinctions.
2. **The disagreement is planted**, not emergent. Observers are *given* conflicting evidence rather than reaching conflicting conclusions from the same data.
3. **The reader cannot test anything.** H4b's simulated gain came from re-testing contested beliefs; here the reader answers once from fixed evidence. The live analogue of H4b's *full* mechanism — disagreement triggering an experiment — remains untested.
4. **Small local models** (3B–7B). A stronger reader might resolve conflicts rather than hedge.
5. Both arms read identical memories, so this isolates consolidation policy — it says nothing about which agent should have been believed.

## Consequence

- **Do not collapse contested memories to the majority.** On this evidence it produces confident, wrong, actionable answers 80% of the time.
- **Duplicate suppression ships** as schema 0.2.0, motivated entirely by what running real agents revealed.
- **The next thing to test** is the half of H4b that is still untested: letting a disagreement *trigger an experiment* rather than just a hedge. That is where the simulated accuracy gain came from, and it is the mechanism the project was designed around.
