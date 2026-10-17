# X6 — a memory one small model writes is as useful to another as to itself

**PORTABLE.** Across three model families, the diagonal interaction — how much
better a model does on memories *it* wrote, beyond being a good reader and a
good writer — is **D = −0.002, 95% CI −0.016 to +0.012**, entirely inside the
registered equivalence margin of ±0.05. As an own-memory bonus that is
**−0.003 [−0.024, +0.018]** (D = b(n−1)/n, the registration's first
amendment), inside its ±0.075 margin.

Registered in [x6-cross-model-portability.md](../prereg/x6-cross-model-portability.md)
before the harness existed, with two amendments made before the registered run.
Produced by `python -m experiments.x6_cross_model --seeds 5 --episodes 24` at
commit `3bc03af` on the local line that was later integrated (preserved as
branch `archive/local-main-2026-10-15`). The checks it imports moved to
`memeval.checks` between the run and this write-up, unchanged. Raw numbers:
[x6-run.json](x6-run.json); per-episode records: [x6-cache.json](x6-cache.json);
secondaries recomputed from them by `python -m experiments.x6_secondary`:
[x6-secondary.json](x6-secondary.json).

- `qwen2.5:3b`, `llama3.2:3b`, `gemma3:4b`, local through Ollama, CPU only.
- 5 seeds × 24 evaluation episodes = **120 paired units**; every cell of the
  3 × 3 matrix and the oracle row is scored on the same units.
- 1,710 model calls. Wall time 41,055 s, of which **32,014 s is one cell that
  ran across a machine sleep** (seed 4, `llama3.2:3b` reading `qwen2.5:3b`);
  its result is cached per episode like every other cell, so the sleep cost
  time and changed nothing.

## 1. The matrix

Task success, reader (row) by writer (column):

| reader \ writer | `qwen2.5:3b` | `llama3.2:3b` | `gemma3:4b` | oracle |
|---|---|---|---|---|
| `qwen2.5:3b` | **0.583** | 0.550 | 0.608 | 0.650 |
| `llama3.2:3b` | 0.592 | **0.575** | 0.600 | 0.633 |
| `gemma3:4b` | 0.608 | 0.575 | **0.600** | 0.733 |

No diagonal cell stands out from its row or column, and that is what D
measures: the diagonal against what the reader and writer effects predict.

| | reader effect | writer effect | own-site-correct lessons |
|---|---|---|---|
| `qwen2.5:3b` | −0.007 | +0.006 | 0.844 (of 90) |
| `llama3.2:3b` | +0.001 | **−0.021** | 0.833 (of 84) |
| `gemma3:4b` | +0.006 | +0.015 | 0.844 (of 90) |

## 2. Checks

- **8b, no arm above its ceiling: passed.** No cell exceeds its reader's
  oracle. The pilot (1 seed × 8 episodes) had three cells above it by one
  episode each, which prompted the second amendment: if it recurred, §2's
  claim that the oracle bounds everything a writer contributes would be
  withdrawn. It did not recur at 120 units, so the claim stands and the
  pilot's excesses read as the noise a one-episode difference at n=8 is.
- **Power: PORTABLE was reachable.** The realised CI half-width on D is
  **0.014**, against the margin of 0.05 it had to fit inside; the registration
  required this to be reported so that INCONCLUSIVE could not be read as a
  soft yes. It did not need to be.
- **Retrieval is independent of the reader**, checked rather than assumed:
  for every seed and writer, `right_in_context` is identical across the three
  readers, as it must be when the query and the index are the same.

## 3. Predictions

| | prediction | outcome |
|---|---|---|
| 1 | PORTABLE, or INCONCLUSIVE leaning that way | ✅ PORTABLE |
| 2 | The writer effect is larger than the diagonal interaction | ✅ writer effects span 0.036 (−0.021 to +0.015); \|D\| is 0.002 |
| 3 | `llama3.2:3b` is the weakest writer | ✅ −0.021, and the fewest lessons (84 of 90) and the lowest own-site correctness (0.833) |
| 4 | If portability fails, retrieval differs more than reading | not tested as stated — portability did not fail. The decomposition is in §4 and points the same way |

## 4. Where the differences that do exist come from

The registration asked for retrieval overlap and per-cell conversion so that
*wrote it wrong*, *wrote it in a way that retrieves badly* and *read it badly*
could be told apart.

| corpus | correct lesson in context | agreement with the other writers |
|---|---|---|
| `qwen2.5:3b` | 0.625 | 0.975 with gemma, 0.942 with llama |
| `llama3.2:3b` | 0.617 | 0.967 with gemma, 0.942 with qwen |
| `gemma3:4b` | 0.650 | — |
| oracle | **0.700** | — |

**Conversion** — success given a correct lesson in context — is 0.86 to 0.96
in every cell, the oracle's included (0.89 to 0.96). It is not higher on the
diagonal: a model converts a correct lesson from another family's prose as well
as from its own.

So the oracle's lead over the model-written corpora — 4.4, 7.0 and 13.9 points
over the mean of each reader's three model-written cells (llama, qwen, gemma) —
is mostly **retrieval**: perfect, uniformly phrased lessons get the right one
into context 70% of the time against 62–65% for any model's. Conversion given
retrieval is the same 0.9 seen in every DepotWorld phase since Phase A. The
same channel that explained Phase A explains this, and the writer-specific part
of it is small: the corpora agree on retrieval in 94–98% of units.

## 5. Cost

Reading, by reader, median seconds per 24-episode cell: `qwen2.5:3b` **88**,
`llama3.2:3b` **96**, `gemma3:4b` **167**. Totals are distorted by the one
cell that spanned a sleep and are in the JSON with their maxima.

**Not reported: writing cost per writer**, which the registration listed. The
harness cached each cell's reading time but not the time spent writing each
corpus, so it cannot be recovered without rerunning the writers. Said here
rather than estimated.

## 6. What this changes, and what it does not establish

**For the product:** one store can serve several model families without
recording which model wrote a memory or translating on read, at least for
short factual lessons. Provenance still records the creating agent — for
accountability, not for portability.

**What it does not establish**, as the registration said in advance:

- **Nothing about frontier or large models.** Three small local models only.
  The asymmetric case — a small model reading a large model's memories, or
  the reverse — is the one real systems have, and it is the obvious next
  experiment. It needs an API model, which this environment's local runs do
  not have.
- **Nothing about long, nuanced or procedural memories**, where a model's
  phrasing has room to matter. DepotWorld lessons are one sentence:
  fault, site, action.
- **Nothing about embedding retrieval**, which may be more sensitive to a
  writer's style than lexical overlap.
- **Seed variance dominates everything here.** Per-seed success runs from
  0.25 to 0.79, against cross-model differences of a few points. The paired
  design is what makes the estimand precise anyway; a reader comparing raw
  cells across seeds would see mostly the seed.
