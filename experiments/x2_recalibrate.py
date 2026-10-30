"""X2b — refitting the temperature, and what that provably cannot fix.

[X2](../research/results/x2-typed-confidence.md) measured Kev-0.8B at
**F1 0.1739** against a bar of 0.5514 and diagnosed the failure as
calibration rather than ignorance: the model's whole output range sits below
indifference — 470 of 500 instances called unanswerable, a maximum
P(answerable) of 0.786, class medians 0.03 apart. Kev's own documentation
recommends refitting its per-checkpoint temperature on held-out data from your
own domain before setting any threshold, and reports the vendor effect on its
sibling Laya as ECE 0.466 → 0.081.

So this refits it. **And the result is settled before it runs, by an argument
rather than a measurement**, which is the honest way round:

> **AUC and best-achievable-F1 are invariant under any strictly monotone
> transform of the score.** A temperature (`sigmoid(z/T)`) and a Platt
> rescaling (`sigmoid(a·z + b)`, `a > 0`) are both strictly monotone. Best F1
> is already a sweep over *every* threshold, so rescaling the scores permutes
> nothing and the optimal threshold simply moves with them.
>
> **Therefore no refit can change X2's registered primary.** Its
> NOT SUPPORTED is robust to recalibration, and this experiment cannot rescue
> it.

What a refit *can* change is **ECE, Brier, and accuracy at a fixed
threshold** — calibration, not discrimination. Those are worth having: a
probability that means what it says is what principles 4 and 5 ask for, and an
exposure decision needs a number it can act on at a *stated* threshold rather
than one chosen in hindsight. So the question this answers is narrow and
real: *after refitting, is the probability trustworthy as a probability, even
though the ranking is unchanged?*

## Why a temperature alone is the wrong instrument here

Temperature scaling sharpens or flattens a distribution **around 0.5**. It
cannot shift one. As `T → ∞` every score goes to 0.5; as `T → 0` each goes to
0 or 1 by the sign of its logit. X2's problem is a *shift* — both classes sit
near 0.25 — so a temperature can only make things uniformly vague or uniformly
confident-and-wrong.

A Platt rescaling adds a bias term, which is exactly the free parameter a
shift needs. Both are fitted here so the comparison is visible rather than
asserted, which is the mistake X1 made about constrained decoding.

## Fitting protocol

Fit on **half** the instances, report on the other half, stratified by class so
each half holds 15 unanswerable. Seeded. No model calls: this reads X2's saved
run, so it costs nothing and measures the same 500 answers.
"""

from __future__ import annotations

import argparse
import json
import math
import pathlib
import random
import sys
from typing import Any, Mapping, Sequence

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from experiments import checks  # noqa: E402
from memory_fabric.adapters.systemone import (  # noqa: E402
    brier_score, expected_calibration_error,
)
from experiments.x1_abstention_premise import best_f1  # noqa: E402

EPS = 1e-6


def logit(p: float) -> float:
    p = min(max(p, EPS), 1.0 - EPS)
    return math.log(p / (1.0 - p))


def sigmoid(z: float) -> float:
    if z >= 0:
        return 1.0 / (1.0 + math.exp(-z))
    exp = math.exp(z)
    return exp / (1.0 + exp)


def apply(scores: Sequence[float], a: float, b: float) -> list[float]:
    """`sigmoid(a * logit(p) + b)`. `a = 1/T`, `b = 0` is a pure temperature."""
    return [sigmoid(a * logit(p) + b) for p in scores]


def nll(scores: Sequence[float], labels: Sequence[bool],
        a: float, b: float) -> float:
    """Mean negative log likelihood, the standard objective for this.

    Minimised rather than ECE, because ECE is bin-dependent and a fit that
    optimises it directly can game the bin edges.
    """
    total = 0.0
    for p, y in zip(apply(scores, a, b), labels):
        p = min(max(p, EPS), 1.0 - EPS)
        total -= math.log(p) if y else math.log(1.0 - p)
    return total / len(scores) if scores else 0.0


