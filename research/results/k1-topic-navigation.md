# K1 — does entering through a topic find what search misses?

Registered in [k1-topic-navigation.md](../prereg/k1-topic-navigation.md). Produced by
`experiments/k1_navigation.py --limit 60` at commit `539ba81` in CI (workflow `k1-eval`,
run 40446593038). Raw numbers in [k1-topic-navigation.json](k1-topic-navigation.json).

| arm | turn recall@10 | p50 latency |
|---|---|---|
| lexical (baseline, measured in the same job) | 0.768 | 11.4 ms |
| nav (open best two topics, rank inside) | 0.476 | 31.6 ms |
| nav+lexical (RRF) | 0.729 | 16.5 ms |
| oracle | 1.000 | — |

| K1a nav+lexical ≥ 0.826 and gain > 0 in 5/5 resamples | K1b p50 ≤ 250 ms | no arm above oracle |
|---|---|---|
| **fail** (gains −0.053, −0.004, +0.002, −0.073, +0.008) | pass | pass |

**Reading.** On LongMemEval the topic tree does not help a retriever find evidence: opening
topics loses evidence that sits in the wrong topic, and fusing with search dilutes rather
than adds. No retrieval-quality claim is made for navigation. As registered, the
`browse_topics` / `open_topic` tools ship anyway, opt-in (`--extended-tools`), as a way for
an agent or person to see *what is there*; they are not a recall improvement.
