"""GME matrix: governance, compression and branching against baselines (blueprint §11.1).

    python -m experiments.gme_matrix --pilot          # seed 0 only: baselines and oracle
    python -m experiments.gme_matrix                  # registered seeds 1..5, every arm
    python -m experiments.gme_matrix --seeds 1 2 3 4 5 --out FILE

Pre-registration: research/prereg/gme-matrix.md. A synthetic plant-operations
world, built from a seed:

- each asset has one current fact (`Pump P7-ROT is pressurised to 41 bar ...`)
  and several notes naming its tag (handovers, spares), some restating the
  value, so a context budget binds and restatements are compressible;
- **corrections**: some facts are revised (the old text stays in any store
  that does not version);
- **withdrawals**: some facts are found wrong, quarantined, and replaced by a
  new fact from another source;
- **disputes**: some assets get a second source with a different value and
  nothing resolves it; the right answer is "disputed";
- **a branch** opened early proposes re-measurements: some on assets main
  never touched afterwards (should merge), some on assets main corrected
  since (main is right), some on facts later withdrawn (must not come back).

Every arm answers the same questions with the same reader under the same
token budget. The reader takes the first context item that names the asset's
tag and states a value, or answers "disputed" if a dispute line names it.

Arms (blueprint labels):

| arm | what it is |
|---|---|
| A | no memory |
| B | conventional retrieval: every text ever written, ranked lexically, no governance |
| C | Memory Fabric governance, canonical records, no compression |
| D | compression without governance: summaries of every text ever written |
| E | Governed Context Map (compact mode) |
| F | branch merged naively: every proposal applied, then governed retrieval |
| G | full system: governed merge, then the Governed Context Map |
| oracle | exactly the true fact (or both sides of a real dispute), same reader and budget |

Phase 1 is asked while the branch is open; phase 2 after the merge. A, B, C, D
and E have no merge: in phase 2 they read the store as it stands (the branch
unmerged for C and E; every text for B and D).
"""

from __future__ import annotations

import argparse
import json
import platform
import random
import re
import statistics
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from memory_fabric import MemoryFabric
from memory_fabric.branching import Branches
from memory_fabric.context_map import ContextMap, build_l1, estimate_tokens, subject
from memory_fabric.context_receipt import rendered_items

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "research" / "results" / "gme-matrix.json"
SITES = ["Rotterdam", "Gdansk", "Leeds", "Porto", "Tampere", "Lyon"]
ASSETS = [("pump", "pressurised to", "bar"), ("boiler", "runs at", "C"),
          ("conveyor", "moves", "t/h"), ("compressor", "is torqued to", "Nm")]
FILLER = ["Shift handover at {site}: {tag} inspected, logbook signed.",
          "Spare parts for {tag} at {site} are in store room {r}.",
          "Vendor visit at {site} scheduled for {tag} servicing.",
          "Incident at {site}: {tag} tripped on low oil and was restarted."]
BUDGET = 60
K = 20
ARMS = ("A", "B", "C", "D", "E", "F", "G", "oracle")


@dataclass
class Asset:
    tag: str
    kind: str
    verb: str
    unit: str
    site: str
    value: int
    fact_id: str = ""
    truth: str = ""
    truth_after_merge: str = ""
    role: str = "plain"
    proposal: int | None = None


def fact(a: Asset, value: int) -> str:
    return f"{a.kind.title()} {a.tag} {a.verb} {value} {a.unit} at the {a.site} plant."


def question(a: Asset) -> str:
    return f"what value for {a.kind} {a.tag} in {a.site}?"


_VALUE = re.compile(r"(\d+(?:\.\d+)?)\s*(bar|C|t/h|Nm)\b")


def read(items: list[str], a: Asset) -> str:
    """The fixed reader: the first item naming the tag with a value, or 'disputed'."""
    tag = a.tag.lower()
    for text in items:
        low = text.lower()
        if tag not in low:
            continue
        if "disputed, unresolved" in low or "[disputed" in low:
            return "disputed"
        m = _VALUE.search(text[low.index(tag):])
        if m:
            return m.group(1)
    return "none"


def within_budget(texts: list[str], budget: int | None = None) -> list[str]:
    budget = BUDGET if budget is None else budget
    out, used = [], 0
    for t in texts:
        cost = estimate_tokens(t)
        if used + cost > budget:
            continue
        out.append(t)
        used += cost
    return out


