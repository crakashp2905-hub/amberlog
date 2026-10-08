"""Read Phase A's per-decision record and test the mechanism, not just the score.

The arm table says *what* happened. This says *why*, and it exists because the
first registered run showed the two arms that withdraw memories on failure
collapsing to barely above having no memory at all — and a collapse like that is
either a real dynamic or a harness bug, which the summary numbers cannot tell
apart.

The hypothesis to test is **over-pruning**: "withdraw whatever was in context
when the episode failed" also withdraws *correct* memories that merely happened
to be present while a different one did the misleading. If that is what is
happening, then for the withdrawing arms the number of correct memories reaching
the prompt should fall over the run, while an arm that never withdraws anything
holds steady over the same episodes and the same released corpus.

**Why `store_size` is not used here.** It means different things per arm: the
vector arms record the eligible set after deletions, the fabric arms record how
many lessons have been *admitted*, which never falls when one is quarantined.
That inconsistency was noticed with the registered run already in flight, and
changing it mid-run would have invalidated the run, so it is left alone and
unused. `shown_right` is the better measure anyway — it counts what actually
reached the prompt, which is the thing that can affect an answer.

    python -m experiments.phase_a_analyse research/results/phase-a-decisions.json
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Sequence

from . import stats

WITHDRAWING = ("shared_memory_decay", "fabric", "fabric_causal")


def load(path: str) -> list[dict]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return data["decisions"]


def by_arm(decisions: Sequence[dict]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = defaultdict(list)
    for decision in decisions:
        out[decision["arm"]].append(decision)
    return out


def thirds(rows: Sequence[dict], field: str) -> tuple[float, float, float]:
    """Mean of `field` over the first, middle and final third of each seed's
    episode sequence. Grouped per seed first: pooling across seeds and then
    cutting would mix episode 0 of one seed with episode 23 of another."""
    per_seed: dict[int, list[dict]] = defaultdict(list)
    for row in rows:
        per_seed[row["seed"]].append(row)
    buckets: list[list[float]] = [[], [], []]
    for seed_rows in per_seed.values():
        ordered = sorted(seed_rows, key=lambda r: r["index"])
        cut = max(1, len(ordered) // 3)
        for bucket, slice_ in zip(
            buckets, (ordered[:cut], ordered[cut : 2 * cut], ordered[-cut:])
        ):
            bucket.extend(float(r[field]) for r in slice_)
    return tuple(stats.mean(b) if b else 0.0 for b in buckets)  # type: ignore[return-value]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Why Phase A came out as it did")
    parser.add_argument("path")
    args = parser.parse_args(argv)

    decisions = load(args.path)
    arms = by_arm(decisions)
    order = [a for a in (
        "no_memory", "local_rag", "shared_memory", "shared_memory_framed",
        "shared_memory_decay", "fabric", "fabric_causal", "oracle",
    ) if a in arms]

    print("=== Correct memories reaching the prompt, by third of the run ===")
    print("Over-pruning predicts a fall for the withdrawing arms and a flat line")
    print("for the arms that never withdraw anything.\n")
    print(f"{'arm':<22} {'1st':>7} {'2nd':>7} {'3rd':>7} {'change':>9}  withdraws")
    print("-" * 70)
    for arm in order:
        first, middle, last = thirds(arms[arm], "shown_right")
        print(f"{arm:<22} {first:>7.2f} {middle:>7.2f} {last:>7.2f} "
              f"{last - first:>+9.2f}  {'yes' if arm in WITHDRAWING else ''}")

    print("\n=== Wrong memories reaching the prompt, by third ===")
    print("Withdrawal is supposed to remove these. If it removes the correct ones")
    print("faster, it is working against itself.\n")
    print(f"{'arm':<22} {'1st':>7} {'2nd':>7} {'3rd':>7} {'change':>9}")
    print("-" * 60)
    for arm in order:
        first, middle, last = thirds(arms[arm], "shown_wrong")
        print(f"{arm:<22} {first:>7.2f} {middle:>7.2f} {last:>7.2f} {last - first:>+9.2f}")

    print("\n=== Memories reaching the prompt at all, by third ===")
    print("The store emptying out is the cruder version of the same story.\n")
    print(f"{'arm':<22} {'1st':>7} {'2nd':>7} {'3rd':>7} {'change':>9}")
    print("-" * 60)
    for arm in order:
        rows = [{**r, "n_shown": len(r["shown"])} for r in arms[arm]]
        first, middle, last = thirds(rows, "n_shown")
        print(f"{arm:<22} {first:>7.2f} {middle:>7.2f} {last:>7.2f} {last - first:>+9.2f}")

    print("\n=== Success by third ===")
    print(f"{'arm':<22} {'1st':>7} {'2nd':>7} {'3rd':>7} {'change':>9}")
    print("-" * 60)
    for arm in order:
        rows = [{**r, "ok": 1.0 if r["success"] else 0.0} for r in arms[arm]]
        first, middle, last = thirds(rows, "ok")
        print(f"{arm:<22} {first:>7.0%} {middle:>7.0%} {last:>7.0%} {last - first:>+9.1%}")

    print("\n=== Exception sites versus base sites ===")
    print("The exception site is where a lesson from elsewhere is actively wrong.")
    print("An arm that only wins on base sites has not solved the stated problem.\n")
    print(f"{'arm':<22} {'base':>8} {'exception':>11} {'gap':>8}")
    print("-" * 52)
    for arm in order:
        base = [1.0 if r["success"] else 0.0 for r in arms[arm] if not r["is_exception"]]
        exc = [1.0 if r["success"] else 0.0 for r in arms[arm] if r["is_exception"]]
        print(f"{arm:<22} {stats.mean(base):>8.0%} {stats.mean(exc):>11.0%} "
              f"{stats.mean(exc) - stats.mean(base):>+8.1%}")

    print("\n=== Does a correct memory in context actually get used? ===")
    print("Conditional success given at least one correct memory was shown, and")
    print("given none was. Separates selection failure from the model ignoring it.\n")
    print(f"{'arm':<22} {'had right':>11} {'n':>5} {'had none':>10} {'n':>5}")
    print("-" * 58)
    for arm in order:
        with_right = [1.0 if r["success"] else 0.0 for r in arms[arm] if r["shown_right"] > 0]
        without = [1.0 if r["success"] else 0.0 for r in arms[arm] if r["shown_right"] == 0]
        print(f"{arm:<22} {stats.mean(with_right):>11.0%} {len(with_right):>5} "
              f"{stats.mean(without):>10.0%} {len(without):>5}")

    print("\n=== Cost ===")
    print(f"{'arm':<22} {'tokens':>8} {'memory ms':>11} {'model ms':>10}")
    print("-" * 54)
    for arm in order:
        cell = arms[arm]
        print(f"{arm:<22} {stats.mean([r['tokens'] for r in cell]):>8.0f} "
              f"{stats.mean([r['memory_ms'] for r in cell]):>11.2f} "
              f"{stats.mean([r['model_ms'] for r in cell]):>10.0f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
