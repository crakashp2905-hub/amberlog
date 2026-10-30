"""S4 -- TransferSim: can a recipient learn which imports to trust from its own outcomes?

Deterministic given the seed, no model. A recipient store works in 3
contexts. It holds imported lessons from 4 senders whose contexts overlap
with its own to different degrees. Each of 20 faults has two lessons from two
different senders. Each lesson has a quality q (U(0.6, 1.0)), which is the
score its sender measured at home. It is **valid** in recipient context c
with probability q * overlap(sender, c), drawn once per seed. Relying on a
valid lesson succeeds with p 0.95, on an invalid one with p 0.05; the local
default action succeeds with p 0.5.

**The context changes.** Halfway through, every lesson's validity in context 2
is drawn again (new equipment there).

Per episode, a random (context, fault). Arms:
  trust_none        always the local default
  trust_all         rely on the most relevant import (the store's top-1)
  sender_value      rely on the import its sender scored highest
  recipient_trust   S4: `trust.TransferTrust`, Thompson sampling over a Beta
                    posterior per (origin store, context) of the recipient's
                    own verified outcomes when it relied on that origin,
                    against its own default
  recipient_local   per-memory: TransferGatePolicy + DR estimator, context-specific
  recipient_pooled  the same, context-blind (episodes carry no context)
  oracle            rely on a valid import if there is one, else the default

Lessons are written at four real sender stores and imported by federation.
The fabric arms run on a real recipient MemoryFabric: retrieval logs exposure
with propensities, the agent cites what it relied on, and a separate
verifier records the outcome.

    python -m experiments.s4_transfer_sim --seeds 10 --out s4.json
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

CONTEXTS = 3
FAULTS = 20
EPISODES = 600
DRIFT_AT = EPISODES // 2
OVERLAP = [[0.95, 0.9, 0.85], [0.9, 0.3, 0.2], [0.2, 0.9, 0.3], [0.3, 0.2, 0.9]]
P_VALID, P_INVALID, P_DEFAULT = 0.95, 0.05, 0.5
ARMS = ("trust_none", "trust_all", "sender_value", "recipient_trust", "recipient_local",
        "recipient_pooled", "oracle")
SPLITS = {"dev": range(100, 103), "test": range(0, 10)}


def world(seed: int) -> dict[str, Any]:
    rng = random.Random(seed)
    lessons = []
    for f in range(FAULTS):
        for s in rng.sample(range(4), 2):
            q = rng.uniform(0.6, 1.0)
            lessons.append({"fault": f, "sender": s, "q": q, "action": rng.randint(1, 9),
                            "valid": [rng.random() < q * OVERLAP[s][c] for c in range(CONTEXTS)]})
    drifted = [rng.random() < x["q"] * OVERLAP[x["sender"]][2] for x in lessons]
    plan = [(rng.randrange(CONTEXTS), rng.randrange(FAULTS)) for _ in range(EPISODES)]
    return {"lessons": lessons, "drifted": drifted, "plan": plan}


def valid(w: dict[str, Any], i: int, c: int, t: int) -> bool:
    if c == 2 and t >= DRIFT_AT:
        return w["drifted"][i]
    return w["lessons"][i]["valid"][c]


def text(lesson: dict[str, Any]) -> str:
    return (f"Fault code F{lesson['fault']:02d} alarm: apply corrective action "
            f"A{lesson['action']} (sender S{lesson['sender']}).")


def query(fault: int) -> str:
    return f"Fault code F{fault:02d} alarm"


class FabricArm:
    def __init__(self, seed: int, w: dict[str, Any], *, policy: str, contextual: bool) -> None:
        from memory_fabric import MemoryFabric
        from memory_fabric.exposure import AlwaysExposePolicy, TopKPolicy, TransferGatePolicy
        from memory_fabric.federation import offer
        from memory_fabric.governance.firewall import (Firewall, rule_capabilities_must_be_granted,
                                                       rule_must_be_active,
                                                       rule_restricted_stays_private)
        from memory_fabric.model import Scope

        exposure = {"gate": TransferGatePolicy(0.2), "top_k": TopKPolicy("relevance"),
                    "trust": AlwaysExposePolicy()}[policy]
        rules = (rule_restricted_stays_private, rule_must_be_active,
                 rule_capabilities_must_be_granted)
        self.fab = MemoryFabric(":memory:", auto_activate=True, estimator="dr",
                                exposure_policy=exposure, seed=seed,
                                firewall=Firewall(rules=rules))
        senders = [MemoryFabric(":memory:", auto_activate=True, firewall=Firewall(rules=rules))
                   for _ in range(4)]
        self.ids = []
        for lesson in w["lessons"]:
            src = senders[lesson["sender"]]
            mid = src.remember(f"tech-s{lesson['sender']}", text(lesson), scope="team")
            src.share(mid, Scope.FEDERATED, actor="op")
            result = offer(src, mid, self.fab, recipient_agent="agent", activate=True)
            assert result.imported_memory_id, result.reasons
            self.ids.append(result.imported_memory_id)
        for src in senders:
            src.close()
        self.policy, self.contextual = policy, contextual
        self.index = {m: i for i, m in enumerate(self.ids)}
        self.w = w
        self.rng = random.Random(seed * 17 + 3)

    def choose(self, t: int, c: int, f: int) -> tuple[int | None, str]:
        from memory_fabric.trust import TransferTrust

        context = {"ctx": c} if self.contextual else None
        episode = self.fab.start_episode("agent", f"t{t}", context=context)
        result = self.fab.retrieve("agent", query(f), context=context,
                                   k=2 if self.policy == "trust" else 1,
                                   episode_id=episode.id,
                                   group_by_source_root=False, expand_lineage=0)
        mine = [m.id for m in result.exposed
                if m.id in self.index and self.w["lessons"][self.index[m.id]]["fault"] == f]
        if self.policy == "trust":
            chosen = TransferTrust(self.fab).choose(mine, context, self.rng)
        else:
            chosen = mine[0] if mine else None
        if chosen is not None:
            self.fab.cite("agent", episode.id, chosen)
        return (self.index[chosen] if chosen is not None else None), episode.id

    def record(self, episode_id: str, outcome: float) -> None:
        self.fab.record_outcome(episode_id, outcome, verifier_id="env")
        self.fab.end_episode(episode_id)


def run_seed(seed: int) -> dict[str, Any]:
    w = world(seed)
    rng = random.Random(seed * 13 + 5)
    by_fault: dict[int, list[int]] = {}
    for i, lesson in enumerate(w["lessons"]):
        by_fault.setdefault(lesson["fault"], []).append(i)
    fabric = {"recipient_trust": FabricArm(seed, w, policy="trust", contextual=True),
              "recipient_pooled": FabricArm(seed, w, policy="gate", contextual=False),
              "recipient_local": FabricArm(seed, w, policy="gate", contextual=True),
              "trust_all": FabricArm(seed, w, policy="top_k", contextual=True)}
    rows: dict[str, list[tuple[int, int, int]]] = {a: [] for a in ARMS}  # (success, harmful, phase)
    for t, (c, f) in enumerate(w["plan"]):
        draw = rng.random()  # one draw per episode, shared by every arm (paired)
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
                p, harmful = P_DEFAULT, 0
            elif valid(w, pick, c, t):
                p, harmful = P_VALID, 0
            else:
                p, harmful = P_INVALID, 1
            success = int(draw < p)
            if episode is not None:
                fabric[arm].record(episode, float(success))
            rows[arm].append((success, harmful, int(t >= DRIFT_AT)))
    for arm in fabric.values():
        arm.fab.close()
    return {"seed": seed, "rows": rows}


def summarise(seeds: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for arm in ARMS:
        rows = [r for s in seeds for r in s["rows"][arm]]
        late = [r for r in rows if r[2] == 1]
        early = [r for r in rows if r[2] == 0]
        out[arm] = {
            "success": round(statistics.mean(r[0] for r in rows), 4),
            "harmful_reliance": round(statistics.mean(r[1] for r in rows), 4),
            "success_before_drift": round(statistics.mean(r[0] for r in early), 4),
            "success_after_drift": round(statistics.mean(r[0] for r in late), 4),
            "harmful_after_drift": round(statistics.mean(r[1] for r in late), 4),
        }
    return out


def paired(seeds: list[dict[str, Any]], arm: str, base: str, rng: random.Random,
           draws: int = 2000) -> dict[str, float]:
    diffs = [a[0] - b[0] for s in seeds for a, b in zip(s["rows"][arm], s["rows"][base])]
    n = len(diffs)
    boots = sorted(sum(diffs[rng.randrange(n)] for _ in range(n)) / n for _ in range(draws))
    return {"diff": round(sum(diffs) / n, 4), "ci_low": round(boots[int(0.025 * draws)], 4),
            "ci_high": round(boots[int(0.975 * draws)], 4),
            "discordance": round(sum(d != 0 for d in diffs) / n, 4), "n_pairs": n}


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
    baselines = ["trust_none", "trust_all", "sender_value"]
    best = max(baselines, key=lambda a: arms[a]["success"])
    result: dict[str, Any] = {
        "experiment": "s4-transfer-sim", "split": args.split,
        "commit": subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True,
                                 text=True).stdout.strip(),
        "seeds": len(seeds), "episodes_per_seed": EPISODES, "arms": arms, "best_baseline": best,
        "no_arm_beats_the_oracle": all(arms[a]["success"] <= arms["oracle"]["success"]
                                       for a in ARMS),
        "trust_vs_best": paired(seeds, "recipient_trust", best, random.Random(3)),
        "local_vs_best": paired(seeds, "recipient_local", best, random.Random(4)),
        "local_vs_pooled": paired(seeds, "recipient_local", "recipient_pooled", random.Random(5)),
    }
    if args.split == "test":
        from memeval import Registration

        verdict = Registration(hypothesis="S4", metric="success", mechanism="recipient_trust",
                               baselines=baselines, ceiling="oracle", seeds_required=10).evaluate(
            arms, seeds=len(seeds), n_pairs=result["trust_vs_best"]["n_pairs"],
            discordance=result["trust_vs_best"]["discordance"])
        result["verdict"] = verdict.to_json()
    if args.out:
        Path(args.out).write_text(json.dumps({**result, "per_seed": seeds}) + "\n",
                                  encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
