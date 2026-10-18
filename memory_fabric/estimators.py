"""Value estimators.

P1 ships two: the baseline that must be beaten, and the simplest estimator that
actually corrects for selection bias. The doubly-robust, paired-replay and
amortized estimators arrive at P4, behind this same protocol.

The baseline matters more than it looks. `NaiveUsageEstimator` is what a good
engineer builds in an afternoon, and if the causal machinery cannot beat it by a
pre-registered margin then the causal machinery is not justified
(CRITICAL_REVIEW section 9.2, EVALUATION.md baseline 5).
"""

from __future__ import annotations

__stability__ = "stable"

import math
from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable, Mapping, Protocol, Sequence

from .model import UNKNOWN_VALUE, ValueEstimate, context_key
from .projections import Episode, ExposureRecord, ProjectionState

Z95 = 1.959963984540054


class ValueEstimator(Protocol):
    id: str

    def fit(self, state: ProjectionState) -> None: ...

    def estimate(
        self, memory_id: str, context: Mapping[str, object] | None = None
    ) -> ValueEstimate: ...


@dataclass
class _Arm:
    """Weighted accumulator for one arm of a comparison."""

    sum_w: float = 0.0
    sum_w2: float = 0.0
    sum_wy: float = 0.0
    sum_wy2: float = 0.0
    n: int = 0

    def add(self, y: float, w: float = 1.0) -> None:
        self.sum_w += w
        self.sum_w2 += w * w
        self.sum_wy += w * y
        self.sum_wy2 += w * y * y
        self.n += 1

    @property
    def n_eff(self) -> float:
        """Kish effective sample size: down-weights a few huge weights."""
        if self.sum_w2 == 0.0:
            return 0.0
        return (self.sum_w * self.sum_w) / self.sum_w2

    @property
    def mean(self) -> float:
        return self.sum_wy / self.sum_w if self.sum_w > 0.0 else 0.0

    @property
    def variance(self) -> float:
        if self.sum_w <= 0.0:
            return 0.0
        second = self.sum_wy2 / self.sum_w
        return max(second - self.mean * self.mean, 0.0)

    @property
    def var_of_mean(self) -> float:
        n_eff = self.n_eff
        return self.variance / n_eff if n_eff > 1.0 else float("inf")


def _outcomes_by_episode(state: ProjectionState) -> dict[str, float]:
    """Only verified outcomes count (SECURITY.md T2)."""
    return {
        episode_id: episode.outcome
        for episode_id, episode in state.episodes.items()
        if episode.has_outcome and episode.verifier_id is not None
        and episode.outcome is not None
    }


def _episode_context(state: ProjectionState, episode_id: str | None) -> str:
    episode: Episode | None = state.episodes.get(episode_id or "")
    return context_key(episode.context if episode else None)


Observation = tuple[ExposureRecord, float, str]


def build_exposure_index(state: ProjectionState) -> dict[str, list[Observation]]:
    """Group exposure decisions by memory, joined to their episode outcome.

    Built once per `fit` rather than scanned per memory. Scanning inside
    `estimate` makes a listing quadratic in the store — every memory walks every
    exposure record — which the dashboard hits directly, since it estimates a
    value for each row it renders.

    Deduplicated per episode and arm: a memory exposed at several steps of one
    episode is one observation, because there is only one outcome to attribute.
    """
    outcomes = _outcomes_by_episode(state)
    contexts = {
        episode_id: context_key(episode.context)
        for episode_id, episode in state.episodes.items()
    }
    index: dict[str, list[Observation]] = defaultdict(list)
    seen: set[tuple[str, str, bool]] = set()
    for record in state.exposures:
        episode_id = record.episode_id
        if episode_id is None or episode_id not in outcomes:
            continue
        key = (record.memory_id, episode_id, record.exposed)
        if key in seen:
            continue
        seen.add(key)
        index[record.memory_id].append(
            (record, outcomes[episode_id], contexts.get(episode_id, "*"))
        )
    return dict(index)


def _wilson_interval(mean: float, n: float) -> tuple[float, float]:
    """Wilson score interval, which stays sensible at tiny n.

    Assumes the outcome is bounded in [0, 1], which holds for the success rates
    and normalised scores this estimator is used on. The sample-variance
    alternative collapses to a zero-width interval after a single observation,
    which reads as certainty when the truth is that we know almost nothing.
    """
    if n <= 0.0:
        return 0.0, 1.0
    p = min(max(mean, 0.0), 1.0)
    z2 = Z95 * Z95
    denominator = 1.0 + z2 / n
    centre = (p + z2 / (2.0 * n)) / denominator
    half = (Z95 * math.sqrt(p * (1.0 - p) / n + z2 / (4.0 * n * n))) / denominator
    return max(centre - half, 0.0), min(centre + half, 1.0)


