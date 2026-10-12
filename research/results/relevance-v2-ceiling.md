# relevance_v2 — the ceiling, and what a harder benchmark found first

**Headroom is +0.193 nDCG@5 on dev, and the first four things the benchmark
found were defects in itself and in the thing it measures.** That is the
result. A no-signal arm scores **0.000** here against **0.843** on v1, which is
the only reason any of the other numbers mean anything.

- **Benchmark:** [relevance_v2](../bench/relevance_v2/README.md) — 66 cases, eleven families of six, ~495 memories a case (~1,895 for `budget_pressure`), dev 33 / test 33
- **Run:** 2026-10-11, `python -m experiments.relevance_bench --benchmark relevance_v2 --split dev`, k=5
- **Deterministic:** no model calls in these arms; two runs of one commit agree exactly
- **The test split is unopened.** Every number here is dev.

---

## 1. The numbers

> **Corrected 2026-10-12.** The nDCG figures below were measured before the
> quarantine-timing fix described in §7, which changed *which memories are
> eligible* — a contested descendant of a retracted memory is withheld — and so
> moved the ranking numbers as well as the stale-citation ones. §7 was
> corrected at the time and this table was not. The original figures are kept
> at the end of this section.

| arm | nDCG@5 | R@5 | MRR | critical recall | critical omission |
|---|---|---|---|---|---|
| `none` | 0.000 | 0.000 | 0.000 | 0.000 | 1.000 |
| `broken_no_signal` | **0.000** | 0.000 | 0.000 | 0.000 | 1.000 |
| `vector` (hashing) | 0.436 | 0.490 | 0.472 | 0.490 | 0.583 |
| `hybrid` (hashing) | 0.490 | 0.552 | 0.529 | 0.552 | 0.542 |
| `store_plain` (product, hybrid, mechanisms off) | 0.545 | 0.531 | 0.646 | 0.531 | 0.542 |
| `lexical` (harness reference) | 0.654 | 0.802 | 0.615 | 0.802 | 0.333 |
| `store_lexical` (product, lexical, mechanisms off) | **0.807** | 0.812 | 0.875 | 0.812 | 0.333 |
| **`lexical_all`** (product, lexical, mechanisms on) | **0.807** | 0.812 | 0.875 | 0.812 | 0.333 |
| `oracle` | 1.000 | 1.000 | 1.000 | 1.000 | 0.000 |

```
best simple arm  B = 0.807   (store_lexical and lexical_all, identically)
ceiling          C = 1.000   (oracle)
headroom             +0.193
  ceiling check: no arm beat oracle (principle 8b)
```

Decomposed:

| from | to | worth |
|---|---|---|
| harness reference `lexical` | the product's own lexical path | **+0.153** |
| mechanisms off | source roots + premise promotion | **+0.000** |
| best arm | oracle | **+0.193** still unclaimed |

**The mechanisms' nDCG gain is now +0.000, where this document reported
+0.022.** `store_lexical` and `lexical_all` are identical on every column, and
on every family: both score 1.000 on `direct`, `facet_trap`,
`independent_support` and `superseded_rev`, 0.667 on `conflicting` and
`budget_pressure`, 0.600 on `multi_hop_3` and 0.519 on `multi_hop_4`.

That is the third time the same correction has landed on these mechanisms. R6's
+0.076 downstream gain did not replicate; their stale-citation advantage was an
artifact of the quarantine timing; and their nDCG advantage goes the same way.
**They have no measured benefit on this benchmark of any kind**, and they are
kept on an argument from design, which §7 already says is weaker than a
measurement.

On the frozen split the same pattern: `store_lexical` and `lexical_all` both
0.652, `store_plain` / `store_roots` / `store_all` all 0.499, `lexical` 0.549.

The original table, measured before the fix:

| arm | nDCG@5 (invalid) |
|---|---|
| `store_lexical` | 0.746 |
| `lexical_all` | 0.768 |

with a reported headroom of +0.232 and a mechanisms gain of +0.022.

