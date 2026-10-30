# Usability study kit (blueprint §11.2 #12, gap G9)

Ready to run with 5–8 developers who have not worked on Memory Fabric. The
sessions themselves need people; everything else is here. Nothing in this kit
collects personal data beyond a participant code.

## Who

Developers who have built at least one LLM agent or RAG application, in two
groups: (A) application developers, (B) platform/operations engineers. Not
anyone who has read this repository's code.

## Setup (per participant, 10 minutes before)

```bash
python -m venv mf-study && mf-study/Scripts/activate   # or bin/activate
pip install memory-fabric        # or the wheel from the release bundle
```

A fresh terminal, the README open in a browser, nothing else. No
help from the moderator except "what would you try next?".

## Tasks (time-boxed, success defined in advance)

| # | task given to the participant | success | limit |
|---|---|---|---|
| T1 | "Store two facts about a pump and retrieve one." | a retrieve returns the fact | 10 min |
| T2 | "Find out where a stored fact came from." | names the author and how it was written (`show` or `explain`) | 8 min |
| T3 | "The first fact was wrong. Withdraw it and check nothing still uses it." | quarantined; derived memory shown as contested; uses the preview | 12 min |
| T4 | "Show what an agent was given for the question 'pump pressure', and what was left out." | runs `context build`, reads the receipt | 10 min |
| T5 | "Propose a change on a branch and see what a merge would do, without changing main." | branch created, merge preview read, main unchanged | 12 min |
| T6 | "Is it safe to use this memory in an action right now?" | uses `verify`/the action gate, or explains the status labels' limits | 8 min |

## What to record (sheet per participant)

- Participant code, group, minutes per task, success yes/partial/no.
- First command tried; every doc page opened; every error seen, verbatim.
- After each task, 1–5: "How sure are you it did what you wanted?"
- At the end, the System Usability Scale (10 standard items) and three open
  questions: what confused you most; what you expected to exist and didn't;
  would you trust it with production memory, and why not.

## Metrics (from blueprint §11.3 "Product")

Time to first success (T1), task completion rate per task, errors per task,
documentation success (solved from docs alone), SUS mean, and confidence
calibration (confidence vs actual success).

## Analysis

Report per task, not only averages; quote errors verbatim; file one issue per
distinct confusion with the participant codes that hit it. Five participants
find most severe problems; do not report percentages from fewer than five.

## Consent text (read aloud)

"We are testing the software, not you. The session is about 75 minutes. We
record your screen and your words, kept under a code, not your name, and
deleted after analysis. You can stop at any time."
