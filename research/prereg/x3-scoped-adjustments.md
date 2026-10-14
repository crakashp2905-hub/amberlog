# Pre-registration — X3: admitting scoped adjustments

**Registered 2026-10-14, after the ceiling was measured and before the
mechanism was measured.** That order needs stating plainly, because it is
unusual and because the alternative is worse. §2 gives a ceiling obtained by
*simulating* admission with no model and no mechanism — adding the memory to a
baseline result and re-scoring. The mechanism itself had not been written when
that was run, and the threshold below is a share of that measured ceiling, so
nothing here is a bar set after seeing the arm.

## 1. The gap, and why it is not a relation

X1 scored **0.000** against a bar of 0.400 and proposed **zero** relations out
of three ([result](../results/x1-extraction.md)). The models were not the
reason: `gemma2` extracted both sides correctly, including
`modifies='axle-set figure'` and `scope=('depot-12',)`.

The mechanism was wrong, and §11 of that result says how. `infer_relations`
joins a modifier to an assertion by string containment, and the corpus holds
**twelve** adjustments differing only by site name:

```
At the harbour  site, add 0.45 bar to the axle-set figure …
At the depot-7  site, add 0.45 bar to the axle-set figure …
At the depot-12 site, add 0.35 bar to the axle-set figure …   <- the answer
… nine more
```

So an adjustment does not qualify one rule rather than another — **all twelve
qualify every axle rule equally**, and which one applies is a property of the
**query's** entities. A memory-to-memory relation cannot express that, for the
same reason `EXCEPTS` could not express a default whose exception names a
*site* rather than a memory ([relations-ceiling.md §3](../results/relations-ceiling.md)).

**And the record was unreachable by any path.** `_admit_defaults` admitted
only records with **exceptions**. A site-scoped adjustment has a scope and no
exceptions, so the correct extraction sat in the index with nothing to consume
it. That is the whole defect, and it is one condition.

## 2. The ceiling, measured first

Simulated by adding the labelled adjustment to the baseline's result and
re-scoring at the same k, with no model and no mechanism:

| split | baseline sufficiency | with the adjustment admitted |
|---|---|---|
| dev | 0.000 (0/3) | **1.000 (3/3)** |
| test | 0.000 (0/3) | **0.000 (0/3)** |

**Dev is fully closed and test is untouched**, and the reason test does not
move is already on the record: the chain retrieves the wrong *sibling* rule —
`c0064`, `c0069`, `c0063` instead of `h3` — so the context is missing a
different memory, which admitting an adjustment cannot supply. This is the
same dev/test asymmetry [P1](../results/p1-evidence-chain-reconstruction.md)
and [relations-ceiling](../results/relations-ceiling.md) both had, and it is
stated here as a prediction rather than discovered later.

## 3. Primary metric and threshold

**Primary: sufficiency at k=5 on `multi_hop_4`**, both splits, the same metric
and budget as X1's amended primary.

```
B = max(sufficient) over {baseline, store_lexical, chain} re-measured in this run
C = the simulated-admission ceiling in section 2, re-measured in this run
support iff sufficient >= B + 0.40 * (C - B)
```

On dev that is `0.000 + 0.40 * 1.000 =` **0.400**. The bar is computed from the
run rather than quoted, which is [principle 8d](../../AGENTS.md) and the thing
X1's registration got wrong.

**8c check — is the primary trivially maximised by a registered baseline?**
No: every baseline is 0.000 on this family at k=3, 5 and 10 on both splits,
and unlike X1's second family that figure **is** sufficiency at k=5, measured
here, not nDCG at k=3 quoted from elsewhere.

**8b check** — no arm may exceed the ceiling; checked every run by
`experiments/checks.py`.

**Abandonment clause.** On test, `C − B = 0.000`, so **test is abandoned in
advance** rather than reported as a failure. A family whose ceiling is zero
cannot carry a confirmatory split, and saying so now prevents a dev-only pass
being presented as a replication.

## 4. What the arm is allowed to use

`retrieve(entities=[...], use_extraction=True)` with records from
`index_extraction`. Two sources of those records are measured separately,
because they answer different questions:

- **`declared`** — the fixture's own `scope` and `modifies`. This is a ceiling for the *admission rule*, holding extraction perfect.
- **`extracted`** — `gemma2` free-form, which is what a product would have. The one call needed is already measured: `scope=('depot-12',)`, `modifies='axle-set figure'`, correct.

Reporting both separates "the admission rule works" from "the extractor
supplies what it needs", which X1 could not separate and which is why its
0.000 took 2.5 hours to attribute.

## 5. Secondary metrics, reported always, decisive for none

- **`must_not_expose_rate`** — zero or the run fails. Vacuous on this family, as X1 §7 records, and reported anyway.
- **Wrongly admitted adjustments**: how many of the eleven other site-variants enter a context. This is the metric that would catch the failure mode worth fearing, and it is the reason `is_adjustment` requires a scope — a quantity match alone would admit all twelve.
- **No-regression** on `relevance_v2`'s other families, `facet_v1` and the `gated` family, since the mechanism changes an admission path shared with defaults.
- **Cost**: one model call per memory at write time, or zero if the records are declared. The admission rule itself is a dictionary lookup.

## 6. Predictions

1. **Dev passes at 1.000 and test scores 0.000.** §2 measured both; the only way this is wrong is if the mechanism differs from the simulation, which is the thing being tested.
2. **`declared` and `extracted` will agree on dev.** `gemma2` already extracts the scope and the target correctly for the one case checked, and the other two dev cases are the same sentence with a different site.
3. **Zero wrongly admitted adjustments.** The eleven other site-variants scope to sites the query does not name. If this is wrong, `applies_to` is wrong, and it is the condition I would most want to fail loudly.
4. **This will not generalise to a second family**, and that is the honest limit. It is one admission rule for one shape of memory, found by measuring a specific failure. The dev-only ceiling says so before the run does.

## 7. What a pass would not establish

That extraction at ingest works — X1 measured that at 0.000 and this does not
revisit it. That the mechanism helps on test, where the ceiling is zero. That
relations are the wrong tool in general, rather than for this shape. Nothing
about a corpus whose adjustments are not site-scoped, and nothing about an
adjustment whose scope the extractor gets wrong, which is untested because
`gemma2` got it right on the one case measured.
