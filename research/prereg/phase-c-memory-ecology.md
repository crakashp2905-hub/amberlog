# Pre-registration — Phase C: can a population learn what should propagate?

- **Written:** 2026-10-08, before the harness and before Phase A or B have produced a result.
- **Origin:** the external review's Phase C, and the "memory ecology" section of the founding document — the most ambitious claim in it and the only one CRITICAL_REVIEW §1 called metaphor rather than mechanism.
- **Gate:** this is **not built until PB1 is supported.** If selective sharing does not beat sharing everything and sharing nothing, there is no gradient for a population to climb and "learning what to propagate" is a search over a flat surface. That gate is ROADMAP principle 9 applied honestly to the project's favourite idea, and writing it down now is the point: the registration exists so the gate cannot be quietly skipped once Phase B's numbers are in.

Thresholds in §5 are fixed now and are not revised after seeing results.

---

## 1. The question, stated so it can fail

The founding document says memories should propagate through a network like traits through an ecology — selected for, inherited, going extinct. That is an analogy. The testable version:

**PC.** A population of agents, each adjusting *who it shares which memories with* from its own observed outcomes, converges on a sharing structure that outperforms every fixed policy from Phase B, including the best one.

The comparison is the whole claim. A learned policy that merely matches `share_overlap` has established that the ecology metaphor buys nothing a static rule did not already buy — and that is the result this registration expects to be most likely, stated plainly in advance.

Two sub-questions, measured but not separately thresholded:

- **Does a memory's "fitness" predict its spread?** Correlation between a memory's causal value estimate and the number of stores it reaches. If propagation is uncorrelated with value, the ecology is drift, not selection — which is a finding, not a failure of the measurement.
- **Does the population specialise?** Whether agents settle into stable sharing neighbourhoods that match their territory overlap, without being told the territories.

## 2. World and population

DepotWorld, 8 agents, territories drawn so that overlap varies continuously rather than falling into the four clean cases Phase B uses. Each agent sees only its own sites and may offer any validated memory to any other agent.

**What is learned.** Each agent keeps, per (recipient, memory-site) pair, a running estimate of whether memories it sent were followed by the recipient succeeding or failing, and shares in proportion to that estimate under an epsilon-greedy rule. Nothing more sophisticated, deliberately: the claim under test is that *any* outcome-driven adjustment beats a fixed rule, and a complicated learner that wins tells us less than a simple one that does.

**Where the feedback comes from.** The recipient's verified outcomes, reported back to the sender. This is a real design commitment and a real cost — it means a federation needs an outcome channel, not just a memory channel — and §6 records it as the limitation it is.

## 3. Arms

| id | Sharing |
|---|---|
| `isolated` | nothing |
| `share_all` | everything to everyone |
| `best_fixed` | whichever Phase B policy won there, carried over unchanged |
| `learned` | the epsilon-greedy outcome-driven policy above |
| `learned_no_feedback` | the same learner, fed only the sender's *own* outcomes |
| `oracle_share` | exactly what is correct for each recipient |

**`learned_no_feedback` is the diagnostic arm.** If `learned` beats it, the outcome channel is what is doing the work and the cost in §6 is justified. If they tie, the learner is not using the channel it requires, and the honest report is that the expensive part is inert — the same shape of finding as H2.

## 4. Metrics

- `success`, per agent per episode, environment-verified.
- `per_agent_spread` — best minus worst agent. Reported beside every mean, for the Phase B reason: a population-level gain extracted from its weakest member is not a result.
- `value_spread_correlation` — Spearman correlation between a memory's causal value estimate and the number of stores it reached. Selection versus drift.
- `neighbourhood_match` — overlap between the learned sharing graph and the true territory-overlap graph.
- `rounds_to_stabilise` — when the sharing graph stops changing, or never.
- `imports` and tokens, as the cost.

## 5. Ceiling and thresholds

Headroom is `oracle_share − best_fixed` on success. Note what that means: the bar is set against the **best static policy**, not against sharing everything. Setting it against `share_all` would be the H3 mistake inverted — an easy baseline making a weak method look strong.

**PC supported** if `learned` captures **≥ 30%** of that headroom, bootstrap interval on the paired difference against `best_fixed` clear of zero, **and** does not reduce the worst agent's success relative to `best_fixed`.

**PC killed** if `learned` does not beat `best_fixed` at all. This is the expected outcome and is written here so that reporting it costs nothing.

**The ecology claim is separately judged, and is not the same as PC.** It is supported only if `value_spread_correlation` exceeds **0.3** with its interval clear of zero. A population can perfectly well improve by learning sharing rules while propagation remains uncorrelated with memory value — that would mean the *selective pressure* story is wrong even though the *learning* story works. Keeping these apart is the difference between testing the mechanism and decorating a result with its metaphor.

## 6. Stated limitations (written now)

1. **The outcome channel is assumed.** `learned` requires recipients to report verified outcomes to senders. Many real federations will not, which bounds the applicability of a positive result more tightly than the result itself will suggest.
2. **8 agents, 5 seeds.** Enough to see a sharing graph form, not enough for population genetics. No claim about scaling follows.
3. **Stationary world.** Territories and answer key are fixed. An ecology's interesting behaviour is mostly in non-stationary environments, and that is not what this measures.
4. **One model throughout**, so agents are more alike than real ones.
5. **The learner is a bandit over recipients.** It cannot represent "share this *kind* of memory with that agent", which is what the founding document actually describes. A null here does not rule out a richer policy class; it rules out the cheap one, which is the right order to test them in.
6. **The metaphor is not under test.** Whether this resembles an ecology is not a measurable question. Whether propagation tracks value is, and that is what §5 thresholds.

## 7. What gets reported

The arm × metric table with intervals; headroom share; the `learned` versus `learned_no_feedback` comparison, which decides whether the outcome channel earns its cost; the value–spread correlation as a separate verdict from PC itself; the learned sharing graph against the true overlap graph; and the verdict against §5, including "killed".
