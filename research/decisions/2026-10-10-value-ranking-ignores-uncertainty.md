# Decision — value ranking ignores its own uncertainty; fix after the runs in flight

- **Date:** 2026-10-10
- **Status:** **fixed** 2026-10-10, after PA′ and Phase B had both finished and Phase C was on its final seed. Recorded before either verdict; applied after, so no registered run changed semantics mid-flight.
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

## The fix, as applied

`has_value_evidence` now requires three things: an estimate exists, it is
**contrastive**, and its interval **clears zero** (`shows_benefit`, or the whole
interval below zero for measured harm). `_rank_key` ranks on value only for such
a candidate and falls back to relevance otherwise.

Measured behaviour after the fix: thin evidence (mean +0.10, interval
[-0.40, 0.60], n=1) now loses to a candidate nineteen times more relevant; solid
evidence (mean +0.80, interval [0.50, 1.00], n=12) still beats relevance; and a
memory measured to *harm* ranks below an unevaluated one. All three are tests. This is the rule
the firewall already applies to scope promotion, so it makes one standard out of
two. `Candidate.has_value_evidence` exists but currently only checks
`n_eff > 0`, which is too weak for this; it needs to mean *the estimate would
survive being acted on*.

Then re-measure `fabric_contrastive`, since its registered question — does
withdrawing on contrastive harm beat withdrawing nothing — has not actually been
asked yet under a ranking that respects its own intervals.

## Audit: this is the only place in the codebase that does it

Every other consumer of a `ValueEstimate` already consults its uncertainty, so
the standard the fix should apply is not a new one — it is the one the rest of
the project already keeps.

| Consumer | What it checks | Verdict |
|---|---|---|
| `governance/firewall.py` | `n_eff > 0`, `contrastive`, `shows_benefit` (lower bound clears zero) | correct |
| `governance/retention.py` | withdraws only at `n_eff >= 10` **and** `ci_high < 0` | correct, and stricter than anything else |
| `adapters/context.py` (`describe_evidence`) | `n_eff`, `contrastive`, `shows_benefit`, `ci_high < 0`; says "unevaluated" or "effect unmeasured" rather than showing a number it cannot justify | correct |
| `explain.py` | prints the mean only beside its interval | correct |
| `federation.py` (`describe`) | `mean if n_eff > 0 else None` | correct |
| `observability/report.py` | `None if n_eff <= 0 else mean` | correct |
| **`exposure.py` (`Candidate.value_mean`)** | **the mean, and nothing else** | **the defect** |

`retention.py` is worth singling out: it refuses to act below ten effective
observations *and* requires the whole interval below zero. That is the right
shape, and it is what the exposure policy should have been doing all along.

So this is not a gap in the project's thinking — the type carries uncertainty,
six of seven call sites use it, and the firewall's `shows_benefit` already
encodes the exact rule the fix needs. One call site reached past it.

## Why it survived

The same reason as the tie-break bug: every test of the ranking gave its
candidates values that differed clearly. None gave one a mean with an interval
spanning zero. The project has a type that carries uncertainty and a principle
that says to use it, and the tests still only exercised the case where the
number happens to be trustworthy.

## Afterwards

`fabric_contrastive`'s registered question — does withdrawing on contrastive
harm beat withdrawing nothing — **has still not been asked** under a ranking
that respects its own intervals. PA′'s number for that arm stands as a
measurement of the old configuration and should not be quoted as a measurement
of contrastive withdrawal. Re-measuring it is a registered follow-up, not a
re-run of PA′.
