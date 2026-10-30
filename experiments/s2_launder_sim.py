"""S2 -- LaunderSim: is a second report a second source?

Deterministic, no model. Real stores (one deciding store D plus two peers),
real retrieval, real exposure logging, and real federation for the
cross-store families. Each seed writes 7 families x 3 clusters. A cluster is
the reports of one equipment fault that reach D. The question per cluster is
the one corroboration asks: do these reports amount to at least two
independent sources?

Families (truth: number of independent observers):
  laundering_local        1 observer; 2 copies written in D by agents shown it  -> 1
  laundering_cross_store  1 observer at s0; a copy written at s1 by an agent
                          shown the import; both shared to D                     -> 1
  collusion               1 observer; a copy written by an agent told off-store
                          (no exposure anywhere)                                  -> 1
  independent_similar     2 observers never shown each other, same template bank -> 2
  independent_cross_store 2 observers at different stores, both shared to D      -> 2
  exposed_but_independent 2 observers; the second was shown the first's report
                          and then made and wrote its own observation            -> 2
  independent_plus_copy   2 observers plus a copy written from one of them       -> 2

Arms count sources:
  count_all    every report is a source
  provenance   distinct original (`independence.global_ref`: lineage, recognised
               copies, federation root) -- the product as it ships
  similarity   provenance, then near-duplicates joined (content-term Jaccard >= tau,
               tau tuned on the dev seeds) -- a deduplicating store
  exposure     `independence.Independence.sources` -- the S2 mechanism
  oracle       the true count

    python -m experiments.s2_launder_sim --split dev --out s2-dev.json
    python -m experiments.s2_launder_sim --split test --tau overlap@0.80 --out s2.json
"""

from __future__ import annotations

import argparse
import json
import random
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

FAMILIES = ("laundering_local", "laundering_cross_store", "collusion", "independent_similar",
            "independent_cross_store", "exposed_but_independent", "independent_plus_copy")
TRUTH = {"laundering_local": 1, "laundering_cross_store": 1, "collusion": 1,
         "independent_similar": 2, "independent_cross_store": 2, "exposed_but_independent": 2,
         "independent_plus_copy": 2}
CLUSTERS_PER_FAMILY = 3
ARMS = ("count_all", "provenance", "similarity", "exposure", "oracle")
SPLITS = {"dev": range(100, 110), "test": range(0, 20)}
TAUS = [round(0.05 * i, 2) for i in range(2, 19)]

SITES = ["Arden", "Bexley", "Calder", "Dunmore", "Elstow", "Fenwick", "Garth", "Holme",
         "Ickford", "Jarrow", "Kelso", "Lydd", "Marske", "Nairn", "Oakham", "Penrith",
         "Quorn", "Rhyl", "Selby", "Thame", "Ulverston", "Ventnor", "Wigton", "Yarm"]
KINDS = [("pump", "P"), ("compressor", "C"), ("valve", "V"), ("fan", "F"), ("motor", "M")]
FAULTS = [
    ("leaking oil from its seal", "has a failed seal and is losing oil", "seal leak"),
    ("running hot", "is overheating", "overheating"),
    ("vibrating badly", "shows heavy vibration", "vibration"),
    ("tripping its breaker", "keeps tripping the breaker", "breaker trips"),
    ("making a grinding noise", "is grinding audibly", "grinding"),
    ("losing pressure", "cannot hold pressure", "pressure loss"),
]
READINGS = [("temperature", "C", 60, 110), ("vibration", "mm/s", 4, 20),
            ("pressure", "bar", 2, 9), ("current", "A", 10, 40)]

OBSERVED = [
    "{equip} at {site} is {fault}; logged {time}, {reading}.",
    "Walk-round {site}, {time}: {equip} {fault}. Reading {reading}.",
    "Noticed {equip} {fault} during the {time} round at {site} ({reading}).",
    "{site}: {equip} {fault}. Measured {reading} at {time}.",
    "At {time} I found {equip} at {site} {fault}, {reading}.",
]
REWORDED = [
    "Reported: {site} {equip} {syn} ({reading}, {time}).",
    "{equip} ({site}) {syn}, per the {time} log; {reading}.",
    "There is a problem at {site}: {equip} {syn}. Seen at {time}, {reading}.",
    "{equip}, {site} site, {syn} -- {reading} recorded {time}.",
]
SUMMARY = ["{equip} at {site}: {short}.", "{site} {equip} {short} reported.",
           "Summary: {short} on {equip}, {site}."]


