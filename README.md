# Memory Fabric (working name)

Research prototype for **memory that is valued by its effect on outcomes, not by its similarity to the query**, and for sharing that memory selectively across agents.

> Working name only. "MemOS" and "MemoryOS" are taken by 2025 projects; see [research/CRITICAL_REVIEW.md](research/CRITICAL_REVIEW.md) §1.

## Status

**All nine milestones closed, and validated against live multi-agent runs.** 392 tests, zero dependencies in the core, Python 3.13 + SQLite. P1–P7 built and measured; P8 and P9 **declined on measurement** rather than deferred — see [ROADMAP.md](ROADMAP.md).

**H1 is supported**: an amortized, propensity-corrected estimator recovers true memory value at ρ=0.76 against a naive baseline's 0.47, on 8% exploration overhead. [Result](research/results/h1-causal-credit.md)

**H2 is killed**: that accuracy did *not* transfer to deciding what to forget — at the registered memory budget the same estimator loses to a smoothed success rate, which captures 93% of what perfect knowledge could achieve. An exploratory sweep found the ordering reverses once the budget actually binds, which reconciles the two results: the estimator's advantage lives in telling *valuable* from merely *harmless*, and a loose budget never asks that. [Result](research/results/h2-credit-driven-retention.md)

**H3 is inconclusive**, and instructively so. The predicted federation crossover curve held cleanly — sharing everything costs 2.6 points when contexts don't overlap, sharing nothing costs 2.7 when they fully do — but the registered margin of +0.030 turned out to exceed the +0.027 that *perfect* knowledge could achieve, so no method could have passed. The threshold was set without first establishing a ceiling. [Result](research/results/h3-selective-federation.md)

**H4b is supported — the project's founding design principle, finally tested.** "Contradictions stay representable" was an assertion for six milestones. Re-testing contested beliefs instead of collapsing to the majority takes a fully-connected population from P(correct) 0.905 to **1.000**, lifts recovery from 24% to **100%**, and does it at *half* the regret and *faster* consensus. It pays for itself: the fifth of a round spent re-testing buys escape from a mistake that otherwise lasts forever. H4a (the Zollman effect) is inconclusive only because I registered the wrong point on the curve — the effect is an inverted U, strongest at degree 2–4 (+0.080, 84% of headroom), not at the sparsest extreme I tested. [Result](research/results/h4-topology-and-diversity.md)

**Validated against live models.** Three local models through Ollama, on the real path: retrieval found the right memory **100%** of the time, a correct memory took accuracy from 6.7% to **100%**, and a wrong one misled **every model, every time**. The fabric's central simulated parameter turned out to be wrong — compliance is 1.00, not the 0.80 RuleWorld assumed — and an end-to-end governance run (governed writes, provenance across a store boundary, retraction following a memory between stores) passes **15/15**. It also found a security bug 384 unit tests had missed. [Result](research/results/live-ollama-validation.md)

**Tested with multiple agents, and it changed the design.** Three models as independent observer agents, each with its own store, federating into a consolidator where the majority is wrong. Collapsing to the majority made the reader **confidently assert a wrong action in 8 of 10 trials**; preserving the disagreement eliminated that entirely (−0.80 [−1.00, −0.50]). It does not make the reader *right* — it converts confident error into flagged uncertainty. Running it also exposed a product gap: the fabric had no deduplication, and one model wrote the same memory four times in a single run, silently inflating a 2-vs-1 majority into 4-vs-1. [Result](research/results/live-multi-agent.md)

**H5 is unaskable and P9 is declined**, both on measurement. The memory path makes **zero** LLM calls at 0.26 ms/episode, so "replace ≥50% of memory-management LLM calls" has no denominator. And 25× more memories costs 1.7× latency, so no load here needs distributing. Both were cancelled by measurement rather than built on anticipation.

## Install

```bash
pip install .
```

