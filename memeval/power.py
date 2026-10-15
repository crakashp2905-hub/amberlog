"""How large an effect can this run see, and how large a run does a claim need?

Neither question is answered by a threshold or a ceiling, which is why both
were missing from the checks that existed before this module.
[X4](../research/results/x4-governed-vs-pooled.md) spent 1.72 hours of
inference on arm differences of about 0.04 with a minimum detectable effect of
0.10 to 0.14: it **could not have detected the effect it reported**, whatever
the truth, and nothing in its registration said so. A threshold set below the
noise floor is the same mistake as one set above the ceiling, in the other
dimension.

Every function here is a closed form, so a registration can state its power
before the run and a result can state what it actually achieved.

* `mde_paired` -- two arms scored on the **same** episodes. The variance of the
  difference is set by how often the arms *disagree*, the discordance rate,
  not by the success rate. Pairing is why a 640-episode paired comparison can
  resolve 4 points and an unpaired one of the same size cannot.
* `mde_independent` -- two arms on different samples.
* `pairs_needed` -- the inverse: how many paired episodes to resolve an effect.
* `absence_bound` -- for a claim that something **never** happens. A zero is
  not evidence of absence unless n was large enough that a real rate would
  have shown up; a zero at n=30 is consistent with a true rate of 9.5%.
"""

from __future__ import annotations

import math

Z_ALPHA = 1.96   # two-sided 0.05
Z_POWER = 0.84   # 80% power
Z = Z_ALPHA + Z_POWER


def mde_paired(n_pairs: int, discordance: float, z: float = Z) -> float:
    """Minimum detectable mean difference for a paired binary comparison.

    `discordance` is the share of pairs on which the two arms differ. The SE
    of the mean paired difference is at most `sqrt(d / n)`, which is the
    conservative form used here.
    """
    if n_pairs <= 0:
        raise ValueError("n_pairs must be positive")
    if not 0.0 <= discordance <= 1.0:
        raise ValueError("discordance must be in [0, 1]")
    return z * math.sqrt(max(discordance, 1e-12) / n_pairs)


def mde_independent(n_per_arm: int, base_rate: float, z: float = Z) -> float:
    """Minimum detectable difference between two independent proportions."""
    if n_per_arm <= 0:
        raise ValueError("n_per_arm must be positive")
    p = min(max(base_rate, 1e-6), 1 - 1e-6)
    return z * math.sqrt(2 * p * (1 - p) / n_per_arm)


def pairs_needed(effect: float, discordance: float, z: float = Z) -> int:
    """Paired episodes needed to detect `effect` at 80% power."""
    if effect <= 0:
        raise ValueError("effect must be positive")
    return math.ceil(discordance * (z / effect) ** 2)


def absence_bound(n: int, confidence: float = 0.95) -> float:
    """The largest true rate a run of `n` could miss with zero events seen.

    Solves `(1 - r) ** n = 1 - confidence` for r. Report it beside any zero,
    because a zero quoted alone reads as a guarantee and is not one.
    """
    if n <= 0:
        raise ValueError("n must be positive")
    return 1.0 - (1.0 - confidence) ** (1.0 / n)