class NaiveUsageEstimator:
    """Smoothed mean outcome over episodes where the memory was exposed.

    Deliberately biased, and deliberately *not* contrastive: it never looks at
    the withheld arm, so it cannot separate "this memory helps" from "this
    memory gets retrieved on easy tasks". Its output is an absolute outcome
    level, not a difference, so it can never on its own justify promoting a
    memory's scope.

    Kept as the baseline to beat (EVALUATION.md baseline 5), not as a
    recommendation.
    """

    id = "naive_usage"

    def __init__(self, prior_mean: float = 0.5, prior_weight: float = 2.0) -> None:
        self.prior_mean = prior_mean
        self.prior_weight = prior_weight
        self._arms: dict[tuple[str, str], _Arm] = {}

    def fit(self, state: ProjectionState) -> None:
        arms: dict[tuple[str, str], _Arm] = defaultdict(_Arm)
        outcomes = _outcomes_by_episode(state)
        seen: set[tuple[str, str]] = set()
        for record in state.exposures:
            if not record.exposed or record.episode_id is None:
                continue
            if record.episode_id not in outcomes:
                continue
            if (record.memory_id, record.episode_id) in seen:
                continue
            seen.add((record.memory_id, record.episode_id))
            y = outcomes[record.episode_id]
            ckey = _episode_context(state, record.episode_id)
            arms[(record.memory_id, "*")].add(y)
            arms[(record.memory_id, ckey)].add(y)
        self._arms = dict(arms)

    def estimate(
        self, memory_id: str, context: Mapping[str, object] | None = None
    ) -> ValueEstimate:
        arm = self._arms.get((memory_id, context_key(context)))
        if arm is None or arm.n == 0:
            return ValueEstimate(
                mean=self.prior_mean,
                ci_low=0.0,
                ci_high=1.0,
                n_eff=0.0,
                estimator=self.id,
                contrastive=False,
            )
        # Laplace-style shrinkage toward the prior.
        total_w = arm.sum_w + self.prior_weight
        mean = (arm.sum_wy + self.prior_mean * self.prior_weight) / total_w
        ci_low, ci_high = _wilson_interval(mean, total_w)
        return ValueEstimate(
            mean=mean,
            ci_low=ci_low,
            ci_high=ci_high,
            n_eff=arm.n_eff,
            estimator=self.id,
            contrastive=False,
        )


class IPSEstimator:
    """Inverse-propensity-weighted difference between the exposed and withheld arms.

    Self-normalised (Hájek) rather than Horvitz-Thompson, because the normalised
    form has far lower variance at these sample sizes even though it carries a
    small bias.

    Returns UNKNOWN_VALUE unless both arms have data. That is the honest answer
    when the logging policy had no overlap: a deterministic policy produces data
    from which no causal claim can be made, however much of it there is.
    """

    id = "ips"

    def __init__(self, min_n_eff: float = 2.0, clip_weight: float = 20.0) -> None:
        self.min_n_eff = min_n_eff
        # Clipping trades a little bias for a large variance reduction; without
        # it a single propensity near zero dominates the estimate.
        self.clip_weight = clip_weight
        self._index: dict[str, list[Observation]] | None = None

    def fit(self, state: ProjectionState) -> None:
        self._index = build_exposure_index(state)

    def estimate(
        self, memory_id: str, context: Mapping[str, object] | None = None
    ) -> ValueEstimate:
        if self._index is None:
            return UNKNOWN_VALUE
        wanted = context_key(context) if context else None
        exposed, withheld = _Arm(), _Arm()
        for record, outcome, ckey in self._index.get(memory_id, ()):
            if wanted is not None and ckey != wanted:
                continue
            weight = min(1.0 / max(record.propensity, 1e-9), self.clip_weight)
            (exposed if record.exposed else withheld).add(outcome, weight)

        if exposed.n_eff < self.min_n_eff or withheld.n_eff < self.min_n_eff:
            return UNKNOWN_VALUE

        difference = exposed.mean - withheld.mean
        var = exposed.var_of_mean + withheld.var_of_mean
        if not math.isfinite(var):
            return UNKNOWN_VALUE
        half = Z95 * math.sqrt(var)
        return ValueEstimate(
            mean=difference,
            ci_low=difference - half,
            ci_high=difference + half,
            n_eff=min(exposed.n_eff, withheld.n_eff),
            estimator=self.id,
            contrastive=True,
        )


