# Pre-registration — P1b: rank covering candidates by how discriminating their link is

**Registered 2026-10-16, before the change to `chains.py` and before any
holdout case exists on disk.**

## Why

P1 found a failure on its frozen test split: on `multi_hop_4`, the chain
covered the remaining query terms with an axle-pressure rule for the **wrong
axle type**. Every axle rule shares the generic tokens *axle* and *set* with
the chain; only the right one also shares *light* or *heavy*. Covering
candidates are ranked by query-term gain and then by retrieval rank, so the two
rules tie on gain and the discriminating link is never consulted.

P1 declined to fix it because the failure was seen on the frozen split, and a
fix judged there would be tuned on it. That split is now **contaminated** for
this change and is reported as such, never as evidence.

## The change

Among covering candidates with equal query-term gain, prefer the one whose
rarest term shared with the current chain is rarest in the candidate pool.
That is the rule bridges already use. Candidates sharing nothing with the
chain rank after those that share something. Nothing else changes.

## Data

- **dev**: `relevance_v2` dev, the chain families (6 cases).
- **holdout (new)**: `multi_hop_3` and `multi_hop_4` built by the frozen
  generator at case indices 100–111, so 24 cases never built before. They are
  generated in memory, scored once, and not inspected before scoring.
- **test (contaminated)**: reported for completeness, labelled contaminated.

## Metric and thresholds (AGENTS.md 8a–8c)

Primary metric: chain **sufficiency**, pooled over the two families. A case is
sufficient when the chain is complete and contains every labelled requirement.

- Ceiling: the oracle, sufficiency 1.000 by construction (the labelled set).
- Baseline B: the unchanged chain on the same cases.
- **SUPPORTED** if the changed chain closes **≥ 40%** of the headroom on the
  holdout, i.e. S ≥ B + 0.4 × (1 − B), **and** dev sufficiency does not fall.
- If B on the holdout is already ≥ 0.9, the headroom is too small to judge and
  the result is reported as **INCONCLUSIVE**, whatever S is.
- 8c check: a degenerate arm that returns every candidate is reported. It
  satisfies coverage trivially, but it is not a chain and cannot be
  "sufficient" under the requirement-set definition, so the metric cannot be
  maxed by a baseline.

Secondary, reported but not gating: `multi_hop_4` alone; mean nodes explored
(cost); chain length.

If NOT SUPPORTED, the change is reverted and the result is reported.
