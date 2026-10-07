# Pre-registration — H3: selective federation across heterogeneous contexts

- **Written:** 2026-10-01, **before** the multi-context world, the federation module, or any arm was built.
- **Milestone:** P6 (ROADMAP.md)
- **Context:** H1 supported (the estimator is accurate), H2 killed at a loose budget but the [exploratory sweep](../results/h2-credit-driven-retention.md#appendix--exploratory-budget-sweep-post-hoc-not-pre-registered) located its advantage in telling *valuable* from merely *harmless*. Sharing is that kind of decision, which is why P6 was not blocked by P5.

Thresholds below are fixed now and are not to be revised after seeing results.

---

## 1. Hypothesis

> When agents work in partly-overlapping contexts, selectively federating memories — sharing only what evidence says transfers — beats both sharing nothing and sharing everything. The result is a **curve over context overlap**, not a single number.

## 2. Why this needs heterogeneous contexts

If every agent works in the same context, full sharing wins trivially and "selective" can only match it or lose. The hypothesis is only meaningful where a shared memory is sometimes **actively wrong for the recipient** (CRITICAL_REVIEW §7).

So the world is parameterised by **overlap `o`**: the fraction of rules that hold identically in both contexts. At `o=0` a memory from A is wrong in B; at `o=1` it is right.

**Predicted shape, registered now:**

| overlap | expected winner |
|---|---|
| `o≈0` | `none` — sharing only imports harm |
| `o≈1` | `full` — everything transfers, probing is wasted effort |
| intermediate | `selective` — captures the transferable half, rejects the rest |

A result that contradicts the two extremes indicates a broken world, not a finding.

## 3. Arms

Two agents, one per context, each with its **own store**. Federation is modelled as separate stores with memories offered across a boundary, which is what federation is; a single store with visibility flags would be testing something else.

| id | Sharing rule |
|---|---|
| `none` | Agents never exchange memories. |
| `full` | Every memory from each agent is imported into the other and immediately active. |
| `selective` | Every memory is offered, but arrives **as a candidate** — not retrievable. During a probe window it is exposed in the recipient's context under ε-greedy; afterwards only those with a positive estimated value **in the recipient's context** are activated, and the rest are forgotten. |

`selective` therefore pays a real cost — the probe exposes memories that may be wrong — and that cost is part of what is measured, not excluded from it.

## 4. Procedure

Per seed, per overlap, per arm:

1. **Local** — 1500 episodes per agent, own context, own store, ε-greedy (ε=0.20).
2. **Offer** — memories crossed per the arm's rule, through the recipient's firewall, with provenance recording the origin agent and memory.
3. **Probe** (`selective` only) — 500 episodes per agent with imported candidates temporarily exposable; then activate those with positive estimated value in-context, forget the others.
4. **Evaluate** — 1500 episodes per agent, relevance-ranked retrieval. **Probe episodes count toward neither phase's success** but their cost is reported separately as federation overhead.

Success is averaged over both agents.

## 5. Metrics

- **Primary:** mean task success over the evaluation phase, across both agents.
- **Negative transfer:** fraction of active imported memories whose true value in the recipient's context is < 0.
- **Transfer gain:** evaluation success minus the same agent's local-phase success.
- **Communication:** memories crossing the boundary, and how many survive.
- **Probe cost:** success during the probe window relative to the local phase.

## 6. Decision rules

Judged on means across 10 seeds, with 95% bootstrap intervals on paired differences.

- **H3 supported** if **both**:
  1. at every `o`, `selective ≥ max(none, full) − 0.02` — it is never meaningfully worse than the better fixed policy; and
  2. at each of `o ∈ {0.25, 0.5, 0.75}`, `selective > max(none, full) + 0.03` with the interval clear of zero.
- **H3 killed** if at no intermediate `o` does `selective` beat `max(none, full)` at all.
- **Inconclusive** otherwise.

**Sanity gates (not hypotheses — a failure here means the world is broken and the run is void):**
- at `o=1.0`: `full > none`
- at `o=0.0`: `none ≥ full`

## 7. Design

- **Seeds:** 10 (`0..9`). **Overlaps:** {0.0, 0.25, 0.5, 0.75, 1.0}. **Agents:** 2.
- **World:** the H2 v2 world per context (40 symptoms, coverage 0.5, harm that bites), with the two contexts agreeing on an `o` fraction of rules. No drift, no rare symptoms, no budget — those are H2's axes and would confound this one.
- **Estimator:** `amortized` over `dr`, per the H1 decision record.
- **Probe exposure:** ε-greedy at ε=0.20, matching H1's operating point.

## 8. Stated limitations (written now)

1. **Two agents, two contexts.** Topology effects — the Zollman question in H4 — need more.
2. **One-shot federation.** Memories cross once, after a fixed local phase. Continuous federation, and memories derived *from* imported ones, are untested.
3. RuleWorld effects remain ~10× production scale; the shape of the curve should transfer, the magnitudes should not.
4. Scripted agent; no LLM confirmation.
5. **The probe is the only transferability mechanism tested.** Cheaper alternatives — sharing metadata first and fetching on demand, or predicting transferability from memory features without probing — are not compared here.
6. Contexts are symmetric: both agents see equally hard worlds and equally useful memories. Asymmetric expertise is untested.

## 9. What gets reported

The full curve for all three arms at every `o`, paired differences with intervals, negative transfer, communication volume, probe cost, the sanity gates, and the verdict against §6 — including "killed" or "inconclusive".
