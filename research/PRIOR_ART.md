# Prior art — verified 2026-10-07

CRITICAL_REVIEW §1 set the rule: *"Citations below are from memory and not yet checked against the papers. Check every one before it appears in a paper or a pitch."* This file holds the ones that have actually been checked, and what each does to this project's novelty claims.

**Provenance note.** The four papers below arrived in a review whose URLs carried `utm_source=chatgpt.com`, meaning they came from another model's browsing and could have been fabricated. All four were fetched and confirmed real before any of them was allowed to change a claim here. That check is the point: a novelty downgrade sourced from an unverified citation would be worse than no downgrade at all.

---

## Verified

### Learning What to Remember (arXiv 2606.12945, June 2026)
Chen & Cheng. *A Cognitively Grounded Multi-Factor Value Model for Agentic Memory.*

Learns a multi-factor value function over seven cognitively-motivated factors (emotional intensity, goal relevance, value alignment, self/user relevance, task utility, reliability, usage history) to decide what to retain, forget or retrieve under a fixed budget. Reports 77% gold-evidence retention against 65.7% uniform weighting and 36.8% recency.

**Effect here:** *"a memory has a learned value score"* is **not novel**. This does it with more factors than we do.

**Where we still differ:** their factors are largely properties of the memory and the query. Ours is an estimate of a **causal effect on outcomes**, corrected for the selection bias that retrieval introduces (H1). Those are different quantities — a point worth making precisely rather than claiming priority.

### AMV-L (arXiv 2603.04443, February 2026)
Bamidele. *Lifecycle-Managed Agent Memory for Tail-Latency Control in Long-Running LLM Systems.*

Value-driven lifecycle tiers with a bounded retrieval candidate set, aimed at tail latency: 3.1× throughput and 4.2× median latency against TTL, with >2s requests cut from 13.8% to 0.007%.

**Effect here:** **lifecycle-managed memory is not novel.** It also reframes the problem usefully — their driver is *latency*, ours is *correctness*. Our [P9 decision](decisions/2026-10-07-p9-declined.md) declined distribution on latency grounds (4.39 ms at 2,000 memories); AMV-L is evidence that latency becomes the binding constraint at a scale we have not reached.

### MeClear (arXiv 2609.09115, September 2026)
*Cooperative Game-Theoretic Attribution and Risk-Aware Memory Clearance for Long-Horizon LLM Agents.*

The closest work to ours. Combines Leave-One-Out screening with sampled Shapley attribution to find memories with negative downstream utility, then applies query-scoped minimal clearance without permanently altering the memory bank. Reports 85.9% target recall and 82.3% task recovery, **+25.5pp over Leave-One-Out baselines**.

**Effect here:** **causal attribution for memory clearance is not novel.** This is the strongest single correction to our positioning.

**But our killed H2 is a direct observation about it.** MeClear's baseline is LOO. [H2](results/h2-credit-driven-retention.md) found that a smoothed usage-success rate *matches* a propensity-corrected amortized estimator for the retention decision, and captures 93% of what a perfect oracle achieves — because harm is directly visible in raw outcomes, so debiasing buys little at the single threshold a budget decision asks about. **An attribution method that beats LOO has not yet been shown to beat the cheap baseline.** That is a testable criticism, and it costs nothing to run.

### MemBuilder (ACL 2026, long paper 1284)
Shen, Wu, Lai, Lian & Rao. *Reinforcing LLMs for Long-Term Memory Construction via Attributed Dense Rewards.*

RL for memory construction using attributed dense rewards, with synthetic question generation for the sparse-reward problem and contribution-aware gradient scaling. A 4B model beats closed-source baselines on long-term dialogue.

**Effect here:** **attributed downstream impact for memory construction is not novel.** It is also the strongest existing answer to the question our [P8 decision](decisions/2026-10-07-h5-premise-false.md) declined to build toward — a learned memory policy — and it learns *construction* where our controller would have learned *lifecycle actions*.

---

## What this leaves

Lowered to **not novel**: memory value scoring, lifecycle management, causal attribution for clearance, attributed memory construction.

Still defensible, and now more precisely stated:

1. **Outcome-grounded governance as a substrate**, rather than a scoring function: provenance, TMS-style retraction that follows a memory across store boundaries, a firewall where the recipient decides, and an audit trail that survives all of it. None of the four papers carries provenance across a federation boundary.
2. **Causal value plus transferability across contexts.** [H3](results/h3-selective-federation.md) measured the crossover curve; the open question it leaves — whether overlap estimation captures most of the available benefit — is a better question than the one we registered.
3. **Contradiction preservation, tested twice.** [H4b](results/h4-topology-and-diversity.md) in simulation and [live](results/live-multi-agent.md) with real disagreeing agents. The live result is narrower than the simulated one and more defensible for it: it prevents unsupported confidence rather than producing correctness.
4. **The negative results themselves.** H2 killed, H3's threshold exceeding its own ceiling, H5 unaskable, P9 declined. Adjacent papers report wins; a published account of what *did not* work, with pre-registered thresholds, is scarce and useful.

## The honest summary

> The implementation is unusually mature for the research stage, and the strongest scientific contribution is still emerging. The component claims are largely not novel; the substrate they sit in, and the negative results, are.

## Addendum, 2026-10-16: work found for the safety plan

A short web search, not a systematic review (see
[docs/RESEARCH_ROADMAP.md](../docs/RESEARCH_ROADMAP.md)), found close 2026 work:

- **MemLineage** (arXiv 2605.14421): cryptographic provenance plus a derivation
  lineage graph, blocking sensitive actions that depend on external ancestry.
- **Proof-Carrying Agent Actions** (arXiv 2606.04104): action certificates with
  pre-action admissibility, approval and audit receipts.
- **SMSR** (arXiv 2606.12703): HMAC provenance at write time, with a certified
  robustness bound for multi-session poisoning.

So lineage-gated actions and action certificates are **not** new mechanisms.
The evidence certificates and action gate here are an implementation of known
ideas over this repository's event log and truth maintenance. None of these
works has been compared with this one on a shared benchmark.
