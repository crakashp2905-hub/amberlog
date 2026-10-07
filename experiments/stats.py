"""Statistics for the experiments: rank correlation and bootstrap intervals.

Stdlib only, so a result can be reproduced without an environment.
"""

from __future__ import annotations

import math
import random
from typing import Sequence


def rank(values: Sequence[float]) -> list[float]:
    """Ranks with ties averaged, which is what Spearman requires.

    Ties matter here: an estimator that declines to score is ranked last, tied
    with every other decliner, so a whole block shares one averaged rank.
    """
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    index = 0
    while index < len(order):
        stop = index
        while stop + 1 < len(order) and values[order[stop + 1]] == values[order[index]]:
            stop += 1
        average = (index + stop) / 2.0 + 1.0
        for position in range(index, stop + 1):
            ranks[order[position]] = average
        index = stop + 1
    return ranks


def pearson(xs: Sequence[float], ys: Sequence[float]) -> float:
    n = len(xs)
    if n < 2:
        return float("nan")
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    dx = [x - mean_x for x in xs]
    dy = [y - mean_y for y in ys]
    denominator = math.sqrt(sum(v * v for v in dx) * sum(v * v for v in dy))
    if denominator == 0.0:
        return float("nan")
    return sum(a * b for a, b in zip(dx, dy)) / denominator


def spearman(xs: Sequence[float], ys: Sequence[float]) -> float:
    """Rank correlation. NaN when either side is constant, which is a real
    answer (an estimator that returns one number for everything has no
    ordering) rather than something to paper over with zero."""
    if len(xs) != len(ys) or len(xs) < 2:
        return float("nan")
    return pearson(rank(xs), rank(ys))


def mean(values: Sequence[float]) -> float:
    finite = [v for v in values if not math.isnan(v)]
    return sum(finite) / len(finite) if finite else float("nan")


def bootstrap_ci(
    values: Sequence[float],
    iterations: int = 2000,
    confidence: float = 0.95,
    seed: int = 0,
) -> tuple[float, float]:
    """Percentile bootstrap over seeds."""
    finite = [v for v in values if not math.isnan(v)]
    if len(finite) < 2:
        return (float("nan"), float("nan"))
    rng = random.Random(seed)
    means = []
    for _ in range(iterations):
        sample = [finite[rng.randrange(len(finite))] for _ in finite]
        means.append(sum(sample) / len(sample))
    means.sort()
    tail = (1.0 - confidence) / 2.0
    low = means[int(tail * len(means))]
    high = means[min(int((1.0 - tail) * len(means)), len(means) - 1)]
    return (low, high)


def fmt_ci(values: Sequence[float], seed: int = 0) -> str:
    low, high = bootstrap_ci(values, seed=seed)
    if math.isnan(low):
        return f"{mean(values):.3f}"
    return f"{mean(values):.3f} [{low:.3f}, {high:.3f}]"
