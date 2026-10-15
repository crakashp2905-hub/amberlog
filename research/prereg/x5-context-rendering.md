# Pre-registration — X5: does the governed context rendering cost accuracy?

**Registered 2026-10-15, before the harness exists.** This is the first
experiment in this project to pre-register a **minimum detectable effect**, and
§4 explains why that omission has been expensive.

## 1. The hypothesis, and where it came from

[X4](../results/x4-governed-vs-pooled.md) §4 found a dissociation it was not
designed to test: `fabric_governed` put the correct lesson in context **more**
often than any pooled arm — 0.642 against 0.600 — and converted it into a
correct answer **equally or less** often, consistently at all three correction
rates. The oracle showed the same from the other side: its score *fell* from
0.650 to 0.608 when two correction documents were added, so perfect filtering
plus extra text is worse than perfect filtering.

The arms differed in retrieval **and** in rendering, so X4 cannot attribute
it. Here retrieval is held **identical** — one retrieval per episode, the same
exposed memories rendered four ways — so rendering is the only variable and
every comparison is paired per episode.

[R6](../results/r6-downstream.md) is the prior: stuffing a context makes this
class of model *less* willing to abstain, and that is the one R6 finding that
survived its frozen split.

## 2. What `build_context` actually bundles

Three separable things, which is why a single rich-versus-plain test would be
useless for deciding anything:

1. **An injection preamble.** A documented security control — SECURITY.md T1: a retrieved memory is text an earlier run wrote, and a poisoned one is a prompt-injection payload aimed at every later run. The preamble says memories are evidence, not instructions.
2. **Delimiters** — `<retrieved_memories>` … `</retrieved_memories>`.
3. **Per-memory annotations** — `[id | type | evidence | lifecycle | contradicts …]`, where evidence reads like *"used 3x, effect unmeasured"* or *"helped (+0.21, n=4)"*. This is the project's "value is not relevance" argument at the point of use: a contested claim must not appear in the same voice as a well-evidenced one.

So the arms decompose it:

| arm | preamble | delimiters | annotations |
|---|---|---|---|
| `plain` | — | — | — |
| `delimited` | **yes** | **yes** | — |
| `annotated` | — | **yes** | **yes** |
| `full` (shipped) | **yes** | **yes** | **yes** |

`full − annotated` is the preamble's cost. `full − delimited` is the
annotations' cost. `full − plain` is the total.

**A pass does not license dropping the preamble.** If the preamble is what
costs accuracy, the finding is a *trade* between a security control and task
success, and the registration records that in advance so it cannot later be
read as a recommendation. The annotations are the component that could be
shortened without losing a documented threat control.

## 3. Primary metric and threshold

**Primary: paired difference in task success, `plain` − `full`**, over
(seed, episode) pairs, bootstrap 95% CI.

```
support (rendering costs accuracy) iff
    the 95% CI on (plain - full) excludes zero
    AND the point estimate is >= 0.05
```

Two clauses, because a statistically real 1-point effect is not a reason to
change a security control. An effect whose CI excludes zero but falls below
0.05 is reported as **real but below the action threshold**, which is a third
verdict this project has not had and should.

**No selection oracle, and the reason.** 8a asks for a ceiling, and for a
*selection* claim that is the perfectly-filtered arm. This is not a selection
claim: every arm sees the identical memories, so there is no better set to
bound against, and an oracle over memories would bound something nobody is
varying. The floor is reported instead — `no_memory` — so the band in which
rendering operates is visible: X4 put that at 0.092 against 0.650, a total
memory value of 0.558, and any rendering effect is a fraction of that.

**8c check.** Is the primary trivially maximised by a baseline? The comparison
is directional between two renderings of one retrieval, and `full` is the
incumbent. Neither can max the other by construction.

## 4. Power, pre-registered — and what that says about X4

For paired binary outcomes the standard error of the mean difference is
`sqrt(d/n)`, where `d` is the discordance rate. At 80% power, two-sided 0.05:

| pairs | d = 0.15 | d = 0.20 | d = 0.30 |
|---|---|---|---|
| 120 (X4's n) | 0.099 | **0.114** | 0.140 |
| 240 | 0.070 | 0.081 | 0.099 |
| **640 (this run)** | **0.043** | **0.049** | 0.061 |

**X4's minimum detectable effect was 0.10 to 0.14, and the effect it reported
was 0.04.** It could not have detected what it saw, whatever the truth. That is
not a small oversight: X4 spent 1.72 hours of inference on arm differences an
order of magnitude below its own resolution, and nothing in 8a–8d catches it,
because they are all about thresholds and ceilings rather than about power.

So: **5 seeds × 128 episodes = 640 pairs**, giving an MDE of about 0.05 at
plausible discordance — matched to the 0.05 action threshold rather than chosen
for convenience. The observed discordance is reported, so a reader can see
whether the realised power matched the registered estimate.

**This becomes a standing requirement.** A registered threshold without a
power calculation is a bar nobody checked was reachable, which is 8a's mistake
in the other dimension: 8a stopped thresholds exceeding the available
headroom; nothing stopped them sitting below the noise floor.

## 5. Secondary metrics, reported always, decisive for none

- **Discordance rate** per comparison, so the realised power is visible.
- **Right memory in context** — identical across arms by construction, and reported as a check that the retrieval really was shared. A difference here is a bug, not a finding.
- **Prompt tokens per arm.** The rendering's cost in context budget, which is the other thing a product would weigh. R6 measured a ~3× token saving from retrieval over stuffing; this measures what the annotations add.
- **Abstention and hedging rate.** R6's surviving finding is that more context makes the model less willing to abstain. DepotWorld already has a hedge detector, and if the rendering changes willingness to commit rather than accuracy, that is the mechanism.
- **Per-component costs**: `full − annotated` and `full − delimited`, each with a CI.

## 6. Predictions

1. **`plain` beats `full`, and by less than 0.05.** The direction from X4 and R6 is consistent, but X4's own estimate was 0.04 and I expect the true effect to be of that order — real, below the action threshold, and therefore **NOT SUPPORTED** under §3's two clauses. I would rather register that than a prediction that lets any outcome look anticipated.
2. **The annotations cost more than the preamble.** The preamble is one block of instruction; the annotations interleave metadata with every memory, and a 3B model has to parse `[id | type | used 3x, effect unmeasured]` before reaching the content.
3. **The mechanism is hedging, not accuracy.** The annotations tell the model some evidence is weak, so it should commit less often — which is *correct behaviour* that this world scores as failure, because DepotWorld demands a single named action. If the hedging rate moves more than the success rate, the rendering is working as designed and the benchmark is punishing it.
4. **Token cost is the finding that survives.** Whatever happens to accuracy, the annotations are not free in context budget, and that is a number a product decision needs regardless of which way the accuracy goes.

## 7. What a pass would not establish

Nothing about dropping the preamble — §2. Nothing about a larger model: this
is `qwen2.5:3b`, and a model that parses metadata more easily may pay nothing
for it, which makes the result a statement about small local models rather than
about rendering. Nothing about other worlds: DepotWorld scores a single named
action, so it cannot reward a model for correctly expressing uncertainty, and
prediction 3 says that is the likeliest confound. And nothing about retrieval,
which is held fixed here precisely so that it cannot be credited or blamed.
