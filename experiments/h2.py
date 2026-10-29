"""H2: does credit-driven forgetting beat the heuristics?

Implements `research/prereg/h2-credit-driven-retention.md`, including its
2026-10-01 amendment. The decision rules there are applied verbatim by
`verdict()`; nothing here chooses a threshold.

    python -m experiments.h2
    python -m experiments.h2 --quick
"""

from __future__ import annotations

import argparse
import math
import random
import sys
from dataclasses import dataclass, field
from typing import Sequence

from amberlog import Amberlog
from amberlog.cli import configure_output
from amberlog.exposure import EpsilonGreedyPolicy, TopKPolicy

from . import stats
from .retention_arms import ARMS, BASELINES, CHALLENGER, make_oracle, prune
from .ruleworld import CLAIM, RuleWorld, WorldConfig, query_for, seed_memories
from .runner import RunConfig, ground_truth, run

# Pre-registered (prereg §6, §8).
MARGIN_TARGET = 0.05
BUDGET = 40
WARMUP_EPISODES = 2000
EVAL_EPISODES = 2000
DRIFT_AT = 1000
PRUNE_EVERY = 500
EPSILON = 0.20
DRIFT_FRACTION = 0.4

H2_WORLD = WorldConfig(
    n_symptoms=40,
    n_actions=8,
    n_correct_claims=20,
    n_wrong_claims=30,
    n_distractors=40,
    compliance=0.8,
    coverage=0.5,
    rare_fraction=0.10,
    rare_rate=0.05,
)

ARM_ORDER = ("random", "frequency", "recency_importance", "naive", "amortized", "oracle")


@dataclass
class ArmOutcome:
    arm: str
    success: float
    pre_drift: float
    post_drift: float
    recovery: float
    rare_retained: float
    harm_retained: float
    kept: int


@dataclass
class SeedOutcome:
    seed: int
    arms: dict[str, ArmOutcome] = field(default_factory=dict)


def _rngs(seed: int) -> dict[str, random.Random]:
    """Separate streams so arms see identical worlds and identical task order.

    One shared generator would couple the draws: an arm that exposes a different
    number of memories would consume a different number of random values and
    every later task would diverge, making the comparison unpaired.
    """
    return {
        "world": random.Random(seed),
        "tasks": random.Random(seed + 10_000),
        "agent": random.Random(seed + 20_000),
        "drift": random.Random(seed + 30_000),
        "prune": random.Random(seed + 40_000),
    }


def _play(
    fabric: Amberlog,
    world: RuleWorld,
    symptoms: Sequence[str],
    rng_agent: random.Random,
    k: int,
    label: str,
) -> list[float]:
    outcomes: list[float] = []
    for index, symptom in enumerate(symptoms):
        session = fabric.session("agent", f"{label}-{index}", {"symptom": symptom})
        result = session.recall(query_for(symptom), k=k)
        ranked = [dict(m.structured or {}) for m in result.exposed]
        action = world.act(symptom, ranked, rng_agent)
        outcome = 1.0 if action == world.rules[symptom].correct_action else 0.0
        session.record_outcome(outcome, verifier_id="env")
        session.close()
        outcomes.append(outcome)
    return outcomes


