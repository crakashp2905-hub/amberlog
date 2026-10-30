# Local-model synthetic shadow rehearsal — 30 October 2026

Measured source commit `ecb3f6bde072e1a09ef2b221504e6113cffe0119`.
Raw result: `no-budget-local-model.json`. The result includes the script hash,
cached model digest, seeds, prompt hashes, token counts and per-call seconds.
The model script is unchanged in the evidence publication follow-up.

Execution **PASS**; improvement claim **INCONCLUSIVE**. This is an internal,
synthetic shadow workflow using real local model inference. It is not a real
customer task, outside pilot, independent reproduction or security assessment.
The only callback effects are markers in an in-process list.

Protocol was committed before model calls. Seeds: 601, 607, 613, 617, 619.
Model: `qwen2.5:1.5b`, cached before the run. Ollama was bound to loopback with
cloud disabled, with two CPU threads and a 1,024-token context. No model was
downloaded; the task-owned service was unloaded and stopped afterwards.

| Arm | Task successes | Stale decisions | False blocks | Abstentions | Correct abstentions |
|---|---:|---:|---:|---:|---:|
| Cached proposal | 1 | 2 | 1 | 2 | 1 |
| Current metadata recheck | 1 | 0 | 1 | 4 | 3 |
| Governed callback | 1 | 0 | 1 | 4 | 3 |
| Truth oracle | 2 | 0 | 0 | 3 | 3 |

The model-backed host-recheck baseline matches the governed arm. Both falsely
block one valid case; the oracle illustrates the remaining task-success gap.
No threshold was registered, no model was tuned after seeing results and no
superiority claim follows from five decisions per arm. The metadata baseline
has privileged current-state access. Its checked model proposal is reused by
the governed arm, so this is not an independent per-arm token-cost comparison.
Cached/recheck/oracle outcomes are descriptive decisions; only the governed
arm actually calls the fenced shadow callback.

The shared run made 20 model calls: 2,010 prompt tokens and 180 completion
tokens (2,190 total), with 50.22 seconds of summed call time. These numbers are
from the raw wrapper records, not throughput estimates or production SLOs.
Model-call cash cost was zero; hardware, electricity and total storage costs
were not measured. There were no malformed-output or runtime errors.

Run this on a clean checkout with cached weights as described in
[the zero-budget guide](../../docs/NO_BUDGET_VALIDATION.md). Treat a later run as
new evidence rather than overwriting these results. Optional runtime versions
and machine load can change model output and timing.
