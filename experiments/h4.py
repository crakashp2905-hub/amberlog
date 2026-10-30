"""H4: does a sparser sharing network reach the right belief more often?

Implements `research/prereg/h4-topology-and-diversity.md`. The decision rules
there are applied verbatim by `verdict()`; nothing here chooses a threshold.

    python -m experiments.h4
    python -m experiments.h4 --quick
"""

from __future__ import annotations

import argparse
import math
import sys
from dataclasses import dataclass, field
from typing import Sequence

from memory_fabric.cli import configure_output

from . import stats
from .banditworld import TOPOLOGY_ORDER, BanditConfig, RunOutcome, simulate

# Pre-registered (§5, §6).
SPARSEST_CONNECTED = "cycle_sparse"
DENSEST = "complete"
H4A_HEADROOM_SHARE = 0.40
H4B_HEADROOM_SHARE = 0.20
REPLICATIONS = 200
CHECKPOINT = 20


@dataclass
class CellResult:
    topology: str
    preserve: bool
    outcomes: list[RunOutcome] = field(default_factory=list)

    @property
    def correct(self) -> list[float]:
        return [1.0 if o.correct else 0.0 for o in self.outcomes]

    @property
    def p_correct(self) -> float:
        return stats.mean(self.correct)

    @property
    def consensus(self) -> float:
        rounds = [o.consensus_round for o in self.outcomes if o.consensus_round is not None]
        return stats.mean([float(r) for r in rounds]) if rounds else float("nan")

    @property
    def regret(self) -> float:
        return stats.mean([o.regret for o in self.outcomes])

    @property
    def recovery_rate(self) -> float:
        wrong = [o for o in self.outcomes if o.wrong_at_checkpoint]
        if not wrong:
            return float("nan")
        return sum(1.0 for o in wrong if o.recovered) / len(wrong)

    @property
    def recovery_round(self) -> float:
        rounds = [
            float(o.recovery_round)
            for o in self.outcomes
            if o.recovery_round is not None
        ]
        return stats.mean(rounds) if rounds else float("nan")


def run_cell(topology: str, preserve: bool, replications: int, config: BanditConfig) -> CellResult:
    cell = CellResult(topology=topology, preserve=preserve)
    for seed in range(replications):
        cell.outcomes.append(simulate(config, topology, preserve, seed, CHECKPOINT))
    return cell


def headroom_share(cell: CellResult, baseline: CellResult) -> float:
    """What fraction of the gap to certainty this cell closes.

    The ceiling here is structural: P(correct) = 1.0. Expressing the threshold
    this way is what AGENTS.md 8a requires after H3 registered an absolute
    margin larger than the effect the world could produce.
    """
    gap = 1.0 - baseline.p_correct
    if gap <= 0:
        return float("nan")
    return (cell.p_correct - baseline.p_correct) / gap


def verdict(grid: dict[tuple[str, bool], CellResult]) -> tuple[str, str, str, str]:
    """Returns (h4a outcome, h4a reason, h4b outcome, h4b reason)."""
    base = grid[(DENSEST, False)]
    sparse = grid[(SPARSEST_CONNECTED, False)]

    # --- H4a: three conditions, all required ---------------------------
    diffs = [s - b for s, b in zip(sparse.correct, base.correct)]
    mean_diff = stats.mean(diffs)
    low, high = stats.bootstrap_ci(diffs)
    share = headroom_share(sparse, base)

    if mean_diff <= 0:
        h4a = ("KILLED", f"{SPARSEST_CONNECTED} does not beat {DENSEST} at all "
                         f"({mean_diff:+.3f}). Sparser is not more accurate here.")
    else:
        failures = []
        if share < H4A_HEADROOM_SHARE:
            failures.append(
                f"captures {share:.0%} of headroom, below {H4A_HEADROOM_SHARE:.0%}"
            )
        if not math.isnan(low) and low <= 0:
            failures.append(f"interval [{low:+.3f}, {high:+.3f}] includes zero")

        connected = [t for t in TOPOLOGY_ORDER if t != "isolated"]
        series = [grid[(t, False)].p_correct for t in connected]
        if any(b < a - 1e-9 for a, b in zip(series, series[1:])):
            failures.append(
                "P(correct) is not monotone as degree falls: "
                + " -> ".join(f"{t}={v:.3f}" for t, v in zip(connected, series))
            )

        # The tradeoff half. Sparse that is both more accurate *and* faster is
        # some other effect, not Zollman's, and the claim does not hold.
        if not (sparse.consensus > base.consensus):
            failures.append(
                f"{SPARSEST_CONNECTED} is not slower to consensus "
                f"({sparse.consensus:.1f} vs {base.consensus:.1f}) - without the "
                f"speed cost this is not the Zollman effect"
            )

        if failures:
            h4a = ("INCONCLUSIVE", "; ".join(failures))
        else:
            h4a = ("SUPPORTED",
                   f"{SPARSEST_CONNECTED} captures {share:.0%} of headroom "
                   f"({mean_diff:+.3f} [{low:+.3f}, {high:+.3f}]), P(correct) is "
                   f"monotone in sparsity, and consensus is slower "
                   f"({sparse.consensus:.1f} vs {base.consensus:.1f})")

    # --- H4b: minority preservation under the densest topology ----------
    preserved = grid[(DENSEST, True)]
    b_diffs = [p - b for p, b in zip(preserved.correct, base.correct)]
    b_mean = stats.mean(b_diffs)
    b_low, b_high = stats.bootstrap_ci(b_diffs)
    b_share = headroom_share(preserved, base)
    recovery_improved = (
        not math.isnan(preserved.recovery_rate)
        and not math.isnan(base.recovery_rate)
        and preserved.recovery_rate > base.recovery_rate
    )

    if b_mean <= 0:
        h4b = ("KILLED", f"preserving minority hypotheses does not improve "
                         f"P(correct) under {DENSEST} ({b_mean:+.3f})")
    elif b_share >= H4B_HEADROOM_SHARE and not (not math.isnan(b_low) and b_low <= 0) and recovery_improved:
        h4b = ("SUPPORTED",
               f"captures {b_share:.0%} of headroom ({b_mean:+.3f} "
               f"[{b_low:+.3f}, {b_high:+.3f}]) and lifts recovery "
               f"{base.recovery_rate:.0%} -> {preserved.recovery_rate:.0%}")
    else:
        reasons = []
        if b_share < H4B_HEADROOM_SHARE:
            reasons.append(f"captures {b_share:.0%}, below {H4B_HEADROOM_SHARE:.0%}")
        if not math.isnan(b_low) and b_low <= 0:
            reasons.append(f"interval [{b_low:+.3f}, {b_high:+.3f}] includes zero")
        if not recovery_improved:
            reasons.append(
                f"recovery not improved ({base.recovery_rate:.0%} -> "
                f"{preserved.recovery_rate:.0%})"
            )
        h4b = ("INCONCLUSIVE", "; ".join(reasons))

    return (*h4a, *h4b)


