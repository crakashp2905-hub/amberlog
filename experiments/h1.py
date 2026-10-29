"""H1: does a propensity-corrected, amortized estimator recover true memory value?

Implements the pre-registration in `research/prereg/h1-causal-credit.md`. The
decision rules there are applied verbatim by `verdict()`; nothing in this file
chooses a threshold.

    python -m experiments.h1            # primary result + power sweep
    python -m experiments.h1 --quick    # fewer seeds and episodes, for a smoke test
"""

from __future__ import annotations

import argparse
import math
import sys
from dataclasses import dataclass, field
from typing import Sequence

from amberlog.estimators import build_estimator
from amberlog.model import UNKNOWN_VALUE

from . import stats
from .runner import (
    RunConfig,
    estimable_memories,
    exploration_overhead,
    ground_truth,
    run,
)

ESTIMATOR_IDS = ("naive_usage", "ips", "dr", "amortized")

# Pre-registered (research/prereg/h1-causal-credit.md §7).
RHO_TARGET = 0.60
RHO_KILL = 0.50
OVERHEAD_TARGET = 0.10
OVERHEAD_KILL = 0.20
MARGIN_OVER_NAIVE = 0.15

EPSILONS = (0.05, 0.10, 0.20, 0.30)
POWER_EPISODES = (250, 500, 1000, 2000, 4000)


@dataclass
class Scored:
    rho: float
    coverage: float
    n: int


@dataclass
class CellResult:
    epsilon: float
    n_episodes: int
    rho: dict[str, list[float]] = field(default_factory=dict)
    coverage: dict[str, list[float]] = field(default_factory=dict)
    overhead: list[float] = field(default_factory=list)
    population: list[int] = field(default_factory=list)


def score_estimator(result, truth: dict[str, float], population: Sequence[str], estimator_id: str) -> Scored:
    """Spearman over the pre-registered population.

    A memory the estimator declines to score is ranked lowest, tied with the
    other decliners: declining is not free, and dropping those memories would
    flatter an estimator that only answers the easy cases.
    """
    estimator = build_estimator(estimator_id)
    estimator.fit(result.fabric.state)

    scored = [mid for mid in population if mid in truth]
    if len(scored) < 3:
        return Scored(float("nan"), 0.0, len(scored))

    estimates: list[float] = []
    answered = 0
    for memory_id in scored:
        value = estimator.estimate(memory_id)
        # "Declined" means the UNKNOWN sentinel, exactly as pre-registered — not
        # `n_eff == 0`. The amortized estimator deliberately returns a finite
        # prediction with no evidence of its own for memories that have none;
        # treating that as a refusal would discard the one thing amortization
        # exists to provide.
        declined = value.estimator == UNKNOWN_VALUE.estimator or not math.isfinite(value.mean)
        if declined:
            estimates.append(-math.inf)
        else:
            answered += 1
            estimates.append(value.mean)

    # -inf ranks lowest and ties; replace with a finite floor so ranking works.
    finite = [v for v in estimates if math.isfinite(v)]
    floor = (min(finite) - 1.0) if finite else 0.0
    estimates = [floor if v == -math.inf else v for v in estimates]

    truths = [truth[mid] for mid in scored]
    return Scored(stats.spearman(estimates, truths), answered / len(scored), len(scored))


def run_cell(epsilon: float, n_episodes: int, seeds: Sequence[int], with_overhead: bool) -> CellResult:
    cell = CellResult(epsilon=epsilon, n_episodes=n_episodes)
    for estimator_id in ESTIMATOR_IDS:
        cell.rho[estimator_id] = []
        cell.coverage[estimator_id] = []

    for seed in seeds:
        config = RunConfig(n_episodes=n_episodes, seed=seed, epsilon=epsilon)
        result = run(config)
        try:
            truth = ground_truth(result)
            population = sorted(estimable_memories(result))
            cell.population.append(len(population))
            for estimator_id in ESTIMATOR_IDS:
                scored = score_estimator(result, truth, population, estimator_id)
                cell.rho[estimator_id].append(scored.rho)
                cell.coverage[estimator_id].append(scored.coverage)
        finally:
            result.close()

        if with_overhead:
            paired = exploration_overhead(
                RunConfig(n_episodes=n_episodes, seed=seed, epsilon=epsilon)
            )
            cell.overhead.append(paired["overhead"])
    return cell


