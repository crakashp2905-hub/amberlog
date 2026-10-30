"""H3: does selective federation beat sharing nothing and sharing everything?

Implements `research/prereg/h3-selective-federation.md`. The decision rules
there are applied verbatim by `verdict()`; nothing here chooses a threshold.

    python -m experiments.h3
    python -m experiments.h3 --quick
"""

from __future__ import annotations

import argparse
import math
import random
import sys
from dataclasses import dataclass, field
from typing import Sequence

from memory_fabric import LifecycleState, MemoryFabric
from memory_fabric.cli import configure_output
from memory_fabric.estimators import build_estimator
from memory_fabric.exposure import EpsilonGreedyPolicy, TopKPolicy
from memory_fabric.federation import describe, imported_from, offer_many

from . import stats
from .contexts import build_contexts, true_value_in
from .ruleworld import RuleWorld, WorldConfig, query_for, seed_memories

# Pre-registered (§6, §7).
NEVER_WORSE_BY = 0.02
STRICTLY_BETTER_BY = 0.03
INTERMEDIATE = (0.25, 0.5, 0.75)
OVERLAPS = (0.0, 0.25, 0.5, 0.75, 1.0)
ARMS = ("none", "full", "selective", "random_probe", "fed_oracle")
# `random_probe` is a CONTROL, added after a quick run showed selective keeps
# only about half the imports — raising the possibility that its advantage comes
# from carrying fewer memories (less crowding in retrieval) rather than from
# choosing well. It pays the identical probe cost and keeps the identical
# number, chosen at random. It can only make the hypothesis harder to support,
# never easier, and it does not enter the pre-registered decision rule in §6.
CONTROL = "random_probe"
# `fed_oracle` is EXPLORATORY and post-hoc: perfect knowledge of which imports
# help in the recipient's context. Added after the registered run because
# without a ceiling there is no way to read the magnitude of selective's
# advantage — H2's oracle is what revealed that the naive baseline was already
# capturing 93% of what was available. It is not a competitor and does not
# enter the §6 decision rule.
ORACLE = "fed_oracle"
FIXED_ARMS = ("none", "full")

LOCAL_EPISODES = 1500
PROBE_EPISODES = 500
EVAL_EPISODES = 1500
EPSILON = 0.20

def experiment_firewall():
    """The product firewall minus its value rule.

    `rule_value_must_show_benefit` refuses to federate a memory without proven
    contrastive benefit — which is itself a selective-sharing policy, and it
    blocks every offer, making all three arms identical. The arms *are* the
    sharing policy here, so the firewall must not pre-empt them. Every other
    rule stands: security class, lifecycle, capabilities, sensitive data.

    Worth noting for the product: that rule gates on value measured in the
    **sender's** context. H3's whole premise is that value does not cross a
    context boundary, so passing the sender's gate says little about whether a
    memory helps the recipient. The result speaks to whether the rule is asking
    the right question.
    """
    from memory_fabric.governance.firewall import (
        Firewall,
        rule_capabilities_must_be_granted,
        rule_evidence_independence,
        rule_must_be_active,
        rule_open_hypothesis_warns,
        rule_restricted_stays_private,
    )

    return Firewall(
        rules=(
            rule_restricted_stays_private,
            rule_must_be_active,
            rule_open_hypothesis_warns,
            rule_capabilities_must_be_granted,
            rule_evidence_independence,
        )
    )


H3_WORLD = WorldConfig(
    n_symptoms=40,
    n_actions=8,
    n_correct_claims=20,
    n_wrong_claims=30,
    n_distractors=40,
    compliance=0.8,
    coverage=0.5,
    rare_fraction=0.0,
)


@dataclass
class ArmResult:
    arm: str
    overlap: float
    local_success: float
    probe_success: float
    eval_success: float
    negative_transfer: float
    offered: int
    accepted: int
    active_imports: int
    bytes_full: int
    bytes_metadata: int


@dataclass
class Cell:
    overlap: float
    arms: dict[str, list[ArmResult]] = field(default_factory=dict)

    def success(self, arm: str) -> list[float]:
        return [r.eval_success for r in self.arms.get(arm, [])]


