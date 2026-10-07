# Result — live models on the fabric: compliance is 1.00, not 0.80

- **Run:** 2026-10-07, Ollama 0.35.1, local models, `nomic-embed-text` embeddings.
- **Raw output:** [live-ollama-run.txt](live-ollama-run.txt) · [live-memory-os-run.txt](live-memory-os-run.txt)
- **Reproduce:** `python -m experiments.live_ollama` and `python examples/live_memory_os.py`

Every result in P1–P7 used a scripted agent. [RETROSPECTIVE.md](../RETROSPECTIVE.md) named the gap: *"nothing here was run against a live LLM agent… that is the first thing a successor should test."* This closes it, and the first thing it found was that the simulation's central parameter was wrong.

---

## 1. Compliance: does a real model follow a retrieved memory?

Multiple choice over 8 responses, so chance is 12.5% and the retrieved memory is the only way to know the answer. 15 trials per arm per model, through the real path — `session.recall` → `build_context` → prompt → model → verified outcome.

| model | no memory | **correct memory** | wrong memory | contested |
|---|---|---|---|---|
| qwen2.5:3b | 6.7% | **100%** | 0.0% | 46.7% |
| llama3.2:3b | 6.7% | **100%** | 0.0% | 53.3% |
| qwen2.5:7b | 6.7% | **100%** | 0.0% | 33.3% |

Retrieval found the right memory **100%** of the time in every arm, among 20 competing claims, using real embeddings. Nothing was unparseable.

### Compliance is 1.00. RuleWorld assumed 0.80.

`WorldConfig.compliance = 0.8` — the probability an agent follows the top-ranked matching claim — sat underneath every number in H1, H2, H3 and H4. It was a guess. Measured across three models and two parameter scales, it is **1.00, unanimously**: 45/45 trials.

The direction matters. A higher compliance *widens* the gap between a correct and a wrong memory, which makes value estimation **easier**, not harder. So the simulations were conservative: H1's ρ=0.76 and H2's margins understate what this task would produce. It does not rescue H2 or H3 — those failed on ceilings and headroom, not on signal strength — but it means no simulated result was flattered by this parameter.

### A wrong memory misleads 100% of the time

Also unanimous: 45/45. **Not one model, at any size, recovered from a plausible-looking wrong memory.** There is no self-correction to rely on.

This is the strongest empirical argument in the whole project for the governance layer. The fabric's premise — that unvalidated memories must not be retrievable, that provenance must survive, that a poisoned memory must be retractable across stores — rests on the claim that a bad memory does real damage. It does. A single wrong claim, retrieved and injected, flips a model from 100% correct to 0%.

### The contested labelling measurably works

Marking two rival claims as contested — the mechanism from `adapters/context.py`, which renders state and caveats alongside each memory — recovers **33–53%** from a 0% floor.

That is independent corroboration of [H4b](h4-topology-and-diversity.md), which found in simulation that preserving contested hypotheses lifts P(correct) from 0.905 to 1.000. Two entirely different substrates — a belief-dynamics simulation and a live prompt — both say that representing disagreement rather than collapsing it is the highest-value mechanism in the design.

Curiously the 7B model benefits *least* (33% against 47–53% for the 3B models). On 15 trials that may be noise; if it is real, a plausible reading is that a stronger model commits harder to the first plausible claim it reads. Not established either way.

## 2. The memory OS layer, end to end

`examples/live_memory_os.py` drives the full governed path with two separate stores and real models: **15/15 checks pass.**

| | check |
|---|---|
| ✅ | An agent writes a memory via the `remember` tool; it arrives **unvalidated** |
| ✅ | It is **not retrievable** before review |
| ✅ | After review, a second agent retrieves and visibly uses it |
| ✅ | A model asked to memorise a credential is **quarantined on ingest** |
| ✅ | The secret is **redacted** in the explanation |
| ✅ | Federation: the recipient's firewall decides, and the import arrives unvalidated |
| ✅ | **Provenance crosses the store boundary** |
| ✅ | The recipient's agent uses the imported memory |
| ✅ | The source is retracted, its copy is **findable by origin** and retracted too |
| ✅ | The retracted memory is retrievable in neither store |

Models wrote in their own words — *"When a depot charger trips its breaker on a cold morning, it is often due to a damp earth bond"* — and the fabric governed it without the model knowing any of it was happening.

## 3. The security bug this found

**The first run failed one check: `explain()` returned the credential unredacted.**

P2 put redaction in the observability read model, so the CLI and dashboard scrubbed. `fabric.explain()` built its narrative straight from raw content — and an explanation is a display surface too. A developer printing one to a terminal saw the exact secret the firewall had just quarantined the memory for containing.

**384 unit tests did not catch this**, because none called `explain()` on a secret-bearing memory and inspected the narrative. A live model, asked to record a deployment note containing a key, did.

Fixed at the source: the scrub helpers moved into `governance/sensitive.py` where the detector lives, `explain()` now redacts and reports the *kind* of secret, and the observability layer uses the same shared code instead of its own copy. The stored record is untouched — redaction is a display concern. Five regression tests added.

## 4. Other defects found by running it

- **A cache miss that would have made the run take hours.** The index embeds content *plus* context; the warm corpus held only raw content, so every store build embedded live at ~1.2s. Fixed, and a guard now fails loudly if the two ever drift apart.
- **One slow model killed the whole run.** A cold load of `qwen2.5:7b` exceeded the timeout and discarded two models' completed work. The client now retries with backoff on timeouts and 5xx, and the harness skips a failing model instead of crashing.
- **`phi4` did not match `phi4:latest`**, so a requested model was silently reported as not installed.

## 5. Limitations

1. **One task family.** A multiple-choice fault-code lookup where the memory is *decisive by construction*. That is why the effect is ~93 points. CRITICAL_REVIEW §2.1 expects real effects of 0.02–0.05 for memories that are merely *helpful*; both can be true, and this run says nothing about the marginal case.
2. **Small local models** (1.5B–7B). Frontier models may behave differently, particularly on the contested arm, where judgement matters most.
3. **15 trials per arm.** Enough for 100%-vs-0% contrasts, not enough to separate 33% from 53% on the contested arm.
4. **Compliance was measured with a single, clearly-stated claim.** Real memories are longer, vaguer and more numerous; compliance on those is untested.
5. **No outcome-driven loop.** Nothing here ran long enough for value estimates to accumulate, so H1's estimator was not exercised against live agents — only the retrieval and governance paths were.

## 6. Consequence

- **Update RuleWorld's documented compliance**, with a note that 0.8 was a guess and 1.0 is the measurement, and that the direction made prior results conservative.
- **The governance layer is now empirically motivated**, not just principled. A wrong memory is followed 100% of the time by every model tested.
- **`OllamaEmbedder` replaces the hashing placeholder** wherever a model is available. Every retrieval number before this was measured against a stand-in that cannot match `symptom_3` to `symptom 3`.
- **The next thing to measure is the marginal case**: tasks where a memory helps rather than decides. That is where the 0.02–0.05 effect sizes live, and where the whole causal-credit apparatus either earns its keep or does not.
