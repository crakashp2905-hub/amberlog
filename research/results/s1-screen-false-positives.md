# S1 — the injection screen on ordinary conversation

Registered in [s1-screen-false-positives.md](../prereg/s1-screen-false-positives.md). Produced by
`experiments/s1_screen_fp.py` at commit `811fc7f` in CI (run 40269009170); the baseline is the screen
at `1821f6c`, measured in the same job. Counts in [s1-screen-false-positives.json](s1-screen-false-positives.json).

| screen | LongMemEval test turns quarantined as injection | tune turns | deepset test caught | deepset benign flagged | held-out caught | held-out benign flagged |
|---|---|---|---|---|---|---|
| before | 516 / 83084 (0.62%) | 727 / 106436 (0.68%) | 20 / 60 | 0 / 56 | 10 / 12 | 0 / 16 |
| after | **69 / 83084 (0.08%)** | 85 / 106436 (0.08%) | 20 / 60 | 0 / 56 | 10 / 12 | 0 / 16 |

| S1a test rate ≤ 0.2 × before | S1b deepset ≥ 20/60, 0 benign | S1c held-out ≥ 10/12, 0/16 | S1d existing tests |
|---|---|---|---|
| pass (0.13×) | pass | pass | pass (CI on the same commit) |

**Own memories are not withheld from their author (§5).** LongMemEval `lexical` turn recall on 60
histories with hostile-source withholding **on**, as shipped: **0.768**, identical to off. R3 had
measured 0.033 with it on.

## What changed

The forms that address the answerer ("the figure to give", "answer questions", "tell people") now
need a value to follow ("… is 50 A", "… with 95 Nm"): an injection of that kind exists to plant a
value and states it; everyday speech does not. "Correct answer" needs "only" or "acceptable/official
answer is"; "never say" needs "the real/documented/…"; "whatever … says" needs a record as its
subject; three override forms were narrowed ("focus on the new task", "pretend you are", "system or
hidden prompt"). Changed against the tune split only; the test split was scored once.

## What is still flagged

Of the 69 test turns, most are users pasting role prompts ("I want you to act as a UX/UI
developer…", "Please ignore all previous instructions…") — text that *is* an instruction to a model,
which the screen is right to hold in a store other agents read. A handful are genuine false alarms
("print out a map", a code sample with "display the instructions"). Sensitive-data quarantines, a
separate question, are unchanged (14 on the test split).