def _play(
    fabric: MemoryFabric,
    world: RuleWorld,
    symptoms: Sequence[str],
    rng: random.Random,
    label: str,
    k: int = 3,
) -> float:
    hits = 0.0
    for index, symptom in enumerate(symptoms):
        session = fabric.session("agent", f"{label}-{index}", {"symptom": symptom})
        result = session.recall(query_for(symptom), k=k)
        ranked = [dict(m.structured or {}) for m in result.exposed]
        action = world.act(symptom, ranked, rng)
        outcome = 1.0 if action == world.rules[symptom].correct_action else 0.0
        session.record_outcome(outcome, verifier_id="env")
        session.close()
        hits += outcome
    return hits / len(symptoms) if symptoms else float("nan")


def _probe_and_filter(
    fabric: MemoryFabric,
    world: RuleWorld,
    symptoms: Sequence[str],
    rng: random.Random,
    imported: Sequence[str],
    label: str,
    by_value: bool = True,
) -> float:
    """Expose imports under randomisation, then drop the ones that did not earn
    their place.

    This is the cost of being selective: during the probe a wrong import can be
    retrieved and followed, so the probe's own success is depressed. Charging
    that to the arm is the point — a policy that tests before trusting has to
    pay for the test.

    `by_value=False` is the control arm: identical probe, identical cost, same
    number of survivors, but chosen at random. Any advantage selective holds
    over it is attributable to *selection*; anything they share is attributable
    to simply carrying fewer memories.
    """
    for memory_id in imported:
        if fabric.get(memory_id).lifecycle_state is LifecycleState.CANDIDATE:
            fabric.validate(memory_id, actor="probe", reason="federation probe")

    previous = fabric.policy
    fabric.policy = EpsilonGreedyPolicy(epsilon=EPSILON, rank_by="relevance")
    success = _play(fabric, world, symptoms, rng, label)
    fabric.policy = previous

    if by_value:
        estimator = build_estimator("amortized")
        estimator.fit(fabric.state)
        drop = [
            memory_id
            for memory_id in imported
            if not (
                math.isfinite(v := estimator.estimate(memory_id).mean) and v > 0.0
            )
        ]
    else:
        # Match the volume the value-based filter would keep, so the only
        # difference between the arms is *which* survive.
        keep_count = _value_keep_count(fabric, imported)
        shuffled = list(imported)
        rng.shuffle(shuffled)
        drop = shuffled[keep_count:]

    for memory_id in drop:
        if fabric.get(memory_id).lifecycle_state is LifecycleState.ACTIVE:
            fabric.forget(
                memory_id,
                reason="probe found no value in this context",
                actor="federation",
            )
    return success


def _value_keep_count(fabric: MemoryFabric, imported: Sequence[str]) -> int:
    estimator = build_estimator("amortized")
    estimator.fit(fabric.state)
    return sum(
        1
        for memory_id in imported
        if math.isfinite(v := estimator.estimate(memory_id).mean) and v > 0.0
    )


