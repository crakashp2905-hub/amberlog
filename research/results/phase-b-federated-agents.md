# Phase B — what should cross a federation boundary?

**PB1 is KILLED. PB2 is SUPPORTED. PB3 is INCONCLUSIVE, by design.**

Selective sharing does not beat sharing everything. Retraction that follows a
memory across a store boundary **eliminates** agents acting on withdrawn
knowledge — completely, under both sharing policies — and does not measurably
change task success. Those two findings together are the whole result.

- **Pre-registration:** [phase-b-federated-agents.md](../prereg/phase-b-federated-agents.md), with **three** dated amendments, two of them about the ceiling.
- **Run:** `python -m experiments.phase_b --seeds 5 --rounds 12`, commit `bb617e6`, 2026-10-10. 2,130 model calls, 906,655 tokens, 11,513s wall.
- **Raw:** [phase-b-run.txt](phase-b-run.txt) · [phase-b-decisions.json](phase-b-decisions.json) · [the abandoned first run](phase-b-abandoned-run.txt)
- 4 agents, partially overlapping territories, 12 episodes each, 5 seeds → **240 verified decisions per arm**.

> **Scope correction, 2026-10-10 (added after the Phase 0 audit).** PB2's result
> is about **lifecycle and enforcement semantics, not distributed delivery.** The
> four stores were four event logs in one Python process, and
> `propagate_retraction` was called with live references to them. Nothing in this
> run crossed a network, survived a restart, or was acknowledged. The measurement
> stands as stated — acting on origin-retracted memory fell from 17% to 0% — but
> "retraction crosses a store boundary" must not be read as durable distributed
> propagation. See [docs/AUDIT.md](../../docs/AUDIT.md) §0 and
> [docs/PROTOCOL.md](../../docs/PROTOCOL.md) for what a protocol would require.

---

## 1. The table

| arm | success | negative transfer | worst agent | spread | imports (wrong) | still acting on a retracted memory |
|---|---|---|---|---|---|---|
| `isolated` | 0.613 [0.554, 0.671] | 0.000 | 55% | 12% | 0 | 0% |
| **`share_all`** | **0.742 [0.688, 0.796]** | 0.138 | **70%** | 10% | 630 (472) | 17% |
| `share_all_propagate` | 0.762 [0.708, 0.817] | 0.117 | 68% | 15% | 630 (472) | **0%** |
| `share_overlap` | 0.750 [0.696, 0.804] | 0.121 | 68% | 15% | 300 (184) | 15% |
| `share_overlap_propagate` | 0.762 [0.713, 0.812] | 0.113 | 65% | 17% | 300 (184) | **0%** |
| `share_valued` | 0.613 [0.550, 0.675] | 0.029 | 50% | 20% | 42 (23) | 0% |
| `share_valued_overlap` | 0.600 [0.542, 0.658] | 0.017 | 47% | 27% | 23 (10) | 0% |
| `oracle_share` | 0.696 [0.637, 0.754] | 0.071 | 55% | 28% | 158 (0) | 0% |

**Federation works.** Any arm that shares broadly beats isolation by 13–15
points, intervals clear. That is the first live confirmation that crossing a
boundary helps at all, and it is the opposite direction to
[Phase A](phase-a-real-agent-benchmark.md), where governance hurt.

## 2. Against the pre-registration

| § | Criterion | Result |
|---|---|---|
| 6 | **PB1** — best selective policy captures ≥ 40% of headroom over `best_simple`, interval clear of zero, **and** the worst agent does not fall | **KILLED on two counts.** `share_overlap` (0.750) against `share_all` (0.742) is **+0.008 [−0.042, +0.058]** — interval spans zero. And the worst agent **fell**, 70.0% → 68.3%. |
| 6 | **PB2** — propagation captures ≥ 50% of the recovery headroom under **both** `share_all` and `share_overlap`, and shortens the lag | **SUPPORTED under both, at 100% of headroom.** Agents still acting on a memory retracted at its origin: 16.7% → **0.0%** under `share_all`, 14.6% → **0.0%** under `share_overlap`. 123 and 59 retractions carried. |
| 6 | **PB3** — reputation weighting | **INCONCLUSIVE.** Not implemented this run. 52 imports per sender pair, so the data would have supported it; the arm was not built. Declared inconclusive rather than dressed up. |
| 8b | Ceiling check | **FAILED.** Four arms beat `oracle_share`, by +0.046 to +0.067. Headroom is **−4.6%**, so no percentage-of-headroom figure is quotable from the success metric. Anticipated and explained in [amendment 3](../prereg/phase-b-federated-agents.md), written before these numbers existed. |

**PB1's kill does not depend on the broken ceiling.** Both failing conditions are
arm-to-arm: an interval spanning zero, and a worst agent that fell. Neither
mentions the oracle.

## 3. Why selective sharing failed, and why the ceiling is beatable

These are the same fact.

`share_overlap` sends 300 memories where `share_all` sends 630, and scores
identically. The corrected `oracle_share` — sharing only what is correct at
**every** site its recipient works — sends 158, with **zero** wrong, and scores
**five points worse than sharing everything indiscriminately**.

The reason is that **a memory wrong at one of a recipient's sites is still right
at another.** Each agent works two or three sites. A lesson that misleads on its
urban episodes is exactly what it needs on its cold-store ones. Excluding it
avoids harm on some episodes and costs coverage on the rest, and which dominates
is *not knowable at share time*.

So no static sharing rule can be a ceiling here, and more sharply:

> **The sharing decision is the wrong place to filter.** Any rule that decides
> per (memory, recipient) makes one choice for a set of episodes that want
> different ones. The filter belongs at exposure, where the episode is known.

That is why the three sharing policies are statistically indistinguishable
(0.742, 0.750, 0.762) while differing fourfold in volume, and why the arm with
*perfect* sharing loses to the arm with no filter at all.

**The value gate is the extreme case.** `share_valued` requires contrastive
evidence before a memory may cross, and sends 42 of a possible 630 — it scores
**0.613, identical to isolation**, with the worst agent at 50% against
isolation's 55%. `share_valued_overlap` is worse still. The product's default
`Firewall` contains that rule. On this evidence it does not make federation
safer; it switches federation off, and makes the weakest agent worse than if it
had never joined.

## 4. What retraction propagation actually bought

PB2 is the project's clearest live win, and it is narrower than it first looks.

**It works, completely and reliably.** Agents acting on memories retracted at
their origin: 17% and 15% of post-retraction episodes without propagation,
**0.0% with it**, under both sharing policies. 182 retractions carried across
boundaries. No partial credit, no seed-dependence.

**It did not measurably improve success.** +0.021 [−0.029, +0.071] under
`share_all` and +0.013 [−0.037, +0.058] under `share_overlap`. Both intervals
span zero.

Those are compatible and the combination is the honest finding. Retracted
memories are a minority of the corpus — only poisoned lessons get retracted —
and the harm they do is small next to the coverage effect that dominates
everything in this world. So propagation reliably stops a specific, auditable
failure (an agent acting on knowledge its author has withdrawn) without shifting
the aggregate number.

**Which is exactly the right claim for the mechanism.** This is the same shape as
the [live multi-agent result](live-multi-agent.md), where preserving disagreement
converted confident error into flagged uncertainty without making the reader
correct. PRIOR_ART identifies cross-boundary provenance as the one thing no
adjacent paper does; Phase B says it delivers a *correctness and auditability*
guarantee, not an accuracy gain. For a regulated deployment the former is worth
more, and claiming the latter would be unsupported.

## 5. The agent nobody should ignore

PB1's second condition exists because a mean can be bought from the weakest
member. It was worth having:

| arm | worst agent | spread |
|---|---|---|
| `share_all` | **70%** | 10% |
| `share_overlap_propagate` | 65% | 17% |
| `oracle_share` | 55% | 28% |
| `share_valued_overlap` | **47%** | 27% |

**Sharing everything is the most equitable policy**, with the highest worst-agent
score and the lowest spread. Every selective policy raised the spread, and the
more selective, the worse the weakest agent did — `share_valued_overlap` leaves
its worst agent at 47%, below isolation's 55%. `west`, with a single site,
benefits most from indiscriminate sharing and is hurt most by filtering, because
filters tuned to the average agent starve the narrow one.

A mean-only report would have shown three sharing policies within noise and
missed this entirely.

## 6. What this does not show

1. **The success ceiling is unquotable** (§2). The fix is registered for any re-run: bound the *pipeline* — share everything, expose only what is correct for the episode — which no sharing policy can beat, since every policy's exposed set is a subset of what sharing everything makes available. It was deliberately **not** substituted mid-run after an arm beat the old one.
2. **`negative_transfer` is loose, and the oracle proves it.** `oracle_share` reports 7.1% negative transfer with **zero** wrong imports, which cannot both be meaningful. The metric counts an imported memory asserting the action the agent took *without checking it was about the episode's fault* — the same cross-fault looseness I found and fixed in [PA′'s analyser](phase-a-prime-attribution.md). The ordering across arms is still informative (0% isolated, 1.7–2.9% value-gated, 11–14% broad sharing); the absolute levels overstate federation-attributable harm and should not be quoted.
3. **PB3 was never built.** The data would have supported it at 52 imports per sender pair. This is a gap in the work, not a finding about reputation.
4. **The first run was abandoned two seeds in** because its oracle shared memories correct at a lesson's own site to recipients working several sites — a bug against the registration's own wording. Its figures appear only in [amendment 2](../prereg/phase-b-federated-agents.md) as evidence for the amendment.
5. **12 episodes per agent, not the registered 24**, amended for compute before any run. 240 decisions per arm, twice Phase A's per-arm count.
6. **Every arm ran under the exposure defect** recorded in [this decision](../decisions/2026-10-10-value-ranking-ignores-uncertainty.md) — ranking on value reads the mean and ignores `n_eff` and the interval. Held constant across arms by amendment, so it cannot bias one policy against another, but it lowers every number including the ceiling.
7. **Between-seed variance exceeds every effect here.** Seed 3 ran at 48–56% where seed 0 ran at 65–90%. The pooled intervals are the only thing worth reading; I over-read single seeds twice while this ran and said so both times.
8. **Four agents, one model, honest senders, no adversary, fixed territories.** As registered.

## 7. The honest summary

> Federation helps: any agent that shares broadly beats one that does not, by 13
> points. *Filtering* what crosses does not help, and cannot, because the
> sharing decision is made before the episode that would tell you whether a
> memory applies — a lesson wrong at one of a recipient's sites is exactly what
> it needs at another. Perfect sharing scored five points *below* sharing
> everything indiscriminately, and the value gate the product ships by default
> reduced federation to silence and left the weakest agent worse than if it had
> never joined. What did work is the mechanism no adjacent paper has: a
> retraction that follows a memory into other stores drove acting-on-withdrawn-
> knowledge from 17% of episodes to zero, under both policies, without changing
> task success. That is an auditability guarantee, not an accuracy gain, and it
> is the one thing this project has now shown live that nothing else does.
