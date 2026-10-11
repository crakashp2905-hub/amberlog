# Memory Fabric (working name)

**Agent memory you can audit, retract across stores, and federate without
silently poisoning your weakest agent.**

Not "memory that makes agents smarter". That claim was pre-registered, tested
against real models at five seeds, and **failed** — the measurements are below
and they are the most reusable thing here.

> Working name only. "MemOS" and "MemoryOS" are taken by 2025 projects; see [research/CRITICAL_REVIEW.md](research/CRITICAL_REVIEW.md) §1.

## What this does, and what it costs

| Guarantee | Evidence |
|---|---|
| A retraction **follows a memory into other stores**, including ones the origin has never heard of, and drives acting-on-withdrawn-knowledge to zero | 17% → **0%** under both sharing policies, 240 decisions per arm ([PB2](research/results/phase-b-federated-agents.md)); re-shared two hops out, under outage, crash, diamond and cycle ([fault matrix](docs/INVARIANTS.md)) |
| A premise can be invalidated **without destroying independently justified conclusions** | Lose one of two independent premises and the conclusion stays active; lose both and it is contested, never deleted ([Phase 4](docs/INVARIANTS.md)) |
| Contradiction is **preserved rather than collapsed**, converting confident error into flagged uncertainty | 80% confidently wrong → **0%** with real disagreeing models ([live](research/results/live-multi-agent.md)); P(correct) 0.905 → 1.000 in simulation ([H4b](research/results/h4-topology-and-diversity.md)) |
| Content can be **erased while the accountability survives** | Crypto-erasure: the text goes, the provenance, lineage, retraction basis and audit trail stay ([Phase 6](SECURITY.md)) |
| A known-invalid version is **never served**, including at action time | One enforcement layer, exposure tokens bound to version and integrity revision ([Phase 3](docs/INVARIANTS.md)) |
| **All of it costs almost nothing** | **0.2 ms** per episode and **1.16×** tokens against an ungoverned vector store |

**722 tests**, 17 deterministic multi-store fault scenarios, six testing layers,
zero runtime dependencies in the core, Python 3.11–3.13 on Linux and Windows —
the suite runs in CI with **nothing installed**, because a zero-dependency claim
is only true if it is tested that way. What was run and what it showed, including
the checks that are not automated: [docs/VALIDATION.md](docs/VALIDATION.md). All **14 integrity invariants**
implemented and tested ([matrix](docs/INVARIANTS.md)), up from 4.

## The accuracy claim failed, and that is the useful part

Five live phases, pre-registered thresholds, real models, ≥5 seeds for three of
them. Full detail in [research/SCORECARD.md](research/SCORECARD.md).

| | claim | outcome |
|---|---|---|
| **A** | Governed memory beats an ungoverned vector store | ❌ **killed** — 0.283 against 0.583 |
| **A′1** | Some withdrawal policy beats withdrawing nothing | ❌ **killed**, as registered in advance |
| **A′2** | Leave-one-out attribution recovers most of naive blame's damage | ✅ supported — 71% of the gap, at 2.55 model calls per episode |
| **B1** | Selective sharing beats sharing all or none | ❌ **killed** — +0.008 [−0.042, +0.058], and the worst agent *fell* |
| **B2** | Retraction propagation works, under both policies | ✅ **supported** — 17% → 0% |
| **C** | A population learns what to propagate | 🔬 exploratory; the outcome channel made it **worse**, −0.042 [−0.081, −0.005] |

**One measurement explains nearly all of it.** Success tracked a single
quantity: whether a correct memory reached the prompt. Conversion given one was
**93–98% in every arm**, and coverage-to-success correlated at **+0.975** across
arms. Everything the memory layer does — ranking, governance, lifecycle — can
only move the outcome through that one channel, and **every withdrawal policy
moved it downwards**. Perfect selection over the corpus was worth **+5 points**;
the rest of the gap is corpus *coverage*, which is memory construction and not
something this project does.

Three consequences, all acted on in the product rather than left in a paper:

1. **Do not withdraw memories because they were in context when something failed.** Of naive blame's 87 withdrawals, **57 were memories about a completely different fault**. `quarantine` now records *why*, and the attention list flags a withdrawal made on weak evidence as the finding — pointing an operator at releasing it rather than at the memory.
2. **Do not filter at share time.** A memory wrong at one of a recipient's contexts is right at another, and which dominates is not knowable before the episode. Perfect sharing scored five points *below* sharing everything indiscriminately.
3. **The value gate the default firewall ships is not a safety feature here.** It reduced federation to 42 imports of a possible 630, scored identically to isolation, and left the weakest agent worse than if it had never joined.

## What simulation established

