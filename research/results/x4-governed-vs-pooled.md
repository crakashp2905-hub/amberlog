# X4 — ABANDONED: perfect memory selection is worth 5 points here, so there is nothing to win

**Every correction rate is abandoned on degenerate headroom, under the
registration's own clause.** The oracle — perfect filtering, same budget, same
corrections — scores **0.650** against a plain pooled vector store's
**0.600** at rate 0, and **0.608 against 0.583** at both non-zero rates.
Headroom of **0.050, 0.025, 0.025**, against an abandonment threshold of 0.05.

So the registered question cannot be answered in this world, and §4 of the
registration said what that means before the run: **the product claim is
unfalsifiable here rather than false.** `fabric_governed` scored 0.567, 0.567
and 0.583 — but those numbers are not evidence either way, because no
mechanism could have passed a bar set as a share of 2.5 points.

**The finding is the headroom itself.** In DepotWorld, knowing which lessons
are wrong for the episode is worth **at most 5 points** over cosine
similarity. That is a stronger and more general statement than PA′'s: not
"withdrawal loses" but **"selection has almost nothing to win here at all"**.

- **Registration:** [x4-governed-vs-pooled.md](../prereg/x4-governed-vs-pooled.md)
- **Harness:** `experiments/x4_governed_vs_pooled.py`, reusing DepotWorld, PA′'s corpus, scoring and release schedule
- **Run:** 2026-10-14, `qwen2.5:3b` + `nomic-embed-text`, 5 seeds × 24 episodes × 3 rates, **1,746 calls, 520,730 tokens, 6,205 s (1.72 h)**
- **Raw:** [x4-run.json](x4-run.json)

---

## 1. The table

| arm | rate | success | right memory in context | wrongly removed | retractions |
|---|---|---|---|---|---|
| `no_memory` | — | 0.092 | 0.000 | — | — |
| `oracle` | 0.0 | **0.650** | 0.600 | — | — |
| `shared_memory` | 0.0 | 0.600 | 0.600 | 0 | — |
| `shared_memory_delete` | 0.0 | 0.600 | 0.600 | 0 | — |
| `fabric_governed` | 0.0 | 0.567 | **0.642** | — | 0 |
| `oracle` | 0.5 | **0.608** | 0.600 | — | — |
| `shared_memory` | 0.5 | 0.583 | 0.600 | 0 | — |
| `shared_memory_delete` | 0.5 | 0.583 | 0.600 | **1** | — |
| `fabric_governed` | 0.5 | 0.567 | **0.642** | — | 8 |
| `oracle` | 1.0 | **0.608** | 0.600 | — | — |
| `shared_memory` | 1.0 | 0.583 | 0.600 | 0 | — |
| `shared_memory_delete` | 1.0 | 0.583 | 0.600 | **4** | — |
| `fabric_governed` | 1.0 | 0.583 | **0.633** | — | 14 |

| rate | C (oracle) | B (best pooled) | headroom | verdict |
|---|---|---|---|---|
| 0.0 | 0.650 | 0.600 | **0.050** | abandoned |
| 0.5 | 0.608 | 0.583 | **0.025** | abandoned |
| 1.0 | 0.608 | 0.583 | **0.025** | abandoned |

**`ceiling` passes at all three rates** — no arm beat the oracle, which the
pilot's version of this arm did not manage and which the fix in §5 was for.
`baseline_max` fails at all three, and that failure is the result.

## 2. Nothing here is distinguishable from noise

Per-seed delta, `fabric_governed` minus `shared_memory`:

| rate | per-seed | mean | sd |
|---|---|---|---|
| 0.0 | −5, 0, −8, −13, +9 | −3.4 | 8.4 |
| 0.5 | −13, +9, −4, −9, +9 | −1.6 | 10.2 |
| 1.0 | −4, 0, −4, +4, +5 | **+0.2** | 4.3 |

And the spread of the **baseline alone** across seeds, at rate 0: 67, 33, 62,
75, 62 — a **42-point range**. Seed-to-seed variance swamps every arm
difference by an order of magnitude. Five seeds is what AGENTS.md requires and
it is nowhere near enough to separate arms 2 points apart; nothing short of a
different world would be.

