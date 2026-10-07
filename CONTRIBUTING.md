# CONTRIBUTING.md

Read [AGENTS.md](AGENTS.md) first; its rules are binding.

## Adding a feature
1. Name the milestone in [ROADMAP.md](ROADMAP.md) it belongs to. If its gate hasn't passed, the feature waits.
2. If it changes the memory schema or event types, update [SPEC.md](SPEC.md), bump `schema_version`, and add a migration.
3. Add unit tests. For estimators or policies, also add known-answer tests on RuleWorld.

## Adding an experimental mechanism
1. Write a pre-registration in `research/prereg/<id>.md`: hypothesis, primary metric, threshold, baselines, seeds, expected cost.
2. Implement it behind the relevant protocol (estimator, exposure policy, conflict detector, firewall policy), not as a special case.
3. Run the baselines and ablations from [EVALUATION.md](EVALUATION.md).
4. Record the decision (proceed / kill / pivot) in `research/decisions/`.

## Graduating from research to product
A mechanism moves into the stable SDK only when it has:
- a reproducible result against its baselines
- a documented failure analysis
- a security review against [SECURITY.md](SECURITY.md)
- an API-stability review