class DoublyRobustEstimator:
    """Outcome model plus an inverse-propensity correction on its residuals.

    Two chances to be right: the estimate is consistent if *either* the outcome
    model or the propensities are correct. It matters here because the outcome
    model absorbs the part of the variation explained by the task itself — which
    is exactly the confound that makes an observational estimate look good — and
    the IPS term then only has to correct what the model missed, so the variance
    is far below plain IPS at the same sample size.

    Covariates come from the episode context the fabric already logs. With no
    context recorded this degenerates to a single stratum, which is still valid
    (the model becomes the overall mean) but gains nothing over IPS.
    """

    id = "dr"

    def __init__(self, min_n_eff: float = 2.0, clip_weight: float = 20.0, prior: float = 2.0) -> None:
        self.min_n_eff = min_n_eff
        self.clip_weight = clip_weight
        # Smoothing on the per-stratum outcome model, so a stratum seen twice
        # does not produce a confident prediction.
        self.prior = prior
        self._index: dict[str, list[Observation]] | None = None
        self._grand_mean: float = 0.5

    def fit(self, state: ProjectionState) -> None:
        self._index = build_exposure_index(state)
        outcomes = list(_outcomes_by_episode(state).values())
        self._grand_mean = sum(outcomes) / len(outcomes) if outcomes else 0.5

    def estimate(
        self, memory_id: str, context: Mapping[str, object] | None = None
    ) -> ValueEstimate:
        if self._index is None:
            return UNKNOWN_VALUE
        observations = self._index.get(memory_id, ())
        wanted = context_key(context) if context else None
        rows = [row for row in observations if wanted is None or row[2] == wanted]
        if not rows:
            return UNKNOWN_VALUE

        # Outcome model: mean outcome per (covariate stratum, arm), smoothed
        # toward the grand mean.
        sums: dict[tuple[str, bool], list[float]] = {}
        for record, outcome, ckey in rows:
            bucket = sums.setdefault((ckey, record.exposed), [0.0, 0.0])
            bucket[0] += outcome
            bucket[1] += 1.0

        def mu(ckey: str, exposed: bool) -> float:
            total, count = sums.get((ckey, exposed), (0.0, 0.0))
            return (total + self._grand_mean * self.prior) / (count + self.prior)

        exposed_arm, withheld_arm = _Arm(), _Arm()
        for record, outcome, ckey in rows:
            (exposed_arm if record.exposed else withheld_arm).add(outcome, 1.0)

        if exposed_arm.n == 0 or withheld_arm.n == 0:
            # No overlap for this memory: the honest answer is that no causal
            # claim can be made, not a number from one arm.
            return UNKNOWN_VALUE

        contributions: list[float] = []
        for record, outcome, ckey in rows:
            mu1, mu0 = mu(ckey, True), mu(ckey, False)
            weight = min(1.0 / max(record.propensity, 1e-9), self.clip_weight)
            if record.exposed:
                value = (mu1 - mu0) + weight * (outcome - mu1)
            else:
                value = (mu1 - mu0) - weight * (outcome - mu0)
            contributions.append(value)

        n = len(contributions)
        mean = sum(contributions) / n
        if n < 2:
            return UNKNOWN_VALUE
        variance = sum((c - mean) ** 2 for c in contributions) / (n - 1)
        n_eff = min(exposed_arm.n_eff, withheld_arm.n_eff)
        if n_eff < self.min_n_eff:
            return UNKNOWN_VALUE
        half = Z95 * math.sqrt(variance / n)
        return ValueEstimate(
            mean=mean,
            ci_low=mean - half,
            ci_high=mean + half,
            n_eff=n_eff,
            estimator=self.id,
            contrastive=True,
        )


def _ridge_solve(rows: Sequence[Sequence[float]], targets: Sequence[float], penalty: float) -> list[float]:
    """Ridge regression by Gaussian elimination on the normal equations.

    Small, dense and low-dimensional, so the normal equations are fine and keep
    the package dependency-free. The penalty also guarantees the system is
    non-singular, so collinear features cannot blow it up.
    """
    if not rows:
        return []
    width = len(rows[0])
    ata = [[0.0] * (width + 1) for _ in range(width)]
    for row, target in zip(rows, targets):
        for i in range(width):
            for j in range(width):
                ata[i][j] += row[i] * row[j]
            ata[i][width] += row[i] * target
    for i in range(width):
        ata[i][i] += penalty

    for col in range(width):
        pivot = max(range(col, width), key=lambda r: abs(ata[r][col]))
        if abs(ata[pivot][col]) < 1e-12:
            continue
        ata[col], ata[pivot] = ata[pivot], ata[col]
        scale = ata[col][col]
        ata[col] = [v / scale for v in ata[col]]
        for r in range(width):
            if r == col:
                continue
            factor = ata[r][col]
            if factor:
                ata[r] = [v - factor * w for v, w in zip(ata[r], ata[col])]
    return [ata[i][width] for i in range(width)]


