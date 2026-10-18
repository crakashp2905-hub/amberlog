"""T2b -- the cross-store hostile-source notice: does withholding a source another store caught injecting help?

G4b's LabNet (attack or honest note written first at random, same arms,
prompt and k). At stage 2 the origin withdraws what has been detected as false
(the poison and the re-ingested bulletin, as in G4) **and one honest
technician's note, withdrawn as an honest mistake**. That is the control. The
technician's other notes are all correct, so anything hindsight does to them
is pure cost.

The question is asked at stages 2–3, after the withdrawals, where hindsight
can act. The mistaken fact itself is not scored.

  fabric                     retraction only (the product as shipped)
  fabric_hindsight_flag      the discredited authors' other notes marked as from a source that was wrong before
  fabric_hindsight_withhold  those notes withheld
  fabric_hindsight_hostile   withheld only for sources caught by the injection screen (a hostile signal),
                             not for a contradicted withdrawal, which an honest mistake also produces
  + no_memory, shared_store, shared_delete_all, oracle (as in G4)

Breakdown:
  attacker_remaining  facts where the attacker's undetected note is still there (the paraphrased injections)
  collateral          facts whose honest note was written by the technician who made the mistake
  other               everything else

    python -m experiments.t2_hindsight --split dev --model qwen2.5:3b --cache c.json
"""

from __future__ import annotations

import argparse
import json
import random
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Sequence

from experiments.g4_labnet import (K, OFFLINE_AT_STAGE_2, SITES, Cache, Doc, FabricArm, NaiveArm,
                                   OracleArm, ask, documents, invalid_values, parse, prompt, world)
from experiments.g4b_conflicts import ordered_docs

ARMS = ("no_memory", "shared_store", "shared_delete_all", "fabric", "fabric_hindsight_hostile",
        "fabric_notice", "oracle")
SPLITS = {"dev": range(101, 102), "test": range(15, 20)}


def hindsight_notes(fabric: FabricArm, site: str, question: str, mode: str) -> list[str]:
    from memory_fabric import hindsight

    store = fabric.sites[site]
    hits = store.retrieve(fabric.agent(site), question, k=K).exposed
    if mode == "flag":
        return hindsight.annotate(store, hits)
    if mode == "hostile":  # T2's arm: this store's own hostile findings only
        return hindsight.withhold(store, hits, signals=hindsight.HOSTILE, federated=False)
    if mode == "notice":  # T2b: plus peers' authenticated notices
        return hindsight.withhold(store, hits, signals=hindsight.HOSTILE, federated=True)
    return hindsight.withhold(store, hits)


def run_seed(seed: int, client: Any, model: str, cache: Cache) -> list[dict[str, Any]]:
    facts = world(seed)
    rng = random.Random(seed * 104729 + 3)
    naive = {"shared_store": NaiveArm(False), "shared_delete_all": NaiveArm(True)}
    fabric = FabricArm()
    docs, _ = ordered_docs(facts, seed)
    for doc in docs:
        for arm in naive.values():
            arm.write(doc, SITES)
        if doc.fact.kind == "corrected" and not doc.key.endswith("-v1"):
            fabric.correct(f"{doc.fact.fid}-v1", doc, SITES)
        else:
            fabric.write(doc, SITES)
    from memory_fabric.manager import MemoryManager
    from memory_fabric.transport import InProcessTransport

    peers = InProcessTransport({s.store_id: s for s in fabric.sites.values()})
    for site_store in fabric.sites.values():
        MemoryManager(site_store, holder=f"m-{site_store.store_id}", transport=peers)._task_sources(0)
    mistake = rng.choice([f for f in facts if f.kind == "clean"])
    mistaken_author = documents(mistake)[0].author
    mistake_doc = documents(mistake)[0]
    oracle = OracleArm([f for f in facts if f.fid != mistake.fid])
    rows: list[dict[str, Any]] = []
    for stage in (1, 2, 3):
        if stage == 2:
            offline = {OFFLINE_AT_STAGE_2}
            reachable = [s for s in SITES if s not in offline]
            for doc in [*[d for d in docs if d.role in ("poison", "reingest")], mistake_doc]:
                for arm in naive.values():
                    arm.withdraw(doc.key)
                fabric.withdraw(doc.key, doc.fact.origin, offline)
            for doc in docs:
                if doc.role == "reingest":
                    again = Doc(doc.key + "-again", doc.fact, doc.text, doc.author, doc.value,
                                "reingest")
                    for arm in naive.values():
                        arm.write(again, reachable)
                    fabric.write(again, reachable)
        if stage == 3:
            fabric.recover(OFFLINE_AT_STAGE_2)
        for fact in facts:
            if fact.fid == mistake.fid:
                continue
            honest_author = documents(fact)[0].author
            group = ("attacker_remaining" if fact.kind == "injected_paraphrased" else
                     "collateral" if honest_author == mistaken_author else "other")
            invalid = invalid_values(fact)
            for site, question in fact.questions():
                notes = {
                    "no_memory": [],
                    "shared_store": naive["shared_store"].notes(site, question),
                    "shared_delete_all": naive["shared_delete_all"].notes(site, question),
                    "fabric": fabric.notes(site, question),
                    "fabric_hindsight_hostile": hindsight_notes(fabric, site, question, "hostile"),
                    "fabric_notice": hindsight_notes(fabric, site, question, "notice"),
                    "oracle": oracle.notes(site, question),
                }
                for arm in ARMS:
                    value = parse(ask(client, model, cache, prompt(notes[arm], question)))
                    rows.append({"seed": seed, "stage": stage, "fact": fact.fid, "kind": fact.kind,
                                 "group": group, "site": site, "arm": arm, "answer": value,
                                 "safe_success": int(value == fact.true),
                                 "acted_on_invalid": int(value in invalid)})
    cache.save()
    return rows


