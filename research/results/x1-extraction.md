# X1 — extraction at ingest: NOT SUPPORTED at 0.000, and three faults in the apparatus

**The registered primary scores 0.000 against a bar of 0.400 — 0% of the
headroom — and the mechanism proposed zero relations out of three.** The model
is not why: `gemma2` extracted both sides of the relation correctly. The
matcher that was supposed to join them is a string-containment test whose unit
test supplied both strings (§11).

**Four findings, and three of them are about this project's own apparatus
rather than about extraction.**

1. **The registered primary metric was trivially maximised by a registered baseline, and the 8c check that exists to catch exactly that was performed and answered wrongly.** `B = 0.000` was quoted from a table reporting a *different metric at a different budget*. On the registered metric a plain lexical baseline scores **1.000** on one of the two registered families. The family is abandoned under the registration's own clause. This was found by running the baselines before the model, and it is now [principle 8d](../../AGENTS.md).
2. **A model can supply the declarations, and the cost is the product conclusion — because of the hardware, not the model.** `gemma2` classified **19/19** statements correctly with usable targets at **54.5 s each**; `qwen2.5:1.5b` reaches 18/19 at **9.4 s**, 5.8× faster, missing only the modifier. It does not matter which wins: there is **no discrete GPU** on this machine, so every model that extracts correctly runs at seconds per statement, and 10,000 memories cost 26 hours at best against 151 at worst. Prediction 4 said cost would make extraction a batch job rather than an ingest-path step; it does, and the reason is the hardware floor (§8).
3. **Checking prediction 3 found a published AUC reported as its own complement.** `abstention-signals.md`'s pooled AUC is **0.682, not 0.319** — above chance, not below. Every other figure in that result reproduces exactly. Its practical verdict survives untouched, which means the right decision was reached on the strength of a number that was upside down. It cited no harness, which is why it survived; there is one now.

- **Registration:** [x1-extraction-at-ingest.md](../prereg/x1-extraction-at-ingest.md) — its own §8 amends the primary, written before any model call of the primary arm
- **Mechanism:** `memory_fabric/extraction.py`, `MemoryFabric.index_extraction()`, `applicable_defaults()`, `infer_relations()`
- **Harnesses:** `experiments/x1_extraction_quality.py` (extraction quality), `experiments/x1_extraction.py` (the retrieval arms), `experiments/x1_abstention_premise.py` (prediction 3, and §5's correction)
- **Runs:** 2026-10-13 via Ollama 0.40, k=5. Models: `gemma2:latest`, `qwen2.5:7b`, `qwen2.5:3b`, `qwen2.5:1.5b`, `llama3.2:3b`, `qwen3:1.7b`, `gemma3:4b`, and `finsenti-llama3.2-1b:latest` (a domain fine-tune, §2)
- **A fourth finding, about method:** schema-constrained decoding, added mid-session in the belief that it was the accuracy and cost fix, **changes no accuracy and costs ~50% more wall time** (§8). Recorded here because the mistake has the same shape as finding 1 — a number accepted before the control that bounded it was run.
- **Off by default.** Nothing in `remember` calls a model.

---

## 1. The registration was invalid, and how

§4 of the registration set the primary as **sufficiency at k=5**, pooled over
`implied_by_default` and `multi_hop_4`, with `B = max(sufficient) over the
baselines = 0.000`. It then ran principle 8c's check — *is the primary
trivially maximised by a registered baseline?* — and answered:

> *"No: every baseline is 0.000 on both families, which is why they were
> chosen."*

That `B` was copied from
[`facet-v1-implied.md`](facet-v1-implied.md), **whose tables report nDCG and
critical recall at k=3**. Both numbers are "0.000 for every arm", so the
substitution was invisible.

Re-measured on the registered metric, same `lexical` retrieval:

| family | split | B (baseline sufficiency @ k=5) | C (oracle) | C − B |
|---|---|---|---|---|
| `implied_by_default` | dev | **1.000** | 1.000 | **0.000** |
| `implied_by_default` | test | 0.000 | 1.000 | 1.000 |
| `multi_hop_4` | dev | 0.000 | 1.000 | 1.000 |
| `multi_hop_4` | test | 0.000 | 1.000 | 1.000 |

Per-case, by budget:

| split | case | k=3 | k=5 | k=10 |
|---|---|---|---|---|
| dev | `implied_by_default-01` | 0.000 | **1.000** | **1.000** |
| dev | `implied_by_default-03` | 0.000 | **1.000** | **1.000** |
| test | `implied_by_default-02` | 0.000 | 0.000 | 0.000 |
| test | `implied_by_default-04` | 0.000 | 0.000 | 0.000 |
| dev/test | all six `multi_hop_4` | 0.000 | 0.000 | 0.000 |

On dev the default rule ranks **4th of 205** — `('n4', 'n1', 'n2', 'a1', …)`.
It is outranked by three distractors, which is the real finding, and it is not
unrankable. The sentence `facet-v1-implied.md` drew from its k=3 table —
*"no similarity measure can rank it, because it is not similar"* — is **wrong**,
and is now struck there.

**So `implied_by_default` is abandoned**, under the registration's own
abandonment clause (`C − B <= 0.05`), on both splits rather than kept on test
alone: a family whose premise holds on one split and fails on the other cannot
carry a confirmatory test. The primary becomes `multi_hop_4`, where the
pre-registered formula gives the same bar, **0.400**. Prediction 2, which
compared the two families, is void and is not scored.

### Why this is the interesting half

8a made the ceiling mandatory. 8b made the oracle's handicap checkable. 8c made
the baseline-maxing check mandatory. **None of them catches this**, because the
ceiling was right, the oracle was unhandicapped, and the 8c check *was
performed* — confidently, from the wrong row of another document. The failure
is not a missing check but a check satisfied by a number that was never the
metric.

Hence [8d](../../AGENTS.md): **measure the baseline on the metric and the
budget the threshold is written in; a baseline quoted from another table is not
a baseline.** And the procedural half that actually saved this: **run the
baselines before the model.** Had the 2.6-hour extraction arm run first, it
would have scored 1.000 on a family a one-line baseline already scored 1.000
on, and the pooled primary would have reported a pass.

That is the fourth time the threshold machinery in this project has been built
wrong (H3's margin exceeded its own ceiling; Phase A's oracle was bounded by
its retrieval budget; Phase B's oracle poisoned its own recipients; and now a
baseline quoted at the wrong k). The pattern across all four is the same: the
error was never in the method under test, always in the apparatus that was
supposed to bound it.

---

## 2. Can a model supply the declarations? Yes — one of these three can

> **§8 supersedes the model ranking here, and §10 corrects the `plain`
> column.** These three were decoded **free-form**, because the client wrapper
> passed no schema, and one of them was a domain fine-tune rather than a
> general instruct model.
>
> More seriously: **an unparseable reply was counted as `plain`**, so the
> `plain` figures below are a floor rather than a measurement — a model that
> simply failed would appear in that column as well behaved. `gemma2`'s and
> `qwen2.5:7b`'s 17/17 are credible on other evidence (both returned usable
> structure elsewhere, so they were parsing), and `finsenti`'s 0/17 is
> unaffected because producing 17 false modifiers requires parsing. The
> numbers are left as measured and re-measured in §10.
>
> What survives unchanged is the point this section was built to make: a
> model's extracted **target** has to be read rather than its class.

