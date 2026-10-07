"""A population of agents sharing evidence about two close-payoff actions.

RuleWorld cannot produce the effect H4 is about. Following a correct claim
there succeeds ~84% of the time against ~5% for a wrong one, and with a gap
that wide no population ever talks itself into the wrong answer.

The Zollman effect needs **close payoffs**, so that small samples genuinely
mislead. Two actions at 0.55 and 0.50 do that.

The mechanism is an absorbing trap. An agent plays greedily — it pulls whatever
its evidence currently favours — so a population that comes to believe the worse
action is better *stops pulling the better one entirely*. No new evidence
arrives, and the error becomes permanent. Dense networks synchronise beliefs, so
they fall in together; sparse ones leave somebody still testing.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Sequence

GOOD = 0
BAD = 1


@dataclass
class BanditConfig:
    n_agents: int = 10
    p_good: float = 0.55
    p_bad: float = 0.50
    rounds: int = 150
    pulls_per_round: int = 10
    known_observations: int = 20
    """Observations of the worse action each agent starts with.

    Enough that its rate is effectively known — the safe arm in a
    safe-versus-risky setup. Only the better action is genuinely uncertain."""

    prior_observations: int = 4
    """Observations of the better action each agent starts with, drawn at a
    uniformly-sampled rate.

    This is what makes starting beliefs *diverse*, and diversity is what the
    experiment needs: if every agent began believing the same wrong thing,
    nobody would ever pull the better action, no evidence about it would ever
    be generated, and no topology could escape. The trap has to be probabilistic
    for sparsity to have anything to preserve."""
    preserve_share: float = 0.20
    """Share of a round's pulls spent re-testing the minority hypothesis while
    the two beliefs are contested."""
    credible: float = 0.90


@dataclass
class Beliefs:
    """Beta posteriors over each action's success rate, from a uniform prior."""

    successes: list[float] = field(default_factory=lambda: [0.0, 0.0])
    failures: list[float] = field(default_factory=lambda: [0.0, 0.0])

    def observe(self, action: int, successes: int, trials: int) -> None:
        self.successes[action] += successes
        self.failures[action] += trials - successes

    def mean(self, action: int) -> float:
        a = self.successes[action] + 1.0
        b = self.failures[action] + 1.0
        return a / (a + b)

    def n(self, action: int) -> float:
        return self.successes[action] + self.failures[action]

    def believes(self) -> int:
        """Which action this agent currently thinks is better.

        Ties break toward BAD so that a population with no information counts
        as wrong rather than accidentally correct — the measurement should not
        be flattered by agents that know nothing.
        """
        return GOOD if self.mean(GOOD) > self.mean(BAD) else BAD

    def interval(self, action: int) -> tuple[float, float]:
        """Normal approximation to the Beta credible interval.

        Adequate here because every posterior quickly carries dozens of
        observations, and it keeps the simulation dependency-free.
        """
        a = self.successes[action] + 1.0
        b = self.failures[action] + 1.0
        total = a + b
        mean = a / total
        sd = math.sqrt(max(mean * (1.0 - mean) / (total + 1.0), 1e-12))
        z = 1.6448536269514722  # 90%, two-sided
        return (max(mean - z * sd, 0.0), min(mean + z * sd, 1.0))

    def contested(self) -> bool:
        """True when the evidence does not yet separate the two actions."""
        low_g, high_g = self.interval(GOOD)
        low_b, high_b = self.interval(BAD)
        return low_g < high_b and low_b < high_g


# --- topologies -------------------------------------------------------------


def complete(n: int, rng: random.Random) -> list[list[int]]:
    return [[j for j in range(n) if j != i] for i in range(n)]


