# Governed decay view (OptMem-inspired compression)

Pre-registration: [decay-view.md](../prereg/decay-view.md). Module:
`memory_fabric/decay.py`. Harness: `experiments/decay_eval.py`. Budget 300
estimated tokens for every arm; 32 assets, 160 notes per seed. Raw:
`decay-view.json` (registered, seeds 1–5), `decay-view-posthoc.json`
(repaired, same seeds), `decay-view-confirm.json` (repaired, seeds 6–10).
`any_arm_beats_oracle` empty on every run.

## Registered run (seeds 1–5): D1 and D2 not supported

| arm | current recall | stale answers | tokens |
|---|---|---|---|
| R newest records | 0.513 | 0.000 | 294 |
| X decay, extractive | 0.350 | 0.169 | 286 |
| S decay, stand-in agent summaries | 0.650 | 0.000 | 279 |
| oracle | 1.000 | 0.000 | 128 |

Diagnosis (by tracing individual answers):

- **Harness defect.** The reader searched past the end of a sentence, so in a
  summary "P6 inspected. P19 runs at 35 bar" read as P6 = 35. Every "stale"
  answer in X was this, not a withdrawn or superseded value. Fixed: the
  reader stays within one sentence or clause.
- **Design defect: corrections were buried.** The timeline ordered memories by
  their first version, so a revised fact stayed at its old position, inside
  the coarsest summaries. Fixed: ordered by the current version, as an
  append-only log appends a correction.
- **Design defect: chatter crowded out facts.** Extractive summaries quoted
  notes with no value ("logbook signed") and cut facts at the length cap.
  Fixed: the latest fact-bearing note per subject; the rest is counted.

## Replication of the repaired code (Addendum A, seeds 6–10)

| arm | current recall | stale answers | tokens |
|---|---|---|---|
| R newest records | 0.500 | 0.000 | 298 |
| X decay, extractive | 0.619 | 0.000 | 293 |
| S decay, stand-in agent summaries | 0.863 | 0.000 | 297 |
| oracle | 1.000 | 0.000 | 128 |

- **D1 not supported, narrowly:** X captured 0.21 of the headroom over R
  (0.00–0.39 by seed; bar 0.25). No stale answers on any seed.
- **D2 not supported, narrowly:** S captured 0.71 (0.45–0.80; bar 0.75). No
  stale answers on any seed.

## What this shows

At the same budget, a view that keeps recent notes whole and summarises
older ones carried **86% of current facts against 50%** for the newest
records alone when its summaries were fact-dense, and 62% with the
extractive summariser — with **no withdrawn or superseded value** reaching
the reader, because a summary is served only while every source is current
and readable. The registered bars were set before the repairs and were not
met; the gain over recency is large and consistent (S beat R on all ten
seeds after repair).

## Limits

S's summaries come from a rule standing in for an agent, not a language model;
whether a model writes summaries this dense is untested here (no API key in
this environment). Synthetic world, rule reader, query-independent view.
OptMem itself was not run or compared: it has no licence, and the comparison
here is to the baseline it improves on, recency truncation.