@dataclass
class Event:
    site: str
    equip: str
    fault: tuple[str, str, str]
    reading: tuple[str, str, int, int]


@dataclass
class Report:
    text: str
    details: dict[str, str]


def observe(rng: random.Random, e: Event) -> Report:
    name, unit, lo, hi = e.reading
    details = {"time": f"{rng.randint(5, 22):02d}{rng.choice(['00', '15', '30', '45'])}",
               "reading": f"{name} {rng.randint(lo, hi)} {unit}"}
    text = rng.choice(OBSERVED).format(equip=e.equip, site=e.site, fault=e.fault[0], **details)
    return Report(text, details)


def launder(rng: random.Random, e: Event, source: Report) -> Report:
    """A copy written from a report: its facts and details, never new ones."""
    form = rng.random()
    if form < 0.2:
        return Report("[filed copy] " + source.text, source.details)
    if form < 0.5:
        return Report(rng.choice(SUMMARY).format(equip=e.equip, site=e.site, short=e.fault[2]), {})
    text = rng.choice(REWORDED).format(equip=e.equip, site=e.site, syn=e.fault[1], **source.details)
    return Report(text, source.details)


class World:
    def __init__(self, seed: int) -> None:
        from memory_fabric import MemoryFabric
        from memory_fabric.governance.firewall import (Firewall, rule_capabilities_must_be_granted,
                                                       rule_must_be_active,
                                                       rule_restricted_stays_private)

        rules = (rule_restricted_stays_private, rule_must_be_active,
                 rule_capabilities_must_be_granted)
        self.rng = random.Random(seed)
        self.s = {n: MemoryFabric(":memory:", firewall=Firewall(rules=rules), auto_activate=True)
                  for n in ("s0", "s1", "D")}
        self.agent = 0
        self.used: set[tuple[str, str]] = set()

    def new_agent(self) -> str:
        self.agent += 1
        return f"ag{self.agent}"

    def event(self) -> Event:
        while True:
            kind, letter = self.rng.choice(KINDS)
            e = Event(self.rng.choice(SITES), f"{kind} {letter}{self.rng.randint(1, 60)}",
                      self.rng.choice(FAULTS), self.rng.choice(READINGS))
            if (e.site, e.equip) not in self.used:
                self.used.add((e.site, e.equip))
                return e

    def write(self, store: str, report: Report, shown: str | None = None) -> str:
        """Write a report as a fresh agent; `shown` is a query it ran first."""
        agent = self.new_agent()
        fab = self.s[store]
        if shown is not None:
            fab.retrieve(agent, shown, k=3)
        return fab.remember(agent, report.text, scope="team")

    def to_d(self, store: str, memory_id: str) -> str:
        from memory_fabric.federation import offer
        from memory_fabric.model import Scope

        src = self.s[store]
        src.share(memory_id, Scope.FEDERATED, actor="op")
        result = offer(src, memory_id, self.s["D"], recipient_agent="intake", activate=True)
        assert result.accepted and result.imported_memory_id, result.reasons
        self.s["D"].share(result.imported_memory_id, Scope.TEAM, actor="op")
        return result.imported_memory_id

    def query(self, e: Event) -> str:
        return f"{e.equip} {e.site}"

    def cluster(self, family: str) -> list[str]:
        e = self.event()
        q = self.query(e)
        rng = self.rng
        if family == "laundering_local":
            a = observe(rng, e)
            ids = [self.write("D", a)]
            ids += [self.write("D", launder(rng, e, a), shown=q) for _ in range(2)]
            return ids
        if family == "laundering_cross_store":
            a = observe(rng, e)
            a0 = self.write("s0", a)
            a1 = self.to_s1(a0)
            self.s["s1"].share(a1, "team", actor="op")
            copy = self.write("s1", launder(rng, e, a), shown=q)
            return [self.to_d("s0", a0), self.to_d("s1", copy)]
        if family == "collusion":
            a = observe(rng, e)
            return [self.write("D", a), self.write("D", launder(rng, e, a))]
        if family == "independent_similar":
            return [self.write("D", observe(rng, e)), self.write("D", observe(rng, e))]
        if family == "independent_cross_store":
            return [self.to_d("s0", self.write("s0", observe(rng, e))),
                    self.to_d("s1", self.write("s1", observe(rng, e)))]
        if family == "exposed_but_independent":
            return [self.write("D", observe(rng, e)), self.write("D", observe(rng, e), shown=q)]
        if family == "independent_plus_copy":
            a, b = observe(rng, e), observe(rng, e)
            ids = [self.write("D", a), self.write("D", b)]
            return ids + [self.write("D", launder(rng, e, rng.choice([a, b])), shown=q)]
        raise ValueError(family)

    def to_s1(self, memory_id: str) -> str:
        from memory_fabric.federation import offer
        from memory_fabric.model import Scope

        self.s["s0"].share(memory_id, Scope.FEDERATED, actor="op")
        result = offer(self.s["s0"], memory_id, self.s["s1"], recipient_agent="intake",
                       activate=True)
        assert result.accepted and result.imported_memory_id, result.reasons
        return result.imported_memory_id


