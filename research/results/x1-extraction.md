# X1 — extraction at ingest: the registration was invalid, and the cost decides the product

**Three findings, and two of them are about this project's own apparatus
rather than about extraction.**

1. **The registered primary metric was trivially maximised by a registered baseline, and the 8c check that exists to catch exactly that was performed and answered wrongly.** `B = 0.000` was quoted from a table reporting a *different metric at a different budget*. On the registered metric a plain lexical baseline scores **1.000** on one of the two registered families. The family is abandoned under the registration's own clause. This was found by running the baselines before the model, and it is now [principle 8d](../../AGENTS.md).
2. **A model can supply the declarations, and the cost is the product conclusion.** `gemma2` classified **19/19** statements correctly with usable targets. It costs **54.5 s each** on this hardware, which runs it on CPU — **20.8 hours** for one arm of one split at full corpus size. Prediction 4 of the registration said the cost would make extraction a batch job rather than an ingest-path step. It does, and by a wider margin than the prediction assumed.
3. **Checking prediction 3 found a published AUC reported as its own complement.** `abstention-signals.md`'s pooled AUC is **0.682, not 0.319** — above chance, not below. Every other figure in that result reproduces exactly. Its practical verdict survives untouched, which means the right decision was reached on the strength of a number that was upside down. It cited no harness, which is why it survived; there is one now.

- **Registration:** [x1-extraction-at-ingest.md](../prereg/x1-extraction-at-ingest.md), amended in §8 before any model call of the primary arm
- **Mechanism:** `memory_fabric/extraction.py`, `MemoryFabric.index_extraction()`, `applicable_defaults()`, `infer_relations()`
- **Harnesses:** `experiments/x1_extraction_quality.py` (extraction quality), `experiments/x1_extraction.py` (the retrieval arms), `experiments/x1_abstention_premise.py` (prediction 3, and §5's correction)
- **Runs:** 2026-10-13, `gemma2:latest` / `qwen2.5:7b` / `finsenti-llama3.2-1b:latest` via Ollama, k=5
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

## 2. Can a model supply the declarations? Yes — one of the three can

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
is. A model this size is not merely worse at the task, it is unaware there is
one.

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

## 4. The primary

_Pending: the `extraction` arm, `gemma2:latest`, dev, `multi_hop_4`, reduced to
60 memories a case. 172 unique statements, ~2.6 h._

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
- **Prediction 3's premise is confirmed; the registered signal itself is not measured.** §5 shows subject-relevant turns are present in the unanswerable cases, which is the reason the signal would fail. It does not run an extraction-based detector over LongMemEval, and §3 says why that is not possible here.
- **The abstention numbers are lexical.** A trained embedder's score distribution could calibrate differently, as `abstention-signals.md` limit 2 already noted; the correction in §5 is to the arithmetic, not to the retrieval.
- **R6's warning still stands** for anything downstream. Nothing here measures whether an agent given a structurally-indexed context answers better.