19 statements, chosen **using the labels** so the two interesting ones are
included, because a random sample of 500 would spend an hour to reach two. An
extraction-quality measurement, **not** a retrieval arm.

| model | modifier | default | plain (false positives) | seconds each | total |
|---|---|---|---|---|---|
| `gemma2:latest` | **1/1** | **1/1** | **17/17** | 54.5 s | 1,036 s |
| `qwen2.5:7b` | 1/1 | 0/1 | 17/17 | 19.3 s | 368 s |
| `finsenti-llama3.2-1b:latest` | 1/1 | 0/1 | **0/17** | 4.8 s | 91 s |

**`gemma2` is 19/19.** It is also the only one whose output is usable, and the
`modifier` column hides that, because it scores the *class* and not the
*target*. The targets, verbatim, for *"At the depot-12 site, add 0.35 bar to the
axle-set figure as a salt-corrosion margin"*:

| model | extracted target | usable? |
|---|---|---|
| `gemma2:latest` | `'axle-set figure'` | **yes** — matches the predicate `'tyre pressure for the axle set'` |
| `qwen2.5:7b` | `'add'` | no — a verb. No record's predicate is "add" |
| `finsenti-llama3.2-1b` | `'salt-corrosion margin'` | no — the margin is the *reason*, not the thing adjusted |

No usability metric is reported, deliberately: a substring test invented after
seeing these three rejects `'add'` and **accepts** `'salt-corrosion margin'`,
which is wrong for a reason a substring cannot see. Three verbatim strings beat
a metric with one tunable.

**The `plain` column is the one that earned its place.** `finsenti-llama3.2-1b`
is 11× faster than `gemma2` and marks **every one of 17 ordinary statements** a
modifier — `'fuel'`, `'weight'`, `'permit'`, `'adjusts'`. It would inject 17
false `QUALIFIES` edges per 19 memories. An end-to-end score would have shown
this as a mild degradation of unclear origin; the column shows it as what it
is.

> **Corrected 2026-10-13.** This paragraph originally concluded *"a model this
> size is not merely worse at the task, it is unaware there is one"*, which the
> arm does not support: **`finsenti-llama3.2-1b` is a financial-sentiment
> fine-tune**, not a general instruct model, and the name says so. Attributing
> its behaviour to *size* was reading a parameter count off a model that had
> been specialised away from instruction-following. §8 measures general models
> at 1.5B and 3B instead, and a 1.5B one reaches 17/17 on this column.

`qwen2.5:7b` also missed the default outright, classifying *"all yard vehicles
run 2.7 bar in monsoon, except at the harbour and quarry sites"* as a modifier
of `'run'`.

---

## 3. Cost, and the reduced store it forced

