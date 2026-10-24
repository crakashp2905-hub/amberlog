"""Paired comparisons with confidence intervals, and nothing that needs numpy.

The bootstrap resamples **units** -- an episode, or a (seed, episode) pair --
and recomputes the statistic on each draw, so dependence between arms scored on
the same unit is preserved. Resampling arms independently would discard the
pairing and widen every interval, which is how a well-designed paired
experiment gets reported as inconclusive.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Callable, Sequence, TypeVar

T = TypeVar("T")


@dataclass(frozen=True)
class Interval:
    point: float
    low: float
    high: float
    n: int

    @property
    def excludes_zero(self) -> bool:
        return self.low > 0.0 or self.high < 0.0

    @property
    def half_width(self) -> float:
        return (self.high - self.low) / 2.0

    def within(self, margin: float) -> bool:
        """Equivalence: the whole interval sits inside `[-margin, +margin]`.

        The only honest way to support a claim of *no effect*. Failing to
        exclude zero is not that -- an interval of [-0.3, +0.3] fails to
        exclude zero and supports nothing.
        """
        return self.low >= -margin and self.high <= margin


def bootstrap(units: Sequence[T], statistic: Callable[[Sequence[T]], float],
              draws: int = 2000, seed: int = 7,
              confidence: float = 0.95) -> Interval:
    """Percentile bootstrap of `statistic` over resampled `units`."""
    if not units:
        raise ValueError("no units to resample")
    rng = random.Random(seed)
    point = statistic(units)
    values = sorted(statistic([units[rng.randrange(len(units))]
                               for _ in units]) for _ in range(draws))
    tail = (1.0 - confidence) / 2.0
    low = values[int(tail * draws)]
    high = values[min(draws - 1, int((1.0 - tail) * draws))]
    return Interval(point=point, low=low, high=high, n=len(units))


def paired_difference(left: Sequence[float], right: Sequence[float],
                      **kwargs) -> tuple[Interval, float]:
    """Mean of `left - right` over paired units, and the discordance rate.

    Discordance is returned because it sets the realised power -- a reader
    should be able to check whether the run delivered the power its
    registration assumed, rather than take that on trust.
    """
    if len(left) != len(right):
        raise ValueError("paired arms must have the same length")
    diffs = [a - b for a, b in zip(left, right)]
    discordance = sum(1 for d in diffs if d != 0) / len(diffs)
    interval = bootstrap(diffs, lambda xs: sum(xs) / len(xs), **kwargs)
    return interval, discordance
