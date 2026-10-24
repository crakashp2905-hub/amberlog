# Pre-registration — S2: is a second report a second source?

**Registered 2026-10-18, after a dev run of every arm and before any test
seed.** This is research direction S2 in [WORKPLAN.md](../../docs/WORKPLAN.md).
The mechanism is `memory_fabric/independence.py` and the harness is
`experiments/s2_launder_sim.py`, both committed with this file.

**Disclosed:** the dev split (seeds 100–109) was run with all five arms, the
mechanism included, before this was written. That run is how the 8c and 8d
checks below were done, and it is also where the bar's consequences were
visible. The bar is the project's standard 40% of headroom (`memeval`'s
default), not a number chosen from dev, and the dev result says the mechanism
will probably miss it (§8).

## 1. Question

Copy laundering means rewording a report you were shown and writing it back as
your own. Can the exposure log the store already keeps (AGENTS.md principle 4)
tell a laundered report from an independent one, inside one store and across
stores, better than a deduplicating store can by wording? And what does it
cost in real corroboration it wrongly discounts?

## 2. Mechanism

`Independence.sources`: a report is not a source if its author had been
**shown** another report's evidence before writing it. That is, the exposure
log has the author exposed to a memory whose original (`global_ref`) is
another member's. Across stores, the dependency travels with the share as
`context.federation.informed_by`, together with `root`, the original's
store-independent name. The test is causal opportunity, not similarity.

## 3. Design: LaunderSim (deterministic, no model)

Three real stores: the deciding store D and peers s0 and s1. Retrieval,
exposure logging and federation are real. Each seed writes 7 families × 3
clusters = 21 clusters, shuffled. A cluster is the reports of one equipment
fault that reach D. An observer's report draws its own time and reading. A
laundered copy is one of three kinds:

- **verbatim** (20%): with a filing prefix;
- **summary** (30%): with no details;
- **reworded** (50%): with the source's details.

A laundered copy never adds information.

| family | what happens | true sources |
|---|---|---|
| `laundering_local` | 1 observer; 2 copies written in D by agents shown it | 1 |
| `laundering_cross_store` | observer at s0; at s1 an agent shown the import writes a copy; both shared to D | 1 |
| `collusion` | 1 observer; a copy by an agent told off-store (no exposure anywhere) | 1 |
| `independent_similar` | 2 observers never shown each other, same template bank | 2 |
| `independent_cross_store` | 2 observers at different stores, both shared to D | 2 |
| `exposed_but_independent` | 2 observers; the second is shown the first's report, then observes for itself | 2 |
| `independent_plus_copy` | 2 observers plus a copy of one of them | 2 |

The decision is the one corroboration asks: **are there at least two
independent sources?**

## 4. Arms

| arm | sources counted as |
|---|---|
| `count_all` | every report |
| `provenance` | distinct originals: lineage, recognised copies and the federation root (the product as it ships) |
| `similarity` | provenance, then near-duplicates joined. Measure and threshold tuned on dev over {content-term Jaccard, overlap coefficient, hashing-embedder cosine} × τ ∈ [0.10, 0.90]. **Dev chose `overlap@0.9`, fixed for test** |
| `exposure` | §2 |
| `oracle` | the true count |

## 5. Ceiling and baseline checks (AGENTS.md 8a–8d), done on dev before registering

These are measured on the same metric (decision accuracy), the same decision
(≥ 2 sources) and the same unit (the cluster) as the threshold. Dev split,
210 clusters:

| arm | decision accuracy | false corroboration | blocked independent |
|---|---|---|---|
| `count_all` | 0.571 | 1.000 | 0.000 |
| `provenance` | 0.605 | 0.922 | 0.000 |
| `similarity` (overlap@0.9) | **0.652** | 0.789 | 0.017 |
| `oracle` | 1.000 | 0 | 0 |

- **8c:** no registered baseline maxes the metric. The best is 0.652 against a
  ceiling of 1.000, so the headroom is 0.348.
- **8b:** the oracle knows only the true count. It uses the same decision rule,
  and every run checks whether any arm beats it.
- **8d:** the baseline number is re-measured on the test split by the run
  itself, and the registration's verdict uses that, not this table.

## 6. Metrics

- **Primary: decision accuracy.** The share of clusters where (counted ≥ 2)
  equals (true ≥ 2).
- **False corroboration:** among one-source clusters, the share decided as
  corroborated.
- **Blocked independent evidence:** among two-source clusters, the share
  decided as uncorroborated.
- Per-family accuracy.

## 7. Hypothesis and threshold

**S2.** On the test split (seeds 0–19, 420 clusters), `exposure` closes **at
least 40%** of the headroom between the best baseline and the oracle on
decision accuracy. The best baseline is whichever of the three registered
baselines scores highest on test. `memeval.Registration` applies, with 20
seeds required. Power: at the dev discordance of 0.39, 420 pairs give an MDE
of 0.085, against roughly 0.14 needed to pass. The verdict reports the
realised MDE.

## 8. Predictions

1. **S2 is not supported at 40%.** On dev, `exposure` closed 27%
   (0.748 against 0.652).
2. All of `exposure`'s errors come from two families:
   - **`exposed_but_independent`:** it scores 0 there. It cannot tell an
     exposed author who observed for themselves from a copier, so it blocks
     real corroboration. This is the price, and it equals that family's share
     of the case mix.
   - **`collusion`:** it scores 0.23 there, the verbatim copies that
     `provenance` already catches. Nothing that reads only the store can see
     influence outside it.
3. `exposure` is perfect on both laundering families, where every baseline
   scores at or below 0.27.
4. `similarity` trades blocked independent evidence for caught copies and
   cannot reach the laundering families: summaries carry no shared details.

## 9. What a pass or a failure would not establish

The texts come from templates I wrote. The similarity baseline's numbers
depend on how far my rewordings drift from their sources, and a real
paraphrase could be nearer or further. The exposure mechanism's numbers do
not depend on wording at all; they depend on the case mix. 2 of 7 families
are where it is blind or costly, and a deployment's mix is unknown. Laundered
copies here never add fabricated details. A launderer who does would defeat
any novelty-based refinement, which is why none is registered.
