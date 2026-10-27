# INT-01 — MemoryWorld 2: true at t vs believed at τ (descriptive)

Produced by `python -m benchmarks.memoryworld2` at commit `8fde780d6ab6`; seeds 1, 2, 3, 4, 5;
20 facts × 3 validity periods, 30% recorded wrong and corrected later, recordings
in shuffled order. 60 questions of each kind per seed. No model; no claim registered.
Raw numbers: [int01-memoryworld2.json](int01-memoryworld2.json).

| question | overwrite | valid time (`retrieve(as_of=t)`) | bitemporal (replay to τ, then at t) | oracle |
|---|---|---|---|---|
| value at t, as known now | 0.313 | 1.000 | 1.000 | 1.000 |
| value at t, as believed at τ | 0.113 | 0.513 | 1.000 | 1.000 |

## Reading

Valid-time retrieval answers "what was true at t" from the product path. "What did the store
believe at τ" needs the log replayed to τ, which only `incident.replay_until` does today; there is
no `retrieve(known_at=τ)`. That API is the open RQ3 work item, and this harness is its acceptance
test. Overwrite (one value per fact) is the baseline that loses both questions once facts change.
