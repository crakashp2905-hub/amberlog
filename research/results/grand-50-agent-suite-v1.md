# Grand 50-agent suite v1

Run on 2026-10-31 at commit
`d4fd174ac9056865c8b73abd857fa681daa6a0d7`. The worktree was dirty with
unrelated user changes, which were preserved. Raw summary:
[`grand-50-agent-suite-v1.json`](grand-50-agent-suite-v1.json). Confirmation
rules: [`grand-50-agent-suite-v1.md`](../prereg/grand-50-agent-suite-v1.md).

## Outcome: FAIL

| component | result | acceptance outcome |
|---|---:|---|
| 50-agent changing-evidence team, unseen seeds 101–105 | Fabric task success 0.584; shared baseline 0.782; oracle 1.000 | **FAIL** |
| stale actions | Fabric 0.000; shared 0.082 | **PASS** |
| valid evidence withheld | Fabric 0.168; limit 0.050 | **FAIL** |
| 50-agent authenticated HTTP, corrected workload | 1,000/1,000 successful; 32.6 ops/s; p99 3,856 ms | correctness **PASS**; throughput/latency **FAIL** |
| LongMemEval full-history qualification, 100 stratified questions | lexical 0.7385 turn recall; hybrid 0.6917 | **FAIL** |
| adversarial gate | environment-invalid; no product verdict | **INVALID** |

The load harness previously seeded private memories, so clients could not reach
the advertised fetch-plus-verify branch. The corrected run seeded team-visible
memories and asserted that every operation family appeared: 306 remember, 496
recall, and 198 fetch-plus-verify sequences. All completed successfully, but the
real mix was about five times slower than the misleading recall-heavy run.

## External-data scale effect

The compact LongMemEval oracle split (500 questions, median 23 turns) favored
hybrid retrieval: 0.8505 versus lexical 0.8165. On the full-history `s` split
qualification (100 stratified questions, median 494 turns), the result reversed:
hybrid 0.6917 versus lexical 0.7385, with higher retrieval latency (25.38 ms
versus 16.13 ms). Do not generalize the compact-split win.

## What held and what did not

Memory Fabric prevented acting on withdrawn knowledge in the 50-agent world,
while the plain shared baseline acted on it in 8.2% of tasks. It achieved that
safety with too much refusal: 16.8% of valid evidence was withheld and task
success fell below the shared baseline. The next engineering target is therefore
calibration and correction-specific invalidation, not a larger claim or another
scale-only run.

The adversarial-gate result is deliberately not classified as a product failure.
The default run hit Windows app-container temp permissions; workspace-temp runs
stalled beyond five minutes both sandboxed and elevated. CI remains the canonical
security-gate environment until that local-runner problem is isolated.