def ring(n: int, rng: random.Random, degree: int = 2) -> list[list[int]]:
    """Each agent shares with `degree` nearest neighbours around a cycle."""
    half = max(degree // 2, 1)
    return [
        sorted({(i + offset) % n for d in range(1, half + 1) for offset in (d, -d)} - {i})
        for i in range(n)
    ]


def cycle_sparse(n: int, rng: random.Random) -> list[list[int]]:
    """Degree 1: a directed cycle, the sparsest connected structure."""
    return [[(i + 1) % n] for i in range(n)]


def small_world(n: int, rng: random.Random, degree: int = 4, rewire: float = 0.10) -> list[list[int]]:
    """Watts-Strogatz: a ring with a few long-range shortcuts."""
    neighbours = [set(group) for group in ring(n, rng, degree)]
    for i in range(n):
        for j in list(neighbours[i]):
            if rng.random() < rewire:
                candidates = [k for k in range(n) if k != i and k not in neighbours[i]]
                if candidates:
                    neighbours[i].discard(j)
                    neighbours[j].discard(i)
                    new = rng.choice(candidates)
                    neighbours[i].add(new)
                    neighbours[new].add(i)
    return [sorted(group) for group in neighbours]


def isolated(n: int, rng: random.Random) -> list[list[int]]:
    return [[] for _ in range(n)]


TOPOLOGIES = {
    "complete": complete,
    "small_world": small_world,
    "ring": ring,
    "cycle_sparse": cycle_sparse,
    "isolated": isolated,
}

# Ordered densest to sparsest, which is the axis H4a predicts along.
TOPOLOGY_ORDER = ("complete", "small_world", "ring", "cycle_sparse", "isolated")


@dataclass
class RunOutcome:
    correct: bool
    consensus_round: int | None
    wrong_at_checkpoint: bool
    recovered: bool
    recovery_round: int | None
    bad_pulls: int
    total_pulls: int

    @property
    def regret(self) -> float:
        return self.bad_pulls / self.total_pulls if self.total_pulls else 0.0


def simulate(
    config: BanditConfig,
    topology: str,
    preserve: bool,
    seed: int,
    checkpoint: int = 20,
) -> RunOutcome:
    """One replication: a population sharing evidence for `rounds` rounds."""
    rng = random.Random(seed)
    neighbours = TOPOLOGIES[topology](config.n_agents, rng)
    payoffs = (config.p_good, config.p_bad)

    agents = []
    for _ in range(config.n_agents):
        belief = Beliefs()
        belief.observe(BAD, _binomial(rng, config.known_observations, config.p_bad),
                       config.known_observations)
        # A uniformly-drawn rate, so the population starts spread across the
        # whole range of opinions about the uncertain action.
        seed_rate = rng.random()
        belief.observe(GOOD, _binomial(rng, config.prior_observations, seed_rate),
                       config.prior_observations)
        agents.append(belief)

    consensus_round: int | None = None
    last_profile: tuple[int, ...] | None = None
    stable_since: int | None = None
    wrong_at_checkpoint = False
    recovery_round: int | None = None
    bad_pulls = 0
    total_pulls = 0

    for round_index in range(config.rounds):
        # Each agent decides and pulls, then results are shared. Collecting
        # first and sharing after keeps the round synchronous: no agent sees a
        # neighbour's results from the same round before choosing.
        results: list[list[tuple[int, int, int]]] = []
        for belief in agents:
            believed = belief.believes()
            allocation = [(believed, config.pulls_per_round)]
            if preserve and belief.contested():
                minority = BAD if believed == GOOD else GOOD
                spend = int(round(config.preserve_share * config.pulls_per_round))
                if spend:
                    allocation = [
                        (believed, config.pulls_per_round - spend),
                        (minority, spend),
                    ]
            observed: list[tuple[int, int, int]] = []
            for action, trials in allocation:
                if trials <= 0:
                    continue
                successes = _binomial(rng, trials, payoffs[action])
                observed.append((action, successes, trials))
                total_pulls += trials
                if action == BAD:
                    bad_pulls += trials
            results.append(observed)

        for index, observed in enumerate(results):
            for action, successes, trials in observed:
                agents[index].observe(action, successes, trials)
                for neighbour in neighbours[index]:
                    agents[neighbour].observe(action, successes, trials)

        profile = tuple(belief.believes() for belief in agents)
        if profile != last_profile:
            last_profile = profile
            stable_since = round_index
        if len(set(profile)) == 1 and stable_since is not None:
            consensus_round = stable_since

        if round_index == checkpoint:
            wrong_at_checkpoint = not all(b == GOOD for b in profile)
        if (
            wrong_at_checkpoint
            and recovery_round is None
            and all(b == GOOD for b in profile)
        ):
            recovery_round = round_index

    correct = all(belief.believes() == GOOD for belief in agents)
    return RunOutcome(
        correct=correct,
        consensus_round=consensus_round,
        wrong_at_checkpoint=wrong_at_checkpoint,
        recovered=wrong_at_checkpoint and correct,
        recovery_round=recovery_round,
        bad_pulls=bad_pulls,
        total_pulls=total_pulls,
    )


def _binomial(rng: random.Random, trials: int, probability: float) -> int:
    """Binomial draw from an injected generator.

    `random.binomialvariate` exists on the module-level generator in 3.12+, but
    AGENTS.md forbids global randomness in experiments — every draw has to come
    from the seeded instance so a replication is reproducible.
    """
    method = getattr(rng, "binomialvariate", None)
    if method is not None:
        return method(trials, probability)
    return sum(1 for _ in range(trials) if rng.random() < probability)