def run_seed(seed: int, arms: Sequence[str], quick: bool = False, budget: int = BUDGET) -> SeedOutcome:
    warmup_n = 400 if quick else WARMUP_EPISODES
    eval_n = 400 if quick else EVAL_EPISODES
    drift_at = 200 if quick else DRIFT_AT
    prune_every = 200 if quick else PRUNE_EVERY

    outcome = SeedOutcome(seed=seed)

    # Ground truth comes from a probe run, which builds its own fabric and so
    # its own memory ids. Keying it by id would silently hand the oracle a
    # dictionary that matches nothing, and it would prune at random while
    # looking like an upper bound.
    #
    # Seeding is deterministic given the seed, so the i-th seeded memory is the
    # same (kind, symptom, action) in every arm. Index is therefore the stable
    # identity across fabrics; ids are not.
    truth_by_index: dict[int, float] = {}
    probe = run(RunConfig(n_episodes=warmup_n, seed=seed, epsilon=EPSILON, world=H2_WORLD))
    try:
        probe_truth = ground_truth(probe)
        truth_by_index = {
            index: probe_truth[s.memory_id]
            for index, s in enumerate(probe.seeded)
            if s.memory_id in probe_truth
        }
    finally:
        probe.close()

    for arm in arms:
        rngs = _rngs(seed)
        world = RuleWorld(H2_WORLD, rngs["world"])
        fabric = Amberlog(
            auto_activate=True,
            seed=seed,
            exposure_policy=EpsilonGreedyPolicy(epsilon=EPSILON, rank_by="relevance"),
        )
        try:
            seeded = seed_memories(fabric, world, rngs["world"])
            # Re-key ground truth onto this fabric's own ids.
            truth = {
                s.memory_id: truth_by_index[index]
                for index, s in enumerate(seeded)
                if index in truth_by_index
            }

            warm_symptoms = [world.sample_symptom(rngs["tasks"]) for _ in range(warmup_n)]
            _play(fabric, world, warm_symptoms, rngs["agent"], k=3, label="warm")

            # Evaluation uses relevance ranking for every arm, so the only
            # difference between arms is what survived.
            fabric.policy = TopKPolicy("relevance")
            eval_symptoms = [world.sample_symptom(rngs["tasks"]) for _ in range(eval_n)]

            scorer = make_oracle(truth) if arm == "oracle" else ARMS[arm]
            kept = prune(fabric, scorer, budget, rngs["prune"])

            rare_truth = {
                s.memory_id
                for s in seeded
                if s.kind == CLAIM
                and s.symptom in world.rare
                and s.action == world.rules[s.symptom].correct_action
            }
            harmful = {
                mid for mid, value in truth.items() if value < -0.05
            } if truth else set()

            outcomes: list[float] = []
            drift_done = False
            for start in range(0, eval_n, prune_every):
                chunk = eval_symptoms[start : start + prune_every]
                if not drift_done and start >= drift_at:
                    world.apply_drift(DRIFT_FRACTION, rngs["drift"])
                    drift_done = True
                outcomes.extend(
                    _play(fabric, world, chunk, rngs["agent"], k=3, label=f"eval{start}")
                )
                if start + prune_every < eval_n:
                    prune(fabric, scorer, budget, rngs["prune"])

            pre = outcomes[:drift_at]
            post = outcomes[drift_at:]
            outcome.arms[arm] = ArmOutcome(
                arm=arm,
                success=sum(outcomes) / len(outcomes),
                pre_drift=sum(pre) / len(pre) if pre else float("nan"),
                post_drift=sum(post) / len(post) if post else float("nan"),
                recovery=_recovery(outcomes, drift_at),
                rare_retained=(
                    len(rare_truth & kept) / len(rare_truth) if rare_truth else float("nan")
                ),
                harm_retained=(
                    len(harmful & kept) / len(harmful) if harmful else float("nan")
                ),
                kept=len(kept),
            )
        finally:
            fabric.close()
    return outcome


def _recovery(outcomes: Sequence[float], drift_at: int, window: int = 200, tolerance: float = 0.02) -> float:
    """Episodes after drift until a rolling mean returns within `tolerance` of
    the pre-drift level. NaN when it never does.

    **Not interpretable as currently reported, and omitted from the H2 result.**
    Averaging this across seeds averages only the seeds that recovered, which is
    a different subset for each arm: an arm where one seed recovered fast and
    nine never did scores better than one where all ten recovered slowly. It
    also favours arms with a *lower* pre-drift level, because they have less
    ground to make up.

    Fix before H3: report a recovery *rate* (what fraction of seeds recovered)
    alongside the time, and measure the gap against a common reference rather
    than each arm's own pre-drift mean.
    """
    pre = outcomes[:drift_at]
    if not pre or drift_at >= len(outcomes):
        return float("nan")
    target = sum(pre) / len(pre) - tolerance
    for end in range(drift_at + window, len(outcomes) + 1):
        chunk = outcomes[end - window : end]
        if sum(chunk) / window >= target:
            return float(end - window - drift_at)
    return float("nan")