Zero runtime dependencies, Python 3.11–3.13, Linux/macOS/Windows — all four checked in CI with
nothing installed, because a zero-dependency claim is only true if it is tested that way.
The adapters are extras: `pip install ".[claude]"`. The Ollama adapter needs nothing, since
Ollama speaks HTTP.

Installing puts a `memory-fabric` command on the path. Everything below works equally as
`python -m memory_fabric` from a checkout.

### Try it

Seed a deliberately messy store — a poisoning and its retraction, an unresolved disagreement,
a leaked secret, a rare-but-critical procedure:

```bash
memory-fabric --db demo.db --create demo
```

Then look at it from either surface:

```bash
memory-fabric --db demo.db attention
```

```bash
memory-fabric --db demo.db --estimator ips serve
```

`attention` is the triage list — what needs a human, worst first, each finding carrying the
command that acts on it. `serve` opens the same information as a local dashboard on 127.0.0.1.

The dashboard prints a one-time URL that carries a session token. It binds to loopback and
refuses to serve unauthenticated on any other address. `--db` on a path that does not exist is
an error, not an empty store; `--create` opts in.

In a container:

```bash
docker build -t memory-fabric . && docker run -p 8765:8765 -v mf-data:/data memory-fabric
```

The volume matters: the event log is the source of truth, and without it the first
`docker rm` takes the data with it.

Two scripted walkthroughs, both offline:

```bash
python examples/poisoning_and_rollback.py
```

```bash
python examples/agent_on_the_fabric.py
```

The first is the governance story. The second runs an agent end to end — transcript ingestion,
retrieval into the prompt, the `remember` tool, and governance on what the agent writes.

### Tests

```bash
python -m unittest discover -s tests -t .
```

### What works

| Capability | Where |
|---|---|
| Append-only event log as the source of truth, with replay | [eventlog.py](memory_fabric/eventlog.py) |
| All state as rebuildable projections | [projections.py](memory_fabric/projections.py) |
| Memory objects with provenance, versions, lifecycle, scope | [model.py](memory_fabric/model.py) |
| Lineage graph, TMS-style retraction, evidence-independence | [lineage.py](memory_fabric/lineage.py) |
| Sensitive-data detection, firewall, retention with rare-event protection | [governance/](memory_fabric/governance/) |
| Exposure policies with logged propensities | [exposure.py](memory_fabric/exposure.py) |
| Value estimation: naive, IPS, doubly robust, amortized | [estimators.py](memory_fabric/estimators.py) |
| `explain()` — "why does the system remember this?", with caveats | [explain.py](memory_fabric/explain.py) |
| SDK facade | [fabric.py](memory_fabric/fabric.py) |
| Shared read model, triage list, health diagnostics | [observability/report.py](memory_fabric/observability/report.py) |
| Read-only HTTP API and web dashboard | [observability/](memory_fabric/observability/) |
| Token auth, Host validation, cross-origin refusal | [observability/auth.py](memory_fabric/observability/auth.py) |
| CLI | [cli.py](memory_fabric/cli.py) |
| Capability-scoped agent sessions | [session.py](memory_fabric/session.py) |
| Prompt context with injection defences | [adapters/context.py](memory_fabric/adapters/context.py) |
| Claude API adapter, transcript ingestion | [adapters/](memory_fabric/adapters/) |
| Federation across store boundaries | [federation.py](memory_fabric/federation.py) |
| Local models + real embeddings | [adapters/ollama.py](memory_fabric/adapters/ollama.py) |

### Not built yet

Paired-replay estimator, topology effects (P7), learned controller (P8), Postgres. See [ROADMAP.md](ROADMAP.md).

**The Claude adapter has not been run against the live API** — there is no key in the development environment, so its loop is covered by a stub client. See the P3 gate note in [ROADMAP.md](ROADMAP.md).

## Quick start

