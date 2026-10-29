# LongMemEval

[LongMemEval](https://arxiv.org/abs/2410.10813) (Wu et al., ICLR 2025) —
500 questions over long chat histories, with turn-level gold evidence written
by its authors. **The second external benchmark in this project, and the first
that tests what Amberlog is for.**

## Why it is here

`research/SCORECARD.md` said for several milestones that SciFact was the only
external check, and that **SciFact has no provenance, no lifecycle, no
retraction and no tenants** — so every claim about corrections, temporal
validity and multi-hop evidence rested on benchmarks written and labelled here.
LongMemEval tests four of them:

| ability | instances | previously measured only on my own fixtures |
|---|---|---|
| knowledge updates | 78 | P3, P2b |
| temporal reasoning | 133 | `superseded_rev` |
| multi-session reasoning | 133 | `multi_hop_3/4` |
| abstention | 30 | **0.000 on every arm, with no external check at all** |

Found by way of [vectorize-io/hindsight](https://github.com/vectorize-io/hindsight),
which evaluates on it. See [research/HINDSIGHT.md](../../HINDSIGHT.md).

## Not committed

```bash
mkdir -p research/bench/longmemeval/data && cd research/bench/longmemeval/data
curl -L -O https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned/resolve/main/longmemeval_oracle.json
curl -L -O https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned/resolve/main/longmemeval_s_cleaned.json
```

15 MB and 277 MB. Gitignored, for the reason the external SciFact corpus is:
this repository has once committed 7.8 MB of benchmark data while its own
documentation said it had not.

Download with no credentials; the upstream code is MIT and the dataset's own
licence is not stated in its README. Treated as untrusted downloaded data —
its own directory, nothing executed from it.

## Splits

| split | haystack | use |
|---|---|---|
| `oracle` | evidence sessions only, median **23 turns** | wiring check. Too small to be a retrieval test — the `relevance_v1` mistake |
| `s` | ~40 sessions, median **485 turns** | the real measurement |
| `m` | ~500 sessions | not downloaded |

## Running it

```bash
python -m experiments.longmemeval_bench --split s --arms lexical vector hybrid chain oracle
```

`--temporal {as_of,until,none}` selects which temporal question the harness
asks. It is a flag because the three give materially different answers — 19
points of turn recall on temporal-reasoning — and a finding reproducible only
by editing the harness is not reproducible.

`--limit` samples **stratified** by question type, round-robin and
deterministic. A plain `data[:60]` returns 60 temporal-reasoning instances and
nothing else, because the file is sorted by type; that looks like a result and
is a slicing artifact.

## What it measures, and what it does not

Turn-level and session-level recall of the gold evidence, broken out by
question type — the **retrieval stage only**. Hindsight and the LongMemEval
paper report end-to-end QA accuracy with a model reading the context, so
**those numbers and these are not comparable** and nothing here is a claim
about relative quality.

The 30 abstention instances are scored separately, on whether the system
reports insufficiency. LongMemEval's own retrieval evaluation **skips them**,
because a question whose answer is "you never told me that" has no gold
location to retrieve — which leaves the one ability this project has
repeatedly measured at zero untested.

Nothing is tuned on this benchmark.