@dataclass
class World:
    seed: int
    assets: list[Asset]
    gov: MemoryFabric               # governed store, branch merged with governance after phase 1
    naive: MemoryFabric             # same timeline, branch merged naively after phase 1
    raw: MemoryFabric               # every text ever written, all active, no governance
    branches: Branches
    stats: dict[str, Any] = field(default_factory=dict)


def build_world(seed: int, n_assets: int = 36) -> World:
    rng = random.Random(seed)
    gov = MemoryFabric(":memory:", auto_activate=True, hold_suspicious=False, seed=seed)
    naive = MemoryFabric(":memory:", auto_activate=True, hold_suspicious=False, seed=seed)
    raw = MemoryFabric(":memory:", auto_activate=True, hold_suspicious=False, seed=seed,
                       recognise_copies=False)
    stores = (gov, naive)

    def both(fn: Callable[[MemoryFabric], str]) -> tuple[str, str]:
        return fn(gov), fn(naive)

    def write_raw(text: str) -> None:
        raw.remember("ops", text, scope="team")

    assets: list[Asset] = []
    for n in range(n_assets):
        kind, verb, unit = ASSETS[n % len(ASSETS)]
        site = rng.choice(SITES)
        a = Asset(f"{kind[0].upper()}{n + 1}-{site[:3].upper()}", kind, verb, unit, site,
                  rng.randint(10, 90))
        assets.append(a)
    roles = ["plain"] * n_assets
    for i, role in enumerate(rng.sample(range(n_assets), n_assets)):
        roles[role] = ("corrected" if i % 9 in (0, 1) else "withdrawn" if i % 9 == 2
                       else "disputed" if i % 9 == 3 else "plain")
    ids: dict[str, tuple[str, str]] = {}
    for a, role in zip(assets, roles):
        a.role = role
        text = fact(a, a.value)
        ids[a.tag] = both(lambda f, t=text: f.remember("ops", t, scope="team"))
        write_raw(text)
        for j in range(3):
            filler = rng.choice(FILLER).format(site=a.site, tag=a.tag, r=rng.randint(1, 30))
            if j == 0:
                filler = f"Measured again on the night shift: {a.tag} {a.verb} {a.value} {a.unit}."
            for f in stores:
                f.remember("crew", filler, scope="team")
            write_raw(filler)

    # The branch opens here, on a base where every fact is still its first version.
    b_gov, b_naive = Branches(gov), Branches(naive)
    for b in (b_gov, b_naive):
        b.create("remeasure", owner="eng", reviewers=("lead",))
    proposals = [a for a in assets if a.role in ("plain", "corrected", "withdrawn")]
    proposals = rng.sample(proposals, max(3, len(proposals) // 3))
    with b_gov.commit("remeasure", "eng", "re-measurement campaign") as cg, \
            b_naive.commit("remeasure", "eng", "re-measurement campaign") as cn:
        for a in proposals:
            a.proposal = a.value + rng.choice([-7, -5, 5, 7])
            text = fact(a, a.proposal)
            cg.revise(ids[a.tag][0], text)
            cn.revise(ids[a.tag][1], text)
            write_raw(text)

    # Main moves on after the branch's base.
    for a in assets:
        g_id, n_id = ids[a.tag]
        if a.role == "corrected":
            new = a.value + rng.choice([-3, 3, 4])
            for f, mid in ((gov, g_id), (naive, n_id)):
                f.revise(mid, fact(a, new), agent_id="ops", reason="recalibrated")
            write_raw(fact(a, new))
            a.value = new
        elif a.role == "withdrawn":
            new = a.value + rng.choice([-11, 11, 13])
            for f, mid in ((gov, g_id), (naive, n_id)):
                f.quarantine(mid, reason="sensor fault", actor="lead")
                f.remember("audit", fact(a, new), scope="team")
            write_raw(fact(a, new))
            a.value = new
        elif a.role == "disputed":
            other = a.value + rng.choice([-9, 9, 12])
            for f in stores:
                f.remember("vendor", fact(a, other), scope="team")
            write_raw(fact(a, other))
        a.fact_id = g_id
        a.truth = "disputed" if a.role == "disputed" else str(a.value)
        # A proposal merges only where main has not touched the fact since the base.
        a.truth_after_merge = (str(a.proposal) if a.proposal is not None and a.role == "plain"
                               else a.truth)
    return World(seed, assets, gov, naive, raw, b_gov,
                 stats={"assets": n_assets, "proposals": len(proposals),
                        "roles": {r: roles.count(r) for r in set(roles)}})


def merge_governed(w: World) -> dict[str, Any]:
    preview = w.branches.preview_merge("remeasure", "lead")
    receipt = w.branches.apply_merge("remeasure", "lead", preview.digest, f"seed-{w.seed}")
    return receipt["summary"]


def merge_naive(w: World) -> None:
    """F: apply every proposal. A withdrawn target comes back as a new active memory."""
    b = Branches(w.naive)
    for c in b.get("remeasure").changes:
        cand = w.naive.get(c["candidate_id"])
        target = w.naive.get(c["memory_id"])
        if target.lifecycle_state.value == "active":
            w.naive.revise(target.id, cand.content, agent_id="eng", reason="merged")
        else:
            w.naive.remember("eng", cand.content, scope="team")


# --- arms -----------------------------------------------------------------

def ranked_texts(f: MemoryFabric, q: str) -> list[str]:
    return [m.content for m in f.retrieve("reader", q, k=K).exposed]


def arm_items(arm: str, w: World, a: Asset, phase: int, cmaps: dict[str, Any]) -> list[str]:
    q = question(a)
    if arm == "A":
        return []
    if arm == "B":
        return within_budget(ranked_texts(w.raw, q))
    if arm == "C":
        plan = cmaps["gov"].plan("reader", q, budget=BUDGET, mode="evidence-first", k=K)
        return rendered_items(plan)
    if arm == "D":
        texts = ranked_texts(w.raw, q)
        return within_budget(cmaps["raw_summaries"](a, texts))
    if arm in ("E", "G"):
        plan = cmaps["gov"].plan("reader", q, budget=BUDGET, mode="compact", k=K)
        return rendered_items(plan)
    if arm == "F":
        plan = cmaps["naive"].plan("reader", q, budget=BUDGET, mode="compact", k=K)
        return rendered_items(plan)
    if arm == "oracle":
        truth = a.truth_after_merge if phase == 2 else a.truth
        if truth == "disputed":
            return [f"Disputed, unresolved: {a.tag} has two sourced values."]
        return [fact(a, int(truth))]
    raise ValueError(arm)


def raw_summariser(w: World) -> Callable[[Asset, list[str]], list[str]]:
    """D: summaries over every text ever written about a subject, never invalidated."""
    by_subject: dict[str, list[Any]] = {}
    for m in w.raw.state.memories.values():
        by_subject.setdefault(subject(m), []).append(m)
    cache: dict[str, str] = {}
    for key, members in by_subject.items():
        if len(members) > 1:
            try:
                cache[key] = build_l1(members, key, "raw").content
            except Exception:
                continue

    def summarise(a: Asset, texts: list[str]) -> list[str]:
        hits = [v for k, v in cache.items() if k == f"id:{a.tag.lower().split('-')[0]}"]
        return hits + texts
    return summarise


def leakage(items: list[str], a: Asset, w: World, phase: int) -> dict[str, int]:
    """Withdrawn or superseded values, and branch-only values before a merge, in context."""
    text = " ".join(items)
    leaked = branch = 0
    # Metric v2: a value counts only as a stated quantity (number, then unit).
    # v1 matched any number after the tag, so "store room 14" counted as a
    # leak of a proposal of 14 (research/results/gme-matrix.md).
    unit = re.escape(a.unit)
    for v in set(getattr(a, "stale_values", ())):
        if re.search(rf"{re.escape(a.tag)}[^.]*\b{v}\s*{unit}(?![\w/])", text):
            leaked = 1
    if phase == 1 and a.proposal is not None and str(a.proposal) != a.truth:
        if re.search(rf"{re.escape(a.tag)}[^.]*\b{a.proposal}\s*{unit}(?![\w/])", text):
            branch = 1
    return {"leak": leaked, "branch_leak": branch}


def run_seed(seed: int, arms: tuple[str, ...]) -> dict[str, Any]:
    w = build_world(seed)
    # Values a correct context must not carry: superseded or withdrawn ones.
    for a in w.assets:
        a.stale_values = []  # type: ignore[attr-defined]
    for m in w.raw.state.memories.values():
        for a in w.assets:
            if a.tag in m.content:
                v = _VALUE.search(m.content)
                if v and a.role in ("corrected", "withdrawn") and v.group(1) != a.truth \
                        and (a.proposal is None or v.group(1) != str(a.proposal)):
                    a.stale_values.append(v.group(1))  # type: ignore[attr-defined]
    results: dict[str, Any] = {"seed": seed, "world": w.stats, "phases": {}}
    for phase in (1, 2):
        if phase == 2:
            results["merge_summary"] = merge_governed(w)
            merge_naive(w)
        cmaps = {"gov": ContextMap(w.gov), "naive": ContextMap(w.naive),
                 "raw_summaries": raw_summariser(w) if "D" in arms else None}
        per_arm: dict[str, Any] = {}
        for arm in arms:
            if phase == 1 and arm in ("F",):
                continue  # F differs from G only after the merge
            correct = tokens = leaks = branch_leaks = 0
            for a in w.assets:
                items = arm_items(arm, w, a, phase, cmaps)
                truth = a.truth_after_merge if phase == 2 and arm in ("F", "G", "oracle") \
                    else a.truth
                correct += read(items, a) == truth
                tokens += sum(estimate_tokens(t) for t in items)
                lk = leakage(items, a, w, phase)
                leaks += lk["leak"]
                branch_leaks += lk["branch_leak"]
            n = len(w.assets)
            per_arm[arm] = {"accuracy": round(correct / n, 4), "tokens_per_task": round(tokens / n, 2),
                            "stale_leak_rate": round(leaks / n, 4),
                            "branch_leak_rate": round(branch_leaks / n, 4)}
        results["phases"][str(phase)] = per_arm
    # Version-control invariants on the governed merge.
    resurrected = sum(1 for a in w.assets if a.role == "withdrawn"
                      and w.gov.get(a.fact_id).lifecycle_state.value == "active")
    lost = sum(1 for a in w.assets if a.role == "corrected" and a.proposal is not None
               and str(a.value) not in w.gov.get(a.fact_id).content)
    results["version_control"] = {"resurrected": resurrected, "lost_updates": lost}
    for f in (w.gov, w.naive, w.raw):
        f.close()
    return results


def summarise(runs: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for phase in ("1", "2"):
        arms = runs[0]["phases"][phase].keys()
        out[phase] = {}
        for arm in arms:
            metrics = runs[0]["phases"][phase][arm].keys()
            out[phase][arm] = {}
            for metric in metrics:
                xs = [r["phases"][phase][arm][metric] for r in runs]
                sd = statistics.stdev(xs) if len(xs) > 1 else 0.0
                out[phase][arm][metric] = {"mean": round(statistics.mean(xs), 4),
                                           "sd": round(sd, 4), "n": len(xs)}
    beats = [(p, arm) for p in out for arm in out[p] if arm != "oracle"
             and out[p][arm]["accuracy"]["mean"] > out[p]["oracle"]["accuracy"]["mean"]]
    out["any_arm_beats_oracle"] = beats  # AGENTS.md 8b: must be empty, or the oracle is wrong
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--pilot", action="store_true", help="seed 0: A, B and the oracle only")
    parser.add_argument("--seeds", type=int, nargs="*", default=[1, 2, 3, 4, 5])
    parser.add_argument("--out", type=Path)
    parser.add_argument("--budget", type=int, default=BUDGET,
                        help="token budget per question (v2 registers 60 and 400)")
    args = parser.parse_args(argv)
    globals()["BUDGET"] = args.budget
    seeds = [0] if args.pilot else args.seeds
    arms = ("A", "B", "oracle") if args.pilot else ARMS
    runs = [run_seed(s, arms) for s in seeds]
    result = {"experiment": "gme-matrix", "metric_version": 2,
              "prereg": "research/prereg/gme-matrix.md, gme-matrix-v2.md",
              "budget_tokens": BUDGET, "k": K, "seeds": seeds, "arms": list(arms),
              "python": platform.python_version(), "runs": runs, "summary": summarise(runs)}
    print(json.dumps(result["summary"], indent=1))
    out = args.out or (None if args.pilot else OUT)
    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
