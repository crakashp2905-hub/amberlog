# Local agent and conformance audit — 29 October 2026

Source protocol/code: `d87ec015f9e084b6861f3d77c4fda1273931b7f0`.
Raw results are in `research/results/local-three-agent.json`,
`local-conformance-audit.json`, and `local-retrieval-partition-audit.json`.
The subtest failure-ID reporting correction is separate from the mechanisms
measured; it does not change this run's all-passing conformance outcome.

## Joint outcomes

Each of five frozen seeds has 36 decisions: twelve jobs, three scripted roles,
six jobs withdrawn before execution. All five seeds produced these counts:

| Arm | Task successes | Stale actions | False blocks | Abstentions | Correct abstentions |
|---|---:|---:|---:|---:|---:|
| shared cached | 18 | 18 | 0 | 0 | 0 |
| shared current-metadata recheck | 18 | 0 | 0 | 18 | 18 |
| governed certificate | 18 | 0 | 0 | 18 | 18 |
| truth oracle | 18 | 0 | 0 | 18 | 18 |

**Superiority: INCONCLUSIVE, no available headroom on this fixture.** The strong
baseline matches the oracle. Do not tune a threshold or weaken that baseline.
Task success excludes justified refusal; abstention is reported separately.
All roles share a local store; these are scripted decisions, not model agents,
separate processes, a live user workflow, or proof of network safety. The
metadata baseline knows the exact cached ID and inspects its current lifecycle;
it is not a claim about semantic retrieval under real workloads.

Raw traces publish per-decision milliseconds, run elapsed seconds and throughput,
retained content bytes and event counts for every seed/arm. They are local
measurements, not SLOs. All arms construct certificates to equalize setup; these
are not minimal-baseline storage costs. Full disk size, model tokens and model
accuracy are NOT_MEASURED. Zero paid calls is not a token-efficiency result.

## Conformance and retrieval findings

The executable audit ran all 41 qualified mapped tests with no failures or skips.
The original map only checks test-name existence and remains a coverage index;
the new report records actual execution. PARTIAL/BLOCKED requirements retain
their declarations. Discovery failure, missing names and execution failure make
the audit fail. Skips produce INCOMPLETE at the affected assertion.

The archived facet-v1 diagnostic reproduces lexical nDCG@3 of 0.25 on dev and
test. This does not fix implied facets. The archived four-hop rerun at k=5
reconstructs all four critical memories with chain search plus perfect declared
relations on both splits, whereas chain alone remains insufficient. Those
relations are gold declarations, not an automatic extraction method. The old
relations-ceiling report describes older code and is retained as historical
evidence. Both splits have already been inspected: these reruns are regression
diagnostics, not a fresh held-out claim. New independent data is required before
tuning or registering a retrieval improvement.

Five-seed chain/star delayed-delivery scenarios again show all five copies
quarantined, five dependent memories contested, five independently supported
memories preserved, and zero old certificates allowed after reconnect. Four
remote copies remain stale during the scheduled partition. No wall-clock bound,
physical-host test or real-network availability claim follows from this.

## External replication

Check out the recorded source commit in an isolated directory; Python 3.11+
and the standard library suffice for the study. Optional dependency differences
must be recorded. Build fixture data before running retrieval diagnostics:

```
python -m research.bench.facet_v1.build
python -m research.bench.relevance_v2.build
python -m unittest tests.test_three_agent tests.test_gov_conformance tests.test_chains tests.test_facet_v1
python -m benchmarks.three_agent --out replication/three-agent.json
python tools/conformance_audit.py --out replication/conformance.json
python -m benchmarks.federation_world --no-write
python -m experiments.relations_ceiling --split dev --json
python -m experiments.relations_ceiling --split test --json
python -m experiments.relevance_bench --benchmark facet_v1 --split dev --k 3 --arms lexical oracle --json
python -m experiments.relevance_bench --benchmark facet_v1 --split test --k 3 --arms lexical oracle --json
```

Compare outcome counts and fixture digests exactly; timing need not match.
Record OS, Python, source SHA, command, optional skips and failures. Inspect the
raw trace rather than treating successful process exit as proof of superiority.

## Remaining gates

Independent adversarial review has NOT been commissioned: no reviewer or
funding is available. A volunteer engagement needs an identified independent
reviewer, fixed reviewed SHA, synthetic tenant fixtures, disclosure channel,
written findings, remediation retests and explicit scope exclusions. Suggested
scope: cross-tenant reads, certificate/action races, replay/import laundering,
erasure and restored keys, malicious document/summary content and transport
replay. Internal tests do not satisfy this gate.

A real workflow pilot is NOT_RUN. A willing participant must identify an actual
three-role workflow and consenting data owner. Before use, freeze tasks, current
shared-memory baseline, correction schedule, permitted actions, abort conditions
and the four joint metrics above. Run in shadow mode first; collect real
corrections and operator feedback without inventing adoption evidence.

Automatic implied-facet extraction, independent fresh retrieval evaluation,
physical network recovery, total storage/token comparisons, independent review
and the real pilot remain open. No next release tag is authorized by this audit;
all required release gates must pass on the exact candidate first.
