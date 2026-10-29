# Causal memory: intervention study design (N35)

Status: proposed controlled design, not a causal product claim or threshold.
Dependency tracing describes what a result rests on; it does not identify the
effect of an action. Preserve that distinction in labels and receipts.

Use a simulator with a hidden structural model containing treatment, outcome,
observed covariates and an unobserved confounder. Randomize treatment through an
injected RNG, log assignment probability, and have the simulator independently
verify outcomes. Keep observational and randomized episodes separate. Negative
controls include an irrelevant treatment and an outcome measured before treatment.
Do not let agents or judges inspect the hidden structural equation or answers.

Arms: no memory, frequency/smoothed success, observational association, IPS/DR,
randomized-intervention learner and same-budget causal oracle. Match episodes,
content budget, tools, exploration spend and rollout horizon. Measure downstream
reward/regret first; effect bias, variance, overlap, calibration and negative-
control failures are diagnostics, not substitutes for useful decisions.

Freeze scenario families and disjoint held-out seeds before tuning. Baseline and
oracle measurements precede threshold registration; inadequate headroom stops
the study. Include sensitivity to overlap violations and hidden confounding.
No retrospective claim graph may be labelled proven causal evidence. H2 remains
negative: H2b requires a separate registration demonstrating a genuinely binding
retention budget before any estimator-driven forgetting experiment.
