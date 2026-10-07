# Decision — H3 inconclusive; ship the module, re-register the hypothesis

- **Date:** 2026-10-05
- **Evidence:** [../results/h3-selective-federation.md](../results/h3-selective-federation.md)
- **Decision: ship the federation module; do not claim selective federation works; re-register as H3b.**

## What was decided

H3 was **inconclusive**. Selective federation is the best policy at every overlap, but by 0.3–1.1 points against a registered bar of 3.0.

**The bar was unpassable.** Perfect knowledge of which imports help — measured post-hoc with an oracle arm — yields at most +0.027 over the better fixed policy, anywhere on the curve. The registered threshold was +0.030. I set a margin without first establishing a ceiling, so no method could have passed.

The verdict stands as written. Moving a threshold after seeing results is the thing pre-registration exists to prevent, and the right repair is a new registration, not an edited one.

## What changes

1. **The federation module ships.** Its guarantees are governance properties — the recipient decides, imports arrive unvalidated, provenance crosses the boundary — and none of them depend on H3's outcome.
2. **No product claim that selective federation improves outcomes.** The evidence does not support it.
3. **The curve itself is the shippable finding.** "Share everything" costs 2.6 points when contexts do not overlap; "share nothing" costs 2.7 when they fully do. A federation layer that knows its agents' overlap can pick correctly between the two, and that is worth more than any cleverness measured here.
4. **Fix the firewall's federation rule, or document it as a floor.** It gates on value measured in the *sender's* context. H3's premise — that value does not survive a context boundary — is now supported by the curve: at o=0 a memory that is genuinely valuable to its owner is wrong for the recipient half the time. The rule blocks memories with no evidence anywhere, which is useful, but it is not evidence about the recipient.

## What the data does support

The probe mechanism works. Against a control that pays the identical cost and keeps the identical number of imports at random, selection wins by +0.010 to +0.021 — at most overlaps a *larger* gap than selective's margin over the fixed policies. The method is sound; the headroom is small.

## Next: H3b

> **H3b** — selective federation captures ≥ 50% of the oracle's available headroom at intermediate overlap, with fresh seeds and the ceiling established before the threshold is set.

Two things H3b must include that H3 lacked:

- **An oracle arm from the start.** A threshold set without a ceiling is not a threshold. This is now a standing requirement for any experiment in this project that compares a method against baselines.
- **An "estimate overlap, then pick a fixed policy" arm.** It may capture most of the achievable gain without probing at all, and if it does, selective federation is not worth its complexity.
