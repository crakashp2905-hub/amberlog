# Pre-registration — P1c: choose the chain whose weakest link is strongest

**Registered 2026-10-16, before the change and before holdout 2 is built.**

## Why

P1b's diagnosis ([p1b-links.md](../results/p1b-links.md)): on the wrong-axle
cases the right and the wrong chain are both complete and both "connected",
but the wrong one is connected only through **set**, a term shared by every
axle rule and present as a verb in unrelated memories. Goal selection compares
length and retrieval cost and never asks how strong a chain's links are.

## The change

Among goal states (complete and connected), prefer the one whose **weakest
link is strongest**. The strength of the link between two connected members is
the rarity of the rarest term they share (lowest document frequency). A
chain's weakest link is the minimum strength over the edges of a spanning tree
that maximises it (the bottleneck). Ties fall back to the current order:
length, then cost. Expansion is unchanged, so cost is bounded as before.

No threshold and no stopword list: the comparison is relative, within one
query's goal states.

## Data

- **dev**: relevance_v2 dev, chain families (6 cases). Must not get worse.
- **holdout 2 (new)**: generator indices **200–211** for `multi_hop_3` and
  `multi_hop_4` (24 cases), built only when the run starts and scored once.
- Holdout 1 (indices 100–111) and the frozen test split are **contaminated**
  for this change. Both are reported, labelled, and neither is evidence.

## Thresholds (AGENTS.md 8a–8c)

Same metric as P1/P1b: pooled chain sufficiency, k = 5, oracle ceiling.

- **SUPPORTED** if, on holdout 2, S ≥ B + 0.4 × (C − B), where B is the
  current chain and C the oracle, **and** dev does not fall.
- **INCONCLUSIVE** if B ≥ 0.9.
- Otherwise **NOT SUPPORTED**, and the change is kept off.

`multi_hop_4` also needs a modifier that no chain search reaches (P1). Its
ceiling for any chain-selection change is therefore ~0, and pooling dilutes
the effect. That is accepted: the threshold is set on the pooled metric before
seeing any result.