def verdict(results: Sequence[SeedOutcome]) -> tuple[str, str]:
    """Apply the pre-registered rules (§6). No threshold is chosen here."""
    def series(arm: str) -> list[float]:
        return [r.arms[arm].success for r in results if arm in r.arms]

    challenger = series(CHALLENGER)
    if not challenger:
        return ("INCONCLUSIVE", "challenger arm did not run")

    failures: list[str] = []
    beats_all = True
    for baseline in BASELINES:
        base = series(baseline)
        diffs = [c - b for c, b in zip(challenger, base)]
        mean_diff = stats.mean(diffs)
        low, high = stats.bootstrap_ci(diffs)
        if mean_diff <= 0 or (not math.isnan(low) and low <= 0 <= high):
            beats_all = False
        if mean_diff < MARGIN_TARGET or (not math.isnan(low) and low <= 0):
            failures.append(
                f"vs {baseline}: {mean_diff:+.3f} [{low:+.3f}, {high:+.3f}]"
            )

    best_baseline = max(BASELINES, key=lambda b: stats.mean(series(b)))
    best_diffs = [c - b for c, b in zip(challenger, series(best_baseline))]
    best_mean = stats.mean(best_diffs)
    best_low, best_high = stats.bootstrap_ci(best_diffs)

    if best_mean <= 0 or (not math.isnan(best_low) and best_low <= 0 <= best_high):
        return (
            "KILLED",
            f"amortized does not beat the best baseline ({best_baseline}): "
            f"{best_mean:+.3f} [{best_low:+.3f}, {best_high:+.3f}]. Per ROADMAP P5, "
            f"credit-driven retention is not justified.",
        )
    if not failures:
        return (
            "SUPPORTED",
            f"amortized beats every baseline by >= {MARGIN_TARGET:.0%} with intervals "
            f"clear of zero (best baseline {best_baseline}: {best_mean:+.3f} "
            f"[{best_low:+.3f}, {best_high:+.3f}])",
        )
    return (
        "INCONCLUSIVE",
        "beats the baselines but not by the registered margin — " + "; ".join(failures),
    )


def print_arms(results: Sequence[SeedOutcome]) -> None:
    print(f"\n{'arm':>20} {'success':>20} {'pre-drift':>12} {'post-drift':>12} "
          f"{'recovery':>10} {'rare kept':>11} {'harm kept':>11}")
    print("-" * 100)
    for arm in ARM_ORDER:
        if not any(arm in r.arms for r in results):
            continue
        get = lambda f: [getattr(r.arms[arm], f) for r in results if arm in r.arms]  # noqa: E731
        recoveries = [v for v in get("recovery") if not math.isnan(v)]
        recovery = f"{stats.mean(recoveries):.0f}" if recoveries else "never"
        print(
            f"{arm:>20} {stats.fmt_ci(get('success')):>20} "
            f"{stats.mean(get('pre_drift')):>12.3f} {stats.mean(get('post_drift')):>12.3f} "
            f"{recovery:>10} {stats.mean(get('rare_retained')):>11.1%} "
            f"{stats.mean(get('harm_retained')):>11.1%}"
        )
    print("\n(success = mean over evaluation episodes [95% bootstrap CI over seeds])")
    print("(rare kept = correct claims about rare symptoms surviving the prune)")
    print("(harm kept = memories with true value < -0.05 surviving the prune)")


