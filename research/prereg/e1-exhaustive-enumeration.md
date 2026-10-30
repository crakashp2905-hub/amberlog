# Pre-registration — E1: exhaustive "which of them all?" queries — typed filter vs search (INT-03)

**Registered 2026-10-28**, before `benchmarks/enumeration.py` was run once. `memory-fabric/typed_query.py`
was written the same day; its code is fixed at the commit that adds this file.

## 1. Question

Sarvam reported that a navigable tree found 7 of 14 qualifying records with 3 false positives,
while a typed ontology found 14/14 with none. K1 already found that topic navigation does not beat
search here. Does a typed filter over the fields writers recorded (`typed_query.select`) answer
"list every X with A and B" **exactly** more often than the strongest search baselines, at
the same visibility rules, when some records were written without typed fields?

## 2. World (seeds 1–5, `benchmarks/enumeration.py`)

Per seed: 1,000 equipment records, kind ∈ {valve, pump, sensor, door, server}, site ∈ 6 sites,
status ∈ {open, closed}, year ∈ 2015–2025, each written as one sentence. Status is phrased four
ways per value, one of them negated ("not closed" for open, "not open" for closed). **10%** of
records are written without `structured` fields (an extraction that failed). 60 notes that
mention a record's id without being a record are also written, untyped. 60 queries per seed, two
types reported separately and pooled for the thresholds: 30 **narrow** (kind and two of {site,
status, year range}; gold sets of a few) and 30 **broad** (kind and one of {site, status}; gold sets
of tens to ~100, often larger than any k a search would use). Every gold set has at least one member.

*Amended before the first run:* the first draft had 300 records and only narrow queries. Every gold
set would then fit inside k = 50, so search plus a filter would likely reach 1.00 by construction
(the 8c failure), and the study would not test corpus-wide enumeration at all.

## 3. Arms (baselines first; all under the same reader and visibility)

- `lexical`: `retrieve(query, k=50)`, then keep each result whose text contains the kind and site
  words, a status phrase from the status table (the baseline is given the full table, negated
  phrases included), and a year in range — the strongest text filter I can write without a model.
- `nav`: `navigation.navigate(query, k=50)`, then the same filter.
- `typed`: `typed_query.select` on kind, site, status, year.
- `typed+fallback` (secondary, not thresholded): `typed`, plus the `lexical` filter applied to the
  selection's unknown memories.
- `oracle`: the gold set.

## 4. Metrics

Primary: **set-exact accuracy** (answer set equals gold set). Secondary: recall, precision,
**certificate soundness** (every `typed` answer that is not exact has `complete == False`), memory
contents read.

## 5. Thresholds (pooled over seeds; B = the better of `lexical` and `nav`, O = 1.0)

- **E1a:** `typed` set-exact ≥ B + 0.40 (O − B), and > B in ≥ 4 of 5 seeds.
- **E1b:** certificate soundness = 1.00 (no `complete` answer that is wrong).
- **8b/8c:** no arm above the oracle; if `lexical` or `nav` reaches 1.00 the metric is wrong and the
  study is INVALID.

Pass: `typed_query` stays experimental but is documented as the way to ask exhaustive questions,
and E2 (typed projection) proceeds to beta work. Fail: it stays experimental, undocumented in user
guides, and the result says so.

## 6. Limits stated in advance

One generated world in English, written by the author who wrote the filter; the 10% untyped rate
is chosen, not measured. This measures exhaustive answers over writer-typed fields, not extraction
quality, which is a separate question (E2 extraction gold sets, not run).
