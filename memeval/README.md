# memeval

An evaluation harness for agent memory that **refuses to give a verdict when
the run made one of the usual mistakes**. Proprietary, under the repository's
[LICENSE](../LICENSE); a separate distribution, not a separate licence. It uses only the standard library and
doesn't depend on Memory Fabric, which it was extracted from.

Most evaluation code works out a number. memeval works out whether the number
can be believed. It was built because Memory Fabric published results that
were wrong in ways no single test caught: a baseline quoted from another
table, a ceiling that one of the arms beat, a threshold above everything
achievable, an AUC reported in the wrong orientation, and a run too small to
see the effect it reported. Each check here comes from one of those cases.

## Use

```python
from memeval import Registration

reg = Registration(
    hypothesis="scoped adjustments raise sufficiency on the seasonal family",
    metric="sufficiency",
    mechanism="adjust_extracted",
    baselines=["vector", "lexical", "full_context"],
    ceiling="oracle",
    share_of_headroom=0.40,     # pass = baseline + 40% of (ceiling - baseline)
    min_effect=0.05,
)

# Before spending compute:
problems = reg.check_before_run(n_pairs=320, expected_discordance=0.25,
                                expected_headroom=0.30)

# After the run, with every arm measured *in this run*:
verdict = reg.evaluate(arms, seeds=5, n_pairs=320, discordance=0.22)
print(verdict.outcome, verdict.reasons)
```

## Verdicts

| outcome | when |
|---|---|
| `INVALID` | A registered baseline, the ceiling or the mechanism wasn't measured in the run; **any** arm scored above the ceiling; or there were fewer seeds than required. |
| `ABANDONED` | The headroom (ceiling minus the best baseline) is at or below `abandon_at_headroom`, so a baseline already does what the metric can measure. |
| `UNDERPOWERED` | The run's minimum detectable effect is bigger than the gain it needed to pass. |
| `SUPPORTED` / `NOT SUPPORTED` | None of the above, and the mechanism did or didn't reach the bar. |

The bar is always a **share of the measured headroom**, never an absolute
margin, so a threshold above the ceiling can't be registered at all.

## Where each refusal comes from

| refusal | the published error it would have stopped |
|---|---|
| baseline not measured | X1 took a baseline of 0.000 from a table of nDCG@3. Its registered metric was sufficiency@5, where the lexical baseline scores 1.000. |
| arm above ceiling | Phase A's oracle was limited by its retrieval budget, and an arm beat it. |
| baseline maxes metric | In P2, the `full_context` baseline reached the oracle's 0.800, so no threshold could be passed. |
| headroom too small | H3 registered a margin of +0.030 when the total gain available was +0.027. |
| underpowered | X4 reported differences of about 0.04 with a minimum detectable effect of 0.10–0.14. |
| AUC orientation (`checks.direction`) | `abstention-signals.md` published 0.319, the complement of 0.682. |
| collapse to prior (`checks.collapsed_to_prior`) | X2b's recalibration got an ECE of 0.008 by predicting the base rate. |

`tests/test_memeval.py` rebuilds each of these cases and asserts the contract
refuses it.

## Modules

* `memeval.contract`: `Registration`, `Verdict`, `Outcome`.
* `memeval.power`: closed-form MDE for paired and independent designs,
  `pairs_needed`, and `absence_bound` (the largest true rate that a zero at
  this n can't rule out).
* `memeval.stats`: a paired bootstrap that resamples units rather than
  arms, and `Interval.within(margin)` for equivalence claims ("no effect" is
  an interval inside a margin, not a failure to exclude zero).
* `memeval.checks`: the individual checks, usable without a registration.

## What it doesn't do

It can't tell you whether a hypothesis is worth testing, whether the world can
show the effect, or whether a fixture encodes the answer
(`checks.fixture_independence` handles that last one at test time). It makes
one class of reporting error impossible to publish without the harness saying
so. It doesn't make an experiment good.