## 2. The falsification, which is the point

| arm | relevance_v1 | relevance_v2 |
|---|---|---|
| `broken_no_signal` (returns storage order) | 0.843 (0.869 before the shuffle) | **0.000** |
| best real arm | 0.832 | 0.768 |

On v1 the broken arm **beat** the hybrid baseline, twice, for two different
reasons — the relevant memory was written first, and `k` was near the corpus
size so ranking could not be wrong. Both were fixed and the second fix (15
shared distractors, 18 memories) was the most that could be done without
rebuilding. At ~495 memories storage order is worth exactly nothing.

Everything below depends on that line and on nothing else.

## 3. The four things it found before it measured anything

Recorded in full because a benchmark's first job is to catch what the previous
one could not, and three of these four are defects rather than findings.

**It leaked its own answers 185 times.** Three separate causes: an axle-pressure
rule repeating a value at a different (axle, season), so a `multi_hop_3` answer
was stated by a rule for the wrong axle; the key `"4 tonnes"` matching
`"14 tonnes"`; and a bare `"14"` matching `forklift-14`. Each would have graded
a *wrong retrieval* as a correct answer. Fixed by an assertion in the generator
rather than three repairs — a case whose answer key matches something it labels
irrelevant does not get built.

**The grading rule had to change.** R6 graded by plain substring, which on this
corpus is not merely crude but wrong: 12 dev cases still contain a plain-substring
match for an answer key and zero contain a boundary-aware one. `key_matches()`
is exported from the generator so the grader and the guard cannot disagree.

**Its own provenance edges were absent.** v1 writes `parents` as
`[[id, weight]]`; v2 wrote bare strings, the harness reads `p[0]`, so every
parent resolved to a single character, matched nothing, and the store recorded
each derived memory as its own source root. `store_roots` was then identical to
`store_plain` on all twelve provenance cases — which read as a finding about the
mechanism and was a defect in the fixture. I had also, in the same hour, written
down a *different* wrong explanation for those identical numbers (that the
premise exemption spared sibling copies) and was disproved by probing it: on
v1's `copied_evidence` the mechanism fires in all three cases. Both the fixture
bug and my explanation of it are recorded because the pattern — an identical
pair of numbers, explained rather than investigated — is the one this project
keeps repeating.

**`facet_trap` is not hard, and it was the family built to be hardest.** Every
statement of the asked predicate is one facet from the answer, and `lexical`
scores **1.000** on it. One facet apart in *form* is not one facet apart in
*difficulty*: the query names every facet, so the discriminating token is
present and IDF separates them cleanly. A near-miss that actually bites would
have to make the discriminating facet *implied* rather than stated. The README
carried this as a caveat before the run; the run converted it into a known
defect.

**Addressed, and measured** ([facet_v1](facet-v1-implied.md), 2026-10-12). With
the deciding facet implied rather than stated, `lexical` scores **1.000 on a
matched stated control and 0.000 on all three implied families, on both
splits** — same questions, same facts, same values, same distractors. One
family, `implied_by_default`, is **0.000 for every arm including a trained
embedder**: a rule reading "all vehicles, except at these two sites" names
neither the unit nor the site asked about, so no similarity measure can rank it
because it is not similar.

## 4. Where the headroom actually is

Re-measured after the quarantine-timing fix. `store_lexical` is identical to
`lexical_all` on every row, so the column is labelled for the product's lexical
path with or without the mechanisms:

| family | `lexical` (reference) | the product | what it tests |
|---|---|---|---|
| `direct` | 1.000 | 1.000 | — solved |
| `facet_trap` | 1.000 | 1.000 | — solved, and see §3 |
| `superseded_rev` | 0.631 | **1.000** | validity intervals |
| `independent_support` | 0.501 | **1.000** | one standing source among retracted ones |
| `conflicting` | 0.667 | 0.667 | both sides of a disagreement |
| `budget_pressure` | 0.667 | 0.667 | the same task at ten times the corpus |
| `multi_hop_3` | 0.437 | **0.600** | 3-hop chain, no direct statement |
| `multi_hop_4` | 0.330 | **0.519** | 4 hops and arithmetic |

