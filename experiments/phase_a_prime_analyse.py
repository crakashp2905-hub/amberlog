"""What PA′'s withdrawals actually destroyed.

The registration's PA′2 criterion counts "correct memories withdrawn", and the
harness labels a withdrawal `was_correct` when the lesson was not poisoned —
that is, when it was correct *at the site where it was written*. That is the
right reading for the criterion: a lesson true somewhere is knowledge, and
withdrawing it is a loss.

But it cannot distinguish two different mistakes, and the difference decides
whether an attribution method is working:

* withdrawing a lesson that is **true everywhere it would be used** — pure loss;
* withdrawing a lesson that is true where it was written but **genuinely
  misleading in the episode that triggered the withdrawal** — arguably correct
  behaviour, since the memory really did mislead this agent here.

Leave-one-out should concentrate its withdrawals in the second category, because
that is what a counterfactual identifies. Naive blame has no way to tell them
apart. So this reports both cuts, from the per-withdrawal record joined to the
decision that triggered it.

    python -m experiments.phase_a_prime_analyse research/results/phase-a-prime-decisions.json
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Sequence

from . import stats


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="What PA' withdrawals destroyed")
    parser.add_argument("path")
    args = parser.parse_args(argv)

    data = json.loads(Path(args.path).read_text(encoding="utf-8"))
    decisions = data["decisions"]
    withdrawals = data.get("withdrawals", [])

    # (arm, seed, index) -> the episode that triggered the withdrawal.
    episode_of = {(d["arm"], d["seed"], d["index"]): d for d in decisions}

    by_arm: dict[str, list[dict]] = defaultdict(list)
    for w in withdrawals:
        by_arm[w["arm"]].append(w)

    print("=== What each policy withdrew ===")
    print("Four categories, and the distinction between the middle two is the whole")
    print("point. `poisoned` was wrong even at its own site: a clean win.")
    print("`misled` was about the same fault and gave the wrong answer for this")
    print("episode, so the memory really did mislead and withdrawing it is")
    print("defensible. `irrelevant` was about a DIFFERENT fault and never applied:")
    print("collateral, and still knowledge about its own fault that the store has")
    print("now lost. `true here` was right for this very episode: pure loss.\n")
    print(f"{'arm':<22} {'withdrew':>9} {'poisoned':>9} {'misled':>8} "
          f"{'irrelevant':>11} {'true here':>10} {'unmatched':>10}")
    print("-" * 84)
    summary: dict[str, dict[str, int]] = {}
    for arm in sorted(by_arm):
        poisoned = misled = irrelevant = true_here = unmatched = 0
        for w in by_arm[arm]:
            if not w["was_correct"]:
                poisoned += 1
                continue
            episode = episode_of.get((w["arm"], w["seed"], w["index"]))
            if episode is None:
                unmatched += 1
            elif w["fault"] != episode["fault"]:
                # Not even about the fault being worked. The first version of
                # this analyser compared only actions, not faults, so these
                # counted as justified and every rule scored 100%.
                irrelevant += 1
            elif w["asserted"] != episode["correct"]:
                misled += 1
            else:
                true_here += 1
        total = len(by_arm[arm])
        print(f"{arm:<22} {total:>9} {poisoned:>9} {misled:>8} "
              f"{irrelevant:>11} {true_here:>10} {unmatched:>10}")
        summary[arm] = {
            "withdrew": total,
            "poisoned": poisoned,
            "misled_here": misled,
            "irrelevant": irrelevant,
            "true_here": true_here,
            "unmatched": unmatched,
        }

    print("\n=== Precision of each withdrawal rule ===")
    print("Justified = poisoned, or it really did mislead this episode.")
    print("Unjustified = irrelevant to the episode, or correct for it.\n")
    for arm, counts in summary.items():
        total = counts["withdrew"]
        if not total:
            print(f"  {arm:<22} withdrew nothing")
            continue
        justified = counts["poisoned"] + counts["misled_here"]
        unjustified = counts["irrelevant"] + counts["true_here"]
        print(f"  {arm:<22} {justified}/{total} = {justified / total:.0%} justified, "
              f"{unjustified} unjustified "
              f"({counts['irrelevant']} irrelevant, {counts['true_here']} true here)")

    print("\n=== Correct memory reaching the prompt, by third ===")
    per_arm: dict[str, list[dict]] = defaultdict(list)
    for d in decisions:
        per_arm[d["arm"]].append(d)
    print(f"{'arm':<22} {'1st':>7} {'2nd':>7} {'3rd':>7} {'change':>9}")
    print("-" * 60)
    for arm in sorted(per_arm):
        per_seed: dict[int, list[dict]] = defaultdict(list)
        for d in per_arm[arm]:
            per_seed[d["seed"]].append(d)
        buckets: list[list[float]] = [[], [], []]
        for rows in per_seed.values():
            ordered = sorted(rows, key=lambda r: r["index"])
            cut = max(1, len(ordered) // 3)
            for bucket, slice_ in zip(
                buckets, (ordered[:cut], ordered[cut : 2 * cut], ordered[-cut:])
            ):
                bucket.extend(1.0 if r["shown_right"] > 0 else 0.0 for r in slice_)
        first, middle, last = (stats.mean(b) if b else 0.0 for b in buckets)
        print(f"{arm:<22} {first:>6.0%} {middle:>6.0%} {last:>6.0%} "
              f"{last - first:>+8.1%}")

    print("\n=== Decomposing success into coverage and guessing ===")
    print("Each arm's success is P(a correct memory arrived) x P(right | it did)")
    print("plus P(none arrived) x P(right | none). The second term is the model")
    print("guessing from six options, and it is why a stripped store still scores")
    print("above zero - so success does NOT track coverage one-for-one, and the")
    print("plain ratio of the two is misleading for exactly the arms that strip the")
    print("store. The column that matters is `from memory`: the share of an arm's")
    print("success that a memory actually supplied.\n")
    print(f"{'arm':<22} {'success':>8} {'coverage':>9} {'P|right':>8} "
          f"{'P|none':>7} {'from memory':>12}")
    print("-" * 72)
    pairs: list[tuple[float, float]] = []
    for arm in sorted(per_arm):
        rows = per_arm[arm]
        success = stats.mean([1.0 if r["success"] else 0.0 for r in rows])
        with_right = [1.0 if r["success"] else 0.0 for r in rows if r["shown_right"] > 0]
        without = [1.0 if r["success"] else 0.0 for r in rows if r["shown_right"] == 0]
        coverage = len(with_right) / len(rows) if rows else 0.0
        p_right = stats.mean(with_right) if with_right else float("nan")
        p_none = stats.mean(without) if without else float("nan")
        from_memory = (
            (coverage * p_right) / success if success > 0 and with_right else 0.0
        )
        pairs.append((coverage, success))
        right_cell = f"{p_right:>8.0%} " if with_right else f"{'n/a':>8} "
        none_cell = f"{p_none:>7.0%} " if without else f"{'n/a':>7} "
        print(f"{arm:<22} {success:>8.0%} {coverage:>9.0%} "
              + right_cell + none_cell + f"{from_memory:>12.0%}")

    usable = [(c, s) for c, s in pairs if c > 0]
    if len(usable) >= 3:
        from .phase_c import spearman

        rho = spearman([c for c, _ in usable], [s for _, s in usable])
        print(f"\n  coverage vs success, rank correlation across arms: "
              f"{rho:+.3f} on {len(usable)} arms")
        print("  High means the arms are ordered by coverage and by nothing else,")
        print("  which is the claim worth stating precisely rather than loosely.")

    print("\n=== Conditional on a correct memory being present ===")
    print(f"{'arm':<22} {'had right':>11} {'n':>5} {'had none':>10} {'n':>5}")
    print("-" * 58)
    for arm in sorted(per_arm):
        rows = per_arm[arm]
        with_right = [1.0 if r["success"] else 0.0 for r in rows if r["shown_right"] > 0]
        without = [1.0 if r["success"] else 0.0 for r in rows if r["shown_right"] == 0]
        print(f"{arm:<22} {stats.mean(with_right):>11.0%} {len(with_right):>5} "
              f"{stats.mean(without):>10.0%} {len(without):>5}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