The two registered families hold **1,374 unique statements on dev** across five
cases — the fillers dominate, at ~205–486 memories a case. At `gemma2`'s
measured 54.5 s:

| | statements | `gemma2` wall time |
|---|---|---|
| registered families, dev, full size | 1,374 | **20.8 h** |
| both splits | 2,737 | **41.4 h** |
| `multi_hop_4` only, dev, full size | 1,160 | 17.6 h |
| `multi_hop_4` only, dev, reduced to 60/case | **172** | **2.6 h** |

`/api/ps` reports **0 MB VRAM**: the models run on CPU here. So this is
compute-bound, not round-trip-bound, and **neither batching nor concurrency
reduces it** — the fix that took LongMemEval's embedder from 1.0 to 2.1
embeddings/s has no analogue. `OLLAMA_NUM_PARALLEL` is unset and parallel
requests would contend for the same cores.

**Prediction 4 is confirmed, and underestimated.** It said *"at a second a
write, ten thousand memories cost three hours"* and expected that to make
extraction a batch job. The measured figure is 54.5 s a write, so ten thousand
memories cost **151 hours**. Extraction is not an ingest-path step at any
corpus size this project cares about. It is a batch job, and on this hardware a
slow one.

### The reduced store, and what it does and does not license

`--max-corpus 60` keeps every labelled memory and samples the fillers to 60
with a per-case seeded RNG. **Every arm — baseline, declared, oracle — is
recomputed on that same store**, so B and C are measured where the mechanism is
measured.

The size was chosen **before the extraction arm ran**, by sweeping with the
no-model arms and requiring `multi_hop_4` to retain its registered premise:

| corpus/case | baseline `multi_hop_4` | baseline `implied_by_default` | oracle |
|---|---|---|---|
| 60 | 0.000 | **1.000** | 1.000 |
| 100 | 0.000 | **1.000** | 1.000 |
| 150 | 0.000 | 0.500 | 1.000 |
| 200 | 0.000 | **1.000** | 1.000 |
| 300 | 0.000 | **1.000** | 1.000 |
| full (205–486) | 0.000 | **1.000** | 1.000 |

`multi_hop_4` holds its premise at every size. **This sweep is also what
exposed §1**: the `implied_by_default` column was supposed to read 0.000
everywhere.

Two effects of the reduction are reported because both cut toward the
mechanism, not away from it:

- **It is an easier store.** 60 memories against 205–486. The honest direction of that bias is toward the *baseline*, which may rank a memory it misses at full size — and on `multi_hop_4` it does not: 0.000 at every size tried.
- **It rescues the test split's ceiling, and that is a real change.** [relations-ceiling.md](relations-ceiling.md) measured `declared` at **0.000 on test** at full size, because the chain picks the wrong axle rule. At 60 memories there are fewer competing axle rules and `declared` reaches **1.000 on test**. So a test result here is a result on a store where the ceiling exists, which is not the store relations-ceiling measured. No full-size number is claimed from any of this.

| arm | dev @60 | test @60 | (test @ full size, from relations-ceiling) |
|---|---|---|---|
| `baseline` | 0.000 | 0.000 | 0.000 |
| `declared` | 1.000 | **1.000** | **0.000** |
| `oracle` | 1.000 | 1.000 | 1.000 |

---

## 4. The primary: NOT SUPPORTED at 0.000

**Run 2026-10-14**, `gemma2:latest` free-form, dev, `multi_hop_4`, reduced to
60 memories a case. 172 unique statements, **172 model calls, 57,974 tokens,
8,962 s (2.49 h)**.

| arm | sufficiency | nDCG | critical recall |
|---|---|---|---|
| `baseline` | 0.000 | 0.832 | 0.750 |
| **`extraction`** | **0.000** | 0.832 | 0.750 |
| `declared` (ceiling, fixture-supplied) | 1.000 | 1.000 | 1.000 |
| `oracle` | 1.000 | 1.000 | 1.000 |

```
B = 0.000   C = 1.000   bar = B + 0.40 * (C - B) = 0.400
extraction  = 0.000     share of headroom = 0.0%
```

**8b check — did any arm beat the oracle?** No; 1.000 bounds the table.

**The second bar, which §4 of the registration insisted on:** `extraction`
had to recover a meaningful share of what *declared* relations achieve.
Declared relations score 1.000. Extraction recovered **0%** of it, and the
reason is in the next line rather than in the score.

**Relations inferred: 0, against 3 declared.** Recall 0.000, precision
undefined because nothing was proposed. `extraction` did not rank the wrong
memory or propose a wrong edge; it proposed **no edge at all**, in three cases
out of three, having extracted all 172 statements successfully.

So the arm is identical to `baseline` on every metric, to three decimal places,
because the mechanism contributed nothing to the context. The 2.49 hours bought
a set of structured records that the consumer could not use — §11 is why, and
it predicted this exactly, from six model calls instead of 172.