**H1 supported** — a propensity-corrected estimator recovers true memory value
at ρ=0.76 against a naive baseline's 0.47, on 8% exploration overhead
([result](research/results/h1-causal-credit.md)). The confound is real and
severe: a memory with *exactly zero* true effect scores 0.84 under naive
usage-success and ≈0.00 under the corrected estimator.

**H2 killed, H3 and H4a inconclusive, H5 unaskable, P9 declined on
measurement.** The estimator's accuracy did not transfer to retention (H2),
and three further live attempts to use it — exposure, withdrawal, sharing —
each lost to a cheap baseline. **The product default is `naive_usage` for that
reason, and value-ranked exposure is not recommended on current evidence.**

H3's threshold exceeded its own ceiling and H4a tested the wrong point on an
inverted-U curve; both are recorded as method failures rather than as results.
That happened three times in this project, which is why
[AGENTS.md](AGENTS.md) principle 8b now requires the oracle to carry no handicap
the competing arms lack, and why `stats.check_ceiling` runs that check
automatically in every phase verdict.

## Novelty, checked rather than claimed

[research/PRIOR_ART.md](research/PRIOR_ART.md) verified four papers that each
remove one claim: learned value scoring, lifecycle management, causal
attribution for clearance, and attributed memory construction are **not novel**.

What survives, and is now measured rather than asserted: **provenance and
retraction that cross a store boundary.** None of the four carries provenance
across a boundary at all, so none can retract across one. Plus contradiction
preservation, and the negative results themselves.

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

### Phase A is killed, and it is the most important result here

Everything above is simulation or a single-mechanism live check. Put on a real
task against a real baseline — 8 arms, 5 seeds, 960 verified decisions through a
live model — **this project's governance made the agent worse.**

| arm | success |
|---|---|
| no memory | 0.075 |
| pooled vector store | 0.558 |
| pooled + the fabric's prompt framing, no governance | **0.583** |
| **governed (contested marking + quarantine on contradiction)** | **0.283** |
| **governed + causal value selection** | **0.242** |
| oracle | 0.633 |

Not through cost — retrieval was 1.7 ms and the token gate passed. The mechanism
is sharper than that. Every arm turned a correct memory into a correct answer
**95%** of the time and failed **95%** of the time without one; the model was
never the variable. Governance cut how often a correct memory arrived from 60% of
episodes to 18%, because **withdrawing the memories blamed for a failure withdrew
the correct ones.** Six actions span six fault codes, so the memory that asserted
what the agent wrongly said was usually a *correct* memory about a different
fault — quarantined for agreeing with a mistake it had nothing to do with.

Principle 1 of [AGENTS.md](AGENTS.md) says value is not relevance. Phase A adds:
**agreement is not causation.** [Result](research/results/phase-a-real-agent-benchmark.md)

**PA′ then asked what to do instead, and the answer is nothing.** Real
counterfactual attribution — re-asking without each memory — withdraws a quarter
as much as naive blame and recovers 71% of the lost accuracy, at 2.55 model calls
per episode, and **still loses to withdrawing nothing**. Two thirds of what naive
blame destroyed was about a completely different fault. Perfect selection over
the corpus was worth only +5 points, so the binding constraint is whether a
correct memory *exists* yet — a coverage problem, not a governance one.
[Result](research/results/phase-a-prime-attribution.md)

The product consequence is immediate and is not a research note:
quarantine-on-contradiction should not be recommended, and the attention list
that invites an operator to withdraw memories needs to say what the evidence
actually is.

| Phase | Question | State |
|---|---|---|
| **A** | Governed memory against an ungoverned vector store | ❌ **Killed** — [result](research/results/phase-a-real-agent-benchmark.md) · [prereg](research/prereg/phase-a-real-agent-benchmark.md) |
| **A′** | If not blame, then what? | ❌ **PA′1 killed**, ✅ **PA′2 supported** — [result](research/results/phase-a-prime-attribution.md) · [prereg](research/prereg/phase-a-prime-attribution.md) |
| **B** | What should cross a federation boundary, and must retraction follow it | ❌ **PB1 killed** · ✅ **PB2 supported** — [result](research/results/phase-b-federated-agents.md) · [prereg](research/prereg/phase-b-federated-agents.md) |
| **C** | Can a population learn what should propagate | 🔬 **Exploratory, no verdict** — gate not passed — [result](research/results/phase-c-memory-ecology.md) · [prereg](research/prereg/phase-c-memory-ecology.md) |

