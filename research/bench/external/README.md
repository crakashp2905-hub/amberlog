# External benchmarks

Third-party datasets with labels this project did not write. **The data is not
committed** — it belongs to its authors, carries its own licence, and the
harness fetches it on demand:

```bash
python -m experiments.external_bench --fetch
```

## SciFact (BEIR / MTEB)

- 5,183 biomedical abstracts, 339 relevance judgements over 300 test queries
- Source: `huggingface.co/datasets/mteb/scifact` (plain JSONL; the canonical BEIR host serves a broken certificate chain)
- Fetched into `scifact-raw/`, which `.gitignore` excludes

**Why an external benchmark.** `relevance_v1` has one weakness no amount of
extra cases fixes: its corpus, queries and labels are all mine, so its result
is "this retriever does well on a world its author built". SciFact's
judgements were made by the SciFact authors for claim verification, years
before this project existed, and nothing in them was chosen to flatter
anything here.

**What it does not test.** SciFact has no provenance, lifecycle, tenants,
retraction or temporal validity. The governance layer is inert against it and
the mechanisms R4/R5 added have nothing to act on. It measures retrieval
quality on a hard real corpus and nothing else. Both benchmarks are needed;
neither substitutes for the other.

Treated as untrusted input: parsed with the standard library, never executed,
and every record validated before use.
