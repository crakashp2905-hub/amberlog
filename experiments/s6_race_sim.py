"""S6 -- RaceSim: does an action ever land after its evidence was withdrawn?

Real processes on a real store file. Per seed and arm, a fresh store whose
active memories each certify one action. The actor (this process) performs
200 tool calls on random memories. Each side effect takes U(5, 40) ms, with
U(1, 10) ms of think time between calls. A retractor *process* withdraws
memories, with one of two timings:

  targeted  (primary) the actor tells the retractor which memory it has just
            verified, and the retractor withdraws it with probability 0.25 at
            once. That is the worst case: the withdrawal aimed at the window.
            60 memories.
  random    every memory once, in a random order, one every U(0, 800) ms.
            12 memories.

A **violation** is a side effect timestamped after the withdrawal of its
evidence had committed. The withdrawal's time is taken when `quarantine`
returns, so this undercounts and never overcounts. Same clock, same machine.

Arms:
  authorize_then_act   authorize, then run the tool (the product before S6)
  reverify             authorize, run 90% of the tool, authorize again, finish
  fenced               ActionGate.execute, lease 1.0 s (S6)
  fenced_overrun       fenced, lease 0.25 s, and 5% of calls hang 1.5 s past it

The targeted signal is sent after each arm's *last* verification before the
side effect -- for `reverify`, after the second check.

    python -m experiments.s6_race_sim --seeds 5 --out s6.json
"""

from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import random
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Sequence

MEMORIES = {"targeted": 60, "random": 12}
ACTIONS = 200
TARGET_P = 0.25
ARMS = ("authorize_then_act", "reverify", "fenced", "fenced_overrun")


def retractor(path: str, ids: list[str], seed: int, ready: Any, go: Any, out: Any) -> None:
    """Withdraw every memory once, on a seeded schedule; report commit times."""
    from memory_fabric import MemoryFabric

    rng = random.Random(seed * 31 + 7)
    fab = MemoryFabric(path)
    order = list(ids)
    rng.shuffle(order)
    gaps = [rng.uniform(0, 0.8) for _ in order]
    ready.set()
    go.wait()
    rows = []
    for memory_id, gap in zip(order, gaps):
        time.sleep(gap)
        started = time.time()
        try:
            fab.quarantine(memory_id, reason="withdrawn", actor="op")
            rows.append({"memory_id": memory_id, "committed": time.time(),
                         "wait_s": time.time() - started, "error": None})
        except Exception as exc:  # noqa: BLE001 - a failed writer is a measured outcome
            rows.append({"memory_id": memory_id, "committed": None,
                         "wait_s": time.time() - started, "error": f"{type(exc).__name__}: {exc}"})
    fab.close()
    out.put(rows)


def targeted_retractor(path: str, seed: int, ready: Any, go: Any, signals: Any,
                       out: Any) -> None:
    """Withdraw a just-verified memory, with probability TARGET_P, at once."""
    import queue

    from memory_fabric import MemoryFabric

    rng = random.Random(seed * 31 + 11)
    fab = MemoryFabric(path)
    ready.set()
    go.wait()
    rows: list[dict[str, Any]] = []
    done: set[str] = set()
    while True:
        try:
            memory_id = signals.get(timeout=5)
        except queue.Empty:
            break
        if memory_id is None:
            break
        if memory_id in done or rng.random() >= TARGET_P:
            continue
        done.add(memory_id)
        started = time.time()
        try:
            fab.quarantine(memory_id, reason="withdrawn", actor="op")
            rows.append({"memory_id": memory_id, "committed": time.time(),
                         "wait_s": time.time() - started, "error": None})
        except Exception as exc:  # noqa: BLE001 - a failed writer is a measured outcome
            rows.append({"memory_id": memory_id, "committed": None,
                         "wait_s": time.time() - started, "error": f"{type(exc).__name__}: {exc}"})
    fab.close()
    out.put(rows)