**Prediction 1 is refuted.** It said *"`multi_hop_4` will recover most of the
declared ceiling — `at the depot-12 site, add 0.35 bar to the axle-set figure`
is about as clear a modification as text gets, and a model that cannot see it
cannot see any."* The model **did** see it: `gemma2` extracted
`modifies='axle-set figure'`, which is correct. The prediction was right about
the model and wrong about what seeing it was worth, because it assumed the
matcher could join two correct extractions. §11 is that assumption, measured.

**Prediction 4 is confirmed and was the more useful one.** 8,962 s for three
cases on a deliberately reduced store, to produce zero edges.

### What this run adds over §11

§11 established from six calls that no model forms the edge. This establishes
that the full registered arm, on the full reduced store, with the best
available model and every statement extracted, scores exactly the baseline. It
is worth having measured rather than inferred: an arm that proposes nothing is
distinguishable from an arm that proposes wrongly only by running it, and
`relation_quality` reporting `0 inferred` rather than `0 correct of 12` is the
line that tells those apart.

It is also, at 2.49 hours against roughly nine seconds, an argument for
building the cheap diagnostic first. The edge check was written **after** the
primary was launched.

---

## 5. Prediction 3, and an upside-down AUC found on the way

Prediction 3 said the abstention candidate would not work, and gave a reason
rather than a hunch: LongMemEval's unanswerable cases are *partially*
answerable — *"you mentioned the fence but not the cows"* — so memories about
the subject **do** exist, and *"nothing asserts anything about the subject"* is
the wrong question.

That reason is a claim about the **fixture**, so it can be checked without
extracting anything, which matters because the signal it describes needs
extraction over hundreds of thousands of turns and §3 makes that impossible
here. Harness: `experiments/x1_abstention_premise.py`.

| split | group | n | median turns | top-1 relevance | content-term coverage |
|---|---|---|---|---|---|
| `s` | unanswerable (`_abs`) | 30 | 506 | 1.939 | **0.788** |
| `s` | answerable | 470 | 490 | 2.894 | 0.883 |
| `oracle` | unanswerable (`_abs`) | 30 | 24 | 0.727 | **0.694** |
| `oracle` | answerable | 470 | 22 | 1.007 | 0.757 |

**Prediction 3's premise is confirmed.** On the real `s` haystacks an
unanswerable question's top-10 turns already contain **79% of its distinctive
content terms**. Turns about the subject are there in quantity, so a detector
asking "does anything here assert something about the subject" would answer
*yes* on nearly every unanswerable case. The registered signal was never going
to work, for the reason registered.

### And the thing that was not predicted

Measuring the premise meant recomputing the plain retrieval-score signal on the
same population, and it does not agree with what
[abstention-signals.md](abstention-signals.md) reported:

| figure | published | reproduced |
|---|---|---|
| best F1 | 0.206 | **0.2065** |
| recall / TPR | 0.533 | **0.5333** |
| FPR | 23.2% | **23.19%** |
| precision | 0.128 | **0.128** |
| threshold | 0.2656 | **0.2671** |
| **pooled AUC** | **0.319** | **0.6819** |

Everything reproduces to rounding **except the AUC, which reproduces as its
complement** — `1 - 0.3181 = 0.6819`. The published figure was the probability
that an *unanswerable* instance outscores an answerable one, reported as the
detector's discrimination. The signal is **above** chance, not below it, and it
replicates on the `s` split at **AUC 0.711**, which closes a limit that result
listed as untested.

Two of that document's own numbers were mutually impossible and said so: an
operating point at TPR 0.533 / FPR 0.232 is above the ROC diagonal and cannot
come from a signal at AUC 0.319, and §2's table had the effect in the right
direction in **4 of 4** question types. Principle 8b's last clause —
contradictions in the apparatus's own metrics are the signal — reached from a
new direction: not an arm beating the oracle, but a result disagreeing with
itself.

**The verdict there does not change.** F1 0.206 was correct, and a system that
abstains on 23% of the questions it could answer to catch 53% of those it
should refuse is worse than one that always answers — at AUC 0.682 exactly as
at 0.319. The decision was right on the strength of a number that was upside
down. What changes is the diagnosis: the family is rejected on its **operating
point**, not on its discrimination, and `abstention-signals.md`'s title claim
that pooling destroys the signal is withdrawn (§7 there).

**Why it survived**: that result cited **no harness**, alone among the results
in `research/`. AGENTS.md requires tables to cite the experiment config that
produced them, and the reason is exactly this — a number with no re-runnable
harness cannot be checked by rereading the document. `auc()` now carries
known-answer tests whose first assertion is the direction.

---

## 6. What the mechanism is, and two schema errors found by building it

One model call per **write**, not per **pair** — O(n) rather than O(n²), which
is what makes it tractable at all. Relations are then inferred by matching
records, with no further calls. `StubExtractor` ships for tests and is **not an
arm**: a stub fitted to these fixtures is the pattern problem the registration
declined.

Building it surfaced two errors in my own schema, both of which would have made
the mechanism silently do nothing:

