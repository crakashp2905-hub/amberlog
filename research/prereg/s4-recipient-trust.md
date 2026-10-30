# Pre-registration — S4: can a recipient learn whom to trust, where, from its own outcomes?

**Registered 2026-10-18, after a dev pilot (seeds 100–102) and before the test
seeds (0–9).** This is research direction S4 in
[WORKPLAN.md](../../docs/WORKPLAN.md), registered against Phase B's PB1. PB1
was killed: selective sharing by the sender's estimated transferability did
not beat sharing all or none, and the worst agent fell. Mechanism:
`memory-fabric/trust.py` (and `exposure.TransferGatePolicy` as a secondary
arm). Harness: `experiments/s4_transfer_sim.py`.

**Disclosed: the dev pilot changed the mechanism.** The first mechanism was
the store's own per-memory, context-specific contrastive estimator behind a
gate that withholds confidently harmful imports. At this budget (about 10
visits per memory and context) it stayed "unknown" almost everywhere. It
scored 0.494 against a default of 0.502 and cut harmful reliance only from
0.53 to 0.46. Transferability is mostly a property of the sender and the
context, so the registered mechanism pools at that grain: a Beta posterior per
(origin store, context) over the recipient's own verified outcomes when it
relied on that origin, against its own default, chosen by Thompson sampling.
The per-memory arms stay as secondary arms, so the pilot's result is tested
again on test seeds rather than dropped.

## 1. Question

Without importing the sender's value score, can a recipient learn from its
own verified outcomes which senders' imports to rely on in which of its
contexts? And can it do that well enough to beat the default and every
sender-trusting baseline, with less harmful reliance than any baseline that
uses imports, while the context changes underneath it?

## 2. Design (TransferSim)

Per seed:

- **Contexts and lessons.** 3 recipient contexts. 20 faults, each with 2
  lessons from 2 of 4 senders. The senders' overlap with the recipient's
  contexts runs from 0.95 for the generalist down to 0.2.
- **Validity.** A lesson has quality q ~ U(0.6, 1), which is its sender's home
  score. It is valid in context c with probability q × overlap.
- **Outcomes.** Relying on a valid lesson succeeds with p 0.95, on an invalid
  one with p 0.05. The default action succeeds with p 0.5.
- **Episodes.** 600, with a random (context, fault) each.
- **Drift.** At episode 300, every lesson's validity in context 2 is drawn
  again.

Lessons are written at 4 real sender stores and arrive by federation.
Outcomes are paired: one draw per episode, shared by every arm.

## 3. Arms

| arm | relies on |
|---|---|
| `trust_none` | nothing: always the default |
| `trust_all` | the most relevant import (the store's top-1) |
| `sender_value` | the import its sender scored highest (q) |
| **`recipient_trust`** | S4: Thompson sampling per (origin, context) against the default |
| `recipient_local` | secondary: per-memory DR estimate + `TransferGatePolicy`, contextual |
| `recipient_pooled` | secondary: the same, context-blind |
| `oracle` | a valid import if one exists, else the default |

**Ceiling and baselines on dev (8a, 8c, 8d).** The metric is success, at the
same decision and the same candidates:

| arm | success |
|---|---|
| `trust_none` | **0.502** (best baseline) |
| `trust_all` | 0.479 |
| `sender_value` | 0.481 |
| `oracle` | 0.829 |

No baseline maxes the metric; the headroom is 0.327. The test run measures
its own baseline and ceiling, and the verdict uses those.

## 4. Metrics

- **Primary: success rate.**
- **Harmful reliance:** the share of episodes relying on an import that is
  invalid there.
- Success and harm before and after the drift.

## 5. Hypotheses

- **S4a.** `recipient_trust` closes **at least 40%** of the headroom between
  the best baseline and the oracle on success. `memeval.Registration` applies,
  with 10 seeds and the realised MDE reported.
- **S4b.** Its harmful reliance is **lower than every baseline that uses
  imports** (`trust_all`, `sender_value`). `trust_none` relies on nothing, so
  it is excluded by construction.

## 6. Predictions

1. **S4a is a coin flip.** Dev closed 39%. S4b holds: dev 0.24 against 0.53.
2. The sender's score is worth nothing here: `sender_value` ≈ `trust_all`.
   Its score describes the sender's home, and that is the point of the
   design.
3. The per-memory arms stay at or below the default at this budget, as in
   the pilot. Context-specific beats context-blind by less than 0.01.
4. After the drift, `recipient_trust` recovers slowly in context 2. Its
   posteriors are cumulative, with no forgetting. Its post-drift advantage
   over the default is smaller in context 2 than in contexts 0–1.

## 7. What this would not establish

A simulator with known overlap structure that I wrote. The grain (sender ×
context) is the one the world was generated with. A world where validity
varies lesson by lesson within a sender would favour the per-memory arms, and
is not tested here. No model.