def run_arm(arm: str, seed: int, timing: str = "targeted") -> dict[str, Any]:
    from memory_fabric import MemoryFabric
    from memory_fabric.actions import (EXECUTED, TIMED_OUT, ActionGate, ActionPolicy, ToolRule,
                                       unfenced_changes)

    rng = random.Random(seed)
    with tempfile.TemporaryDirectory() as tmp:
        path = str(Path(tmp) / "store.db")
        fab = MemoryFabric(path, auto_activate=True)
        ids = [fab.remember("author", f"Valve V{i} may be opened below {3 + i % 4} bar.",
                            scope="team") for i in range(MEMORIES[timing])]
        certs = {m: fab.certify(f"open-{m}", [m], "ops", ttl_ms=None) for m in ids}
        gate = ActionGate(fab, ActionPolicy(tools={"open": ToolRule("open")},
                                            grants={"ops": frozenset({"open"})}))
        ctx = mp.get_context("spawn")
        ready, go, out, signals = ctx.Event(), ctx.Event(), ctx.Queue(), ctx.Queue()
        if timing == "targeted":
            proc = ctx.Process(target=targeted_retractor,
                               args=(path, seed, ready, go, signals, out))
        else:
            proc = ctx.Process(target=retractor, args=(path, ids, seed, ready, go, out))
        proc.start()
        ready.wait(60)
        plan = [(rng.choice(ids), rng.uniform(0.005, 0.040), rng.uniform(0.001, 0.010),
                 rng.random() < 0.05) for _ in range(ACTIONS)]
        effects: list[dict[str, Any]] = []
        outcomes: dict[str, int] = {}
        go.set()
        started = time.time()
        for n, (memory_id, latency, think, hangs) in enumerate(plan):
            time.sleep(think)
            key = f"s{seed}-{arm}-{n}"
            stamp: dict[str, float] = {}

            def signal(memory_id: str = memory_id) -> None:
                if timing == "targeted":
                    signals.put(memory_id)

            # Every loop variable bound now: an overrunning tool finishes after
            # the loop has moved on, and a late-bound `stamp` would record its
            # effect in a later call's slot (found in the dev pilot).
            def tool(_key: str, latency: float = latency, hangs: bool = hangs,
                     stamp: dict[str, float] = stamp) -> None:
                if arm in ("fenced", "fenced_overrun"):
                    signal()  # verified, inside the fence
                if arm == "fenced_overrun" and hangs:
                    time.sleep(0.25 + 1.5)
                else:
                    time.sleep(latency)
                stamp["effect"] = time.time()

            if arm in ("authorize_then_act", "reverify"):
                decision = gate.authorize("open", "ops", certs[memory_id])
                if not decision.allowed:
                    outcomes["refused"] = outcomes.get("refused", 0) + 1
                    continue
                if arm == "reverify":
                    time.sleep(latency * 0.9)
                    if not gate.authorize("open", "ops", certs[memory_id]).allowed:
                        outcomes["refused_late"] = outcomes.get("refused_late", 0) + 1
                        continue
                    signal()  # after the last verification, as for every arm
                    time.sleep(latency * 0.1)
                    stamp["effect"] = time.time()
                else:
                    signal()  # verified
                    tool(key)
                outcomes["executed"] = outcomes.get("executed", 0) + 1
                effects.append({"key": key, "memory_id": memory_id, "effect": stamp["effect"],
                                "timed_out": False})
            else:
                lease = 1.0 if arm == "fenced" else 0.25
                result = gate.execute("open", "ops", tool, certs[memory_id], key=key, lease_s=lease)
                outcomes[result.outcome] = outcomes.get(result.outcome, 0) + 1
                if result.outcome in (EXECUTED, TIMED_OUT):
                    effects.append({"key": key, "memory_id": memory_id, "effect": None,
                                    "stamp": stamp, "timed_out": result.outcome == TIMED_OUT})
        signals.put(None)
        time.sleep(2.5)  # let overrunning tools finish and stamp their effect
        for e in effects:
            if "stamp" in e:
                e["effect"] = e.pop("stamp").get("effect")
        wall = time.time() - started
        rows = out.get(timeout=120)
        proc.join(60)
        fab.refresh()
        flagged = {c["key"] for c in unfenced_changes(fab)}
        fab.close()
    committed = {r["memory_id"]: r["committed"] for r in rows}
    violations = [e for e in effects if e["effect"] is not None
                  and committed.get(e["memory_id"]) is not None
                  and e["effect"] > committed[e["memory_id"]]]
    waits = sorted(r["wait_s"] for r in rows)
    return {
        "arm": arm, "seed": seed, "timing": timing, "actions": ACTIONS, "outcomes": outcomes,
        "withdrawals": len(rows),
        "effects": len(effects), "violations": len(violations),
        "violations_in_overruns": sum(e["timed_out"] for e in violations),
        "violations_outside_overruns": sum(not e["timed_out"] for e in violations),
        "violations_flagged": sum(e["key"] in flagged for e in violations),
        # per overrun: seconds from the side effect to its evidence's withdrawal
        # (positive: withdrawn after; None: not withdrawn), and whether flagged
        "overruns": [[round(committed[e["memory_id"]] - e["effect"], 3)
                      if committed.get(e["memory_id"]) and e["effect"] else None,
                      e["key"] in flagged] for e in effects if e["timed_out"]],
        "writer_failures": sum(r["error"] is not None for r in rows),
        "writer_wait_p50_s": round(statistics.median(waits), 4) if waits else None,
        "writer_wait_p95_s": round(waits[int(0.95 * (len(waits) - 1))], 4) if waits else None,
        "writer_wait_max_s": round(waits[-1], 4) if waits else None,
        "actions_per_s": round(ACTIONS / wall, 2),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--seeds", type=int, default=5)
    parser.add_argument("--first-seed", type=int, default=0)
    parser.add_argument("--arms", default=",".join(ARMS))
    parser.add_argument("--timing", default="targeted,random")
    parser.add_argument("--out")
    args = parser.parse_args(argv)
    runs = []
    timings = args.timing.split(",")
    for seed in range(args.first_seed, args.first_seed + args.seeds):
        for timing in timings:
            for arm in args.arms.split(","):
                runs.append(run_arm(arm, seed, timing))
                r = runs[-1]
                print(f"  seed {seed} {timing} {arm}: {r['violations']}/{r['effects']} violations, "
                      f"writer p95 {r['writer_wait_p95_s']} s, failures {r['writer_failures']}",
                      file=sys.stderr, flush=True)
    summary: dict[str, Any] = {}
    for timing in timings:
        summary[timing] = {}
        for arm in args.arms.split(","):
            summary[timing][arm] = _summarise([r for r in runs
                                               if r["arm"] == arm and r["timing"] == timing])
    result = {"experiment": "s6-race-sim",
              "commit": subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                                       capture_output=True, text=True).stdout.strip(),
              "seeds": args.seeds, "first_seed": args.first_seed, "summary": summary,
              "runs": runs}
    if args.out:
        Path(args.out).write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "runs"}, indent=2))
    return 0


def _summarise(mine: list[dict[str, Any]]) -> dict[str, Any]:
    effects = sum(r["effects"] for r in mine)
    violations = sum(r["violations"] for r in mine)
    waits = [r["writer_wait_p95_s"] for r in mine if r["writer_wait_p95_s"] is not None]
    maxes = [r["writer_wait_max_s"] for r in mine if r["writer_wait_max_s"] is not None]
    return {
        "effects": effects, "violations": violations,
        "violation_rate": round(violations / effects, 4) if effects else None,
        "seeds_with_a_violation": sum(r["violations"] > 0 for r in mine),
        "withdrawals": sum(r["withdrawals"] for r in mine),
        "violations_outside_overruns": sum(r["violations_outside_overruns"] for r in mine),
        "violations_in_overruns": sum(r["violations_in_overruns"] for r in mine),
        "violations_flagged": sum(r["violations_flagged"] for r in mine),
        "writer_failures": sum(r["writer_failures"] for r in mine),
        "writer_wait_p95_s_max": max(waits) if waits else None,
        "writer_wait_max_s": max(maxes) if maxes else None,
        "actions_per_s": round(statistics.mean(r["actions_per_s"] for r in mine), 2),
    }


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