def print_paired(results: Sequence[SeedOutcome]) -> None:
    challenger = [r.arms[CHALLENGER].success for r in results]
    print(f"\n{'comparison':>36} {'difference':>22}")
    print("-" * 60)
    for baseline in BASELINES:
        base = [r.arms[baseline].success for r in results]
        diffs = [c - b for c, b in zip(challenger, base)]
        print(f"{'amortized - ' + baseline:>36} {stats.fmt_ci(diffs):>22}")
    print(f"\n(registered bar: >= {MARGIN_TARGET:+.2f} with the interval clear of zero)")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="H2: credit-driven retention")
    parser.add_argument("--quick", action="store_true")
    parser.add_argument("--seeds", type=int, default=10)
    parser.add_argument("--budget-sweep", action="store_true",
                        help="EXPLORATORY: sweep the memory budget (post-hoc, not registered)")
    args = parser.parse_args(argv)

    seeds = list(range(3 if args.quick else args.seeds))
    arms = list(ARM_ORDER)

    configure_output()
    print("H2 - credit-driven forgetting")
    print("Pre-registration: research/prereg/h2-credit-driven-retention.md")
    print(f"seeds={len(seeds)}  budget={BUDGET}  arms={arms}")

    if args.budget_sweep:
        return _budget_sweep(seeds, args.quick)

    results = [run_seed(seed, arms, quick=args.quick) for seed in seeds]

    print("\n=== Arms ===")
    print_arms(results)
    print("\n=== Paired differences ===")
    print_paired(results)

    outcome, reason = verdict(results)
    print(f"\n{'=' * 78}\nVERDICT: {outcome}\n{reason}\n{'=' * 78}")

    guard = _guardrail(results)
    if guard:
        print(f"\nGUARDRAIL (prereg §7): {guard}")
    return 0


def _budget_sweep(seeds: Sequence[int], quick: bool) -> int:
    """EXPLORATORY, post-hoc. Not part of the registered H2 test.

    The registered design fixes one budget (40 of ~120). Limitation 5 flagged
    that as untested, and the headline result makes it material: if a generous
    budget leaves room to keep both the valuable and the merely harmless, a
    better ranking has little to prove. This asks whether the ordering changes
    when the budget actually bites. It cannot overturn the verdict above; it can
    only say whether a differently-registered test is worth running.
    """
    arms = ("random", "frequency", "recency_importance", "naive", "amortized", "oracle")
    budgets = (10, 20, 40, 80)
    print("\n=== EXPLORATORY budget sweep (post-hoc, not pre-registered) ===")
    print(f"{'budget':>8} " + " ".join(f"{a:>20}" for a in arms))
    print("-" * (9 + 21 * len(arms)))
    for budget in budgets:
        results = [run_seed(s, arms, quick=quick, budget=budget) for s in seeds]
        row = f"{budget:>8} "
        for arm in arms:
            series = [r.arms[arm].success for r in results]
            row += f"{stats.fmt_ci(series):>20} "
        print(row)
        challenger = [r.arms[CHALLENGER].success for r in results]
        naive = [r.arms["naive"].success for r in results]
        diffs = [c - n for c, n in zip(challenger, naive)]
        print(f"{'':>8} amortized - naive: {stats.fmt_ci(diffs)}")
    return 0


def _guardrail(results: Sequence[SeedOutcome]) -> str:
    """Pre-registered §7: does credit-driven forgetting delete the rare ones?"""
    def rare(arm: str) -> float:
        return stats.mean(
            [r.arms[arm].rare_retained for r in results if arm in r.arms]
        )

    challenger = rare(CHALLENGER)
    comparator = rare("recency_importance")
    if math.isnan(challenger) or math.isnan(comparator):
        return ""
    if challenger < comparator:
        return (
            f"TRIGGERED — amortized retains {challenger:.1%} of rare-but-correct "
            f"memories against recency_importance's {comparator:.1%}. Credit-driven "
            f"retention must not ship without the rare-event protection in "
            f"RetentionPolicy."
        )
    return (
        f"not triggered — amortized retains {challenger:.1%} of rare-but-correct "
        f"memories against recency_importance's {comparator:.1%}."
    )


if __name__ == "__main__":
    sys.exit(main())
