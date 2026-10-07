# Result — H3: the crossover curve is real; the registered threshold was unpassable

- **Pre-registration:** [../prereg/h3-selective-federation.md](../prereg/h3-selective-federation.md)
- **Run:** 2026-10-05, 10 seeds, 5 overlaps, 2 agents, 1500 local + 500 probe + 1500 evaluation episodes each. Raw output: [h3-run.txt](h3-run.txt).
- **Reproduce:** `python -m experiments.h3`

## Verdict: **INCONCLUSIVE**

Condition 1 passed: `selective` is never meaningfully worse than the better fixed policy. Condition 2 failed at every intermediate overlap:

| overlap | selective − max(none, full) | registered bar |
|---|---|---|
| 0.25 | +0.003 [−0.006, +0.012] | +0.030 ❌ |
| 0.50 | +0.011 [+0.000, +0.022] | +0.030 ❌ |
| 0.75 | +0.006 [−0.000, +0.011] | +0.030 ❌ |

**The threshold was larger than the effect the world can produce.** With perfect knowledge of which imports help — the `fed_oracle` arm, added post-hoc — the total available gain over the better fixed policy is:

| overlap | best fixed | oracle | **headroom** | selective's share |
|---|---|---|---|---|
| 0.00 | 0.488 | 0.496 | **+0.008** | — |
| 0.25 | 0.489 | 0.509 | **+0.020** | 15% |
| 0.50 | 0.489 | 0.516 | **+0.027** | 41% |
| 0.75 | 0.504 | 0.528 | **+0.024** | 25% |
| 1.00 | 0.517 | 0.541 | **+0.024** | 0% |

**The maximum headroom anywhere is +0.027, against a registered bar of +0.030.** No policy — not even one with perfect transferability knowledge — could have passed H3 as written. That is a defect in the pre-registration, not a finding about selective federation: I set a margin without first establishing a ceiling. The verdict stands as INCONCLUSIVE because moving a threshold after seeing results is exactly what pre-registration prevents.

## The crossover curve

| overlap | none | full | **selective** | random_probe | *fed_oracle* |
|---|---|---|---|---|---|
| 0.00 | **0.488** | 0.462 | 0.484 | 0.471 | *0.496* |
| 0.25 | 0.489 | 0.474 | **0.492** | 0.482 | *0.509* |
| 0.50 | 0.489 | 0.485 | **0.500** | 0.487 | *0.516* |
| 0.75 | 0.490 | 0.504 | **0.510** | 0.489 | *0.528* |
| 1.00 | 0.490 | **0.517** | **0.517** | 0.502 | *0.541* |

The shape predicted in §2 held, cleanly:

- **`none` is flat** (0.488 → 0.490) — as it must be, since an agent that shares nothing cannot care how much its context overlaps anyone else's. This is the strongest evidence the world is wired correctly.
- **`full` rises monotonically** (0.462 → 0.517) and **crosses `none` between o=0.5 and o=0.75.**
- **`selective` tracks the upper envelope** of the two fixed policies throughout, slightly above it in the middle.

Both sanity gates passed: `full > none` at o=1.0, `none ≥ full` at o=0.0.

## What is actually actionable

**Sharing everything is harmful when contexts differ.** At o=0, `full` scores 0.462 against `none`'s 0.488 — **2.6 points worse than not sharing at all**, and its negative-transfer rate is 50.2%. Half of what crossed the boundary was wrong for the recipient. Indiscriminate federation is not a neutral default; it is a way to make agents worse.

**Not sharing is just as costly in the other direction.** At o=1, `none` leaves 2.7 points on the table against `full`.

So the single most useful thing a federation layer can know is **how much its agents' contexts overlap** — and the gain from being clever beyond that is small. A policy of "estimate overlap, then pick none or full" was not tested and might capture most of selective's advantage far more cheaply than probing. That is the obvious missing arm.

## The probe does work — it is the headroom that is small

