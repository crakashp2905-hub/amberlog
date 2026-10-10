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
    print("`poisoned` was wrong even at its own site: withdrawing it is a clean win.")
    print("`misleading here` was right where written and wrong in the episode that")
    print("triggered the withdrawal: defensible. `true here` was right for that very")
    print("episode: pure loss, and the number that matters.\n")
    print(f"{'arm':<22} {'withdrew':>9} {'poisoned':>9} {'misleading':>11} "
          f"{'true here':>10} {'unmatched':>10}")
    print("-" * 76)
    summary: dict[str, dict[str, int]] = {}
    for arm in sorted(by_arm):
        poisoned = misleading = true_here = unmatched = 0
        for w in by_arm[arm]:
            if not w["was_correct"]:
                poisoned += 1
                continue
            episode = episode_of.get((w["arm"], w["seed"], w["index"]))
            if episode is None:
                unmatched += 1
            elif w["asserted"] != episode["correct"]:
                misleading += 1
            else:
                true_here += 1
        total = len(by_arm[arm])
        print(f"{arm:<22} {total:>9} {poisoned:>9} {misleading:>11} "
              f"{true_here:>10} {unmatched:>10}")
        summary[arm] = {
            "withdrew": total,
            "poisoned": poisoned,
            "misleading_here": misleading,
            "true_here": true_here,
            "unmatched": unmatched,
        }

    print("\n=== Precision of each withdrawal rule ===")
    print("Share of withdrawals that removed something genuinely unhelpful in the")
    print("episode that triggered them. This is the question attribution exists to")
    print("answer, and the one `was_correct` alone cannot.\n")
    for arm, counts in summary.items():
        total = counts["withdrew"]
        if not total:
            print(f"  {arm:<22} withdrew nothing")
            continue
        justified = counts["poisoned"] + counts["misleading_here"]
        print(f"  {arm:<22} {justified}/{total} = {justified / total:.0%} justified, "
              f"{counts['true_here']} pure losses")

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
