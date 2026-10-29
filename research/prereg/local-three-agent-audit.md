# Local three-agent audit protocol — 29 October 2026

Descriptive functional comparison, not a registered superiority test. Frozen
seeds: 601, 607, 613, 617, 619. Four arms: shared cached evidence, shared evidence
with current metadata recheck, governed action certificates, and truth oracle.
Each seed has twelve jobs, six withdrawn before execution and six unchanged;
observer/planner/executor each make one decision per job from one cached item.
Every arm receives identical initial evidence; no refresh content reads. The
recheck baseline is deliberately strong and can inspect current local metadata.
Oracle receives the same budget and perfect withdrawal knowledge. Certificates
are constructed in every arm to equalize setup, so this is not a comparison of
minimal baseline storage or setup cost. No threshold is registered before
baseline/oracle headroom is measured. Saturation means INCONCLUSIVE for any
superiority hypothesis, not permission to weaken the baseline.

Report task success, stale execution, false blocking, total abstention and
correct abstention with raw per-decision traces and denominators. A justified
refusal is not task execution success. Report per-decision latency and whole-run
decision throughput separately; whole-run time includes setup and teardown.
Retained content bytes and event counts are proxies, not total disk footprint.
Model tokens are NOT_MEASURED; zero calls is not measured token-efficiency gain.
This is one shared store, three scripted roles, no real pilot or network claim.

Run after committing the protocol/code:

```
python -m benchmarks.three_agent --out research/results/local-three-agent.json
python tools/conformance_audit.py --out research/results/local-conformance-audit.json
python -m benchmarks.federation_world --no-write
```

Conformance audit resolves every mapped test name to qualified IDs, executes all
matches, records errors and skips, and preserves PARTIAL/BLOCKED declarations.
Independent review and GOV-20 physical-host evidence cannot be supplied here.
