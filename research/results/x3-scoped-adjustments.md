# X3 — scoped adjustments: dev 0.000 → 1.000, and X1's null result explained

**SUPPORTED on dev. Test abandoned in advance.** Admitting a site-scoped
*adjustment* the way a default is admitted takes `multi_hop_4` from **0.000 to
1.000** sufficiency on dev, 3 cases of 3, with critical recall 0.750 → 1.000.
The registered bar was 0.400.

**And it explains X1.** X1's registered primary scored
[0.000](x1-extraction.md) with *correct* extractions, and the reason was not
only the matcher that §11 there identifies. `gemma2` extracted
`modifies='axle-set figure'` **and** `scope=('depot-12',)` — everything needed
— and no code path could consume it: `_admit_defaults` admitted records with
**exceptions** only, so a record with a scope and no exceptions was
unreachable. With that gap closed, **X1's own `extraction` arm, same model,
same records, scores 1.000 on dev.**

- **Registration:** [x3-scoped-adjustments.md](../prereg/x3-scoped-adjustments.md), threshold set as a share of a ceiling measured before the mechanism was written
- **Mechanism:** `Extracted.is_adjustment`, `applicable_adjustments()`, `MemoryFabric._admit_defaults`
- **Harness:** `experiments/x1_extraction.py`, arms `adjust_declared` and `adjust_extracted`
- **Runs:** 2026-10-14, `relevance_v2` `multi_hop_4`, 3 cases a split, k=5, `gemma2:latest` free-form
- **Off by default**, like all extraction: `retrieve(use_extraction=True)`

---

## 1. The numbers

**dev, full corpus (486 memories a case), fixture-declared records**

| arm | sufficiency | critical recall |
|---|---|---|
| `baseline` | 0.000 | 0.750 |
| **`adjust_declared`** | **1.000** | **1.000** |
| `oracle` | 1.000 | 1.000 |

```
B = 0.000   C = 1.000   bar = 0.400   measured = 1.000   headroom claimed = 100%
```

**test, full corpus** — `baseline` 0.000, `adjust_declared` 0.000, critical
recall 0.417 → 0.667. Abandoned in §3 of the registration before the run,
because the ceiling there is 0.000: the chain retrieves the wrong *sibling*
rule (`c0064`, `c0069`, `c0063` instead of `h3`), so the context is missing a
different memory and no admission rule can supply it.

**dev, reduced to 60 memories a case, model-extracted records**

