"""T1 -- learned staleness: does trust that learns how fast to forget, per context, decide better?

S4's TransferSim, with one change to the world: the contexts drift at
**different rates**. That is what makes "adaptive" a question at all:

  context 0  never changes
  context 1  every 120 episodes, which sender is reliable here is reshuffled
  context 2  reshuffled once, at episode 450

900 episodes per seed. Arms, all on a real recipient store:
  trust_none                    the local default
  sender_value                  the import its sender scored highest
  trust_cumulative              S4's TransferTrust, no forgetting (the product as shipped)
  trust_fixed                   TransferTrust(half_life=60), the same everywhere
  invalidate_on_contradiction   Zep-style: when a cell's 3 latest outcomes all
                                contradict its earlier majority, the earlier
                                ones are dropped
  trust_adaptive                TransferTrust(adaptive=True): half-life chosen per context
                                by prequential log score (T1)
  oracle                        a valid import if one exists now, else the default

    python -m experiments.t1_staleness --split test --out t1.json
"""

from __future__ import annotations

import argparse
import json
import random
import statistics
import subprocess
import sys
from pathlib import Path
from typing import Any, Sequence

from experiments import s4_transfer_sim as s4

EPISODES = 900
ARMS = ("trust_none", "sender_value", "trust_cumulative", "trust_fixed",
        "invalidate_on_contradiction", "trust_adaptive", "oracle")
SPLITS = {"dev": range(100, 103), "test": range(0, 10)}