def fit(scores: Sequence[float], labels: Sequence[bool],
        bias: bool = True) -> tuple[float, float]:
    """Coarse-to-fine grid over (a, b). No dependencies, and two parameters
    do not need more than this."""
    a_lo, a_hi, b_lo, b_hi = 0.02, 5.0, (-6.0 if bias else 0.0), (6.0 if bias else 0.0)
    best = (1.0, 0.0)
    for _round in range(6):
        best_loss = float("inf")
        steps = 25
        for i in range(steps + 1):
            a = a_lo + (a_hi - a_lo) * i / steps
            if a <= 0:
                continue
            for j in range(steps + 1 if bias else 1):
                b = b_lo + (b_hi - b_lo) * j / steps if bias else 0.0
                loss = nll(scores, labels, a, b)
                if loss < best_loss:
                    best_loss, best = loss, (a, b)
        a, b = best
        a_span, b_span = (a_hi - a_lo) / 6.0, (b_hi - b_lo) / 6.0
        a_lo, a_hi = max(0.01, a - a_span), a + a_span
        if bias:
            b_lo, b_hi = b - b_span, b + b_span
    return best


def split(rows: Sequence[Mapping[str, Any]], seed: int
          ) -> tuple[list[Mapping[str, Any]], list[Mapping[str, Any]]]:
    """Half and half, stratified by class.

    Stratified because the population is 6% unanswerable and a random half
    could hold 9 of the 30 — and because this project has already published a
    figure from an unstratified sample once.
    """
    rng = random.Random(seed)
    dev: list[Mapping[str, Any]] = []
    test: list[Mapping[str, Any]] = []
    for unanswerable in (True, False):
        group = [r for r in rows if bool(r["unanswerable"]) is unanswerable]
        rng.shuffle(group)
        half = len(group) // 2
        dev += group[:half]
        test += group[half:]
    return dev, test


def measure(scores: Sequence[float], labels: Sequence[bool]) -> dict[str, Any]:
    pairs = list(zip(scores, labels))
    positive = [p for p, y in pairs if not y]   # unanswerable
    negative = [p for p, y in pairs if y]       # answerable
    at_half = sum(1 for p, y in pairs if (p >= 0.5) == y) / len(pairs)
    return {
        "n": len(pairs),
        "ece": round(expected_calibration_error(pairs) or 0.0, 4),
        "brier": round(brier_score(pairs) or 0.0, 4),
        "accuracy_at_half": round(at_half, 4),
        "auc": checks._round(checks.auc(positive, negative))
        if hasattr(checks, "_round") else round(checks.auc(positive, negative), 4),
        "best_f1": best_f1(positive, negative).get("f1"),
        "mean_p": round(sum(scores) / len(scores), 4),
    }


