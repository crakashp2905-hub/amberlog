# Decision — value ranking ignores its own uncertainty; fix after the runs in flight

- **Date:** 2026-10-10
- **Status:** defect recorded, **fix deliberately deferred** until PA′ and Phase B have both finished.
- **Written before** either verdict, so that neither result can be reinterpreted in light of a fix made afterwards.

## The defect

`rank_by="value"` orders candidates on `ValueEstimate.mean` alone. It does not
consult `n_eff` or the credible interval. Measured directly:

| candidate | relevance | n_eff | mean | interval | P(expose) |
|---|---|---|---|---|---|
| A | 0.05 | 1 | +0.10 | [−0.40, 0.60] | **0.90** |
| B | 0.95 | 0 | — | — | **0.10** |

A single observation whose interval spans zero outranks an unevaluated memory
**nineteen times more relevant**. One episode is not evidence that a memory
helps, and nothing in the ranking says so.

This contradicts the project's own fifth principle — *credit is a distribution,
not a number* — which the type system enforces everywhere else. `ValueEstimate`
carries `ci_low`, `ci_high`, `n_eff` and `contrastive` precisely so that callers
cannot treat a mean as a fact; the firewall already refuses to promote a memory
on non-contrastive evidence. The exposure policy is the one place that reads the
mean and discards the rest.

It is **distinct from the tie-break bug** fixed earlier the same day. That one
made *all* candidates tie at zero and fall through to creation time, and the fix
added relevance as a tie-break. This one bites after evidence starts to
accumulate: a memory with any non-zero mean no longer ties, so the relevance
fallback never applies to it, however worthless the number is.

## Why the fix is deferred

Two registered runs are in flight when this was found. PA′'s
`fabric_contrastive` arm and **every** arm of Phase B run under
`epsilon_greedy:value`. Changing the ranking now would mean PA′ ran under one
semantics and Phase B under another, and the two would stop being comparable —
which is worse than either running under a known, documented defect.

So both runs complete under the current behaviour, and this file is the record
that the behaviour was known and characterised before their numbers were seen.

## What it means for the results

**PA′'s `fabric_contrastive`.** Its deficit against the pooled baseline cannot
be attributed to its withdrawal rule. [PA′'s registration](../prereg/phase-a-prime-attribution.md)
§3 already stated that confound in advance — "a loss by this arm cannot be
cleanly attributed between the withdrawal rule and the exploration it requires"
— and this is the specific mechanism behind it. The arm's number stands as a
measurement of *that whole configuration*, not of contrastive withdrawal.

**Phase B.** The exposure policy is held constant across every arm by
[amendment](../prereg/phase-b-federated-agents.md), so the defect applies
uniformly and cannot bias one sharing policy against another. It does lower
every arm including `oracle_share`, and PB1's threshold is a share of that
ceiling's headroom, so the comparison remains well-posed while the absolute
numbers run low.

**Phase A is unaffected.** Its `fabric` arm used `top_k:relevance`, and the
correction to `fabric_causal` is already recorded in §6a of
[its result](../results/phase-a-real-agent-benchmark.md).

## The fix, once both runs are done

Rank on value only where the estimate supports a claim — contrastive, and the
interval clear of zero — and fall back to relevance otherwise. This is the rule
the firewall already applies to scope promotion, so it makes one standard out of
two. `Candidate.has_value_evidence` exists but currently only checks
`n_eff > 0`, which is too weak for this; it needs to mean *the estimate would
survive being acted on*.

Then re-measure `fabric_contrastive`, since its registered question — does
withdrawing on contrastive harm beat withdrawing nothing — has not actually been
asked yet under a ranking that respects its own intervals.

## Why it survived

The same reason as the tie-break bug: every test of the ranking gave its
candidates values that differed clearly. None gave one a mean with an interval
spanning zero. The project has a type that carries uncertainty and a principle
that says to use it, and the tests still only exercised the case where the
number happens to be trustworthy.