# --- the arms -----------------------------------------------------------------

MEASURES = ("jaccard", "overlap", "hashing_cosine")


def similarity(measure: str, a: str, b: str) -> float:
    """Three near-duplicate measures a deduplicating store might use.

    Content-term Jaccard, the overlap coefficient (|A n B| / min), and cosine
    over the product's hashing embedder. The measure and its threshold are
    both tuned on the dev seeds, so the baseline is the best of the three.
    """
    from memory_fabric.duplicates import terms
    from memory_fabric.vectors import HashingEmbedder, cosine

    if measure == "hashing_cosine":
        embedder = HashingEmbedder()
        return cosine(embedder.embed(a), embedder.embed(b))
    left, right = terms(a), terms(b)
    if not left or not right:
        return 0.0
    shared = len(left & right)
    if measure == "overlap":
        return shared / min(len(left), len(right))
    return shared / len(left | right)


def count_similarity(fab: Any, ids: Sequence[str], measure: str, tau: float) -> int:
    from memory_fabric.independence import global_ref

    parent = {m: m for m in ids}

    def find(m: str) -> str:
        while parent[m] != m:
            m = parent[m]
        return m

    for i, left in enumerate(ids):
        for right in ids[i + 1:]:
            if (global_ref(fab, left) == global_ref(fab, right)
                    or similarity(measure, fab.state.memories[left].content,
                                  fab.state.memories[right].content) >= tau):
                parent[find(left)] = find(right)
    return len({find(m) for m in ids})


def run_seed(seed: int, taus: Sequence[float]) -> list[dict[str, Any]]:
    from memory_fabric.independence import Independence, global_ref

    world = World(seed)
    written = []
    order = [f for f in FAMILIES for _ in range(CLUSTERS_PER_FAMILY)]
    world.rng.shuffle(order)
    for family in order:
        written.append((family, world.cluster(family)))
    fab = world.s["D"]
    ind = Independence(fab)
    rows = []
    for family, ids in written:
        counts: dict[str, Any] = {
            "count_all": len(ids),
            "provenance": len({global_ref(fab, m) for m in ids}),
            "exposure": len(ind.sources(ids)),
            "oracle": TRUTH[family],
            "similarity": {f"{m}@{t}": count_similarity(fab, ids, m, t)
                           for m in MEASURES for t in taus},
        }
        rows.append({"seed": seed, "family": family, "truth": TRUTH[family], "counts": counts,
                     "texts": [fab.state.memories[m].content for m in ids]})
    return rows


def decide(count: int) -> bool:
    return count >= 2


