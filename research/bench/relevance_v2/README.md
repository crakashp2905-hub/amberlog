# relevance_v2

The benchmark v1 and SciFact both said was needed. **v1 is frozen and stays
frozen** — this is a new directory, not an edit, because a benchmark that
changes under its own results is not a benchmark.

## Why

Two runs said the same thing about v1 and neither was looking for it.
[SciFact](../../results/scifact-external.md) showed v1 flattering the hashing
embedder by a factor of four in the size of the gap. [R6](../../results/r6-downstream.md)
measured perfect selection as worth **+0.000** downstream on its frozen split,
because a model handed 19 memories answered as well as one handed the correct 3.
Neither is a verdict on retrieval. Both are verdicts on a corpus a model can
simply read, with distractors chosen to be obviously wrong.

## What changed, and nothing else

| | v1 | v2 |
|---|---|---|
| memories per case | 18 | **~495**, and ~1,895 for `budget_pressure` |
| approximate prompt tokens for the whole corpus | ~300 | **~6,600**, and ~25,000 for `budget_pressure` |
| distractors | 15 shared depot facts, deliberately off-topic | every statement of the asked predicate, **one facet changed** |
| longest evidence chain | 2 hops | **4 hops**, with no direct statement of the asked quantity anywhere |
| unanswerable cases | 3 | **6**, each surrounded by its own neighbours |
| labels | relevant / critical / irrelevant / must-not-expose | the same, plus **`requirements`** (evidence slots) and **`stale`** (active memories with a retracted root) |
| cases | 50 | 66, eleven families of six |

The near-miss mechanism is the one that matters. Each fact is a predicate at a
facet tuple — `tyre_pressure(unit=crane-5, site=coastal, season=winter)` — and
every distractor on the asked topic is that same sentence with exactly one
facet changed and a **different value**. One discriminating token in twelve,
every other token shared.

## Families

| family | ×6 | what it is for |
|---|---|---|
| `direct` | | the asked tuple is stated once; neighbours are one facet away |
| `facet_trap` | | *every* statement of the predicate is one facet away. Vocabulary cannot narrow it |
| `multi_hop_3` | | bay → vehicle → axle set → pressure rule. No direct statement exists |
| `multi_hop_4` | | the same, plus a site margin applied on top, so the answer needs arithmetic |
| `superseded_rev` | | two statements of one tuple, separated only by validity interval |
| `unanswerable` | | the tuple is absent and all its neighbours are present |
| `conflicting` | | two standing sources disagree; the defensible answer needs both |
| `gated` | | the only answer is capability-gated, so abstention is correct and sufficiency is zero |
| `shared_root` | | four apparent supports, all derived from one retracted survey |
| `independent_support` | | three derived from the retracted survey, one not. Blanket invalidation gets this wrong |
| `budget_pressure` | | `direct` at ten times the size, so the full-context baseline has a price |

`shared_root` and `independent_support` are a matched pair with identical
surface and opposite correct answers. They exist for the correction-propagation
question rather than to make retrieval harder.

## Building it

```bash
python -m research.bench.relevance_v2.build
```

The split JSON is **generated, not committed** — 12.4 MB each — and
`MANIFEST.json` carries the SHA-256 of both. `tests/test_relevance_v2.py`
rebuilds and compares, which is a stronger reproducibility claim than
committing the bytes: it asserts the generator still produces them. (v1 commits
its JSON; it is 50 small cases. This repository has also committed 7.8 MB of
SciFact while its own documentation said it had not, which is the other reason.)

Running it:

```bash
python -m experiments.relevance_bench --benchmark relevance_v2 --split dev
```

`k` defaults to **5** here against v1's 3, because a 4-hop chain needs four
slots and a smaller `k` would score a perfect selection as a miss — the oracle
would be handicapped, which principle 8b forbids.

## What it found in its first week

Four things, three of them defects in the thing being measured rather than
results about it. Recorded because a benchmark's first job is to catch what the
previous one could not.

1. **It leaked its own answers 185 times.** Three separate causes: an
   axle-pressure rule that repeated a value at a different (axle, season); the
   key `"4 tonnes"` matching `"14 tonnes"`; and a bare `"14"` matching
   `forklift-14`. Each would have graded a wrong retrieval as a correct answer.
   Fixed with a **generator assertion** rather than three repairs — a case whose
   answer key matches something it labels irrelevant does not get built.
2. **The grading rule had to change.** R6 graded by plain substring, which on
   this corpus is not merely crude but wrong. `key_matches()` in the generator
   is boundary-aware, exported, and is the same function the guard uses, so the
   grader cannot disagree with the proof that the corpus holds no other match.
3. **Its own provenance edges were absent.** v1 writes `parents` as
   `[[id, weight]]` pairs; v2 wrote bare strings, the harness reads `p[0]`, so
   every parent resolved to a single character, matched nothing, and the store
   recorded each derived memory as its own source root. The two families built
   for correction propagation had no derivation structure, and `store_roots`
   was identical to `store_plain` on all twelve — which read as a finding about
   the mechanism and was a defect in the fixture. Now guarded by a schema
   assertion.
4. **`broken_no_signal` scores 0.000.** On v1 the same arm scored 0.843, then
   0.869 before the shuffle, because with `k` near the corpus size ranking
   cannot be wrong. At ~495 memories returning storage order is worth nothing,
   which is the property that makes the rest of the numbers mean anything.

## What it does not establish

- **The labels are still mine.** v2 is harder, not independent, and nothing
  here replaces SciFact as the only external check in this project.
- **The text is generated from templates.** That buys controlled near-misses
  and costs surface diversity; a method could in principle exploit the template
  grammar rather than the semantics. The broken arms are the check, and there
  is more than one phrasing per topic.
- **"One facet apart" is an assumption about difficulty, not a proof of it.**
  The evidence that it worked is the measured gap between a no-signal arm and a
  real one, which the harness reports on every run.
- **Six cases a family, three a split.** Every per-family number is three
  cases. Family-level differences are directions, not estimates.
- **The test split is unopened.** Every number in
  [relevance-v2-ceiling.md](../../results/relevance-v2-ceiling.md) is dev.