The `random_probe` control pays the identical probe cost and keeps the identical number of imports, chosen at random. Selection beats it consistently:

| overlap | 0.00 | 0.25 | 0.50 | 0.75 | 1.00 |
|---|---|---|---|---|---|
| selective − random_probe | +0.013 | +0.010 | +0.013 | +0.021 | +0.015 |

At most overlaps that gap is **larger** than selective's margin over the better fixed policy. The mechanism is doing real work; the fixed policies are simply already close to the envelope. Without this control the small headline margin would have been easy to misread as "the probe does nothing".

`selective` also carries less harm than `full` at every overlap (negative transfer 49.3% vs 50.2% at o=0; 31.2% vs 33.3% at o=1), and its probe cost moves exactly as it should — **−0.032** at o=0, where probing exposes mostly-wrong imports, to **+0.031** at o=1, where it exposes mostly-right ones.

## Metadata-first costs more than it saves here

The offered metadata totalled **52,461 bytes against 8,973 bytes of content** — roughly 6× more. A RuleWorld memory is about 50 characters, so a description that carries id, type, context, value and capabilities dwarfs the body it describes.

This is an artifact of toy-sized content, not a finding against the protocol: metadata-first saves only when content is much larger than its description, which is the normal case in production and not the case here. **No claim about communication savings is supported by this run.**

## Defects found, and what was done

**The first full run was invalid and was discarded.** In the `full` arm imports arrive active, so the second offer direction re-shared them: each agent received its own memories back, 270 imports instead of 90. That inflated crowding in exactly the arm meant to represent "share everything", penalising it. Fixed by snapshotting each store's native memories before anything crosses, pinned by a regression test, and the experiment re-run from scratch.

**Two arms were added after the registered design, both disclosed and neither entering the §6 decision rule:**

- `random_probe`, a control that can only make the hypothesis *harder* to support. Added when a smoke run showed selective keeps about half the imports, raising the possibility that its advantage came from carrying fewer memories rather than choosing better ones.
- `fed_oracle`, added because without a ceiling the magnitude of any margin is unreadable — the lesson from [H2](h2-credit-driven-retention.md), where the oracle revealed the naive baseline was already capturing 93% of what was available. It is what showed the registered threshold to be unpassable.

**A smoke run on 3 seeds suggested selective sat on the oracle at o≥0.5. The 10-seed run does not support that** — selective captures 15–41%. The smoke figure was noise, and it is recorded here because it was briefly believed.

## Limitations

The six from the pre-registration stand. Three are now material:

1. **Two agents, two symmetric contexts.** Topology is H4.
2. **One-shot federation**, after a fixed local phase. Continuous federation, and memories derived from imported ones, are untested.
3. **The probe is the only transferability mechanism tested.** Predicting transferability from memory features without probing, and the "estimate overlap then pick a fixed policy" baseline above, are both untested and both plausibly cheaper.
4. RuleWorld effects remain ~10× production scale; the curve's *shape* should transfer, its magnitudes should not.
5. Scripted agent; no LLM confirmation.

## Consequence

- **The crossover curve is the deliverable**, and it is a real one: it says when to share and when not to. "Share everything" costs 2.6 points at low overlap; "share nothing" costs 2.7 at high overlap.
- **Do not ship selective federation as a headline capability** on this evidence. It is the best policy at every overlap, but by 0.3–1.1 points — below what this experiment can distinguish from the simpler alternative of choosing a fixed policy by overlap.
- **The federation module ships regardless.** Its guarantees — the recipient decides, imports arrive unvalidated, provenance crosses — are governance properties, not performance claims, and they do not depend on H3.
- **Re-register as H3b with a ceiling-aware threshold.** The right form is a *share of headroom* ("selective captures ≥ 50% of the oracle's gain at intermediate overlap"), not an absolute margin, because an absolute margin cannot be set honestly before the ceiling is known. H3b should also include the untested "estimate overlap, then pick a fixed policy" arm, which may dominate the whole approach.