The headroom is almost entirely in **chains and provenance**, not in
discriminating near-misses. `direct` and `facet_trap` are finished; `multi_hop_4`
at 0.519 against a ceiling of 1.000 is where a ranker would have something to
win. That is a more specific instruction than "build a better ranker", and it is
the opposite of what v1 suggested, where four arms sat within 0.04 of each other
and no family stood out.

**Hybrid loses to lexical again**: 0.490 against 0.654, and 0.545 against 0.746
through the store. That is the fourth independent confirmation, after SciFact,
v1's test split, and the trained-embedder run — and the first on a corpus built
after the rule was written.

## 5. Sufficiency: a different question, with its own ceiling

| arm | sufficient | requirement recall | stale cited / case | latency ms |
|---|---|---|---|---|
| `none` | 0.000 | 0.000 | 0.000 | 0.00 |
| `vector` | 0.333 | 0.392 | 1.000 | 35.8 |
| `hybrid` | 0.367 | 0.442 | 2.000 | 48.2 |
| `store_plain` | 0.367 | 0.425 | 1.500 | 144.6 |
| `store_roots` | 0.367 | 0.425 | **1.000** | 151.4 |
| `lexical` | 0.533 | 0.642 | 3.333 | 10.1 |
| `lexical_all` | **0.533** | 0.650 | **1.000** | 141.5 |
| `oracle` | **0.800** | 0.800 | 0.000 | 0.00 |

`sufficient` is the share of cases where **every** critical evidence requirement
was met by something the gates allowed. Satisfiers are intersected with the
returned set *minus* the forbidden set, so an arm that bypasses a gate gains
nothing here — the same rule that stopped a gate-bypassing arm being paid an
nDCG of 1.090.

**The ceiling is 0.800, not 1.000, and that is correct.** `gated` and
`shared_root` are built to be insufficient: the only memory that satisfies their
critical requirement is one the gates refuse, so 6 of the 30 cases with
requirements cannot be satisfied by anything, and abstention is the right
answer. A sufficiency arm scoring above 0.800 would have exposed something it
may not.

**Sufficiency headroom is +0.267, larger than the ranking headroom of +0.193**,
and the two do not move together: `store_lexical` and `lexical_all` differ by
0.022 nDCG and are identical on sufficiency, while `lexical` and `store_plain`
differ by 0.166 on sufficiency and 0.109 on nDCG. Ranking well and assembling
enough are related and not the same, which is the premise of the next milestone
rather than a conclusion of this one.

## 6. No arm abstains. Ever.

Every real arm scores **0.000 abstention precision** on the 9 dev cases where
abstention is the only correct answer — 3 `unanswerable`, 3 `gated`, 3
`shared_root`. Top-k retrieval over ~495 memories always has a fifth-best
candidate to return, so it returns one.

This is a product finding, not a benchmark artifact. Nothing in the retrieval
path can say *the corpus does not answer this*, even when the reachable
relevant set is empty and the store knows it. R6 found the related effect from
the other side — a stuffed context makes a model less willing to abstain — and
that was the one R6 result to survive its frozen split. The two together are
the argument for making sufficiency a first-class output rather than something
read off a ranking.

## 7. Stale evidence: the store already handles it completely

> **Corrected 2026-10-12.** This section previously reported that source-root
> grouping cuts stale-evidence citation by 70% and is "the first measured
> number for the provenance machinery acting on the case it was designed for".
> That was an artifact of the same class as the three defects in §3, and the
> original numbers are kept below.

Re-measured with the fixture's quarantine applied **after** the corpus is
written, which is what any real caller does:

| arm | mechanism | stale cited / case |
|---|---|---|
| `lexical` (harness reference, no store) | none | **3.333** |
| `store_plain` | none | **0.000** |
| `store_roots` | source roots | 0.000 |
| `store_all` | all three | 0.000 |
| `lexical_all` | source roots + promotion | 0.000 |
| `oracle` | — | 0.000 |

