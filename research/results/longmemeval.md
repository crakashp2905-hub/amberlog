# LongMemEval — the second external benchmark, and the first that tests corrections

**The benchmark found a shipped mechanism mis-specified within the hour, and
gave the cleanest demonstration yet of a rule this project had only shown
across benchmarks.** It also confirmed externally, on 500 third-party
questions, the gap every internal measurement has reported: **the fabric
essentially never says it does not know.**

- **Benchmark:** [LongMemEval](https://arxiv.org/abs/2410.10813) (Wu et al., ICLR 2025) — 500 questions, turn-level gold evidence written by its authors
- **Found via** [vectorize-io/hindsight](https://github.com/vectorize-io/hindsight); see [HINDSIGHT.md](../HINDSIGHT.md)
- **Runs:** 2026-10-12, `python -m experiments.longmemeval_bench`, k=10
- **Retrieval stage only.** The paper and Hindsight report end-to-end QA accuracy with a model reading the context, so **those numbers and these are not comparable**
- Nothing is tuned on this benchmark

---

> **Re-measured at the product's default settings** (2026-10-26, CI run 40391715822, commit
> `725ccb2`): `lexical` turn recall **0.750**, session recall **0.919** on all 500 `s` histories, with
> hostile-source withholding on as shipped. Before S1 that setting withheld whole histories (0.08 turn
> recall on a sample); after it, the default costs 0.003, about what the ~0.08% of turns the screen
> still holds would explain ([s1-screen-false-positives.md](s1-screen-false-positives.md)).

## 1. The realistic split — 500 instances, median 491 turns a history

| arm | turn recall | session recall | any gold turn | returned | latency ms |
|---|---|---|---|---|---|
| **`lexical`** | **0.753** | **0.921** | 0.847 | 9.9 | 11.2 |
| `hybrid` | 0.693 | 0.911 | 0.813 | 10.0 | 12.2 |
| `chain` | 0.460 | **0.898** | 0.617 | **3.6** | **67.7** |
| `vector` (hashing) | 0.456 | 0.811 | 0.598 | 10.0 | 4.3 |
| `oracle` | 1.000 | 1.000 | 1.000 | 1.8 | 0.1 |

By question type, turn recall:

| arm | knowledge-update (78) | multi-session (133) | temporal-reasoning (133) | single-user (70) | single-assistant (56) | single-preference (30) |
|---|---|---|---|---|---|---|
| `lexical` | **0.935** | 0.689 | 0.593 | 0.969 | 0.893 | 0.528 |
| `hybrid` | 0.889 | 0.634 | 0.553 | 0.953 | 0.750 | 0.383 |
| `chain` | 0.451 | 0.305 | 0.392 | 0.773 | 0.714 | 0.244 |
| `vector` | 0.669 | 0.365 | 0.361 | 0.648 | 0.500 | 0.222 |

**Knowledge updates are the easiest type and preference questions the hardest.**
That is worth sitting with: the thing Memory Fabric is built for — a fact being
superseded — is the one retrieval handles best here (0.935), because the
corrected statement is lexically close to the question. The hard types are
preference (0.528) and temporal reasoning (0.593), neither of which this
project has a mechanism aimed at.

## 2. The fusion rule, finally demonstrated inside one benchmark

The same two arms, the same benchmark, two haystack sizes:

| | vector alone | lexical alone | hybrid | fusion is worth |
|---|---|---|---|---|
| `oracle` split, median **23** turns | 0.820 | 0.817 | **0.851** | **+0.034** |
| `s` split, median **491** turns | 0.456 | 0.753 | 0.693 | **−0.060** |

**Fusion helps when the second arm is comparable and hurts when it degrades**,
and here the degradation is visible in the same column: the hashing vector arm
goes from 0.820 to 0.456 as the haystack grows twentyfold, and the moment it
becomes the weak arm, fusing it costs 6 points.

Every previous confirmation of this rule was a comparison *across* benchmarks —
SciFact against `relevance_v1`, `facet_v1` against both. This is the first
**controlled** version: one corpus, one query set, one pair of arms, the only
variable being how much hay there is. It reproduces the SciFact result
(hashing_hybrid 0.558 against lexical 0.621 at 5,183 documents) on an
independent corpus with someone else's labels.

It is also the clearest statement of why the rule is a workaround rather than a
design: reciprocal-rank fusion gives every arm equal rank votes and **cannot
notice that one of them has gone bad**. A reranker would.

## 3. The abstention gap, externally confirmed

LongMemEval includes **30 instances whose correct answer is that the history
does not say**, and its own retrieval evaluation **skips them** — reasonably,
since a question with no answer has no gold location to retrieve. That leaves
untested the one ability this project has measured at zero everywhere.

Scored here on whether the system reports insufficiency:

| arm | reports insufficiency (30 unanswerable) | false insufficiency (470 answerable) |
|---|---|---|
| `lexical` | 0.033 | 0.002 |
| `vector` | 0.000 | 0.002 |
| `hybrid` | 0.000 | 0.002 |
| `chain` | **0.067** | 0.074 |

**0 to 7%.** `relevance_v2` §6 recorded that no arm abstains on the nine cases
where abstention is the only correct answer; P1 found the chain arm abstaining
on 1 of 9; P2's selector could be made to abstain on everything or nothing and
nothing in between. All of that was on my own fixtures. **It now replicates on
500 questions someone else wrote**, and the diagnosis is unchanged: the fabric
can express insufficiency — `reconstruct` returns an incomplete chain naming
what it could not cover — and nothing computes it well enough to be worth
acting on.

`chain` is the only arm above zero and pays for it: 0.067 correct against 0.074
false, which is barely better than noise and is the same trade P2 measured.

## 4. What it found in the product, in the first hour

**`as_of` is mis-specified for a whole class of question, and no internal
benchmark could have shown it.**

`retrieve(as_of=T)` means *state at a point*: `valid_from <= T < valid_to`. Its
docstring recommended that a caller who knows its task's time pass it, and
`experiments/relevance_bench._as_of` does so automatically. Reproducible with
`--temporal`, on the oracle split:

| `--temporal` | knowledge-update | multi-session | temporal-reasoning |
|---|---|---|---|
| `as_of` (the question's date) | 0.947 | 0.742 | **0.644** |
| `until` (history through it) | 0.947 | 0.742 | **0.644** |
| `none` | **0.968** | 0.742 | **0.834** |

**19 points on temporal reasoning**, because 20.4% of the turns in those
instances are dated *after* the question is asked. *"Which did I do first,
fixing the fence or buying the cows?"* is a question about ordering across the
whole history, not about what was true at a moment, and filtering to a snapshot
discards a fifth of the evidence. `applies_at` is correct; the call was wrong.

Every internal benchmark agreed with the old advice for one reason:
**none of them ever placed evidence after the task's event time.**
`relevance_v2` sets a single event time for every case. That is precisely the
blind spot an external benchmark exists to find, and it took one run.

Fixed as a capability rather than a caveat — `retrieve` and `reconstruct` now
take `until` as well as `as_of`, so the three temporal questions are distinct:

| question | call |
|---|---|
| what is true now, or was true at T | `as_of=T` |
| what did we know through T, including since-superseded claims | `until=T` |
| when did things happen | neither |

**`until` is not validated by this benchmark**, and the table above says why:
it is indistinguishable from `as_of` here, because the two differ only when a
claim has been superseded and LongMemEval's turns carry no end dates. The
measured finding is narrow — *passing the question's date as a temporal bound
at all costs 19 points on ordering questions* — and `until` rests on
`tests/test_bitemporal.py`, a file that did not exist before: schema 0.7.0
added bitemporal validity and nothing asserted what the modes **mean**.

## 5. The chain arm: worse on recall, nearly equal on location

`chain` looks bad at 0.460 turn recall against lexical's 0.753, and the
session-recall column is the honest reading: **0.898 against 0.921** while
returning **3.6 memories instead of 9.9**.

So it finds the right conversation almost as often as top-k does, from a
quarter of the context. On a recall@10 metric against a gold set of 1.8 turns,
an arm that returns 3.6 items cannot win, and that is a property of the metric
rather than a verdict on the mechanism — P1 registered sufficiency as its
primary metric for this reason.

**The cost finding is now explained and largely fixed.** The first run cost
**193 ms a query** against lexical's 11 ms, where P1 had measured the same
search at 13 ms over ~495 candidates on `relevance_v2`. Profiling found the
cost tracking **query length rather than corpus size** — a 6-token question
cost 34 ms and a 17-token one 182 ms over the same ~500 candidates — because
`_bridge_terms` ran 35,000 times a query with a regex per shared term, 423,918
matches in three reconstructions.

Three changes, none of which alter what the search returns:

| | worst case |
|---|---|
| as first measured | 193 ms |
| components computed once per state, not twice per candidate | 182 ms |
| linkable term sets precomputed, so an edge test is one set operation | 94 ms |
| tokenisation cached on the fabric, as the IDF already was | **68 ms** |

**2.9× faster with turn recall and session recall unchanged to three decimals**
(0.460 and 0.898), which is how a behaviour-preserving change should look. The
floor is now 8.3 ms on a question that expands no search nodes, against
lexical's 11 ms.

My first guess at the cause was wrong and is worth recording: I expected the
per-candidate component recomputation to dominate and it was worth 11 ms of the
193. The regex in the inner loop was worth 88.

## 5a. A trained embedder is *worse* here, and the cost closes P9

The `oracle` split with the trained arms, 500 instances. The `s` split's
~245,500 embeddings are ~32 hours even batched, so this is the tractable half
and §7 says what stays untested because of it.

| arm | turn recall | session recall | latency a query |
|---|---|---|---|
| `lexical` | 0.817 | 0.968 | 3.3 ms |
| `vector` (hashing, 256-dim) | **0.820** | 0.970 | 3.2 ms |
| **`hybrid`** (hashing) | **0.851** | 0.970 | 4.5 ms |
| `real_vector` (trained, 768-dim) | **0.811** | 0.970 | **393.0 ms** |
| `real_hybrid` (trained) | 0.836 | 0.970 | 2.8 ms* |
| `oracle` | 1.000 | 1.000 | 0.0 ms |

\* the query embedding was already cached from `real_vector`'s run, so this
number is the scan alone and not a per-query cost.

**The trained embedder loses to the hashed one** — 0.811 against 0.820 — and
**hashing hybrid at 0.851 beats trained hybrid at 0.836.** On every question
type bar one, `real_vector` is at or below `vector`.

That is the opposite of SciFact, where the trained embedder scored **0.701
against the hashed arm's 0.315** and the gap was the largest single effect this
project had measured. Both are real, and together they say the embedder's value
is a **property of the corpus**, not of the embedder:

| corpus | documents | hashing | trained |
|---|---|---|---|
| SciFact abstracts | 5,183 long scientific paragraphs | 0.315 | **0.701** |
| LongMemEval turns | ~23 short conversational utterances | **0.820** | 0.811 |

A hashed bag of words is weak on a paraphrased abstract and strong on a short
turn that shares most of its words with the question. "Fix the embedder" was
the right conclusion from SciFact and is not a general one — which is the
second time this benchmark has corrected a conclusion that every internal
measurement agreed with.

**And the latency closes P9.** That milestone declined distribution at
**4.39 ms a retrieval**, measured with the 256-dimension hashing embedder, and
`memory-fabric/vectors.py` has carried an open item ever since: the figure was
taken at the wrong dimension. Here a trained-embedder retrieval costs
**393 ms**, on a corpus of 23 documents — the cost is **embedding the query**,
one model call, and is therefore independent of corpus size. That is **89× the
figure the decision rested on**, before any scan. Taken with
[p4-envelope.md](p4-envelope.md)'s 19 ms for lexical retrieval at 10,000
memories, the ordering is now measured at three points and P9's conclusion does
not transfer to the embedder SciFact recommends.

**Abstention is identical across all five arms at 0.067**, trained arms
included — one more confirmation that it is not a retrieval-side property
([abstention-signals.md](abstention-signals.md)).

## 6. The oracle split is too small to be a retrieval test

Reported because the mistake is one this project has already made:

| | median turns | `lexical` turn recall |
|---|---|---|
| `oracle` (evidence sessions only) | 23 | 0.817 |
| `s` (~40 sessions) | 491 | 0.753 |

`relevance_v1` was invalid twice because 18 memories against k=3 meant ranking
could not be wrong. The oracle split is 23 turns against k=10 and is used here
as a wiring check only. Every headline number in §1 is from `s`.

## 7. What this does not establish

1. **Retrieval stage only.** No model reads the context, so nothing here is an answer-quality claim and nothing is comparable with the paper's or Hindsight's end-to-end accuracy.
2. **Turn granularity is a choice.** Each turn is one memory. Session granularity would change every number, and the reference harness supports both.
3. **The `m` split is not run.** ~500 sessions a question is the harder regime and is untouched.
4. **The trained arms ran on the `oracle` split only** (§5a). The `s` split needs ~245,500 embeddings at a measured 2.1 a second batched — about **32 hours** — and an unbatched 60-instance attempt timed out at 5,400 s. So the prediction §2 invites, that a trained arm rescues fusion at 491 turns a history where the hashed one collapses to 0.456, **remains untested**. §5a makes it less likely than it looked: on short conversational turns the trained embedder is the *weaker* arm.
5. **Abstention scoring is mine.** LongMemEval skips these instances, so "reports insufficiency" is a metric I defined on their data, not one they endorse.
6. **One run, no seeds.** The deterministic arms are byte-identical across runs; there is no sampling to vary.

## 8. The honest summary

> An external benchmark with 500 questions and someone else's labels found a
> shipped mechanism mis-specified **within the hour**: passing a question's own
> date as `as_of` costs **19 points of turn recall** on ordering questions,
> because a fifth of their evidence postdates the question. Every internal
> benchmark endorsed the old advice, because none of them ever placed evidence
> after the task's event time.
>
> It also gave the first **controlled** demonstration of the fusion rule. Same
> corpus, same queries, same two arms: at 23 turns a history the vector arm
> scores 0.820 and fusion gains 4 points; at 491 turns it scores 0.456 and
> fusion costs 6. Reciprocal-rank fusion cannot notice that an arm has gone
> bad, which is why the rule is a workaround and a reranker is the fix.
>
> And the abstention gap is no longer an internal finding. On 30 questions
> designed to be unanswerable, the fabric reports insufficiency **0 to 7% of
> the time** — the same number `relevance_v2`, P1 and P2 reported on my own
> fixtures, now replicated on data I did not write.
>
> The one encouraging number is the one I would have guessed wrong:
> **knowledge-update is the easiest question type at 0.935**, and preference
> and temporal reasoning are the hardest at 0.528 and 0.593. The thing this
> project is built for is not where its retrieval struggles.