## 3. The predictions, scored

1. **"At rate 0, `fabric_governed` ties `shared_memory` within noise."** **Held.** −3.4 points, sd 8.4, and the registration's near-neutrality condition passed (`rate_zero_near_neutral: True`). Governance costs nothing measurable when idle — which was the thing I most wanted to know and the one clause the registration required rather than merely reported.
2. **"`fabric_governed` beats both pooled arms at rate 1.0."** **Refuted.** It ties, +0.2 points.
3. **"`shared_memory_delete` beats `shared_memory`, and still loses to the fabric."** **Refuted twice.** The two pooled arms are *identical* at every rate, to four decimals. Deletion changed no outcome at all — even though it **mis-deleted 4 of 14 corrections** at rate 1.0, which confirms the mechanism the prediction named while showing it did not matter.
4. **"The crossover is near rate 0."** **No crossover exists.**
5. **"This will not revive Phase A's claim."** **Held**, and more completely than intended: it does not refute it either.

## 4. The one signal worth a follow-up, reported as a signal

`fabric_governed` puts the correct lesson in context **more often** than any
pooled arm — 0.642 against 0.600 at rates 0 and 0.5, 0.633 against 0.600 at
rate 1.0 — and converts it into a correct answer **equally or less** often.
Consistent in direction at all three rates.

That dissociation has a candidate cause and it is not governance: the governed
arm renders context through `build_context`, with provenance and caveats, while
the pooled arms use `render_plain`. [R6](r6-downstream.md) measured the related
effect and it is the one R6 finding that survived its frozen split — stuffing a
context makes this class of model *less* willing to abstain.

**The oracle shows the same thing from another direction.** Its score *falls*
when corrections are added: 0.650 at rate 0 against 0.608 at rates 0.5 and 1.0.
Perfect filtering plus two extra documents is worse than perfect filtering.
The correction text mildly harms every arm that receives it.

So the hypothesis worth registering next is **about rendering, not about
memory**: does the provenance-and-caveats presentation cost accuracy at equal
retrieval? It is cheap to test — one arm, same corpus, plain rendering — and it
is stated here as a hypothesis rather than a finding, because this run was not
designed to isolate it and 5 seeds cannot resolve 4 points.

## 5. What the pilot cost and bought

The pilot failed `ceiling`: `shared_memory` at rate 1.0 beat the oracle,
1.000 against 0.917. The cause was mine and it is **Phase A's amendment 3
recurring from the other side.** That amendment fixed an oracle that showed
one memory where every arm showed three. Here the correction stream handed
every *other* arm an explicit *"disregard that lesson"* and the oracle, which
only filters, never saw the text — an arm with information the ceiling lacks is
not bounded by it. The oracle is now swept with the arms and receives the same
corrections, keeping only its real advantage. `ceiling` passes on the full run.

The pilot also reported headroom 0.000 and *looked* like this result. It was
not representative and said so on its face: `shared_memory` scored 0.917
against PA′'s published 0.608. Twelve episodes, and a seed with 2 poisoned
lessons of 18 where a 0.25 rate predicts ~4.5. **The registered run has real
headroom — 2.5 to 5 points of it — and that is still too little.**

## 6. What this settles, and what it does not

**Settles:** the registered question is unanswerable in DepotWorld, because
the world's own ceiling is 2.5–5 points above a vector store. Any future
memory-selection experiment in this world is subject to the same limit, and
measuring the ceiling first — as 8a requires — would have shown that before
1.72 hours of inference. **That is the operational lesson: this world is
exhausted for selection questions.**

**Does not settle:** whether the recommended configuration beats a pooled
store. That claim is still open, and X4 is evidence about the *venue* rather
than about the claim. Answering it needs a world where memory selection is
worth more than 5 points — which means contradictions the model cannot resolve
from context ([H4b](../SCORECARD.md)'s territory, where the effect was 0.905 →
1.000), or corrections whose *target* is ambiguous, or a corpus large enough
that similarity genuinely fails.

**And it does not revive or re-kill Phase A.** PA and PA′ measured withdrawal
losing by 30 points, which is far outside this world's noise and stands. X4
asked a narrower question and returned "not here".
