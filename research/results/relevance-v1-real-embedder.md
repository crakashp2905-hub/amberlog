# A trained embedder against the hashing stub

**The embedder was the biggest single lever, bigger than every mechanism I
built — and the two splits disagree about how much bigger, which is now the
binding constraint on all of this.**

R1 said the hashing embedder was "the single biggest limitation of every number
here" and that a real model "might close most of the headroom with no new
mechanism". It was worth testing before building a ranker. It was.

- **Model:** `nomic-embed-text` (768-dim) via Ollama, through the existing `OllamaEmbedder`
- **Run:** 2026-10-11, `python -m experiments.relevance_bench --arms real_vector real_hybrid …`
- **Benchmark:** `relevance_v1`, unchanged — same cases, same labels, same `k=3`, same gates

---

## 1. The numbers

| arm | dev nDCG | dev crit. omission | test nDCG | test crit. omission |
|---|---|---|---|---|
| `vector` (hashing) | 0.728 | 0.286 | 0.485 | 0.400 |
| `lexical` | 0.778 | 0.286 | 0.804 | 0.200 |
| `hybrid` (shipped default) | 0.752 | 0.214 | 0.732 | **0.000** |
| `store_all` (all three mechanisms) | 0.795 | 0.143 | 0.732 | **0.000** |
| **`real_vector`** | **0.933** | **0.071** | 0.802 | 0.400 |
| **`real_hybrid`** | 0.879 | 0.143 | **0.849** | 0.200 |
| `oracle` | 1.000 | 0.000 | 1.000 | 0.000 |

**On dev**, `real_vector` closes **0.155 of the 0.222 headroom — about 70%** —
and takes critical-memory omission from 0.286 to 0.071. That is more than every
mechanism in this project combined: `store_all`, with bitemporal filtering,
source-root grouping and premise promotion, reached 0.795.

**On the frozen test split it closes +0.045** over `lexical`, and the best arm
is `real_hybrid` at 0.849.

## 2. The splits disagree, and 5 cases cannot settle it

Stated before the headline is repeated anywhere else:

| | dev says | test says |
|---|---|---|
| best arm | `real_vector` 0.933 | `real_hybrid` 0.849 |
| fusing lexical with the real embedder | **hurts** (0.933 → 0.879) | **helps** (0.802 → 0.849) |
| real embedder vs `lexical` | +0.155 | +0.045 (within noise at n=5) |
| real embedder's critical omission | 0.071, best of any arm | 0.400, **worse** than `hybrid`'s 0.000 |

The test split is **five cases**. It cannot separate 0.849 from 0.804, and the
direction of the fusion question flips between splits. So the claim this
licenses is narrow:

> A trained embedder is clearly better than the hashing stub. **How much
> better is not established**, and whether to fuse it with lexical retrieval is
> not established either.

Sample size is now the binding constraint on every comparison in this
benchmark — more than any mechanism, and more than the ranker R2 was going to
build. That is the next thing to fix.

## 3. Where it wins, and where it loses

Per-family nDCG on dev. The interesting column is the comparison with
`store_all`, because those mechanisms were built *for* these families.

| family | `lexical` | `store_all` | `real_vector` |
|---|---|---|---|
| `rare_critical` | **0.000** | 0.387 | **0.920** |
| `temporal_drift` | 0.500 | 0.631 | **1.000** |
| `lexical_trap` | 0.631 | 0.500 | **1.000** |
| `indirect` | 0.613 | **1.000** | **1.000** |
| `near_duplicate` | 0.613 | 0.307 | **0.920** |
| `copied_evidence` | 0.613 | 0.387 | 0.613 |
| `apparent_conflict` | **0.920** | **0.920** | 0.693 |
| `constrained` | **1.000** | **1.000** | 0.920 |

**Three things here are uncomfortable and belong in the record.**

**It matches premise promotion on `indirect` without any lineage mechanism.**
Both reach 1.000. The conclusion and its premise are semantically close enough
that a real embedder simply retrieves both — so the lineage walk, bounded and
tested and measured at +0.034 on its own, bought on this benchmark what a
better embedder buys for free. The mechanism is still the only thing that works
when a premise shares no *meaning* with the task, and nothing here tests that
case.

**Root grouping is worse than doing nothing on two of the families it targets.**
`store_all` scores 0.387 on `copied_evidence` and 0.307 on `near_duplicate`,
against `lexical`'s 0.613 on both. Grouping improves those families relative to
plain hybrid — the test asserting that still holds — but plain hybrid is itself
the weaker starting point, so the comparison that matters was never made. I
measured the mechanism against the wrong baseline.

**The real embedder is worse on `apparent_conflict` and `constrained`.** It
over-matches on semantics: given "safe at 20 °C" and "not rated below 5 °C" it
cannot tell which scope the task selected, and it does not respect an explicit
constraint the way token overlap does. These are exactly the two families where
`lexical` is strongest, which is the honest argument *for* fusion — and the
dev split says fusion hurts overall. Unresolved.

## 4. The product recommendation, and why the default does not change

**The hashing embedder stays the default.** Zero runtime dependencies in the
core is a stated commitment ([AGENTS.md](../../AGENTS.md), `pyproject.toml`) and
`OllamaEmbedder` needs a running service. A default that silently requires one
would break the installs-anywhere property the project has tested in CI since
P1.

**It is one line to switch**, and the numbers above are the argument:

```python
from amberlog.adapters.ollama import OllamaEmbedder
fabric = Amberlog("memory.db", embedder=OllamaEmbedder())
```

Cost, now measurable because it was not: embedding calls go through the one
client wrapper and land in `usage()` like any completion. They did not before —
`OllamaClient.embed` posted and returned without recording a `CallRecord`, so
an embedder billed invisibly, which is the easiest way to make a retrieval
result look cheaper than it is. ~23 prompt tokens and ~0.16 s for a warm batch
of three here; the embedder caches, so a store pays once per distinct text.

## 5. What this does not establish

1. **No downstream claim.** Still retrieval metrics. nDCG is not task success and R6 has not run.
2. **One embedding model, one benchmark, 20 cases.** Another model could be better or worse, and §2 is the reason not to read the dev figure as the result.
3. **Nothing about a ranker.** The headroom left after `real_hybrid` on test is +0.151, and whether a ranker can take any of it is untested.
4. **`copied_evidence` is unsolved by everything.** Best arm 0.613 against an oracle of 1.000, and the mechanism built for it makes the plain arm worse. Source-root grouping needs re-measuring against `lexical`, not against plain hybrid.
5. **The benchmark is mine.** One author, one world, no independently labelled subset.

## 6. The honest summary

> A trained embedder closes about **70% of the measured headroom on dev** and
> **+0.045 on the frozen split**, and those two numbers are far enough apart
> that the honest claim is only "clearly better, by an unestablished amount".
> It beats every mechanism in this project combined on dev, and it matches
> bounded premise promotion on the `indirect` family without any lineage
> machinery at all.
>
> It is also *worse* where explicit scope and constraints matter, which is the
> case for fusing it with lexical retrieval — and the dev split says fusing
> hurts while the test split says it helps.
>
> **Sample size is now the binding constraint**, ahead of any mechanism and
> ahead of the ranker. Twenty cases cannot separate arms that differ by 0.05,
> and the next useful work on this benchmark is more labelled cases, not more
> retrieval machinery.