def run_cell(overlap: float, arm: str, seeds: Sequence[int], quick: bool) -> list[ArmResult]:
    local_n = 300 if quick else LOCAL_EPISODES
    probe_n = 120 if quick else PROBE_EPISODES
    eval_n = 300 if quick else EVAL_EPISODES

    out: list[ArmResult] = []
    for seed in seeds:
        rng_world = random.Random(seed)
        pair = build_contexts(H3_WORLD, overlap, rng_world)

        fabrics, worlds, rngs, seeded = [], list(pair.worlds()), [], []
        for index, world in enumerate(worlds):
            fabric = MemoryFabric(
                auto_activate=True,
                seed=seed + index,
                estimator="amortized",
                exposure_policy=EpsilonGreedyPolicy(epsilon=EPSILON, rank_by="relevance"),
                firewall=experiment_firewall(),
            )
            seeded.append(seed_memories(fabric, world, random.Random(seed + 100 * index)))
            fabrics.append(fabric)
            rngs.append(random.Random(seed + 200 * index))

        try:
            task_rng = random.Random(seed + 7777)
            local_tasks = [
                [w.sample_symptom(task_rng) for _ in range(local_n)] for w in worlds
            ]
            probe_tasks = [
                [w.sample_symptom(task_rng) for _ in range(probe_n)] for w in worlds
            ]
            eval_tasks = [
                [w.sample_symptom(task_rng) for _ in range(eval_n)] for w in worlds
            ]

            local = [
                _play(fabrics[i], worlds[i], local_tasks[i], rngs[i], f"local{i}")
                for i in range(2)
            ]

            offered = accepted = 0
            bytes_full = bytes_metadata = 0
            imported_ids: list[list[str]] = [[], []]
            if arm in ("full", "selective", CONTROL, ORACLE):
                # Snapshot each store's own memories before anything crosses.
                # Otherwise the second direction re-offers what the first just
                # delivered: in the `full` arm imports arrive active, so A
                # receives its own memories back as imports (270 instead of 90),
                # inflating crowding and penalising exactly the arm that is
                # meant to represent "share everything".
                native = [
                    [
                        memory_id
                        for memory_id, memory in fabric.state.memories.items()
                        if memory.lifecycle_state is LifecycleState.ACTIVE
                    ]
                    for fabric in fabrics
                ]
                for source, target in ((0, 1), (1, 0)):
                    summary = offer_many(
                        fabrics[source],
                        fabrics[target],
                        recipient_agent="agent",
                        memory_ids=native[source],
                        activate=(arm == "full"),
                    )
                    offered += summary.offered
                    accepted += summary.accepted
                    for result in summary.results:
                        if result.accepted and result.imported_memory_id:
                            imported_ids[target].append(result.imported_memory_id)
                            bytes_full += len(
                                fabrics[source].get(result.source_memory_id).content
                            )
                            bytes_metadata += len(
                                str(describe(fabrics[source], result.source_memory_id))
                            )

            if arm == ORACLE:
                for i in range(2):
                    for memory_id in imported_ids[i]:
                        structured = dict(fabrics[i].get(memory_id).structured or {})
                        if true_value_in(worlds[i], structured) > 0:
                            fabrics[i].validate(memory_id, actor="oracle",
                                                reason="helps in this context")

            probe = [float("nan"), float("nan")]
            if arm in ("selective", CONTROL):
                probe = [
                    _probe_and_filter(
                        fabrics[i], worlds[i], probe_tasks[i], rngs[i],
                        imported_ids[i], f"probe{i}", by_value=(arm == "selective"),
                    )
                    for i in range(2)
                ]

            for fabric in fabrics:
                fabric.policy = TopKPolicy("relevance")
            evaluation = [
                _play(fabrics[i], worlds[i], eval_tasks[i], rngs[i], f"eval{i}")
                for i in range(2)
            ]

            active_imports = 0
            harmful_active = 0
            for i in range(2):
                for memory_id in imported_ids[i]:
                    memory = fabrics[i].get(memory_id)
                    if memory.lifecycle_state is not LifecycleState.ACTIVE:
                        continue
                    active_imports += 1
                    if true_value_in(worlds[i], dict(memory.structured or {})) < 0:
                        harmful_active += 1

            out.append(
                ArmResult(
                    arm=arm,
                    overlap=overlap,
                    local_success=stats.mean(local),
                    probe_success=stats.mean(probe),
                    eval_success=stats.mean(evaluation),
                    negative_transfer=(
                        harmful_active / active_imports if active_imports else 0.0
                    ),
                    offered=offered,
                    accepted=accepted,
                    active_imports=active_imports,
                    bytes_full=bytes_full,
                    bytes_metadata=bytes_metadata,
                )
            )
        finally:
            for fabric in fabrics:
                fabric.close()
    return out


def verdict(cells: Sequence[Cell]) -> tuple[str, str]:
    by_overlap = {c.overlap: c for c in cells}

    # Sanity gates: a failure here voids the run rather than answering it.
    extreme_problems: list[str] = []
    if 1.0 in by_overlap:
        cell = by_overlap[1.0]
        if stats.mean(cell.success("full")) <= stats.mean(cell.success("none")):
            extreme_problems.append("at o=1.0 full does not beat none")
    if 0.0 in by_overlap:
        cell = by_overlap[0.0]
        if stats.mean(cell.success("none")) < stats.mean(cell.success("full")):
            extreme_problems.append("at o=0.0 none is worse than full")
    if extreme_problems:
        return ("VOID", "world sanity gate failed: " + "; ".join(extreme_problems))

    never_worse = True
    worse_at: list[str] = []
    for cell in cells:
        selective = stats.mean(cell.success("selective"))
        best_fixed = max(stats.mean(cell.success(a)) for a in FIXED_ARMS)
        if selective < best_fixed - NEVER_WORSE_BY:
            never_worse = False
            worse_at.append(f"o={cell.overlap}: {selective - best_fixed:+.3f}")

    strictly_better: list[str] = []
    beat_somewhere = False
    for overlap in INTERMEDIATE:
        cell = by_overlap.get(overlap)
        if cell is None:
            continue
        selective = cell.success("selective")
        best_arm = max(FIXED_ARMS, key=lambda a: stats.mean(cell.success(a)))
        diffs = [s - b for s, b in zip(selective, cell.success(best_arm))]
        mean_diff = stats.mean(diffs)
        low, high = stats.bootstrap_ci(diffs)
        if mean_diff > 0:
            beat_somewhere = True
        if mean_diff < STRICTLY_BETTER_BY or (not math.isnan(low) and low <= 0):
            strictly_better.append(
                f"o={overlap}: {mean_diff:+.3f} [{low:+.3f}, {high:+.3f}] vs {best_arm}"
            )

    if not beat_somewhere:
        return (
            "KILLED",
            "selective never beats the better fixed policy at any intermediate "
            "overlap. Per ROADMAP P6, selective federation is not justified.",
        )
    if never_worse and not strictly_better:
        return ("SUPPORTED", "never worse than the better fixed policy, and strictly "
                             "better at every intermediate overlap")

    problems = []
    if not never_worse:
        problems.append("worse than the better fixed policy at " + "; ".join(worse_at))
    if strictly_better:
        problems.append("did not clear the margin at " + "; ".join(strictly_better))
    return ("INCONCLUSIVE", "; ".join(problems))


