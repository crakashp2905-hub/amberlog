# facet_v1 — when the deciding facet is implied, retrieval collapses

**`lexical` scores 1.000 on the stated control and 0.000 on all three implied
families, on both splits.** That total separation is the result, and it is the
thing `facet_trap` was built to show and could not.

A trained embedder recovers some of it and **nothing recovers
`implied_by_default`**, which is 0.000 for every arm on both splits.

- **Fixture:** [facet_v1](../bench/facet_v1/build.py) — 16 cases, four families of four, ~205 memories a case, dev 8 / test 8
- **Runs:** 2026-10-12, `python -m experiments.relevance_bench --benchmark facet_v1 --split {dev,test}`, k=3
- **Deterministic** apart from the `real_*` arms, which call `nomic-embed-text` via Ollama

---

## 1. Why this exists

relevance_v2's `facet_trap` was the family built to be hardest: every statement
of the asked predicate exactly one facet from the answer, same register, one
discriminating token in twelve. `lexical` scored **1.000** on it.

The [v2 ceiling](relevance-v2-ceiling.md) §3 recorded that as a defect of my
design, with the diagnosis: the query names every facet, so the discriminating
token is present in both the query and the answer and IDF separates them
cleanly. **One facet apart in form is not one facet apart in difficulty.**

So the deciding facet has to be *absent* from the answer-bearing memory and
*present* in the wrong ones. That inverts the signal: the memory that answers
lacks the query's most discriminating word, and every memory that has it is
wrong. A token-overlap retriever is then actively misled rather than merely
unhelped.

## 2. The numbers

| arm | dev nDCG@3 | test nDCG@3 |
|---|---|---|
| `none` | 0.000 | 0.000 |
| `broken_no_signal` | **0.000** | **0.000** |
| `lexical` | 0.250 | 0.250 |
| `store_lexical` | 0.250 | — |
| `lexical_all` | 0.250 | — |
| `real_hybrid` | 0.250 | 0.250 |
| `real_vector` (trained embedder) | 0.312 | **0.516** |
| `oracle` | 1.000 | 1.000 |

The broken arm is at 0.000 on both splits, so the fixture is sound in the way
`relevance_v1` twice was not. Headroom against the best deterministic arm is
**+0.750**.

## 3. The control earns the claim

This is the comparison `facet_trap` lacked, and the whole design turns on it.
`stated_control` asks the **same questions** about the **same facts** with the
**same distractors** and the same values — the only difference is that the
answer states the season instead of excluding the other two.

`lexical`, both splits, identical:

| family | nDCG@3 | critical recall |
|---|---|---|
| `stated_control` | **1.000** | **1.000** |
| `implied_by_exclusion` | **0.000** | 0.000 |
| `implied_by_default` | **0.000** | 0.000 |
| `implied_by_paraphrase` | **0.000** | 0.000 |

1.000 against 0.000, with everything else held fixed. The difficulty is
attributable to the implication and to nothing else — not to corpus size, not
to distractor choice, not to vocabulary, because the control shares all three.

`facet_trap` could not make this argument at all. It had no control, so its
1.000 was uninterpretable: it could have meant the family was easy or that
everything in the benchmark was easy.

## 4. A trained embedder helps, unevenly, and not where I predicted

`real_vector` by family:

| family | dev | test |
|---|---|---|
| `stated_control` | 1.000 | 1.000 |
| `implied_by_exclusion` | 0.250 | **0.816** |
| `implied_by_paraphrase` | 0.000 | 0.250 |
| `implied_by_default` | **0.000** | **0.000** |

**`implied_by_paraphrase` refutes a prediction I wrote into the generator.** The
family's docstring calls it "deliberately the one family a lexical retriever
cannot solve even in principle … a trained embedder should close this one and
not the other two". It does not: 0.000 on dev and 0.250 on test.
`nomic-embed-text` does not match *"the number five crane on the seaward berth
takes 3.1 bar in the cold season"* to *"the winter tyre pressure for crane-5 at
the coastal site"*. The prediction is left in the generator rather than edited
out.

**`implied_by_default` is 0.000 for every arm on both splits** — lexical,
hybrid, store, mechanisms, trained embedder. The answer is *"All yard vehicles
run 3.9 bar in winter, except at the harbour and quarry sites"*, and it names
neither the unit nor the site the query asks about, so it shares almost nothing
with the query while four distractors name both. No similarity measure can
rank it, because it is not similar. Reaching it requires knowing that a general
rule applies unless its exception list says otherwise, which is inference over
the corpus rather than retrieval from it.

That is the sharpest statement of the gap this project has produced: **the
headroom relevance_v2 located in multi-hop chains is of the same kind as this.**
Both need something that reasons about what a memory *entails*, not what it
resembles.

**Fusion hurts again, for the fourth time and now in the other direction.**
`real_hybrid` (0.250) falls back to `lexical`'s score from `real_vector`'s 0.516
on test. Every earlier confirmation had a weak vector arm dragging a strong
lexical one; here a strong vector arm is dragged down by a weak lexical one.
Same mechanism, same conclusion — **do not fuse a weak arm into a strong one** —
and the rule is now measured with the roles reversed.

## 5. What this does not establish

1. **Sixteen cases, two a family a split.** Every per-family number is two cases. The 1.000/0.000 separation is large enough to survive that; the `real_vector` dev/test difference (0.312 against 0.516) is not, and is reported as a range rather than an estimate.
2. **A focused fixture, not a benchmark.** One predicate, one domain, four hand-written implication patterns. There is no claim that these are the implications that matter in practice.
3. **My labels, and my idea of what is implied.** `implied_by_default` assumes a reader applies an exception list; a different reader might call the case under-specified. That is a judgement built into the fixture.
4. **Generated from templates**, with the same caveat as relevance_v2: a method could exploit the pattern rather than the semantics. The broken arm at 0.000 is the check that it has not been exploited *yet*.
5. **No downstream measurement.** Whether a model handed the default rule applies it correctly is unmeasured, and separate from whether retrieval finds it.
6. **One embedding model.** A stronger one could close `implied_by_paraphrase`; it is much less likely to close `implied_by_default`, which is not a similarity problem.

## 6. The honest summary

> **1.000 on the stated control, 0.000 on all three implied families, both
> splits.** The same questions, facts, values and distractors — the only change
> is whether the deciding facet is stated or implied. `facet_trap` scored 1.000
> and had no control, so it could not tell an easy family from an easy
> benchmark; this one can, and the difficulty is attributable to the
> implication alone.
>
> A trained embedder recovers part of `implied_by_exclusion` — unevenly, 0.250
> on dev and 0.816 on test — and **refutes the prediction I wrote into the
> generator** by not closing `implied_by_paraphrase`.
>
> **`implied_by_default` is 0.000 for every arm on both splits.** A rule that
> says "all vehicles, except at these two sites" names neither the unit nor the
> site asked about, so no similarity measure can rank it, because it is not
> similar. Reaching it means knowing that a default applies unless an exception
> says otherwise.
>
> That is the same kind of gap relevance_v2 found in its multi-hop families, and
> saying so is the useful part: the unclaimed headroom in this project is not
> waiting for a better similarity function. It is waiting for something that
> reasons about what a memory entails.