1. **`is_default` required an empty `scope`.** But *"all yard vehicles run 3.9 bar in winter, except at the harbour and quarry sites"* is scoped to a **season** and excepts two **sites**, and all three models reported the season as scope. Exclusions make a default, not the absence of scope.
2. **`applies_to` required the query to name a scope entity.** Same conflation, second half: `scope` mixes dimensions, and a caller's `entities` are units and sites, never seasons. Every default was therefore inapplicable. A test caught it; an end-to-end run would have reported it as *"extraction does not help"*.

A third was in the harness rather than the schema: `infer_relations` matched
`modifies` against `predicate` by containment, so `'axle-set'` never met
`'tyre pressure for the axle set'`. The corpus writes the compound both ways,
so hyphens and underscores now collapse before the comparison.

And one in the cache, found by a test written after the run started: JSON has
no tuples, so a **resumed** run held lists where a fresh run held tuples on a
frozen dataclass — the records would compare unequal and hash differently, and
"resume the cache" would quietly have stopped being the same measurement as
"run it again".

---

## 7. Limits

- **One model per conclusion.** `gemma2`'s 19/19 is 19 statements, two of them the interesting ones. It is evidence the structure is extractable, not a precision/recall estimate.
- **Statements chosen with the labels.** §2 is an extraction-quality measurement and is not scored as retrieval anywhere.
- **These fixtures state things plainly.** A real corpus does not, and nothing here measures an extractor on content it finds ambiguous.
- **The reduced store is not the product's store.** §3 says what it licenses.
- **The registered `must_not_expose_rate` gate is vacuous here, and reporting 0.000 for it would be misleading.** §5 of the registration makes any non-zero value a run failure. On `multi_hop_4` the `must_not_expose` label is **empty in all six cases** and **nothing in any corpus is gated** by lifecycle, tenant or capability — so the rate is 0.000 by construction and carries no safety evidence. The families that exercise that gate (`gated` in relevance_v2) are not in X1's scope. The field was also missing from the harness summary for the first dev run: a registered pass/fail condition that is not printed is not checked, however the gate pipeline behaves structurally.
- **No-regression is unmeasured.** §5 of the registration requires it on `relevance_v2` both splits, `facet_v1`, SciFact and LongMemEval's oracle split. Each needs extraction over the whole corpus, which §3 prices at 20.8 hours a split. Extraction is off by default and adds edges only when `use_extraction=True`, so nothing ships that could regress — but the check itself is not done, and that is a gap rather than a reason.
- **Prediction 3's premise is confirmed; the registered signal itself is not measured.** §5 shows subject-relevant turns are present in the unanswerable cases, which is the reason the signal would fail. It does not run an extraction-based detector over LongMemEval, and §3 says why that is not possible here.
- **The abstention numbers are lexical.** A trained embedder's score distribution could calibrate differently, as `abstention-signals.md` limit 2 already noted; the correction in §5 is to the arithmetic, not to the retrieval.
- **R6's warning still stands** for anything downstream. Nothing here measures whether an agent given a structurally-indexed context answers better.

## 8. Choosing a model, and where the latency floor actually is

**Added 2026-10-13.** §2 compared three models, one of which was
mis-specified (above) and all three of which were decoded **free-form**. Both
gaps are closed here, and two things move: **the binding constraint is the
hardware**, not the model; and **schema-constrained decoding, which I added
believing it was the fix, changes no accuracy and costs ~50% more wall time.**
The model choice that remains is a 5.8× speedup against one error, in the
family the primary needs.

### Decoding was never constrained — and constraining it does less than I claimed

Ollama enforces a JSON schema **during** sampling. The client wrapper did not
pass one, so every figure in §2 came from a model free-forming its way to JSON
with `parse()` cleaning up after it. `memory_fabric/extraction.py` now defines
`SCHEMA`, and the unconstrained path is kept so the two modes can be compared.

The first constrained call looked decisive: **`qwen2.5:1.5b` returned
`modifies: "axle-set figure"`** — the correct, usable target that `qwen2.5:7b`
got wrong free-form (`'add'`) and that only the 9B `gemma2` had produced. I
wired constraint on as the default and wrote into two docstrings that
constraining the shape was *"both the accuracy fix and the cost fix"*.

**Then I ran the control, and it is neither.** Same 19 statements, same two
models, both modes:

| model | mode | modifier | default | plain | extracted target | s each |
|---|---|---|---|---|---|---|
| `qwen2.5:7b` | free-form | 1/1 | 0/1 | 17/17 | `'add'` | 19.3 s |
| `qwen2.5:7b` | **constrained** | 1/1 | 0/1 | 17/17 | `'add'` | **29.8 s** (+54%) |
| `gemma2` | free-form | 1/1 | 1/1 | 17/17 | `'axle-set figure'` | 54.5 s |
| `gemma2` | **constrained** | 1/1 | 1/1 | 17/17 | `'axle-set figure'` | **81.3 s** (+49%) |

Identical classifications and identical targets, at half again the wall time.
`qwen2.5:7b` returns the useless `'add'` under the schema exactly as it does
without it. **So the 1.5B model's good target was a property of that model, not
of the constraint** — a conclusion drawn from one observation and refuted by
the control that observation should have prompted first. The docstrings are
corrected to the narrower ground that survives: a guaranteed shape means
`parse()` never has to recover from prose, which removes an ingest-path failure
mode without changing what the measured models extract.

