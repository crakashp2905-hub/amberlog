# R6 pre-registration — does better retrieval change what an agent answers?

**Registered 2026-10-11, before the run.** Thresholds, arms, seeds and the
analysis are fixed here; the result goes in `research/results/`, and if it is
negative it stays.

---

## 1. The question

Every number in R1–R5 is a retrieval metric. nDCG is not task success, and the
conversion between them is assumed rather than measured. This project has been
caught by that gap before: Phase A measured governed memory **losing** to an
ungoverned vector store by 34 points, and the mechanism was that success
tracked one thing — whether a correct memory reached the prompt — at 93–98%
conversion in every arm.

> **H-R6:** Retrieval that scores better on `relevance_v1` produces better
> answers from a real model at a fixed token budget.

The null is live and plausible: the benchmark's distractors may be easy enough
for a model to ignore, in which case a worse retriever costs nothing and the
whole relevance track is measuring something that does not matter downstream.

## 2. Arms

Same corpus, same task text, same budget, same model, same decoding. The only
difference is which memories reach the prompt.

| arm | retrieval |
|---|---|
| `no_memory` | nothing. The floor, and the only arm that can show memory hurting |
| `all_memory` | every memory in the corpus, truncated to the budget. The "just give the model everything" baseline that R1's `broken_no_signal` cannot represent |
| `store_plain` | hybrid retrieval, mechanisms off |
| `store_all` | hybrid + source roots + premise promotion + `as_of` |
| `oracle_memory` | exactly the labelled relevant set |

`oracle_memory` is the ceiling and takes the same budget and the same `k` as
every other arm (AGENTS.md 8b). `all_memory` matters because a budget large
enough to hold the corpus would make retrieval irrelevant by construction, and
naming that arm is how we find out.

## 3. Measures

**Primary:** answer correctness, graded against the case's labelled
`relevant` set by an exact-match rule on a required token, declared per case
before the run. Not a model grading itself, and not a model grading another
model — PA′'s first analyser scored every withdrawal rule "100% justified"
because it compared actions without comparing faults, and an LLM judge here
would be the same error with more steps.

**Secondary:**
- critical-fact presence: did the `critical` memory reach the prompt
- unsupported-answer rate: an answer asserting something no exposed memory says
- abstention on `unanswerable` cases
- **gate violations**: any `must_not_expose` memory reaching the prompt. Non-zero fails the run regardless of correctness
- prompt tokens, wall seconds, model calls

## 4. Thresholds, as a share of measured headroom

Registered **before** the run, as a share of the ceiling the oracle reveals
(principle 8a). Let `C` be `oracle_memory`'s correctness and `B` the best of
`store_plain` / `all_memory`.

- **Supported** if `store_all` ≥ `B` + 0.40 × (`C` − `B`), interval clear of zero.
- **Killed** if `store_all` ≤ `B`, i.e. the mechanisms buy nothing a plain arm did not.
- **Inconclusive** otherwise, and reported as inconclusive rather than argued either way.

If `C` − `B` ≤ 0.05 the comparison is **abandoned, not reinterpreted**: there
is no headroom to divide and a threshold on it would be the H3 mistake —
registering +0.030 when only +0.027 existed.

## 5. Design

- **Model:** one local Ollama model, named in the result with its exact tag. Temperature 0.
- **Seeds:** 5. Temperature 0 is not determinism — prompt order and tokeniser state move answers — so the spread is reported, not assumed away.

### Amendment, 2026-10-11, before the run

**Seeds reduced from 5 to 3 per split.** Measured cost: ~7 s per case per arm,
so 5 arms × 50 cases × 5 seeds is ~2 h 25 m of model calls per split. Three
seeds is ~1 h 25 m for both splits together.

What this costs: less protection against an unlucky prompt-order draw, and
wider intervals. The spread across the three is reported rather than hidden,
and the registered threshold is unchanged — a result that needs a fourth seed
to clear it does not clear it.

Recorded before the run and before seeing any number, which is the only time an
amendment like this is worth anything. The alternative considered and rejected
was a smaller model: `qwen2.5:3b` would be ~3× faster, but model size plausibly
changes the *direction* of the result — a weaker model may be less able to
ignore distractors — so trading it for seeds would confound the thing being
measured.
- **Cases:** every `relevance_v1` case with a labelled answer. `unanswerable` cases score abstention instead of correctness.
- **Budget:** fixed token budget per case, from the case's own `token_budget`.
- **Order:** memories are shuffled within the prompt per seed, so a model that favours the first item cannot flatter whichever arm happens to rank well.
- **Blind grading:** the grader sees the answer and the required token, never the arm.

## 6. What a positive result would and would not license

Would: "on this benchmark, with this model, retrieval changes answered by this
much."

Would **not**: a general claim about agents. One model, one synthetic world,
one author's labels. R1's own result already showed the dev/test gap moving a
conclusion, and that was a retrieval metric with no model in the loop.

## 7. Predictions, recorded to be wrong

1. `all_memory` beats `store_plain`. The corpora are 18–20 memories and a modern model reads all of them; if so, **retrieval quality matters less than the ranking numbers suggest**, and that is the finding.
2. The gap between `store_all` and `oracle_memory` is smaller than the nDCG gap, because a model recovers from a mediocre context more often than a metric rewards.
3. `no_memory` is far below everything, which establishes only that the corpus is load-bearing — a result worth nothing on its own and worth stating so.

Prediction 1 is the one that would most change the roadmap. If a model handles
the whole corpus, the honest conclusion is that this benchmark's corpora are
too small to need retrieval, and the next benchmark needs corpora a model
cannot swallow.