**Every arm that goes through the store cites zero stale evidence, with every
mechanism off.** `quarantine(propagate=True)` contests the descendants of a
retracted memory and contested memories are withheld by default, so the
question is settled before retrieval runs. Source-root grouping contributes
nothing to it.

The only arm that cites stale evidence is `lexical` — the harness's own
reference implementation, which scores the corpus directly and has no lifecycle
propagation at all. The 3.333 is a property of the benchmark harness, not of the
product.

What the earlier version measured was the product with its own retraction
propagation prevented from running: the fixture quarantined inside the write
loop, so when a parent was retracted its children did not yet exist and there
was nothing to propagate to. The original table, preserved:

| arm | stale cited / case (invalid) |
|---|---|
| `lexical` | 3.333 |
| `store_plain` / `store_lineage` / `store_temporal` | 1.500 |
| `store_roots` / `store_all` | 1.000 |

[P3](p3-correction-propagation.md) has the full account and the corrected
comparison against blanket invalidation and graph traversal.

## 8. Cost

The product's lexical path costs ~140 ms a query at ~495 memories against the
harness reference's ~10 ms, and the mechanisms add ~10 ms on top of that. Most
of the 140 ms is per-case store construction rather than retrieval, so it is
not a per-query figure for a warm store and is reported as what it is.

It belongs here anyway, because **P9 was declined on a 4.39 ms figure** that
later turned out to have been measured with the 256-dimension hashing embedder
while the evidence recommends a 768-dimension trained one at ~50× the cost. A
cost column that only appears once something looks slow is a cost column that
arrives too late.

## 9. What this does not establish

1. **Dev only.** The test split is unopened and no threshold has been evaluated against it.
2. **Three cases a family.** Every per-family number is three cases; §4's ordering is a direction, not an estimate.
3. **The labels are mine.** v2 is harder, not independent. SciFact remains the only external check in this project and this does not change that.
4. **Generated text.** Controlled near-misses bought with template grammar; `facet_trap` scoring 1.000 is the first evidence that the control is imperfect in a way that matters.
5. **No downstream measurement.** Every number here is retrieval. Whether a sufficient context changes what a model answers is R6's question, re-asked on a corpus that can finally pose it, and it has not been run.
6. **`lexical_all` is not a ranker.** It is the product with two mechanisms enabled. The +0.232 is what a ranker would have to compete for, and R2 stays blocked until the sufficiency question is answered.

## 10. The honest summary

> A no-signal arm scores **0.000** where it scored **0.843** on v1. That single
> line is what the rebuild bought, and every other number depends on it.
>
> The ceiling says **+0.193 nDCG@5** is unclaimed on dev (corrected from
> +0.232; see §1), and the per-family breakdown says almost all of it is in
> **multi-hop chains**, not in telling near-misses apart. `direct` and `facet_trap` are finished at
> 1.000 — including the family built to be hardest, which is a defect in my
> design and is recorded as one.
>
> Sufficiency has a **larger** headroom (+0.267) than ranking and does not move
> with it, and **no arm abstains even once** on the nine cases where abstention
> is the only correct answer. Those two facts are the case for the next
> milestone being about assembled evidence rather than about ordering.
>
> **Corrected:** an earlier version of this summary credited source-root
> grouping with cutting stale-evidence citation by 70%. In fact every
> store-backed arm cites **zero** stale evidence with every mechanism off,
> because quarantining a memory already contests its descendants and contested
> memories are withheld. The 70% was measured against a store whose own
> propagation the fixture had prevented from running. See §7 and
> [P3](p3-correction-propagation.md).
>
> And the benchmark found three bugs in itself and one in its fixture before it
> measured anything, including a leak that would have graded wrong retrievals
> as correct answers 185 times. On the previous benchmark that class of defect
> shipped twice and was found by a broken arm outscoring a real one. Finding it
> before the first measurement is the improvement.