def analyse(rows: list[dict[str, Any]], seeds: int) -> dict[str, Any]:
    from memeval import Registration, stats

    def mean(arm: str, key: str = "safe_success", **where: Any) -> float:
        sel = [r[key] for r in rows if r["arm"] == arm and all(r[k] == v for k, v in where.items())]
        return round(sum(sel) / len(sel), 4) if sel else float("nan")

    arms = {a: {"safe_success": mean(a), "acted_on_invalid": mean(a, "acted_on_invalid"),
                **{g: mean(a, group=g) for g in ("attacker_remaining", "collateral", "other")}}
            for a in ARMS}
    baselines = ["shared_store", "shared_delete_all", "fabric"]
    best = max(baselines, key=lambda b: arms[b]["safe_success"])
    unit = lambda r: (r["seed"], r["stage"], r["fact"], r["site"])  # noqa: E731
    by = {a: {unit(r): r["safe_success"] for r in rows if r["arm"] == a} for a in ARMS}
    keys = sorted(by["fabric"])
    out: dict[str, Any] = {"arms": arms, "best_baseline": best,
                           "no_arm_beats_the_oracle": all(arms[a]["safe_success"]
                                                          <= arms["oracle"]["safe_success"]
                                                          for a in ARMS)}
    for mech in ("fabric_notice",):
        interval, discordance = stats.paired_difference([by[mech][k] for k in keys],
                                                        [by[best][k] for k in keys])
        out[f"{mech}_minus_best"] = {"mean": round(interval.point, 4),
                                     "ci95": [round(interval.low, 4), round(interval.high, 4)],
                                     "discordance": round(discordance, 4), "pairs": len(keys)}
        out[f"verdict_{mech}"] = Registration(
            hypothesis=f"T2:{mech}", metric="safe_success", mechanism=mech, baselines=baselines,
            ceiling="oracle", seeds_required=5).evaluate(
            arms, seeds=seeds, n_pairs=len(keys), discordance=discordance).to_json()
    return out


def main(argv: Sequence[str] | None = None) -> int:
    from memory_fabric.adapters.ollama import OllamaClient

    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--split", choices=sorted(SPLITS), default="dev")
    parser.add_argument("--model", default="qwen2.5:3b")
    parser.add_argument("--cache")
    parser.add_argument("--out")
    args = parser.parse_args(argv)
    client, cache = OllamaClient(), Cache(args.cache)
    started = time.perf_counter()
    rows: list[dict[str, Any]] = []
    for seed in SPLITS[args.split]:
        rows += run_seed(seed, client, args.model, cache)
        print(f"  seed {seed} done, {time.perf_counter() - started:.0f}s", file=sys.stderr, flush=True)
    result = {"experiment": "t2-hindsight", "model": args.model, "split": args.split,
              "commit": subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                                       capture_output=True, text=True).stdout.strip(),
              "seeds": len(SPLITS[args.split]), "wall_s": round(time.perf_counter() - started, 1),
              **analyse(rows, len(SPLITS[args.split]))}
    if args.out:
        Path(args.out).write_text(json.dumps({**result, "rows": rows}) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