def correct(row: dict[str, Any], arm: str, tau: str | None) -> bool:
    count = row["counts"][arm]
    if arm == "similarity":
        count = count[tau]
    return decide(count) == decide(row["truth"])


def summarise(rows: list[dict[str, Any]], tau: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for arm in ARMS:
        ok = [correct(r, arm, tau) for r in rows]
        single = [r for r in rows if r["truth"] < 2]
        multi = [r for r in rows if r["truth"] >= 2]
        out[arm] = {
            "decision_accuracy": round(sum(ok) / len(ok), 4),
            "false_corroboration": round(sum(not correct(r, arm, tau) for r in single)
                                         / len(single), 4),
            "blocked_independent": round(sum(not correct(r, arm, tau) for r in multi)
                                         / len(multi), 4),
            "by_family": {f: round(sum(correct(r, arm, tau) for r in rows if r["family"] == f)
                                   / max(1, sum(r["family"] == f for r in rows)), 4)
                          for f in FAMILIES},
        }
    return out


def tune(rows: list[dict[str, Any]]) -> str:
    """The measure@threshold that maximises decision accuracy (ties: first listed, lowest)."""
    keys = [f"{m}@{t}" for m in MEASURES for t in TAUS]
    return max(keys, key=lambda k: (sum(correct(r, "similarity", k) for r in rows),
                                    -keys.index(k)))


def paired(rows: list[dict[str, Any]], arm: str, base: str, tau: str, rng: random.Random,
           draws: int = 4000) -> dict[str, float]:
    diffs = [int(correct(r, arm, tau)) - int(correct(r, base, tau)) for r in rows]
    n = len(diffs)
    boots = sorted(sum(diffs[rng.randrange(n)] for _ in range(n)) / n for _ in range(draws))
    return {"diff": round(sum(diffs) / n, 4), "ci_low": round(boots[int(0.025 * draws)], 4),
            "ci_high": round(boots[int(0.975 * draws)], 4),
            "discordance": round(sum(d != 0 for d in diffs) / n, 4), "n_pairs": n}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--split", choices=sorted(SPLITS), default="dev")
    parser.add_argument("--tau", help="similarity measure@threshold, e.g. overlap@0.8 "
                        "(default: tune on this split)")
    parser.add_argument("--out")
    args = parser.parse_args(argv)
    started = time.perf_counter()
    rows = [row for seed in SPLITS[args.split] for row in run_seed(seed, TAUS)]
    tau = args.tau if args.tau is not None else tune(rows)
    arms = summarise(rows, tau)
    baselines = ["count_all", "provenance", "similarity"]
    best = max(baselines, key=lambda a: arms[a]["decision_accuracy"])
    result: dict[str, Any] = {
        "experiment": "s2-launder-sim", "split": args.split,
        "commit": subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True,
                                 text=True).stdout.strip(),
        "seeds": len(SPLITS[args.split]), "clusters": len(rows), "tau": tau,
        "tau_source": "given" if args.tau is not None else f"tuned on {args.split}",
        "similarity_by_tau": {f"{m}@{t}": round(sum(correct(r, "similarity", f"{m}@{t}")
                                                     for r in rows) / len(rows), 4)
                              for m in MEASURES for t in TAUS},
        "arms": arms, "best_baseline": best,
        "no_arm_beats_the_oracle": all(arms[a]["decision_accuracy"]
                                       <= arms["oracle"]["decision_accuracy"] for a in ARMS),
        "exposure_vs_best": paired(rows, "exposure", best, tau, random.Random(7)),
        "wall_s": round(time.perf_counter() - started, 1),
    }
    if args.split == "test":
        from memeval import Registration

        verdict = Registration(hypothesis="S2", metric="decision_accuracy", mechanism="exposure",
                               baselines=baselines, ceiling="oracle", seeds_required=20).evaluate(
            arms, seeds=result["seeds"], n_pairs=result["exposure_vs_best"]["n_pairs"],
            discordance=result["exposure_vs_best"]["discordance"])
        result["verdict"] = verdict.to_json()
    if args.out:
        Path(args.out).write_text(json.dumps({**result, "rows": rows}, indent=2) + "\n",
                                  encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())