| arm | sufficiency | critical recall |
|---|---|---|
| `baseline` | 0.000 | 0.750 |
| `adjust_declared` | 1.000 | 1.000 |
| **`adjust_extracted`** | **1.000** | **1.000** |
| `extraction` (X1's arm) | **1.000** | **1.000** |
| `oracle` | 1.000 | 1.000 |

**Prediction 2 confirmed**: `adjust_extracted` equals `adjust_declared`
exactly, so extraction quality is not the limiting factor. The 172 cached
`gemma2` extractions from X1's primary were reused, so this costs nothing and
measures the same records that scored 0.000 there.

**8b check:** no arm exceeds the oracle on any run. On test the
`adjustment_ceiling` check **fails by design** — the declared-admission arm
sits below the oracle there, which is exactly the registered reason test was
abandoned, and the check saying so on every run is the point of it.

## 2. Why a relation could never have worked

The corpus holds **twelve** adjustments differing only by site name:

```
At the harbour  site, add 0.45 bar to the axle-set figure as a salt-corrosion margin.
At the depot-7  site, add 0.45 bar to the axle-set figure …
At the depot-12 site, add 0.35 bar to the axle-set figure …   <- the answer
… nine more
```

An adjustment therefore does **not** qualify one rule rather than another —
all twelve qualify every axle rule equally — and which applies is a property
of the **query's** entities. That is not expressible as a memory-to-memory
edge, for the same reason `EXCEPTS` could not express a default whose
exception names a *site* rather than a memory
([relations-ceiling §3](relations-ceiling.md)).

So X1 built the wrong consumer **twice**: a relation matcher that cannot
represent the thing, and an admission path that excluded the record shape it
had just extracted correctly. §11 of that result is about the first. This is
the second, and it is the one that mattered — the family never needed a
relation at all.

## 3. Three defects in the admission path, and the one that was self-revealing

The mechanism is one condition. Getting it to work found three faults in code
that already shipped, and the third is the interesting one.

**It only admitted records with exceptions.** A scoped adjustment has a scope
and no exceptions. One condition, and the reason X1 scored 0.000.

**It appended admitted records below the entire candidate pool.** The pool is
`max(k * 4, k)` and the policy then exposes the top `k`, so an admitted
memory was ranked 21st of 21 at k=5 and could never be exposed. **The
mechanism was inert in any store large enough to have a pool**, and its unit
test passed because that store held *one memory*. This had been true since
defaults were added, which means the `implied_by_default` mechanism never
worked either, in any measured arm.

An admitted record is now placed just above the weakest candidate that would
otherwise be exposed. That makes a design claim worth stating rather than
burying: **an applicable rule is worth more than the k-th similarity match.**
At most `k − 1` are admitted, so at least one similarity match survives.

**It promoted only records that similarity had missed entirely.** The
appending version skipped records already in the pool, so a record ranked 6th
of 60 — inside the pool of 20, outside the exposed 5 — kept its losing score,
while the *same record* in a larger store ranked below the pool, counted as
new, and was admitted.

**The symptom was a sufficiency that went down as the corpus grew: 1.000 at
486 memories and 0.333 at 60.** A mechanism that helps more on a harder store
is not a mechanism, and the non-monotonicity is what exposed it. It is now
consistent at 60, 300 and 486.

That is the kind of fault worth naming a habit around. It was invisible in
every arm's score, visible immediately in a two-size comparison, and it cost
nothing to check.

## 3a. No-regression, as §5 of the registration requires

The admission path is shared with defaults, so changing it could move any arm
that enables extraction, and the gate ordering matters for `must_not_expose`.
Measured after the change, `dev`:

| benchmark | arm | nDCG | published | `must_not_expose_rate` |
|---|---|---|---|---|
| `relevance_v2` | `lexical` | 0.654 | — | 0.000 |
| `relevance_v2` | `store_lexical` | **0.8066** | **0.807** | 0.000 |
| `relevance_v2` | `chain` | 0.8733 | — | 0.000 |
| `relevance_v2` | `oracle` | 1.000 | 1.000 | 0.000 |
| `facet_v1` | `lexical` | **0.250** | **0.250** | 0.000 |
| `facet_v1` | `store_lexical` | 0.250 | 0.250 | 0.000 |

`store_lexical` matches [relevance-v2-ceiling.md](relevance-v2-ceiling.md)'s
0.807 to three decimals, and `facet_v1`'s 0.250 is exactly the mean of its
documented 1.000 stated control and three 0.000 implied families. **No arm
moved, and `must_not_expose_rate` is 0.000 everywhere**, which is the gate
condition that fails a run.

Nothing moved because extraction is off unless a caller asks: the admission
path only runs under `use_extraction=True`, and no standard arm passes it. The
corollary is the uncomfortable one — **the only arms that ever exercised this
code are X1's**, which is how a path inert in any store with a candidate pool
survived from the commit that added defaults until now.

## 4. What this does not establish

- **Dev only, and the registration said so first.** The ceiling on test is 0.000 and was abandoned in advance. A dev-only pass is not a replication, and this is the third mechanism in this project with exactly that shape ([P1](p1-evidence-chain-reconstruction.md), [relations-ceiling](relations-ceiling.md)).
- **One admission rule for one shape of memory**, found by measuring a specific failure. Prediction 4 of the registration says it will not generalise to a second family, and nothing here tests that.
- **`adjust_extracted` is measured at the reduced 60-memory store**, because that is where the cached extractions are. Full-corpus model extraction is ~1,400 calls at 47 s, which §3 of [X1](x1-extraction.md) prices at 18 hours.
- **The extractor got the scope right on the cases measured.** An adjustment whose scope the model mis-extracts is untested, and `gemma2` was correct on all three dev cases.
- **Nothing about relations is retracted.** Zero relations are still inferred, and §11 of X1 stands: the matcher is fitted to its own fixture. What changes is that this family never needed it.

## 5. Does X1's result change?

Its measured 0.000 stands — that is what the registered arm scored on the day,
and §4 there reports it unchanged. What changes is the **attribution**. X1's
§11 concluded the models were not the reason and the matcher was. The first
half is right. The second was incomplete: with the admission path fixed, the
same model and the same records reach 1.000, so the binding constraint was a
missing consumer rather than a semantic gap in the matcher.

Both are faults in the apparatus around the mechanism rather than in the
mechanism, which is now the pattern across five consecutive results and the
reason `experiments/checks.py` exists.
