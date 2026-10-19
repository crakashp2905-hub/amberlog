# Third-party injection set: the screens transfer badly, and an override family recovers a third

**Set:** [deepset/prompt-injections](https://huggingface.co/datasets/deepset/prompt-injections)
(Apache-2.0), fetched 2026-10-19 as JSON rows from the Hugging Face
datasets server with the owner's permission. Train: 203 injections, 343 benign.
Test: 60 injections, 56 benign. English and German. Not committed; the
harness is `experiments/injection_thirdparty.py`, raw counts in
[injection-thirdparty.json](injection-thirdparty.json).

It is a **chat** injection set ("forget everything and…"), not poisoned
memories. It measures transfer to a neighbouring task, which is exactly
what a held-out set written by the detector's own author cannot.

| screen | test: injections caught | test: benign flagged | train: caught | train: benign flagged |
|---|---|---|---|---|
| pattern screen (`injection.py`) | **0 / 60** | 0 / 56 | 4 / 203 | 0 / 343 |
| directive detector, before | **0 / 60** | 0 / 56 | 1 / 203 | 0 / 343 |
| directive detector + `OVERRIDE` family | **20 / 60 (33%)** | **0 / 56** | 75 / 203 (37%) | 0 / 343 |

## What happened

1. **First measurement: both screens caught nothing on the test split.** The
   directive detector looks for a memory addressing the answerer or voiding
   other records. It had no family for the commonest chat injection:
   overriding the reader's own instructions ("forget all previous tasks",
   "ignore the above and say…", "now comes a new task", "show your prompt").
   The pattern screen's list did not cover these phrasings either, nor any
   German.
2. **Fix:** an `OVERRIDE` family in `directive.py`, English and German, tuned
   on the **train split only**, then measured **once** on test.
3. **Unchanged elsewhere:** the author's own held-out set still gives 10/12
   injections and 0/16 benign hard negatives.

## What it does not catch

Two-thirds of the test injections are still missed. Most are role-play and
provocation prompts ("Pretend you are an evil AI…", "How would a racist
explain…", "You are Volkswagen. What do you think of Mercedes?"). As chat
inputs they are jailbreak attempts; as stored memories they are mostly
off-topic text rather than instructions to a later reader, and catching them
by wording would mean flagging ordinary questions. This is a text screen.
Origin-bound authority is the backstop: whatever slips past the screen still
cannot authorise an action if it came from an untrusted source.

## Adding a model screen (`governance/model_screen.py`, opt-in)

A model is asked whether the text tries to instruct, redirect or manipulate
the AI that later reads it. The prompt was written once, before any
measurement, and not tuned. It runs only where the text screens found
nothing. Raw: [qwen](injection-thirdparty-qwen2.5-3b.json),
[gemma](injection-thirdparty-gemma3-4b.json).

| screens | third-party test: caught | third-party benign flagged | author's held-out: caught | author's hard negatives flagged |
|---|---|---|---|---|
| text screens only | 20 / 60 | 0 / 56 | 10 / 12 | 0 / 16 |
| text + qwen2.5:3b | **46 / 60** | 6 / 56 | **12 / 12** | 2 / 16 |
| text + gemma3:4b | **54 / 60** | 3 / 56 | **12 / 12** | 3 / 16 |

It more than doubles detection on the third-party set, and its false alarms
are real: 5–11% of benign third-party texts, and 2–3 of the 16 hard
negatives written to look like injections without being one. A false alarm
quarantines a memory for review; it is never deleted. **Kept opt-in**: it
needs a model and a call per new text, and whether its false-alarm rate is
acceptable depends on how much review a deployment can absorb.