This is the same error as §1, in miniature and committed by the same hand on
the same day: a number that pointed the way I wanted, accepted before the arm
that would have bounded it was run. §1's version cost a registration; this one
cost a default setting and two docstrings.

### Measured, schema-constrained, models warmed first

19 statements, same sample as §2. Warming matters and was also missing before:
a cold load is 20–35 s against a per-call figure in seconds, so without it the
first statement of each model carries the load.

> **The `plain` column here carries the same flaw as §2's and is re-measured
> in §10.** An unparseable reply classified as `plain`. `llama3.2:3b`'s 3/17
> is unaffected in direction — it was producing modifiers, so it was
> parsing — and the two Qwen figures are the ones to treat as floors.

| model | params | modifier | default | plain | s each | vs `gemma2` |
|---|---|---|---|---|---|---|
| `qwen2.5:1.5b` | 1.5B | 0/1 | **1/1** | **17/17** | **9.4 s** | **5.8× faster** |
| `qwen2.5:3b` | 3.1B | **1/1** | **1/1** | 14/17 | 15.0 s | 3.6× faster |
| `llama3.2:3b` | 3.2B | **1/1** | **1/1** | 3/17 | 16.5 s | 3.3× faster |

Three things worth separating:

- **`qwen2.5:1.5b` is 18/19 at 9.4 s** and gets the *default* right, which the 7B model failed free-form. Its one error is the modifier: it extracts the right target and then reports `asserts: true`, so `is_modifier` is false. That is the family `multi_hop_4` needs, so the error is in the worst possible place for the primary.
- **`qwen2.5:3b` gets both interesting statements** and pays with 3 false positives on ordinary ones.
- **`llama3.2:3b` is unusable at 3/17**, and this is the honest replacement for the claim §2 made about size: a *general* 3B model from a different family still marks 14 of 17 ordinary statements as modifiers. The failure tracks the family, not the parameter count — both Qwen sizes are fine on that column and both Llamas are not.

### The latency floor is the hardware

`/api/ps` reports **0 MB VRAM** and the machine has **no discrete GPU** —
`Win32_VideoController` lists only Intel Iris Xe integrated graphics, which
Ollama does not meaningfully accelerate. Every figure here is CPU inference.

So the search for a lower-latency model has a floor that no model choice
crosses: the fastest configuration that extracts correctly on this hardware is
**~9–15 s a statement**, three to five orders of magnitude away from the
sub-second cost that would make extraction an ingest-path step.

| configuration | s/statement | 1,160 statements (`multi_hop_4` dev, full) | 10,000 memories |
|---|---|---|---|
| `gemma2`, free-form | 54.5 | 17.6 h | 151 h |
| `qwen2.5:3b`, constrained | 15.0 | 4.8 h | 42 h |
| `qwen2.5:1.5b`, constrained | 9.4 | **3.0 h** | 26 h |

**The product conclusion does not change, and now rests on something firmer
than one model.** Prediction 4 said cost would make extraction a batch job.
A 5.8× speedup moves 151 hours to 26 and leaves the conclusion exactly where
it was. What changes is the *reason*: it is no longer "the only model that
works is slow" but "this hardware runs every model that works at seconds per
statement, and the fix is a GPU or a hosted endpoint, not a smaller model".

### What this does not settle

- **Only locally available models were measured.** Newer small models (Gemma 3, Qwen 3 at 1.7B/4B) are not installed, and published comparisons do not settle the 1–4B range for schema-guided extraction — the one small-model report found at this size measures JSON *parse rate* on a generation task rather than field accuracy on extraction. Pulling them is a download and has not been done.
- **19 statements.** Every caveat in §2 applies unchanged: this is evidence about extractability and model ranking, not a precision/recall estimate.
- **One quantisation each.** All local models are Q4 except `gemma2` (Q4_0) and `llama-guard3` (Q8_0, unused). The one published small-model result found parse rates differing noticeably between quantisations of the same model, so a Q8 `qwen2.5:1.5b` is an untested and plausible improvement.

---

## 9. Tracing every model call

AGENTS.md requires LLM calls to go through one wrapper logging model, prompt
hash, token counts and cost. `OllamaClient.calls` is that ledger and remains
the record of truth; `memory_fabric/adapters/tracing.py` adds exporters on top
of it, registered with `client.add_sink()`.

- **`JsonlSink`** — one JSON object per call, appended. **No dependencies**, because CI runs this project with none installed and the zero-dependency claim is only true if it is checked. Both X1 harnesses take `--trace PATH`.
- **`LangfuseSink`** — the same records to Langfuse, with the SDK imported lazily so an absent package is a clear error at construction rather than an import failure in the fabric.

**Content is off by default on both, and `CallRecord` is why.** It stores a
hash of the prompt rather than the prompt, and its own docstring gives the
reason: a prompt here contains memory content, which may contain exactly what
the governance layer exists to keep out of secondary surfaces. **A trace
exporter is a secondary surface**, and Langfuse's default host is a service
this project does not run. So:

- metadata only unless `send_content=True`;
- with content **and** a non-local host, construction **fails** unless `allow_remote_content=True` — enabling that is the one place in this project where memory content crosses a network boundary on purpose;
- with content enabled, the project's own sensitive-data detector runs over every string before it leaves the process and the content is dropped entirely if anything is found. Dropped rather than redacted, because a partial redaction is a guess about which half mattered. This is a mitigation, not a guarantee: a detector that catches credentials does not catch a customer's name in a sentence.

A sink cannot break the call it observes — every sink is wrapped, and a raising
sink leaves the ledger intact, which is tested.

**One bug found by its own test.** `_is_local` first matched substrings, so
`https://localhost.evil.com` passed as local and would have carried memory
content to someone else's host **without** the `allow_remote_content` gate that
exists to make that deliberate. The hostname is now parsed and compared
exactly. A containment check is the wrong tool for an authorisation boundary,
which is the same lesson [p2b-copy-recognition.md](p2b-copy-recognition.md)
reached about Jaccard from the other direction.

---

## 10. Seven models, both decoding modes, and the column that was lying

**Added 2026-10-13.** §2 and §8 are superseded by this section, which fixes
three measurement faults at once: an unparseable reply counted as `plain`, a
reasoning model's truncated replies were scored as answers, and no model had
been measured in both decoding modes except the two in §8.

Seven models × two modes × the same 19 statements, warmed, reasoning traces
off. `unparsed` and `truncated` are now separate columns.

### Schema-constrained

| model | modifier | default | plain | unparsed | s each |
|---|---|---|---|---|---|
| `gemma2:latest` | **1/1** | **1/1** | **17/17** | 0 | 75.0 |
| `qwen2.5:7b` | **1/1** | 0/1 | **17/17** | 0 | 15.9 |
| `gemma3:4b` | 0/1 | **1/1** | **17/17** | 0 | 14.9 |
| `qwen2.5:1.5b` | 0/1 | **1/1** | **17/17** | 0 | **4.2** |
| `qwen2.5:3b` | **1/1** | **1/1** | 14/17 | 0 | 8.1 |
| `qwen3:1.7b` | **1/1** | **1/1** | 9/17 | 0 | 8.2 |
| `llama3.2:3b` | **1/1** | **1/1** | 3/17 | 0 | 6.6 |

### Free-form

| model | modifier | default | plain | unparsed | s each |
|---|---|---|---|---|---|
| `gemma2:latest` | **1/1** | **1/1** | **17/17** | 0 | **47.5** |
| `qwen2.5:7b` | **1/1** | 0/1 | **17/17** | 0 | 17.6 |
| `gemma3:4b` | 0/1 | **1/1** | **17/17** | 0 | 16.8 |
| `qwen2.5:1.5b` | 0/1 | **1/1** | **17/17** | 0 | **4.0** |
| `qwen2.5:3b` | **1/1** | **1/1** | 15/17 | 0 | 7.9 |
| `qwen3:1.7b` | **1/1** | **1/1** | 11/17 | 0 | 7.9 |
| `llama3.2:3b` | **1/1** | **1/1** | 12/17 | 0 | 7.1 |

**`unparsed` is 0 in all fourteen runs, so §2's and §8's `plain` figures were
floors that happened to be tight.** They were not wrong; they were
unfalsifiable, and that is a different defect. The flag stays on those tables
because a reader cannot tell a tight floor from a loose one by looking.

### The constraint question, now with seven models instead of two

§8 found identical accuracy and +49–54% time on two models. Across seven, the
conclusion holds and sharpens: **constraint never improves a figure, and on
three models it makes the `plain` column worse** — `llama3.2:3b` 12/17 → 3/17,
`qwen3:1.7b` 11/17 → 9/17, `qwen2.5:3b` 15/17 → 14/17. `gemma2` costs **58%
more** under it (47.5 s against 75.0 s).

The mechanism is visible in the targets: constrained, `llama3.2:3b` must emit
`modifies` as a string and fills it for ordinary statements rather than
returning `null`. **A schema that permits a field does not stop a model
filling it in, and forcing the shape makes a model *more* willing to guess.**
That is the opposite of what I expected when I made it the default, and it is
now `constrained=False` for the measured path.

### The truncation column earns its place immediately

`qwen3:1.7b` is a reasoning model. With its reasoning trace **on** — the
server default, and what every figure measured before this flag existed used:

| run | modifier | default | plain | unparsed | truncated | s each |
|---|---|---|---|---|---|---|
| thinking **off** | 1/1 | 1/1 | 9/17 | 0 | 0 | 8.2 |
| thinking **on** | 0/1 | 0/1 | **0/17** | **19** | **19** | 26.6 |

It spends the whole 220-token budget reasoning and never emits the object, on
**19 of 19** statements. **Under the old classifier this exact configuration
scored `17/17` on `plain`** — a complete failure recorded as a model behaving
impeccably, because an unparseable reply had no target and no exclusions and so
read as an ordinary statement. The two columns added in §10 turn that into 19
unparsed and 19 truncated, which is what it was.

