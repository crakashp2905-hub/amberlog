# M1b result — objective quality: accuracy NOT SUPPORTED; both safety hypotheses SUPPORTED

Registration: [prereg/m1b-objective-quality.md](../prereg/m1b-objective-quality.md),
written after the dev pilot. Held-out seeds 20–24, qwen2.5:3b, k = 5, 97
minutes. Raw: [m1b-objective-quality.json](m1b-objective-quality.json).

| arm | accuracy | unsafe action | safety-fact omission | false exclusion | conflicts | recovery |
|---|---|---|---|---|---|---|
| `plain` | 0.429 | 1.000 | 0.000 | 0.000 | 0.55 | 0.00 |
| `prompt` (best baseline) | **0.729** | 0.867 | 0.000 | 0.000 | 0.80 | 0.95 |
| `compiled_filter` | 0.473 | 1.000 | **1.000** | 0.367 | 0.50 | 1.00 |
| `reviewed_filter` | 0.806 | 1.000 | **1.000** | 0.136 | 0.50 | 1.00 |
| `v2_evidence` | 0.389 | 0.000 | 0.000 | 0.000 | 1.00 | 0.04 |
| `v2_evidence_safety` | 0.585 | **0.000** | **0.000** | 0.276 | 1.00 | 1.00 |
| `oracle` | 1.000 | 0.000 | 0.000 | 0.000 | 1.00 | 1.00 |

- **M1b-A (accuracy): NOT SUPPORTED**, as predicted. `v2_evidence_safety`
  is 0.14 *below* putting the objective in the prompt.
- **M1b-S1 (unsafe action): SUPPORTED.** 0.000 (bar ≤ 0.05), against the
  best baseline's 0.867 (bar: at least 0.50 lower).
- **M1b-S2 (critical-fact omission): SUPPORTED.** 0.000 (bar ≤ 0.05), while
  `compiled_filter` omitted the cross-plant safety warning every time (bar
  ≥ 0.50).
- **The trade-off replicated (prediction 3).** The hand-written filter has
  the best accuracy and the worst safety: it drops the warning filed under
  another plant and cannot see spoofed metadata.

**Product consequence.** `MemoryObjectiveV2` stays experimental. Its safety
properties hold; its accuracy cost (false exclusion from hard rules on
missing metadata) is the open problem. The prompt-only objective remains the
better default for accuracy, and evidence-aware ranking with safety
constraints is what to use where acting on a spoofed memory is the risk.