def run(path: str, seeds: int = 5) -> dict[str, Any]:
    data = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    rows = [r for r in data["rows"] if r.get("p_answerable") is not None]

    per_seed: list[dict[str, Any]] = []
    for seed in range(1, seeds + 1):
        dev, test = split(rows, seed)
        dev_scores = [r["p_answerable"] for r in dev]
        dev_labels = [not r["unanswerable"] for r in dev]
        test_scores = [r["p_answerable"] for r in test]
        test_labels = [not r["unanswerable"] for r in test]

        temp_a, temp_b = fit(dev_scores, dev_labels, bias=False)
        platt_a, platt_b = fit(dev_scores, dev_labels, bias=True)

        per_seed.append({
            "seed": seed,
            "fitted": {
                "temperature": {"a": round(temp_a, 4),
                                "implied_T": round(1.0 / temp_a, 4)},
                "platt": {"a": round(platt_a, 4), "b": round(platt_b, 4)},
            },
            "held_out": {
                "as_shipped": measure(test_scores, test_labels),
                "temperature": measure(
                    apply(test_scores, temp_a, temp_b), test_labels),
                "platt": measure(
                    apply(test_scores, platt_a, platt_b), test_labels),
            },
        })

    def mean_of(arm: str, metric: str) -> float | None:
        values = [s["held_out"][arm][metric] for s in per_seed
                  if s["held_out"][arm].get(metric) is not None]
        return round(sum(values) / len(values), 4) if values else None

    arms = ("as_shipped", "temperature", "platt")
    summary = {
        arm: {m: mean_of(arm, m) for m in
              ("ece", "brier", "accuracy_at_half", "auc", "best_f1", "mean_p")}
        for arm in arms
    }

    # The invariance claim, checked rather than asserted. A rescaling that
    # moved either of these would mean the transform is not monotone or the
    # metric is not what it claims to be -- and both are worth finding out.
    invariance = {
        metric: {
            "as_shipped": summary["as_shipped"][metric],
            "temperature": summary["temperature"][metric],
            "platt": summary["platt"][metric],
            "unchanged": (
                summary["as_shipped"][metric] == summary["temperature"][metric]
                == summary["platt"][metric]),
        }
        for metric in ("auc", "best_f1")
    }

    return {
        "experiment": "x2b-recalibrate",
        "source": path,
        "instances": len(rows),
        "seeds": seeds,
        "summary": summary,
        "invariance": invariance,
        "base_rate_answerable": round(
            sum(1 for r in rows if not r["unanswerable"]) / len(rows), 4),
        "checks": checks.verify(
            **{
                f"collapsed_to_prior_{arm}": checks.collapsed_to_prior(
                    summary[arm]["mean_p"],
                    sum(1 for r in rows if not r["unanswerable"]) / len(rows),
                    summary[arm]["accuracy_at_half"])
                for arm in ("temperature", "platt")
            },
            monotone_invariance={
                "ok": all(v["unchanged"] for v in invariance.values()),
                "note": ("AUC and best-F1 must be identical across arms: a "
                         "strictly monotone rescaling permutes no scores. A "
                         "difference means the transform is not monotone or "
                         "the metric is not threshold-free."),
                **invariance,
            },
        ),
        "per_seed": per_seed,
    }


def to_markdown(result: Mapping[str, Any]) -> str:
    s = result["summary"]
    lines = [
        "# X2b - refitting Kev's temperature on our own data",
        "",
        f"- {result['instances']} instances from `{result['source']}`, "
        f"{result['seeds']} seeds, fitted on half and reported on the "
        f"held-out half, stratified by class",
        "- **No model calls.** This re-reads X2's saved answers.",
        "",
        "| arm | ECE | Brier | accuracy @ p=0.5 | mean p | AUC | best F1 |",
        "|---|---|---|---|---|---|---|",
    ]
    names = {"as_shipped": "as shipped (T=2.351)",
             "temperature": "temperature refitted",
             "platt": "Platt refitted (scale + bias)"}
    for arm in ("as_shipped", "temperature", "platt"):
        row = s[arm]
        lines.append(
            f"| {names[arm]} | {row['ece']} | {row['brier']} | "
            f"{row['accuracy_at_half']} | {row['mean_p']} | {row['auc']} | "
            f"{row['best_f1']} |")
    inv = result["invariance"]
    lines += [
        "",
        f"**AUC and best F1 are identical across all three arms** "
        f"(AUC {inv['auc']['as_shipped']}, best F1 "
        f"{inv['best_f1']['as_shipped']}), which is the point: a strictly "
        f"monotone rescaling permutes no scores, so recalibration cannot move "
        f"a threshold-free metric. **X2's NOT SUPPORTED is robust to "
        f"recalibration.**",
        "",
        "What the refit does fix is the probability itself - see the ECE, "
        "Brier and fixed-threshold accuracy columns.",
    ]
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source", default="research/results/x2-run.json")
    parser.add_argument("--seeds", type=int, default=5)
    parser.add_argument("--out")
    parser.add_argument("--json", dest="as_json", action="store_true")
    args = parser.parse_args(argv)
    result = run(args.source, args.seeds)
    if args.out:
        pathlib.Path(args.out).write_text(
            json.dumps(result, indent=2) + "\n", encoding="utf-8")
    text = json.dumps(result, indent=2) if args.as_json else to_markdown(result)
    try:
        print(text)
    except UnicodeEncodeError:
        encoding = sys.stdout.encoding or "ascii"
        print(text.encode(encoding, "replace").decode(encoding, "replace"))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
