# Documentation

Every document in the repository, by what you are trying to do.
`tests/test_doc_index.py` fails if a document here is missing from this page.

## Getting started

| document | for |
|---|---|
| [../README.md](../README.md) | What it is, why, and a first example |
| [QUICKSTART.md](QUICKSTART.md) | Ten minutes: install, store, retrieve, inspect, correct, verify |
| [CONCEPTS.md](CONCEPTS.md) | The ideas: memories, the log, lifecycle, scope, authority, correction |
| [COOKBOOK.md](COOKBOOK.md) | Task-sized recipes, each run by a test |
| [FAQ.md](FAQ.md) | Common questions, short answers |
| [PIPELINE.md](PIPELINE.md) | One memory from write to erasure, with what is and is not measured |
| [../examples/README.md](../examples/README.md) | Runnable examples |

## Reference

| document | for |
|---|---|
| [API.md](API.md) | The Python API, generated from the code |
| [CLI.md](CLI.md) | Every command and option, generated from the parser |
| [INTEGRATIONS.md](INTEGRATIONS.md) | MCP, HTTP, SDK, LangChain, Claude, Ollama, PostgreSQL |
| [PROTOCOL.md](PROTOCOL.md) | The federation protocol, v1 ([schemas](protocol/)) |
| [../SPEC.md](../SPEC.md) | The memory schema and event types, by version |
| [RELEVANCE_SPEC.md](RELEVANCE_SPEC.md) | The relevance contract |
| [DATA_ACCESS.md](DATA_ACCESS.md) | Every public way to reach a memory, and what each enforces |
| [../ARCHITECTURE.md](../ARCHITECTURE.md) | The design |

## Operating

| document | for |
|---|---|
| [../DEPLOYMENT.md](../DEPLOYMENT.md) | Serving, capacity as measured, upgrades |
| [OPERATIONS.md](OPERATIONS.md) | Day-two operations, incidents, background maintenance |
| [RUNBOOKS.md](RUNBOOKS.md) | Step by step: leaked credentials, key rotation, poisoning, restore |
| [TROUBLESHOOTING.md](TROUBLESHOOTING.md) | Every error message and what to do |
| [MIGRATION.md](MIGRATION.md) | Moving between versions, and moving in from elsewhere |
| [SCALE.md](SCALE.md) | How many agents, how far federated, what carries between sessions |
| [REFERENCE_DEPLOYMENT.md](REFERENCE_DEPLOYMENT.md) | Two federated stores in five minutes |

## Trust and security

| document | for |
|---|---|
| [../SECURITY.md](../SECURITY.md) | The threat model, T1–T12, and how to report a vulnerability |
| [SAFETY_AND_SECURITY.md](SAFETY_AND_SECURITY.md) | The safety model |
| [LIMITATIONS.md](LIMITATIONS.md) | What it does not do |
| [../STABILITY.md](../STABILITY.md) | What is stable, beta and experimental; what is tested |
| [HARDENING_STATUS.md](HARDENING_STATUS.md) | The owner's hardening lists, item by item, with evidence |
| [SAFETY_ROADMAP_COVERAGE.md](SAFETY_ROADMAP_COVERAGE.md) | The AI-safety roadmap, item by item |
| [SECURITY_REVIEW.md](SECURITY_REVIEW.md) | The internal security review and its findings |
| [SECURITY_TEST_PLAN.md](SECURITY_TEST_PLAN.md) | How security properties are tested |
| [INDEPENDENT_EVALUATION.md](INDEPENDENT_EVALUATION.md) | What an independent reviewer would need, and what has not happened |
| [INVARIANTS.md](INVARIANTS.md) | Each integrity invariant and the test that holds it |
| [AUDIT.md](AUDIT.md) | Implementation against the spec |
| [VALIDATION.md](VALIDATION.md) | What was run and what it showed |

## Releases

| document | for |
|---|---|
| [../CHANGELOG.md](../CHANGELOG.md) | Every change |
| [RELEASE_NOTES_0.12.0.md](RELEASE_NOTES_0.12.0.md) | 0.12.0, in qualification |
| [RELEASE_NOTES_0.11.0.md](RELEASE_NOTES_0.11.0.md) | 0.11.0 |
| [RELEASE_EVALUATION.md](RELEASE_EVALUATION.md) | The release gate's evidence, per release |
| [../VERSIONING.md](../VERSIONING.md) | What a version number promises; supported versions |

## For maintainers

Internal: how the project is planned, measured and changed. Not needed to
use the product.

| document | for |
|---|---|
| [../ROADMAP.md](../ROADMAP.md) | Milestones, gates and open decisions |
| [WORKPLAN.md](WORKPLAN.md) | Work in progress, with every result and failure |
| [IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md) | What is implemented, task by task |
| [RESEARCH_ROADMAP.md](RESEARCH_ROADMAP.md) | The research agenda |
| [AI_SAFETY_CYBER_RESEARCH_IMPLEMENTATION_PLAN.md](AI_SAFETY_CYBER_RESEARCH_IMPLEMENTATION_PLAN.md) | The safety and security implementation plan |
| [../research/SCORECARD.md](../research/SCORECARD.md) | Every research claim and its outcome |
| [../RESEARCH.md](../RESEARCH.md), [../EVALUATION.md](../EVALUATION.md) | Research design and evaluation method |
| [BRANCHES.md](BRANCHES.md) | Branches and how they are protected |
| [../CONTRIBUTING.md](../CONTRIBUTING.md), [../AGENTS.md](../AGENTS.md) | How to change this repository |
