# Decision — P8: do not build the learned controller

- **Date:** 2026-10-07
- **Decision: H5 is not run, and the System-1 controller is not built.** Its premise is measurably false in this system.

## H5 as registered

> A distilled small controller matches the LLM controller (≥ 90% agreement, ≤ 2 pp loss) while **replacing ≥ 50% of memory-management LLM calls**.

## The measurement

Counting what the fabric actually spends on memory management, over 300 episodes of retrieve + write + outcome:

| | |
|---|---|
| Time per episode | **0.26 ms** |
| LLM calls in the memory path | **0** |

Every memory-management decision the fabric makes today is a rule evaluation or an index lookup:

| decision | cost |
|---|---|
| retrieve / rank / expose | vector search + estimator lookup |
| write (`remember`) | regex ingest screen |
| forget / retention sweep | rule evaluation |
| share / firewall | rule evaluation |

**The denominator is zero.** "Replaces ≥ 50% of memory-management LLM calls" is undefined when there are none to replace, so H5 is not falsifiable as written — not failed, unaskable.

## Why, and what it would take to make the question real

This is exactly what [CRITICAL_REVIEW](../CRITICAL_REVIEW.md) §6 predicted: *"Retrieve / store / forget decisions are already cheap… The expensive calls are the LLM calls for consolidation, contradiction detection and skill synthesis. A small controller saves money only if it replaces LLM calls, so measure which ones."*

Those three are the LLM-expensive parts of the design, and **none of them are built**:

- **Contradiction detection** — a P7 deliverable that was never implemented. `challenge()` is manual: a human or a caller names the conflicting memories.
- **Consolidation** — episodes into semantic beliefs. Not built.
- **Skill synthesis** — trajectories into procedures. Not built.

So there is nothing to distill because the parts that would need a model were never written. A learned controller would be a cheaper version of a cost the system does not pay.

## Consequence

Per AGENTS.md principle 9 — *infrastructure follows measured need* — the controller is not built. This is the principle doing its job rather than being quoted at a decision already made: the measurement came first and the build was cancelled by it.

**H5 is re-registerable only after an LLM-dependent memory operation exists.** The natural candidate is contradiction detection, which the project needs anyway (P7 shipped `challenge()` manual) and which would be called often enough for its cost to matter. The right sequence is:

1. Build LLM-backed contradiction detection, and measure its precision and recall — CRITICAL_REVIEW §4 flags it as a likely source of downstream errors, so it needs measuring in its own right.
2. Measure what it costs per episode. If that cost is immaterial, stop: there is still nothing to optimise.
3. Only then register **H5′**, with the denominator established first — the same discipline AGENTS.md 8a imposes on thresholds.

## What was delivered instead

Nothing, deliberately. The measurement above and this record.