def world(seed: int) -> dict[str, Any]:
    rng = random.Random(seed)
    base = s4.world(seed)
    lessons = base["lessons"]
    epochs: dict[int, list[list[bool]]] = {}

    def draw(c: int) -> list[bool]:
        # The change is in *who* is reliable here: the senders' overlaps with
        # this context are permuted. Redrawing each lesson at the same rates
        # (the first dev pilot) leaves every sender's reliability unchanged in
        # expectation, so there is nothing for trust to forget.
        overlap = [s4.OVERLAP[s][c] for s in range(4)]
        rng.shuffle(overlap)
        return [rng.random() < x["q"] * overlap[x["sender"]] for x in lessons]

    epochs[1] = [[x["valid"][1] for x in lessons]] + [draw(1) for _ in range(EPISODES // 120)]
    epochs[2] = [[x["valid"][2] for x in lessons], draw(2)]
    plan = [(rng.randrange(s4.CONTEXTS), rng.randrange(s4.FAULTS)) for _ in range(EPISODES)]
    return {"lessons": lessons, "epochs": epochs, "plan": plan}


def valid(w: dict[str, Any], i: int, c: int, t: int) -> bool:
    if c == 1:
        return w["epochs"][1][t // 120][i]
    if c == 2:
        return w["epochs"][2][int(t >= 450)][i]
    return w["lessons"][i]["valid"][0]


class TrustArm(s4.FabricArm):
    """S4's recipient store, choosing with a configurable TransferTrust."""

    def __init__(self, seed: int, w: dict[str, Any], **trust: Any) -> None:
        super().__init__(seed, w, policy="trust", contextual=True)
        self.trust_args = trust
        self.invalidate = trust.pop("invalidate", False)
        self.cells: dict[tuple[str, int], list[float]] = {}

    def choose(self, t: int, c: int, f: int) -> tuple[int | None, str]:
        from amberlog.trust import DEFAULT, Beta, TransferTrust, origin_of

        context = {"ctx": c}
        episode = self.fab.start_episode("agent", f"t{t}", context=context)
        result = self.fab.retrieve("agent", s4.query(f), context=context, k=2,
                                   episode_id=episode.id, group_by_source_root=False,
                                   expand_lineage=0)
        mine = [m.id for m in result.exposed
                if m.id in self.index and self.w["lessons"][self.index[m.id]]["fault"] == f]
        if self.invalidate:
            def beta(cell: str) -> Beta:
                xs = self.cells.get((cell, c), [])
                return Beta(1.0 + sum(xs), 1.0 + len(xs) - sum(xs))
            best, best_draw = None, beta(DEFAULT).sample(self.rng)
            for m in mine:
                draw = beta(origin_of(self.fab, m) or DEFAULT).sample(self.rng)
                if draw > best_draw:
                    best, best_draw = m, draw
            chosen = best
            self._pending = (origin_of(self.fab, chosen) if chosen else DEFAULT, c)
        else:
            chosen = TransferTrust(self.fab, **self.trust_args).choose(mine, context, self.rng)
        if chosen is not None:
            self.fab.cite("agent", episode.id, chosen)
        return (self.index[chosen] if chosen is not None else None), episode.id

    def record(self, episode_id: str, outcome: float) -> None:
        super().record(episode_id, outcome)
        if self.invalidate:
            xs = self.cells.setdefault(self._pending, [])
            xs.append(outcome)
            if len(xs) >= 6:
                earlier, latest = xs[:-3], xs[-3:]
                majority = sum(earlier) / len(earlier) >= 0.5
                if all((x >= 0.5) != majority for x in latest):
                    del xs[:-3]  # invalidate on contradiction


def run_seed(seed: int) -> dict[str, Any]:
    w = world(seed)
    rng = random.Random(seed * 13 + 5)
    by_fault: dict[int, list[int]] = {}
    for i, lesson in enumerate(w["lessons"]):
        by_fault.setdefault(lesson["fault"], []).append(i)
    fabric = {"trust_cumulative": TrustArm(seed, w),
              "trust_fixed": TrustArm(seed, w, half_life=60.0),
              "invalidate_on_contradiction": TrustArm(seed, w, invalidate=True),
              "trust_adaptive": TrustArm(seed, w, adaptive=True)}
    rows: dict[str, list[tuple[int, int, int]]] = {a: [] for a in ARMS}
    for t, (c, f) in enumerate(w["plan"]):
        draw = rng.random()
        for arm in ARMS:
            episode = None
            if arm == "trust_none":
                pick = None
            elif arm == "sender_value":
                pick = max(by_fault[f], key=lambda i: w["lessons"][i]["q"])
            elif arm == "oracle":
                good = [i for i in by_fault[f] if valid(w, i, c, t)]
                pick = good[0] if good else None
            else:
                pick, episode = fabric[arm].choose(t, c, f)
            if pick is None:
                p, harmful = s4.P_DEFAULT, 0
            elif valid(w, pick, c, t):
                p, harmful = s4.P_VALID, 0
            else:
                p, harmful = s4.P_INVALID, 1
            success = int(draw < p)
            if episode is not None:
                fabric[arm].record(episode, float(success))
            rows[arm].append((success, harmful, c))
    chosen = {}
    for name, arm in fabric.items():
        if name == "trust_adaptive":
            from amberlog.trust import TransferTrust

            chosen = TransferTrust(arm.fab, adaptive=True).chosen
        arm.fab.close()
    return {"seed": seed, "rows": rows, "adaptive_half_lives": chosen}


def summarise(seeds: list[dict[str, Any]]) -> dict[str, Any]:
    out = {}
    for arm in ARMS:
        rows = [r for s in seeds for r in s["rows"][arm]]
        out[arm] = {"success": round(statistics.mean(r[0] for r in rows), 4),
                    "harmful_reliance": round(statistics.mean(r[1] for r in rows), 4),
                    "by_context": {c: round(statistics.mean(r[0] for r in rows if r[2] == c), 4)
                                   for c in range(s4.CONTEXTS)}}
    return out


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--split", choices=sorted(SPLITS), default="dev")
    parser.add_argument("--out")
    args = parser.parse_args(argv)
    seeds = []
    for seed in SPLITS[args.split]:
        seeds.append(run_seed(seed))
        print(f"  seed {seed} done", file=sys.stderr, flush=True)
    arms = summarise(seeds)
    baselines = ["trust_none", "sender_value", "trust_cumulative", "trust_fixed",
                 "invalidate_on_contradiction"]
    best = max(baselines, key=lambda a: arms[a]["success"])
    result: dict[str, Any] = {
        "experiment": "t1-staleness", "split": args.split,
        "commit": subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True,
                                 text=True).stdout.strip(),
        "seeds": len(seeds), "arms": arms, "best_baseline": best,
        "no_arm_beats_the_oracle": all(arms[a]["success"] <= arms["oracle"]["success"] for a in ARMS),
        "adaptive_vs_best": s4.paired(seeds, "trust_adaptive", best, random.Random(3)),
        "adaptive_half_lives": [s["adaptive_half_lives"] for s in seeds],
    }
    if args.split == "test":
        from memeval import Registration

        verdict = Registration(hypothesis="T1", metric="success", mechanism="trust_adaptive",
                               baselines=baselines, ceiling="oracle", seeds_required=10).evaluate(
            arms, seeds=len(seeds), n_pairs=result["adaptive_vs_best"]["n_pairs"],
            discordance=result["adaptive_vs_best"]["discordance"])
        result["verdict"] = verdict.to_json()
    if args.out:
        Path(args.out).write_text(json.dumps({**result, "per_seed": seeds}) + "\n",
                                  encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