```python
from memory_fabric import MemoryFabric

fabric = MemoryFabric("memory.db")

episode = fabric.start_episode("agent-a", task_id="onboard-42", context={"team": "sales"})
mid = fabric.remember(
    "agent-a",
    "Email follow-up beats calling after a failed onboarding.",
    source_episodes=[episode.id],
)
fabric.validate(mid, actor="reviewer")            # candidates are not retrievable

hits = fabric.retrieve("agent-a", "how to follow up?", episode_id=episode.id)
fabric.record_outcome(episode.id, outcome=1.0, verifier_id="env")   # never self-reported

print(fabric.explain(mid).narrative())
fabric.share(mid, "team")                          # default-deny; returns a reasoned ruling
```

## Two rules the observability surfaces follow

Both surfaces read through one model ([report.py](memory_fabric/observability/report.py)), so the CLI and the dashboard cannot tell different stories about the same store. Two properties are enforced by tests:

1. **Browsing is read-only.** Search goes to the index directly rather than through `retrieve()`, because retrieval writes exposure events — an observability tool that logged an operator's queries would feed its own browsing into the data every value estimate is computed from. There is no mutating HTTP endpoint at all.
2. **Secrets are never displayed.** Quarantining a credential and then printing it in the review tool defeats the control that caught it; the value would reach a terminal scrollback, a browser's memory and any screenshot of either. The reviewer is shown the *kind* of secret, which is what they need in order to decide.

## Three design choices worth knowing

1. **Propensities are logged from day one.** Every exposure decision records the probability it was made with, including the withheld ones. It costs one float and cannot be added retroactively; without it, no historical data can ever support an unbiased value estimate.
2. **Value estimates carry a `contrastive` flag.** An absolute success rate over episodes where a memory appeared cannot show that the memory helped — that is the value/relevance confusion this project exists to avoid — so the type distinguishes the two and the firewall refuses to promote a memory on non-contrastive evidence.
3. **Outcomes need a third-party verifier.** An agent that scores its own episodes can manufacture value for any memory it likes, so `record_outcome` rejects a verifier equal to the acting agent.

The test that demonstrates the point is `test_naive_is_fooled_by_selection_bias_and_ips_is_not` in [tests/test_estimators.py](tests/test_estimators.py): a memory with *exactly zero* true effect scores 0.84 under naive usage-success and ≈0.00 under the propensity-corrected estimator.

## Read in this order

| Doc | What it is |
|---|---|
| [research/CRITICAL_REVIEW.md](research/CRITICAL_REVIEW.md) | Stress test of the original vision, written before any code |
| [research/RETROSPECTIVE.md](research/RETROSPECTIVE.md) | **What nine milestones actually established** — the scorecard, and what the measurements killed |
| [AGENTS.md](AGENTS.md) | Repository constitution and engineering rules (humans and AI agents) |
| [RESEARCH.md](RESEARCH.md) | Hypotheses, novelty boundary, related work, experiments |
| [EVALUATION.md](EVALUATION.md) | RuleWorld environment, metrics, baselines, statistics |
| [SPEC.md](SPEC.md) | Memory object, event log, lifecycle, API v0 |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Components, data flow, storage, layout |
| [ROADMAP.md](ROADMAP.md) | The single roadmap, with gates and kill criteria |
| [SECURITY.md](SECURITY.md) | Threat model |
| [VERSIONING.md](VERSIONING.md) | What the version number promises — the schema, not the API |
| [CHANGELOG.md](CHANGELOG.md) | What changed, and which bugs it fixed |
| [research/PRIOR_ART.md](research/PRIOR_ART.md) | Verified related work, and what it does to the novelty claims |
| [CONTRIBUTING.md](CONTRIBUTING.md) | How to add a feature or an experiment |

## Central question

> Can we estimate the causal value of agent memories accurately and cheaply enough that retaining, retrieving and sharing memories by that value beats strong heuristic baselines?

If not, everything downstream (federation, ecology, the learned controller) has no foundation — but the governance layer still stands on its own, which is why it was built first. See the kill criteria in [ROADMAP.md](ROADMAP.md).
