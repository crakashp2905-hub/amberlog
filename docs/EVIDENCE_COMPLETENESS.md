# Evidence Completeness v1 (experimental)

`amberlog.evidence_completeness.classify` partitions the eligible scoped
corpus into typed matches, typed nonmatches, and unknown candidates. A false
conjunct excludes a record even when another field is missing. `None` tenant
means the default tenant; cross-tenant operator enumeration is not supported.
Erased content is excluded using the canonical event-derived erasure projection.

`exhaustive` retains typed matches and invokes an operator-supplied evaluator
only on unknown records, up to `max_reads`. Each fallback read goes through
`retrieve`, which enforces current access and lifecycle and logs exposure
propensities. The evaluator returns `True`, `False`, or `None` for ambiguity.
An exception propagates rather than producing a positive certificate. No
extracted fields, inferred authority or new persistent index are created.

```python
from amberlog.evidence_completeness import exhaustive

result = exhaustive(
    fabric, "reader", {"kind": "sensor", "status": "open"},
    query="sensor open", evaluate=approved_evaluator,
    evaluator_id="reviewed-parser/1", max_reads=20,
)
ids = result.ids
coverage = result.certificate()
```

IDs are selection results, not content-read capabilities. Reading matches later
must still use the normal enforced retrieval/action path. A coverage certificate
records the query, tenant, eligible ID/version corpus digest, typed and fallback
counts, unresolved count, evaluator identity and snapshot changes. Positive
coverage means every record in that bounded eligible corpus was classified,
conditional on writer fields and evaluator correctness. It does not establish
truth, inaccessible-corpus completeness, source independence or action authority.
Corpus changes during evaluation invalidate completeness and withdrawn matches
are removed. Certificates are historical diagnostics, not reusable access grants.

The registered study design and frozen corpus are in
`research/prereg/ecv1-design.md` and `benchmarks/completeness_data.py`.
Development lexical retrieval saturated the measured oracle, so no attainable
improvement threshold was registered. See the raw development/held-out data
and the INCONCLUSIVE decision in `research/results/ecv1-test.json` and
`research/results/bench_runs/evidence-completeness-v1.json`. Do not promote
this feature based on that study. The synthetic evaluator supports explicit
key/value evidence, not arbitrary natural-language inference.