Two decisions made before the run are why the result is usable. The decisive
baseline was not a strawman — a pooled store that deletes what was in context at
a failure, one line of code that reacts to outcomes, because governance beating a
*naive* store would establish nothing and
[H2](research/results/h2-credit-driven-retention.md) is the precedent for the
cheap baseline winning. And an ablation arm was added when the pilot exposed a
confound: the fabric arms rendered memories in a provenance-and-caveats framing
while the vector arms got plain text. That arm won. Without it, a prompt's effect
would have been scored as governance.

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
| CLI, including verified backup | [cli.py](memory_fabric/cli.py) |
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

## One store, several customers

```python
fabric.principals.register("agent-acme", key=ACME_KEY, tenant_id="tn_acme")
acme = fabric.as_principal(credential)      # verified: signed, unexpired, registered
acme.remember("valve 7 is upstream of the pump")
acme.retrieve("valve")                      # cannot be asked to read outside tn_acme
```

The methods on that handle take no `tenant_id`, so there is no call site at
which someone can omit it. The filter sits **before the index is queried** and
the enforcement check refuses **before resolving the lifecycle**, so a
cross-tenant refusal says only "not yours" — not the version, not that the
memory was withdrawn on weak evidence, each of which is a true statement about
another customer's data.

**What this is not.** It is an authorisation boundary, not a physical one. It
holds against a bug in a ranking policy, an index query or a federation import;
it holds against nothing that can read the file, and a caller holding the
`MemoryFabric` can still act as any agent. That is not a patch waiting to
happen — the check and the bypass would be on the same side of that boundary —
and [SECURITY.md](SECURITY.md) says so plainly. `memory-fabric tenants` says
which arrangement a store is actually in.

## Is this installation sound?

```bash
memory-fabric --db memory.db doctor
```

A different question from `attention`, which asks what in a knowledge base
needs a human. `doctor` asks whether the installation's answers can be
believed, and it reports three outcomes rather than two: **ok** (verified, not
merely "nothing raised"), **warn** (a real condition that does not invalidate
the answers), **fail** (do not use this store for decisions). Exit codes 0, 1
and 5, so it runs as a health check in a script.

Eight checks. The one worth naming: a retraction that has permanently failed to
reach a recipient raises nothing anywhere — the origin's own copy is withdrawn,
the local store looks correct, and the recipient goes on exposing knowledge
that was withdrawn hours ago. That is the one guarantee the research supported,
and it is the one that can rot quietly.

A check that *cannot run* reports a warning with the reason, never `ok`. That
rule caught a real bug in one of the checks within an hour of being written.

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
| [research/SCORECARD.md](research/SCORECARD.md) | **Every registered claim and what the measurements did to it** — simulated, live and deterministic, kept apart on purpose |
| [research/RETROSPECTIVE.md](research/RETROSPECTIVE.md) | The simulated milestones P1–P9 in detail |
| [AGENTS.md](AGENTS.md) | Repository constitution and engineering rules (humans and AI agents) |
| [RESEARCH.md](RESEARCH.md) | Hypotheses, novelty boundary, related work, experiments |
| [EVALUATION.md](EVALUATION.md) | RuleWorld environment, metrics, baselines, statistics |
| [SPEC.md](SPEC.md) | Memory object, event log, lifecycle, API v0 |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Components, data flow, storage, layout |
| [ROADMAP.md](ROADMAP.md) | The single roadmap, with gates and kill criteria |
| [SECURITY.md](SECURITY.md) | Threat model |
| [DEPLOYMENT.md](DEPLOYMENT.md) | **Running it for real** — backup, serving, capacity, upgrades, and what it is not ready for |
| [docs/AUDIT.md](docs/AUDIT.md) | **Which guarantees are actually implemented** — and which are specification only |
| [docs/INVARIANTS.md](docs/INVARIANTS.md) | Every invariant mapped to the test that proves it, or to the gap |
| [docs/PROTOCOL.md](docs/PROTOCOL.md) | The federation protocol v1 — identities, events, state machine, delivery |
| [docs/REFERENCE_DEPLOYMENT.md](docs/REFERENCE_DEPLOYMENT.md) | **A two-store federation end to end in five minutes**, plus troubleshooting |
| [VERSIONING.md](VERSIONING.md) | What the version number promises — the schema, not the API |
| [CHANGELOG.md](CHANGELOG.md) | What changed, and which bugs it fixed |
| [research/PRIOR_ART.md](research/PRIOR_ART.md) | Verified related work, and what it does to the novelty claims |
| [CONTRIBUTING.md](CONTRIBUTING.md) | How to add a feature or an experiment |

## Central question

> Can we estimate the causal value of agent memories accurately and cheaply enough that retaining, retrieving and sharing memories by that value beats strong heuristic baselines?

If not, everything downstream (federation, ecology, the learned controller) has no foundation — but the governance layer still stands on its own, which is why it was built first. See the kill criteria in [ROADMAP.md](ROADMAP.md).