def verdict(cells: Sequence[CellResult]) -> tuple[str, str]:
    """Apply the pre-registered decision rules. No threshold is chosen here."""
    ordered = sorted(cells, key=lambda c: c.epsilon)

    for cell in ordered:
        rho = stats.mean(cell.rho["amortized"])
        naive = stats.mean(cell.rho["naive_usage"])
        overhead = stats.mean(cell.overhead)
        if math.isnan(rho) or rho < RHO_TARGET:
            continue
        margin = rho - naive
        if overhead <= OVERHEAD_TARGET and margin >= MARGIN_OVER_NAIVE:
            return (
                "SUPPORTED",
                f"at eps={cell.epsilon}: rho={rho:.3f} >= {RHO_TARGET}, "
                f"overhead={overhead:.1%} <= {OVERHEAD_TARGET:.0%}, "
                f"margin over naive={margin:+.3f} >= {MARGIN_OVER_NAIVE}",
            )
        reasons = []
        if overhead > OVERHEAD_TARGET:
            reasons.append(f"overhead {overhead:.1%} > {OVERHEAD_TARGET:.0%}")
        if margin < MARGIN_OVER_NAIVE:
            reasons.append(f"margin over naive {margin:+.3f} < {MARGIN_OVER_NAIVE}")
        return (
            "INCONCLUSIVE",
            f"first eps reaching rho>={RHO_TARGET} was {cell.epsilon} "
            f"(rho={rho:.3f}) but " + "; ".join(reasons),
        )

    for cell in ordered:
        rho = stats.mean(cell.rho["amortized"])
        overhead = stats.mean(cell.overhead)
        if not math.isnan(rho) and rho >= RHO_KILL and overhead <= OVERHEAD_KILL:
            return (
                "INCONCLUSIVE",
                f"no eps reached rho>={RHO_TARGET}; best was {rho:.3f} at "
                f"eps={cell.epsilon} (overhead {overhead:.1%}), above the kill line",
            )

    best = max(
        (stats.mean(c.rho["amortized"]) for c in ordered if not math.isnan(stats.mean(c.rho["amortized"]))),
        default=float("nan"),
    )
    return (
        "KILLED",
        f"no eps reached rho>={RHO_KILL} within {OVERHEAD_KILL:.0%} overhead "
        f"(best rho={best:.3f}). Per ROADMAP P4: credit stays a heuristic, "
        f"governance remains the product, P5 does not start.",
    )


def print_table(cells: Sequence[CellResult]) -> None:
    print(f"\n{'eps':>6} {'overhead':>18} " + " ".join(f"{e:>22}" for e in ESTIMATOR_IDS))
    print("-" * (26 + 23 * len(ESTIMATOR_IDS)))
    for cell in sorted(cells, key=lambda c: c.epsilon):
        overhead = stats.fmt_ci(cell.overhead) if cell.overhead else "—"
        row = f"{cell.epsilon:>6.2f} {overhead:>18} "
        row += " ".join(f"{stats.fmt_ci(cell.rho[e]):>22}" for e in ESTIMATOR_IDS)
        print(row)
    print("\n(rho = Spearman vs true value, mean over seeds [95% bootstrap CI])")


def print_coverage(cells: Sequence[CellResult]) -> None:
    print(f"\n{'eps':>6} {'memories':>10} " + " ".join(f"{e:>16}" for e in ESTIMATOR_IDS))
    print("-" * (18 + 17 * len(ESTIMATOR_IDS)))
    for cell in sorted(cells, key=lambda c: c.epsilon):
        pop = f"{stats.mean([float(p) for p in cell.population]):.0f}"
        row = f"{cell.epsilon:>6.2f} {pop:>10} "
        row += " ".join(f"{stats.mean(cell.coverage[e]):>15.1%} " for e in ESTIMATOR_IDS)
        print(row)
    print("\n(coverage = fraction of the analysis population the estimator scored)")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="H1: causal memory value estimation")
    parser.add_argument("--quick", action="store_true", help="fewer seeds and episodes")
    parser.add_argument("--seeds", type=int, default=10)
    parser.add_argument("--episodes", type=int, default=2000)
    args = parser.parse_args(argv)

    seeds = list(range(3 if args.quick else args.seeds))
    episodes = 500 if args.quick else args.episodes
    epsilons = (0.1, 0.2) if args.quick else EPSILONS

    print("H1 — causal memory value estimation")
    print("Pre-registration: research/prereg/h1-causal-credit.md")
    print(f"seeds={len(seeds)}  episodes={episodes}  eps={list(epsilons)}")

    cells = [run_cell(eps, episodes, seeds, with_overhead=True) for eps in epsilons]

    print("\n=== Primary: rho by exploration rate ===")
    print_table(cells)
    print("\n=== Coverage ===")
    print_coverage(cells)

    if not args.quick:
        print("\n=== Power sweep (eps=0.20) ===")
        power = [run_cell(0.20, n, seeds, with_overhead=False) for n in POWER_EPISODES]
        print(f"\n{'episodes':>9} " + " ".join(f"{e:>22}" for e in ESTIMATOR_IDS))
        print("-" * (10 + 23 * len(ESTIMATOR_IDS)))
        for cell, n in zip(power, POWER_EPISODES):
            print(f"{n:>9} " + " ".join(f"{stats.fmt_ci(cell.rho[e]):>22}" for e in ESTIMATOR_IDS))

    outcome, reason = verdict(cells)
    print(f"\n{'=' * 78}\nVERDICT: {outcome}\n{reason}\n{'=' * 78}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