def print_curve(cells: Sequence[Cell]) -> None:
    print(f"\n{'overlap':>8} " + " ".join(f"{a:>22}" for a in ARMS) + f" {'winner':>12}")
    print("-" * (10 + 23 * len(ARMS) + 13))
    for cell in sorted(cells, key=lambda c: c.overlap):
        row = f"{cell.overlap:>8.2f} "
        means = {a: stats.mean(cell.success(a)) for a in ARMS}
        row += " ".join(f"{stats.fmt_ci(cell.success(a)):>22}" for a in ARMS)
        winner = max(means, key=lambda a: means[a])
        print(row + f" {winner:>12}")
    print("\n(success = evaluation phase, both agents, mean over seeds [95% CI])")


def print_transfer(cells: Sequence[Cell]) -> None:
    print(f"\n{'overlap':>8} {'arm':>11} {'imports kept':>13} {'neg transfer':>13} "
          f"{'probe cost':>11} {'bytes full':>11} {'bytes meta':>11}")
    print("-" * 82)
    for cell in sorted(cells, key=lambda c: c.overlap):
        for arm in ("full", "selective", CONTROL):
            rows = cell.arms.get(arm, [])
            if not rows:
                continue
            probe = stats.mean([r.probe_success - r.local_success for r in rows])
            print(
                f"{cell.overlap:>8.2f} {arm:>11} "
                f"{stats.mean([float(r.active_imports) for r in rows]):>13.0f} "
                f"{stats.mean([r.negative_transfer for r in rows]):>12.1%} "
                f"{('—' if math.isnan(probe) else f'{probe:+.3f}'):>11} "
                f"{stats.mean([float(r.bytes_full) for r in rows]):>11.0f} "
                f"{stats.mean([float(r.bytes_metadata) for r in rows]):>11.0f}"
            )
    print("\n(neg transfer = active imports that are wrong in the recipient's context)")
    print("(probe cost = success during the probe minus the local phase)")


def main(argv: Sequence[str] | None = None) -> int:
    configure_output()
    parser = argparse.ArgumentParser(description="H3: selective federation")
    parser.add_argument("--quick", action="store_true")
    parser.add_argument("--seeds", type=int, default=10)
    args = parser.parse_args(argv)

    seeds = list(range(3 if args.quick else args.seeds))
    overlaps = (0.0, 0.5, 1.0) if args.quick else OVERLAPS

    print("H3 - selective federation")
    print("Pre-registration: research/prereg/h3-selective-federation.md")
    print(f"seeds={len(seeds)}  overlaps={list(overlaps)}  arms={list(ARMS)}")

    cells: list[Cell] = []
    for overlap in overlaps:
        cell = Cell(overlap=overlap)
        for arm in ARMS:
            cell.arms[arm] = run_cell(overlap, arm, seeds, args.quick)
        cells.append(cell)

    print("\n=== Crossover curve ===")
    print_curve(cells)
    print("\n=== Transfer and cost ===")
    print_transfer(cells)

    outcome, reason = verdict(cells)
    print(f"\n{'=' * 78}\nVERDICT: {outcome}\n{reason}\n{'=' * 78}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