def print_grid(grid: dict[tuple[str, bool], CellResult]) -> None:
    print(f"\n{'topology':>14} {'preserve':>9} {'P(correct)':>22} {'consensus':>10} "
          f"{'recovery':>10} {'regret':>8}")
    print("-" * 80)
    for topology in TOPOLOGY_ORDER:
        for preserve in (False, True):
            cell = grid.get((topology, preserve))
            if cell is None:
                continue
            recovery = (
                "—" if math.isnan(cell.recovery_rate) else f"{cell.recovery_rate:.0%}"
            )
            consensus = (
                "never" if math.isnan(cell.consensus) else f"{cell.consensus:.1f}"
            )
            print(
                f"{topology:>14} {str(preserve):>9} {stats.fmt_ci(cell.correct):>22} "
                f"{consensus:>10} {recovery:>10} {cell.regret:>8.1%}"
            )
    print("\n(P(correct) = all agents end believing the better action [95% CI])")
    print("(consensus = first round of a stable unanimous belief)")
    print("(recovery = of runs wrong at round 20, the share ending correct)")
    print("(regret = share of all pulls spent on the worse action)")


def print_headroom(grid: dict[tuple[str, bool], CellResult]) -> None:
    base = grid[(DENSEST, False)]
    print(f"\nceiling P(correct) = 1.00;  headroom from {DENSEST} = "
          f"{1.0 - base.p_correct:.3f}")
    print(f"\n{'arm':>26} {'P(correct)':>12} {'gain':>9} {'headroom captured':>19}")
    print("-" * 70)
    for topology in TOPOLOGY_ORDER:
        for preserve in (False, True):
            cell = grid.get((topology, preserve))
            if cell is None or (topology == DENSEST and not preserve):
                continue
            share = headroom_share(cell, base)
            label = f"{topology}{'+preserve' if preserve else ''}"
            print(f"{label:>26} {cell.p_correct:>12.3f} "
                  f"{cell.p_correct - base.p_correct:>+9.3f} "
                  f"{('—' if math.isnan(share) else f'{share:.0%}'):>19}")


def main(argv: Sequence[str] | None = None) -> int:
    configure_output()
    parser = argparse.ArgumentParser(description="H4: topology and minority hypotheses")
    parser.add_argument("--quick", action="store_true")
    parser.add_argument("--replications", type=int, default=REPLICATIONS)
    args = parser.parse_args(argv)

    config = BanditConfig(rounds=40 if args.quick else 150)
    replications = 40 if args.quick else args.replications

    print("H4 - topology, premature consensus, and minority hypotheses")
    print("Pre-registration: research/prereg/h4-topology-and-diversity.md")
    print(f"agents={config.n_agents}  replications={replications}  "
          f"rounds={config.rounds}  p={config.p_good}/{config.p_bad}")

    grid: dict[tuple[str, bool], CellResult] = {}
    for topology in TOPOLOGY_ORDER:
        for preserve in (False, True):
            grid[(topology, preserve)] = run_cell(topology, preserve, replications, config)

    print("\n=== Topology x minority preservation ===")
    print_grid(grid)
    print("\n=== Headroom ===")
    print_headroom(grid)

    h4a, h4a_reason, h4b, h4b_reason = verdict(grid)
    print(f"\n{'=' * 78}")
    print(f"H4a (Zollman):             {h4a}\n  {h4a_reason}")
    print(f"\nH4b (minority preserved):  {h4b}\n  {h4b_reason}")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    sys.exit(main())
