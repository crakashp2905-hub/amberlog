# Evidence Completeness v1 — INCONCLUSIVE

Design: [ecv1-design.md](../prereg/ecv1-design.md).
Frozen development ceiling decision: [ecv1-threshold.json](../prereg/ecv1-threshold.json).
Corpus/split: `benchmarks/completeness_data.py`, frozen at commit `212c175`.
Development and test use five disjoint seeds each, separate identifiers and
different authoring templates. Ground truth is computed from latent records,
independently of the key/value reader. No third-party replication is claimed.

Reproduce:

```bash
python -m benchmarks.evidence_completeness --split dev --baselines-only
python -m benchmarks.evidence_completeness --split test
python -m unittest tests.test_evidence_completeness tests.test_ecv1_benchmark
```

Raw observations, per-query latency, returned/gold sets and seed results:
[ecv1-dev.json](ecv1-dev.json), [ecv1-test.json](ecv1-test.json).
Run manifest: [evidence-completeness-v1.json](bench_runs/evidence-completeness-v1.json).
Every file identifies its own producing commit and corpus SHA-256.

## Ceiling gate

At the fixed primary content-read budget (12/query), development lexical
retrieval reached set-exact 1.0, equal to the oracle. No attainable headroom
existed. The separate registration records a null threshold before held-out
execution. The held-out run is diagnostic; its lexical score of 0.90 does not
retroactively justify a new threshold or another tuning pass.

## Held-out diagnostic

| arm | set-exact | reads/query | positive complete certificates |
|---|---|---|---|
| lexical | 0.90 | 12 | 0 |
| typed | 0.00 | 0 | 0 |
| typed+fallback | 0.20 | 12 | 0 |
| selective fallback | 0.20 | 12 | 0 |
| budget-matched oracle | 1.00 | 12 | 0 |

The strong typed+fallback control uses the same three-valued unknown set,
evaluator and actual read budget as selective fallback. It is deliberately
not weakened to scan known nonmatches or stop after failed read attempts.
The oracle uses ordinary enforced reads and the same budget, differing only in
knowing which unknown records are positives. Exact answers need not imply
coverage: unread unknown negatives still prevent a complete certificate.

No arm emitted a false positive completeness assertion. That observation alone
would be vacuous because all primary-budget certificates were incomplete.
The separate full-budget certificate audit therefore requires positive complete
certificates for nonempty independent-gold queries and checks exact answer sets.
Other tests require incomplete certificates on unread/ambiguous records,
mid-evaluation mutation, and revoked content; tenant/private/candidate/erased
records never reach the fallback evaluator.

Latency is recorded per query and averaged by arm in the raw files; these are
local, sequential microbenchmarks, not production SLOs. Metadata classification
work is included in elapsed time, but the read metric counts exposed content,
not CPU instructions, event scans or storage operations. External-model spend
is zero; hardware/electricity costs are unpriced, not claimed zero.

## Decision

**INCONCLUSIVE for registered improvement** due to the failed development
headroom gate. Selective fallback also did not outperform the strong fallback
control in held-out set-exact accuracy and was slower in this local run. Keep
experimental; no default changes or general natural-language completeness claim.
Any broader task corpus or semantic evaluator needs a new split and registration.
