# Preregistration: decision routing contract v1

## Question

Does the dependency-free System 1 contract abstain on ties and escalate every
declared consequential or low-confidence action without an unsafe un-escalated
decision?

## Frozen setup

- Five seeds: 1–5 (the baseline is deterministic; repetition checks stability).
- Four cases: routine, tied, consequential, and low-confidence.
- Primary metric: unsafe un-escalated decisions; threshold exactly zero.
- Secondary metrics: selection accuracy, escalation rate, and elapsed latency.
- Oracle: the registered expected selection/escalation labels.
- Baseline: deterministic score normalization with tie abstention.

The contract result is not evidence about Laya, Jev, encoder classifiers, or
real-agent task quality. Those require a separately registered dataset, model
versions, prompts, budgets, and distribution-shift split.
