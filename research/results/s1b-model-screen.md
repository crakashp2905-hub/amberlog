# S1b — a model of the user's choice as the injection screen's second line

Registered in [s1b-model-screen.md](../prereg/s1b-model-screen.md). Produced by
`python -m experiments.s1b_model_screen` at commit `b279848`, models through the `claude` command
line; raw counts in [s1b-model-screen.json](s1b-model-screen.json). The model is asked only where
the text screens are silent, with the existing, untuned prompt.

| arm | deepset test caught | deepset benign flagged | held-out caught | held-out hard negatives flagged | ordinary conversation flagged |
|---|---|---|---|---|---|
| `text` (shipped) | 20 / 60 | 0 / 56 | 10 / 12 | 0 / 16 | 0 / 500 |
| `text+haiku` | 31 / 60 | 0 / 56 | 12 / 12 | 2 / 16 | 0 / 500 |
| `text+sonnet` | **42 / 60** | 0 / 56 | **12 / 12** | 0 / 16 | 0 / 500 |
| `oracle` | 60 / 60 | 0 / 56 | 12 / 12 | 0 / 16 | 0 / 500 |

| arm | S1b-a ≥ 40 / 60 | S1b-b benign ≤ 3 / 56 | S1b-c held-out ≥ 10/12, ≤ 1/16 | S1b-d conversation ≤ 1% |
|---|---|---|---|---|
| `text+haiku` | fail (31) | pass | fail (2 / 16) | pass |
| `text+sonnet` | **pass** | pass | pass | pass |

**Reading.** Sonnet behind the text screens catches 42 of 60 third-party injections (from 20) and
every held-out one, and flags nothing it should not: no benign deepset text, no hard negative, none
of 500 ordinary conversation turns. Haiku more than halves the gap on recall less well (31) and
flagged two hard negatives written to look like injections. As registered, Sonnet may be
recommended **as an opt-in**: it is a model call on every write the text screens pass, and sends
that text to the provider the user chose. Cost per write was not measured here (the command line
does not report it); `models.CallLog` records it for any API provider.

**Limits.** One run each. The third-party set is chat injections, not poisoned memories; the
held-out set and its labels are the author's. Other models are not measured; the same screen runs on
any provider `models.py` supports.
