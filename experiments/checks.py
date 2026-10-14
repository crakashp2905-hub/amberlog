"""Runtime checks that run on every experiment, not tests that run in CI.

AGENTS.md principle 8b says *"did any arm beat the oracle?" is checked on
**every run***, and the reason it says "every run" is that these faults are
invisible on inspection. This module is the four checks that actually caught
errors in this project, made mechanical so the next experiment cannot forget
them.

Each one exists because of a specific published number that was wrong:

| check | what it caught |
|---|---|
| `direction` | `abstention-signals.md` reported **AUC 0.319** for a signal whose true value is 0.682 — the same number upside down. Three of its four other figures reproduced exactly, and the one summary statistic nobody could eyeball was the one that was wrong. |
| `ceiling` | H3 registered a margin larger than its own ceiling; Phase A's oracle was bounded by its retrieval budget. Principle 8b. |
| `baseline_max` | P2's `full_context` baseline *reached* the oracle's 0.800, so the threshold was unreachable before any method existed. Principle 8c. |
| `class_collapse` | `parse()` returned a record that classified as `plain`, the majority class, so a model that failed on all 19 statements scored **17/17** on the column built to catch bad behaviour. |

A fifth fault has no runtime check and gets a test helper instead:
`infer_relations`' unit test supplied **both** strings it matched, so it passed
on one of four combinations of {hand-written, measured} × {target, predicate}.
See `fixture_independence`.

## How to use it

Harnesses call `verify(...)` and put the returned block in their result, so
every run carries its own audit. A check that **fails** is not an exception by
default: an experiment that dies before writing its output has lost the
measurement, which this session did three times. The block says `ok: false`
and names the reason, and `raise_on_fail=True` is available where a caller
would rather stop.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Sequence


def auc(positive: Sequence[float], negative: Sequence[float]) -> float | None:
    """P(a negative scores above a positive), ties at half.

    One implementation, used by every caller, so a convention error is made
    once rather than per experiment.
    """
    if not positive or not negative:
        return None
    wins = sum((1.0 if n > p else 0.5 if n == p else 0.0)
               for p in positive for n in negative)
    return wins / (len(positive) * len(negative))


def direction(positive: Sequence[float], negative: Sequence[float],
              expect: str = "negative_scores_higher") -> dict[str, Any]:
    """Report **both** orientations of an AUC, and which one was claimed.

    The complement error is undetectable from a single number: 0.319 and 0.682
    are equally plausible-looking, and `abstention-signals.md` built a title, a
    summary table and two sections of narrative on the wrong one. Reporting
    both makes the mistake visible in the output rather than discoverable a
    year later by an unrelated experiment.

    `expect` names the convention the caller intends, so the result records an
    intention rather than an artefact.
    """
    forward = auc(positive, negative)
    if forward is None:
        return {"ok": True, "auc": None,
                "note": "one group was empty; no direction to check"}
    backward = 1.0 - forward
    claimed = forward if expect == "negative_scores_higher" else backward
    return {
        "ok": True,
        "expect": expect,
        "auc": round(claimed, 4),
        "auc_if_reversed": round(1.0 - claimed, 4),
        "above_chance": claimed > 0.5,
        "note": ("both orientations are reported because a single AUC cannot "
                 "be checked by eye; see checks.direction"),
    }


def ceiling(arms: Mapping[str, Mapping[str, Any]], metric: str,
            ceiling_arm: str = "oracle") -> dict[str, Any]:
    """Principle 8b: an arm above the ceiling proves the ceiling is wrong.

    Not "is a surprising result". H3, Phase A and Phase B each had a ceiling
    that looked unimpeachable until an arm beat it.
    """
    if ceiling_arm not in arms:
        return {"ok": True, "note": f"no {ceiling_arm!r} arm in this run"}
    limit = arms[ceiling_arm].get(metric)
    if limit is None:
        return {"ok": True, "note": f"{ceiling_arm!r} has no {metric!r}"}
    over = {
        name: row[metric] for name, row in arms.items()
        if name != ceiling_arm and row.get(metric) is not None
        and row[metric] > limit
    }
    return {
        "ok": not over,
        "ceiling_arm": ceiling_arm,
        "ceiling": limit,
        "arms_above_ceiling": over,
        "note": ("an arm above the ceiling is a proof the ceiling is wrong, "
                 "not a result (principle 8b)") if over else "",
    }


def baseline_max(arms: Mapping[str, Mapping[str, Any]], metric: str,
                 baselines: Sequence[str],
                 ceiling_arm: str = "oracle",
                 tolerance: float = 0.05) -> dict[str, Any]:
    """Principle 8c: a primary metric a baseline already maxes is not a metric.

    Reports the headroom `C - B` and whether the abandonment clause applies.
    This is the check X1's registration performed and answered from the wrong
    row of another document (principle 8d), which is why the numbers here come
    from the run rather than from prose.
    """
    present = [b for b in baselines if b in arms]
    scores = [arms[b][metric] for b in present
              if arms[b].get(metric) is not None]
    if not scores:
        return {"ok": True, "note": "no registered baseline scored this metric"}
    best = max(scores)
    limit = (arms.get(ceiling_arm) or {}).get(metric)
    # Rounded to the precision it is reported at, because the comparison is
    # against a registered boundary and float arithmetic does not respect it:
    # `1.0 - 0.95` is 0.050000000000000044, so a headroom of exactly the
    # abandonment tolerance passed a `<= 0.05` test. A boundary check that
    # fails at its own boundary is worse than no check, because it passes.
    headroom = None if limit is None else round(limit - best, 4)
    degenerate = headroom is not None and headroom <= tolerance
    return {
        "ok": not degenerate,
        "metric": metric,
        "baselines_measured": present,
        "B_best_baseline": round(best, 4),
        "C_ceiling": limit,
        "headroom": None if headroom is None else round(headroom, 4),
        "note": (f"headroom {headroom} <= {tolerance}: the metric is maxed by "
                 f"a baseline and the abandonment clause applies "
                 f"(principle 8c)") if degenerate else "",
    }


def class_collapse(counts: Mapping[str, int],
                   failure_classes: Iterable[str] = ("unparsed", "error",
                                                     "truncated"),
                   majority_class: str | None = None) -> dict[str, Any]:
    """Flag a classifier whose failure mode is its own majority answer.

    An unparseable reply became `Extracted(asserts=False)`, which has no
    target and no exclusions, so it classified as `plain` — the majority class
    — and a model that failed on every statement scored full marks on the
    column built to catch exactly that.

    The check is that a failure class is **counted at all**. A classifier that
    reports no failure class has not shown that it can distinguish silence
    from its most common correct answer.
    """
    named = [c for c in failure_classes if c in counts]
    if not named:
        return {
            "ok": False,
            "counts": dict(counts),
            "note": ("no failure class is counted, so a reply the classifier "
                     "could not read is indistinguishable from its majority "
                     "answer; count 'unparsed' explicitly"),
        }
    return {
        "ok": True,
        "failure_classes_counted": named,
        "failures": {c: counts[c] for c in named},
        "majority_class": majority_class,
    }


def collapsed_to_prior(mean_probability: float, base_rate: float,
                       accuracy_at_half: float,
                       tolerance: float = 0.02) -> dict[str, Any]:
    """Did a recalibration buy its calibration by predicting the base rate?

    Added after X2b. A Platt rescaling of Kev-0.8B's answers reached
    **ECE 0.0083** -- better than the vendor's own reported figure for a
    refit -- with a mean probability of **0.94** on a population that is 94%
    answerable. It had learned the prior and thrown away the signal: a
    detector that always says "answerable" is perfectly calibrated and
    perfectly useless.

    ECE and Brier cannot see this. A constant predictor at the base rate is
    *optimally* calibrated by construction, and on a skewed population its
    Brier looks excellent too -- 0.0563 here, purely because 94% is far from
    0.5. So a calibration figure quoted without this check is not evidence
    that anything was learned.
    """
    collapsed = (abs(mean_probability - base_rate) <= tolerance
                 and abs(accuracy_at_half - base_rate) <= tolerance)
    return {
        "ok": not collapsed,
        "mean_probability": round(mean_probability, 4),
        "base_rate": round(base_rate, 4),
        "accuracy_at_half": round(accuracy_at_half, 4),
        "note": ("the rescaling predicts the base rate: perfectly calibrated "
                 "and uninformative, so ECE and Brier say nothing here")
                if collapsed else "",
    }


def fixture_independence(match: Any, measured: Mapping[str, Any],
                         fixture: Mapping[str, Any]) -> dict[str, Any]:
    """Does a matcher pass only on the pair whose halves were both chosen?

    For **tests**, not runs. `infer_relations`' unit test asserted an edge from
    `modifies="axle-set"` against `predicate="tyre pressure for the axle set"`,
    and it matches on one of the four combinations of
    {hand-written, model-produced} × {target, predicate} — the one where both
    halves were written by me. Each half alone fails. That is what "fitted to
    my phrasing" means, and it is invisible from the passing test.

    `match(**kwargs)` is called with each combination of the two mappings'
    values. `ok` is False when **only** the all-fixture combination matches,
    because that is the signature of a fixture that encodes the answer.
    """
    keys = sorted(set(measured) | set(fixture))
    results: dict[str, bool] = {}
    for mask in range(1 << len(keys)):
        kwargs, label = {}, []
        for index, key in enumerate(keys):
            use_fixture = bool(mask & (1 << index))
            source = fixture if use_fixture else measured
            kwargs[key] = source[key]
            label.append(f"{key}={'fixture' if use_fixture else 'measured'}")
        results[", ".join(label)] = bool(match(**kwargs))
    all_fixture = ", ".join(f"{k}=fixture" for k in keys)
    only_fixture = (results.get(all_fixture) is True
                    and sum(results.values()) == 1)
    return {
        "ok": not only_fixture,
        "combinations": results,
        "note": ("only the combination whose every half was hand-written "
                 "matches, so the fixture encodes the answer") if only_fixture
                else "",
    }


def verify(raise_on_fail: bool = False, **checks: Mapping[str, Any]
           ) -> dict[str, Any]:
    """Collect checks into one block for a result to carry.

    A failing check does **not** raise by default. An experiment that dies
    before writing its output has lost the measurement, which happened three
    times in one session here, and a harness that refuses to record a run
    because a check failed destroys the evidence of the failure.
    """
    failed = [name for name, row in checks.items() if not row.get("ok", True)]
    block = {"ok": not failed, "failed": failed, **checks}
    if failed and raise_on_fail:
        reasons = "; ".join(
            f"{name}: {checks[name].get('note') or 'failed'}"
            for name in failed)
        raise AssertionError(f"experiment checks failed -- {reasons}")
    return block