class AmortizedEstimator:
    """Per-memory estimates shrunk toward a prediction from memory features.

    The sample-size arithmetic (CRITICAL_REVIEW §2.1) says most memories will
    never accumulate enough evidence for a per-memory estimate to be worth
    much. Amortization borrows strength across the population: a model learns
    what *kinds* of memory tend to help, and each memory's own noisy estimate is
    pulled toward that prediction in proportion to how little evidence it has.

    A memory with plenty of evidence keeps its own number; one with almost none
    gets the population's opinion about memories like it, rather than a number
    driven by two lucky episodes.
    """

    id = "amortized"

    def __init__(
        self,
        base: ValueEstimator | None = None,
        penalty: float = 1.0,
        shrink_n: float = 12.0,
        min_training: int = 8,
    ) -> None:
        self.base = base or DoublyRobustEstimator()
        self.penalty = penalty
        # Evidence at which a memory's own estimate carries half the weight.
        self.shrink_n = shrink_n
        self.min_training = min_training
        self._weights: list[float] = []
        self._state: ProjectionState | None = None
        self._index: dict[str, list[Observation]] | None = None

    def fit(self, state: ProjectionState) -> None:
        self.base.fit(state)
        self._state = state
        self._index = build_exposure_index(state)

        rows: list[list[float]] = []
        targets: list[float] = []
        for memory_id in state.memories:
            estimate = self.base.estimate(memory_id)
            if estimate.n_eff <= 0.0 or not math.isfinite(estimate.mean):
                continue
            rows.append(self._features(memory_id))
            targets.append(estimate.mean)

        self._weights = (
            _ridge_solve(rows, targets, self.penalty)
            if len(rows) >= self.min_training
            else []
        )

    def _features(self, memory_id: str) -> list[float]:
        state = self._state
        assert state is not None
        memory = state.memories.get(memory_id)
        stats = state.stats_for(memory_id)
        observations = (self._index or {}).get(memory_id, ())

        exposed = [o for o in observations if o[0].exposed]
        withheld = [o for o in observations if not o[0].exposed]
        exposed_mean = sum(o[1] for o in exposed) / len(exposed) if exposed else 0.5
        withheld_mean = sum(o[1] for o in withheld) / len(withheld) if withheld else 0.5

        total = stats.exposures + stats.withholdings
        return [
            1.0,
            exposed_mean,
            withheld_mean,
            exposed_mean - withheld_mean,
            math.log1p(total),
            1.0 if memory and memory.type.value == "procedural" else 0.0,
            1.0 if memory and memory.type.value == "semantic" else 0.0,
        ]

    def _predict(self, memory_id: str) -> float | None:
        if not self._weights:
            return None
        features = self._features(memory_id)
        return sum(w * f for w, f in zip(self._weights, features))

    def estimate(
        self, memory_id: str, context: Mapping[str, object] | None = None
    ) -> ValueEstimate:
        own = self.base.estimate(memory_id, context)
        prediction = self._predict(memory_id)

        if own.n_eff <= 0.0:
            if prediction is None:
                return UNKNOWN_VALUE
            # No evidence of its own: report the population's view, marked as
            # resting on nothing so nothing downstream treats it as proven.
            return ValueEstimate(
                mean=prediction,
                ci_low=float("-inf"),
                ci_high=float("inf"),
                n_eff=0.0,
                estimator=self.id,
                contrastive=True,
            )
        if prediction is None:
            return own

        weight = own.n_eff / (own.n_eff + self.shrink_n)
        mean = weight * own.mean + (1.0 - weight) * prediction
        half = (own.ci_high - own.ci_low) / 2.0
        if not math.isfinite(half):
            half = abs(own.mean) + 1.0
        # Shrinking moves the point estimate but does not narrow the interval:
        # borrowing strength is not the same as having gathered evidence.
        return ValueEstimate(
            mean=mean,
            ci_low=mean - half,
            ci_high=mean + half,
            n_eff=own.n_eff,
            estimator=self.id,
            contrastive=True,
        )


ESTIMATORS: dict[str, type] = {
    "naive_usage": NaiveUsageEstimator,
    "ips": IPSEstimator,
    "dr": DoublyRobustEstimator,
    "amortized": AmortizedEstimator,
}


def build_estimator(spec: str | ValueEstimator) -> ValueEstimator:
    if not isinstance(spec, str):
        return spec
    if spec not in ESTIMATORS:
        raise KeyError(f"unknown estimator {spec!r}; known: {sorted(ESTIMATORS)}")
    return ESTIMATORS[spec]()


def estimate_all(
    estimator: ValueEstimator, state: ProjectionState, memory_ids: Iterable[str] | None = None
) -> dict[str, ValueEstimate]:
    estimator.fit(state)
    ids: Sequence[str] = list(memory_ids) if memory_ids is not None else list(state.memories)
    return {memory_id: estimator.estimate(memory_id) for memory_id in ids}
