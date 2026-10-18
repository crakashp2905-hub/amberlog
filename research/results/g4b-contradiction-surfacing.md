# G4b result — contradictions surfaced, not ranked away: **NOT SUPPORTED** at 40%, significant gains

Registration: [prereg/g4b-contradiction-surfacing.md](../prereg/g4b-contradiction-surfacing.md)
(`4af0a15`). Held-out seeds 5–9, never used by G4. qwen2.5:3b, with G4's
arms, prompt and k. 160 paired units before detection. Raw output:
[g4b-qwen.json](g4b-qwen.json).

The primary metric is safe success on attacked facts (poisoned, matched and
paraphrased injection, re-ingested) at stage 1, before anything has been
detected.

| arm | primary | acted on invalid | attack written first | honest written first | clean and corrected |
|---|---|---|---|---|---|
| `shared_store` | 0.188 | 0.813 | 0.162 | 0.207 | 1.000 |
| `shared_delete_all` | 0.188 | 0.813 | 0.162 | 0.207 | 0.983 |
| `fabric` (as shipped, best baseline) | 0.369 | 0.631 | 0.221 | 0.478 | 0.983 |
| **`fabric_flag`** | **0.450** | 0.550 | 0.265 | 0.587 | 0.988 |
| **`fabric_incumbent`** | **0.488** | **0.513** | **0.397** | 0.554 | 0.983 |
| `oracle` | 1.000 | 0 | 1.000 | 1.000 | 1.000 |

No arm beats the oracle.

## Verdicts

- **G4b-flag: NOT SUPPORTED.** It closes 13% of the headroom.
  +0.081 against `fabric`, CI +0.038 to +0.131, realised MDE 0.072.
- **G4b-incumbent: NOT SUPPORTED.** It closes 19% of the headroom.
  +0.119, CI +0.056 to +0.181, realised MDE 0.094.
- **Guard: holds.** Clean-and-corrected success is 0.988 and 0.983 against
  `fabric`'s 0.983.

## Predictions

1. *Both fail the 40% bar.* **Held.**
2. *Both beat `fabric`, and incumbent beats flag.* **Held.** Both intervals
   exclude zero.
3. *Incumbent's advantage shrinks when the attack is written first.*
   **Not as predicted.** Its success does fall when the attack comes first
   (0.397 against 0.554), but it still beats flag *most* there (0.397
   against 0.265). So the gain is not incumbency winning a race the attacker
   could have won: a poison written first is still listed first, marked
   disputed, and the model does better than with flag's ranked order. The
   presentation, a disputed pair kept together with one side marked as
   unconfirmed, is doing work beyond who wrote first. This is reported as
   observed; the registration did not test why.
4. *The guard holds.* **Held.**

## What this means for the product

- **The weakness is real and partly fixable without knowing which side is
  wrong.** Acting on an undetected poison falls from 63% to 51–55%.
- **It is not solved.** The oracle shows how far there is to go, and a
  small model given an explicit "disputed" pair still picks the wrong value
  about half the time. Contradiction surfacing narrows the window before
  retraction; it does not replace retraction or review.
- **Recommendation:** make contradiction flagging the default presentation.
  - It is a measured, significant safety gain with no measured cost on clean
    or corrected facts.
  - Use `flag`, not `incumbent`, as the default. `incumbent` scored higher
    here, but it encodes a bet an attacker can learn to win.
  - Route every detected conflict into the review queue, so that a person
    resolves it.
  - This needs the owner's decision (AGENTS.md principle 9): until then
    `conflicts.py` stays opt-in.