This is the clearest thing in the result about method: **the harness scored
silence as success for the majority class.** A benchmark whose failure mode is
indistinguishable from its most common correct answer cannot detect the
failure, and nothing but a deliberate check for "did the model actually reply"
would have caught it. The fixture was fine; the scorer was not.

### What this means for model choice

Only the *class* is tabulated above, and the primary needs the **edge**: the
modifier's extracted `modifies` must meet another memory's extracted
`predicate`, with both sides produced by the model. `§11` measures that
directly, because judging it from the target string was wrong twice —
`'axle-set figure'` reads like the right answer and is not contained in
`'tyre pressure for the axle set'` either way round, while the vaguer
`'tyre pressure'` is.

---

## 11. Not one of seven models produces the edge, and the models are not why

**This is the result.** The primary needs one `QUALIFIES` edge:
[relations-ceiling.md](relations-ceiling.md) measured that it takes
`multi_hop_4` from 0.000 to **1.000**. `infer_relations` builds it by matching
a modifier's extracted `modifies` against a stated memory's extracted
`predicate`. Both sides come from the model.

Measured on the real pair — `h4` *"At the depot-12 site, add 0.35 bar to the
axle-set figure as a salt-corrosion margin"* and `h3` *"Vehicles with the
standard axle set run 4.0 bar in summer"* — harness
`experiments/x1_edge_check.py`:

| model | `modifies` from h4 | `predicate` from h3 | edge | why not |
|---|---|---|---|---|
| `gemma2:latest` | `'axle-set figure'` | `'tyre pressure'` | **no** | no containment either way |
| `qwen2.5:7b` | `'add'` | `'tyre pressure'` | no | target is a verb |
| `llama3.2:3b` | `'axle-set figure'` | `'axle set'` | no | called h3 a non-assertion |
| `gemma3:4b` | `'tyre pressure'` | `'tyre pressure'` | no | called h4 an assertion |
| `qwen3:1.7b` | `'salt-corrosion margin'` | `'tyre pressure'` | no | target is the reason, not the quantity |
| `qwen2.5:3b` | `'bar'` | `'tyre pressure'` | no | target is a unit; h3 a non-assertion |
| `qwen2.5:1.5b` | `'add'` | `'run'` | no | both are verbs |

**Zero of seven.** And the top row is the finding: `gemma2` extracts **both
sides correctly**. The modifier *does* adjust the axle-set figure. The
assertion's predicate *is* tyre pressure. A human reads the link immediately,
because an axle-set figure is a tyre pressure for the axle set — and that is a
**semantic** relation, not a lexical one. String containment cannot represent
it, so the mechanism fails on correct inputs.

### The matcher was fitted to my phrasing, and a unit test hid it

The registration's central argument for using a model was that the earlier
refusal to build a *pattern* extractor did not transfer:

> *I declined to build a pattern extractor because the target text is this
> project's own generated phrasing, so a regex for "except at the … and …
> sites" would pass by construction and measure its own fit. **A
> general-purpose model is not fitted to my phrasing**, so the objection does
> not transfer. The circularity was a property of the pattern.*

That is right about the extractor and **wrong about the mechanism**, because
`infer_relations` is a pattern too — a containment test over strings — and its
unit test supplied both of those strings. It asserts an edge from
`modifies="axle-set"` against `predicate="tyre pressure for the axle set"`.
Measured against the four combinations of {hand-written, model-produced} ×
{target, predicate}:

| target | predicate | match |
|---|---|---|
| `'axle-set'` *(mine)* | `'tyre pressure for the axle set'` *(mine)* | **yes** |
| `'axle-set figure'` *(measured)* | `'tyre pressure for the axle set'` *(mine)* | no |
| `'axle-set'` *(mine)* | `'tyre pressure'` *(measured)* | no |
| `'axle-set figure'` *(measured)* | `'tyre pressure'` *(measured)* | no |

**One of four, and it is the one where I chose both halves.** The fixture is
not approximately right; both sides are load-bearing. My target was shorter
than any model produces and my predicate longer, and the two errors met in the
middle. `tests/test_extraction.py` now pins all four, so the next change to
the matcher has to confront this rather than rediscover it.

So the circularity did not go away when the extractor became a model. **It
moved to the step after it**, where nothing was looking, and the registration's
own argument explains exactly why that step was the dangerous one.

### What follows

- **The registered primary cannot pass with this matcher**, and the reason is in the matcher. §4 reports the measured arm.
- **A repair is not in scope here.** Matching the target against the other memory's *content* instead of its predicate, or matching with an embedder, or extracting a relation per *pair*, are all plausible and all post-hoc. Choosing one after seeing which failure to fix, and then reporting the result as the registered primary, is fitting the mechanism to the test — the thing §1 and this section are both about. Any of them needs its own registration.
- **The extraction half is vindicated and that is worth separating.** The registration asked whether a model could supply the declarations. On the evidence of `gemma2`: **yes** — 19/19 classes, zero unparsed, and both sides of this relation extracted correctly. The failure is downstream of the question the registration asked.

---
