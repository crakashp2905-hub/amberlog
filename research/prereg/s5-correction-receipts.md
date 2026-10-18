# Pre-registration — S5: a correction receipt that reveals nothing but the correction

**Registered 2026-10-18, after a one-seed dev pilot (seed 100) and before
seeds 0–4.** This is research direction S5 in
[WORKPLAN.md](../../docs/WORKPLAN.md). Mechanism: `memory_fabric/receipts.py`.
Harness: `experiments/s5_receipt_leakage.py`. Both are committed with this
file. The pilot changed nothing in either.

## 1. Question

A recipient tells the origin it enforced a retraction. Can it do so in a form
the origin cannot learn anything else from — its activity, how many copies it
held, who it re-shared to, what it built on the copy — while still being held
to the claim at audit?

## 2. What is compared

| what the origin receives | fields |
|---|---|
| `ack`: today's `Acknowledgement` | state, `state_revision` (the recipient's log head), `origin_sequence_seen`, `at`, `detail` (bounded free text: "N memory/ies withdrawn; forwarded to K peer(s)") |
| `receipt`: S5's `CorrectionReceipt` | ids, `state`, a 32-byte `commitment` to (local ids, apply sequence, chain digest) under a nonce only the recipient can derive, and a 32-byte HMAC `tag` |

## 3. Design

Five seeds, 30 recipients per seed, 150 in all. Each recipient draws four
private attributes:

| attribute | range |
|---|---|
| activity between two retractions | 0..300 events |
| copies held | 1..3 |
| onward peers | 0..3 |
| dependents | 0..3 |

Each recipient receives two retractions. The origin then infers each
attribute with the best of its attackers, every one of which sees every field
of what it received:

- **parse rules** written for the `ack` fields;
- **serialised length**;
- **the first byte of each hex field**.

Scoring is leave-one-out over the population: accuracy minus the
always-guess-the-commonest baseline for the categorical attributes, and R²
for activity.

**Soundness.** For each recipient:

- (a) an honest receipt must pass audit;
- (b) a forged commitment must fail;
- (c) a store that never applied the retraction can neither issue a receipt
  nor pass audit with someone else's;
- (d) a copy re-activated after the receipt must be reported.

## 4. Ceiling and validity

The oracle leaks nothing, so its advantage is 0. **Validity (8c analogue):**
the attack has to work on something. If `ack` shows advantage below 0.4 on
every one of activity, copies and peers, the attackers are too weak to show
anything and S5 is INVALID.

## 5. Hypotheses

- **S5a.** The best attacker's advantage against `receipt` is at most **0.05
  on every attribute**.
- **S5b.** Soundness checks (a)–(d) hold for **150/150** recipients.
- Reported, not registered: `ack`'s advantage per attribute.

## 6. Predictions

1. S5a and S5b hold.
2. `ack` leaks activity almost exactly (R² ≈ 1, from `state_revision`) and
   onward peers (from `detail`). It leaks copies held only partly, and
   dependents not at all: the detail line counts withdrawn copies, not
   contested conclusions.

## 7. What this would not establish

- **Timing.** The origin sees when a receipt arrives. That is the network,
  and it is out of scope.
- **Simple attackers only.** A learned attacker over many receipts is not
  tested. The receipt's fields are a hash and an HMAC, so the argument
  against one is cryptographic, not empirical.
- **Binding needs the chain digest to be trusted** at audit. Off-host
  checkpoints are the operator's job.
- **The receipt is opt-in.** Until the wire format carries it, the leak in
  `ack` is in every deployment. This experiment measures that leak.
