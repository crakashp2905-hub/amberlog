"""Paired statistics for registered studies (MF-040). Seeded, standard library only.

- `paired_bootstrap`: CI for the mean paired difference, resampling task
  clusters (pass `clusters` to keep a user's or session's tasks together).
- `wilson`: interval for a proportion; `zero_events_upper` is the bound a
  "0 violations in n" claim may state (rule of three at 95%).
- `holm`: family-wise correction for a portfolio of comparisons.
- `cohen_kappa`: agreement between a judge and a human adjudicator.
"""

from __future__ import annotations

import math
import random
from typing import Hashable, Sequence


def mean(xs: Sequence[float]) -> float:
    return sum(xs) / len(xs) if xs else float("nan")


def paired_bootstrap(a: Sequence[float], b: Sequence[float], seed: int, resamples: int = 2000,
                     clusters: Sequence[Hashable] | None = None, level: float = 0.95) -> dict[str, float]:
    """Mean of b - a with a percentile CI, resampling clusters (default: each pair its own)."""
    if len(a) != len(b) or not a:
        raise ValueError("paired samples must be the same, non-zero length")
    keys = list(clusters) if clusters is not None else list(range(len(a)))
    groups: dict[Hashable, list[float]] = {}
    for k, x, y in zip(keys, a, b):
        groups.setdefault(k, []).append(y - x)
    ids = list(groups)
    rng = random.Random(seed)
    stats = []
    for _ in range(resamples):
        diffs = [d for _ in ids for d in groups[rng.choice(ids)]]
        stats.append(mean(diffs))
    stats.sort()
    lo = stats[int((1 - level) / 2 * resamples)]
    hi = stats[min(resamples - 1, int((1 + level) / 2 * resamples))]
    return {"diff": mean([y - x for x, y in zip(a, b)]), "lo": lo, "hi": hi,
            "positive_share": sum(s > 0 for s in stats) / resamples}


def wilson(successes: int, n: int, z: float = 1.959964) -> tuple[float, float]:
    if n == 0:
        return (0.0, 1.0)
    p = successes / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return (max(0.0, centre - half), min(1.0, centre + half))


def zero_events_upper(n: int, level: float = 0.95) -> float:
    """Exact upper bound on a rate after 0 events in n trials: 1 - (1-level)^(1/n)."""
    if n <= 0:
        return 1.0
    return 1 - (1 - level) ** (1 / n)


def holm(pvalues: Sequence[float], alpha: float = 0.05) -> list[bool]:
    order = sorted(range(len(pvalues)), key=lambda i: pvalues[i])
    reject = [False] * len(pvalues)
    for rank, i in enumerate(order):
        if pvalues[i] <= alpha / (len(pvalues) - rank):
            reject[i] = True
        else:
            break
    return reject


def sign_test_p(diffs: Sequence[float]) -> float:
    """Two-sided exact sign test on paired differences (ties dropped)."""
    pos = sum(d > 0 for d in diffs)
    neg = sum(d < 0 for d in diffs)
    n = pos + neg
    if n == 0:
        return 1.0
    k = min(pos, neg)
    tail = sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n
    return min(1.0, 2 * tail)


def cohen_kappa(a: Sequence[Hashable], b: Sequence[Hashable]) -> float:
    if len(a) != len(b) or not a:
        raise ValueError("two equal, non-empty label lists")
    n = len(a)
    observed = sum(x == y for x, y in zip(a, b)) / n
    labels = set(a) | set(b)
    expected = sum((list(a).count(c) / n) * (list(b).count(c) / n) for c in labels)
    return 1.0 if expected == 1 else (observed - expected) / (1 - expected)
