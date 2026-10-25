# C3 — a model-backed check for free-text claims

Registered in [c3-free-text-claims.md](../prereg/c3-free-text-claims.md) before the harness
existed. Produced by `python -m experiments.c3_free_text` at commit `36d9027`; raw numbers in
[c3-free-text.json](c3-free-text.json). Seeds (1, 2, 3, 4, 5); 32 new claims a seed, each written to a
fresh store holding 24 established free-text facts. Models through the `claude` command line.


Share of each kind of new claim **held for review** (contradictions should be; nothing else
should be), mean over seeds, and model cost per checked write:

| arm | contradiction | paraphrase | new detail | other place | cost a write |
|---|---|---|---|---|---|
| `structural` | 0.00 | 0.00 | 0.00 | 0.00 | $0.00000 |
| `haiku` | 1.00 | 0.00 | 0.00 | 0.20 | $0.00037 |
| `sonnet` | 1.00 | 0.00 | 0.00 | 0.17 | $0.00670 |
| `oracle` | 1.00 | 0.00 | 0.00 | 0.00 | $0.00000 |

| arm | C3a recall ≥ structural + 50% of headroom | C3b false holds ≤ 0.10 | C3c both, ≥ 4 of 5 seeds |
|---|---|---|---|
| `haiku` | pass | pass | pass |
| `sonnet` | pass | pass | pass |

**Reading.** Both models held every contradiction and never held a paraphrase or a new detail.
Their false holds all came from the hardest kind: a claim worded as a contradiction ("the archive
is closed to everyone") about a place with no established fact, which the model sometimes read as
contradicting a similar fact about another place. Haiku costs about a twentieth of Sonnet a write
for the same result here. Opt-in, as registered: every checked write is a model call, and content
goes to the provider the user chose.
