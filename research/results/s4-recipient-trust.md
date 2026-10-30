# S4 result — recipient-specific trust: **SUPPORTED, on the bar** (S4a), **SUPPORTED** (S4b)

Registration: [prereg/s4-recipient-trust.md](../prereg/s4-recipient-trust.md)
(`aae4e57`, after a disclosed dev pilot that changed the mechanism).
Mechanism: `memory-fabric/trust.py`. Run: `python -m experiments.s4_transfer_sim
--split test`, in a worktree pinned at `aae4e57`. Seeds 0–9, 600 episodes
each, 6,000 paired episodes per arm. Deterministic, no model. Raw output:
[s4-transfer-sim.json](s4-transfer-sim.json).

**S4a: SUPPORTED, and only just.** `recipient_trust` closes **40.04%** of the
headroom, against a registered 40%: 0.6360 against a bar of 0.6359. The paired
gain over the best baseline is +0.130, CI +0.117 to +0.144. The pass needed
+0.1299, so the interval contains values on both sides of the bar. Under the
registered rule this is a pass, and it carries no margin; a different set of
seeds could have gone either way. The registration predicted a coin flip.
The realised MDE was 0.020, so the test was not underpowered. The effect sits
almost exactly at the bar.

**S4b: SUPPORTED.** Harmful reliance is 0.231, against 0.490 for
`sender_value` and 0.521 for `trust_all`.

## Results (test, 10 seeds)

| arm | success | harmful reliance | before drift | after drift |
|---|---|---|---|---|
| `trust_none` | 0.503 | 0 | 0.497 | 0.508 |
| `trust_all` | 0.480 | 0.521 | 0.479 | 0.481 |
| `sender_value` (best baseline) | 0.506 | 0.490 | 0.505 | 0.507 |
| **`recipient_trust`** (S4) | **0.636** | **0.231** | 0.613 | 0.659 |
| `recipient_local` (per-memory, contextual) | 0.497 | 0.451 | 0.485 | 0.508 |
| `recipient_pooled` (per-memory, context-blind) | 0.500 | 0.446 | 0.491 | 0.508 |
| `oracle` | 0.831 | 0 | 0.825 | 0.836 |

No arm beats the oracle.

After the drift, by context:

| arm | contexts 0–1 | context 2 (drifted) |
|---|---|---|
| `recipient_trust` | 0.657 | 0.662 |
| `trust_none` | 0.494 | 0.537 |
| `oracle` | 0.820 | 0.870 |

## Predictions: all four held

1. *A coin flip on S4a; S4b holds.* **Held**: 40.04%, and 0.23 against 0.49.
2. *The sender's score is worth nothing here.* **Held, nearly.** It beats
   trusting every import by 0.026 and the default by 0.003. Its harmful
   reliance (0.49) is twice the recipient's own.
3. *Per-memory arms at or below the default; context-specific beats
   context-blind by less than 0.01.* **Held**: 0.497 and 0.500 against 0.503,
   and a difference of −0.003. **At about 10 visits per memory and context,
   the store's contrastive estimator learns nothing usable.** That is the
   pilot's finding, now reproduced on test seeds.
4. *Slower recovery in the drifted context.* **Held, weakly.** After the
   drift, the advantage over the default is +0.126 in context 2 against
   +0.163 elsewhere. The gap to the oracle is 0.21 against 0.16. The
   posteriors have no forgetting.

## What was learned

- **A recipient can learn whom to trust, where, from its own outcomes.** It
  does so at the grain of the sender and its own context, without the
  sender's score, and halves harmful reliance. This is the question PB1 could
  not resolve. PB1 asked whether the *sender* could choose what to share;
  this asks whether the *recipient* can choose what to rely on.
- **The grain is the finding.** The same evidence kept per memory gives
  nothing at this budget. Pooled by sender × context, it gives +0.13.
- **The world was generated at exactly that grain**, so this result is the
  favourable case for pooling. A world where validity varies lesson by lesson
  within one sender would favour the per-memory arms, and was not tested.
- **Not wired in.** `trust.py` is opt-in. A pass on the bar, in a simulator,
  is not the evidence AGENTS.md principle 9 asks for before it changes what
  every recipient does.

## What this does not establish

A simulator I wrote, with known overlap structure. No model. A one-shot
drift. No forgetting was tested, and none was registered.
